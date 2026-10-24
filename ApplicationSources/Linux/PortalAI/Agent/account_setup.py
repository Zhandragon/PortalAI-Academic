"""User-supplied setup data creates normal mission and schedule records.

Runs only inside a real authenticated controller. Connection and setup state
are saved together in one encrypted bundle. Repeating an interrupted request
continues the same records, never creates another running workflow.
"""
import hashlib
import json
from pathlib import Path
import re
import time
import uuid
from account_connections import read,write,session_key,unlock_session,require_session
from mission_runner import Missions,process_lock
from mission_schedule import Schedules
from mission_catalog import MissionCatalog
from profile_paths import private_path


def load_request(path):
    from account_import import source_file
    value=json.loads(source_file(path,64*1024).read_text(encoding='utf-8-sig'))
    validate(value)
    return value


def validate(spec):
    if not isinstance(spec,dict) or spec.get('version')!=1:raise ValueError('Expected a version 1 connection setup request')
    if not re.fullmatch('[a-f0-9]{32}',str(spec.get('id',''))):raise ValueError('Setup ID must be a UUID without hyphens')
    if not isinstance(spec.get('target_username'),str) or not spec['target_username']:raise ValueError('Select the receiving PortalAI username')
    if not isinstance(spec.get('objective'),str) or not 1<=len(spec['objective'].strip())<=16000:raise ValueError('Expected an ordinary mission objective')
    for field,low,high in (('max_steps',1,100),('interval_seconds',60,31536000),('max_runs',0,10000)):
        if type(spec.get(field)) is not int or not low<=spec[field]<=high:raise ValueError('Invalid '+field)
    if not isinstance(spec.get('sources'),list) or not 1<=len(spec['sources'])<=8:raise ValueError('Select the credential sources explicitly')
    if type(spec.get('autonomous_recovery',False)) is not bool:raise ValueError('Invalid recovery preference')
    # Deliberately no enable/run field: importing data cannot start a worker.
    if spec.get('enabled') or spec.get('run_now'):raise ValueError('Enable the saved schedule separately after setup')


def apply(root, session, spec):
    validate(spec)
    require_session(root,session)
    if session.role!='admin':raise PermissionError('Sign in as an administrator to create persistent missions, as required by the Missions interface')
    key,context=session_key(root,session)
    if session.username.casefold()!=spec['target_username'].casefold():raise PermissionError('Sign in to the receiving account named in this setup request')
    stamp=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    with process_lock(private_path(root,'Data/Accounts/setup.lock',context=context)):
        data=read(root,key=key);saved=data['setups'].get(spec['id'])
        if saved and saved['request_sha256']!=stamp:raise ValueError('This setup ID already belongs to different input data')
        if not saved:
            from mission_accounts import Accounts
            from account_import import collect
            old=Accounts(root).profiles()
            try:profiles,secrets=collect(root,spec['sources'])
            except Exception:raise RuntimeError('Credential import failed. Check the selected files and original Windows/GitHub sign-in; source credentials were preserved. No secret-bearing diagnostics are displayed.') from None
            if old.keys() & profiles.keys():raise ValueError('A connection name is already in use; choose new names instead of overwriting it')
            data['profiles'].update(profiles);data['secrets'].update(secrets)
            saved={'request_sha256':stamp,'mission_id':uuid.uuid4().hex,'schedule_id':None,
                   'connections':list(profiles),'state':'imported','created_at':time.time()}
            data['setups'][spec['id']]=saved;write(root,session,data)
        unlock_session(root,session)
        store=Missions(root);mid=saved['mission_id']
        if not store.checkpoint_path(mid).exists():
            if saved['state']=='complete':raise RuntimeError('A previously created mission is missing; setup will not recreate or arm it')
            store.create(spec['objective'],'full',spec['max_steps'],mission_id=mid)
        mission=store.load(mid)
        if mission['objective']!=spec['objective'] or mission['mode']!='full':raise RuntimeError('Setup mission changed; existing records are preserved')
        MissionCatalog(root,store=store).mark_origin(mid)
        schedules=Schedules(root)
        if not saved['schedule_id']:
            # Recover publication if a previous process ended after create()
            # and before its encrypted setup receipt was persisted.
            matches=[s for s in schedules.list() if s.get('source_mission')==mid]
            if len(matches)>1:raise RuntimeError('Multiple schedules reference this setup mission; review the existing records')
            schedule=matches[0] if matches else schedules.create(spec['objective'],'full',spec['max_steps'],
                spec['interval_seconds'],max_runs=spec['max_runs'],source_mission=mid,origin='user')
            saved['schedule_id']=schedule['id'];write(root,session,data)
        schedule=schedules.load(saved['schedule_id'])
        if schedule.get('source_mission')!=mid:raise RuntimeError('Setup schedule association changed')
        if saved['state']!='complete':
            schedules.set_autonomous_recovery(schedule['id'],spec.get('autonomous_recovery',False))
            saved.update(state='complete',finished_at=time.time());write(root,session,data)
        # This receipt has no source paths, addresses, secrets, or auth material.
        from mission_supervisor import read_policy
        return {'verified':True,'mission_id':mid,'schedule_id':schedule['id'],
            'connections':saved['connections'],'mission_armed':bool(read_policy(store,mid).get('enabled')) ,
            'schedule_enabled':schedules.enabled(schedule),'setup_id':spec['id']}


def check_connections(root, session, names):
    """Read-only service checks, no mail send, post, repository write or transfer."""
    require_session(root,session)
    session_key(root,session)
    from mission_accounts import Accounts
    api=Accounts(root);profiles=api.profiles();results={}
    operations={'imap-smtp':'email_list','evm':'wallet_balance','github':'github_identity','moltbook':'moltbook_status'}
    for name in names:
        session_key(root,session)
        try:
            op=operations[profiles[name]['backend']]
            value=api.call({'id':'connection-check','steps':0,'mode':'full'},name,op,{})
            results[name]={'status':'verified','operation':op}
            if op=='github_identity':results[name]['login']=value['result']['login']
            if op=='moltbook_status':
                state=value['result'].get('status')
                results[name]['claim_status']=state if state in ('claimed','pending_claim') else 'unknown'
        except Exception:results[name]={'status':'check_failed','next_step':'Review service authentication/network access; imported encrypted credentials are retained.'}
    return results
