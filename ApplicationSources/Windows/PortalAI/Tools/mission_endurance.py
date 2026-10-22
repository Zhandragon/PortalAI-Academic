"""Wall-clock mission/schedule/memory/account endurance test with a fixed planner.

Uses isolated SSD state and mock accounts, never a live model/account or host
shell action. This validates the controller over elapsed time, not LLM quality.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_runner import Missions,process_lock
from mission_schedule import Schedules
from mission_supervisor import Supervisor,pause_all
from runtime_policy import atomic_json,portable_env,require_space


def case_root(case):
    if not re.fullmatch(r'[a-f0-9]{32}',case):raise ValueError('Invalid endurance case ID')
    return ROOT/'Maintenance/Endurance'/case


def create(hours):
    if not 0 < hours <= 168:raise ValueError('Endurance duration must be positive and at most 168 hours')
    require_space(ROOT,256*1024**2,for_outputs=True)
    case=uuid.uuid4().hex;root=case_root(case)
    policy=json.loads((ROOT/'Agent/hardware_profiles.json').read_text(encoding='utf-8'))
    atomic_json(root/'Agent/hardware_profiles.json',{'storage':policy['storage']})
    atomic_json(root/'Data/Accounts/profiles.json',{'simulation':{'backend':'mock','enabled':True,
                'permissions':['wallet_balance','wallet_send']}})
    atomic_json(root/'Data/Accounts/Simulated/simulation.json',{'inbox':[],'outbox':[],
                'balance_wei':'100000','transactions':[]})
    schedule=Schedules(root).create('Fixed-planner endurance: preserve schedule memory and record one simulated transfer per run.',
                                    mode='full',max_steps=6,interval_seconds=60,max_runs=0)
    Schedules(root).enable(schedule['id'])
    config={'version':2,'case':case,'created_at':time.time(),'requested_hours':hours,
            'deadline':time.time()+hours*3600,'schedule':schedule['id'],'planner':'fixed, no LLM',
            'accounts':'mock only','status':'created','automatic_host_startup':False}
    atomic_json(root/'case.json',config)
    return config


def fixed_action(mission,prior_completed=False):
    step=mission['steps']
    if step==0:return {'action':'recall','query':'endurance-sentinel'}
    if step==1:
        if prior_completed and 'PORTAL_ENDURANCE_MEMORY_OK' not in mission['history'][-1]['result']:
            raise AssertionError('Previous scheduled-run memory was not retained')
        return {'action':'remember','key':'endurance-sentinel','text':'PORTAL_ENDURANCE_MEMORY_OK'}
    if step==2:return {'action':'account','profile':'simulation','operation':'wallet_send',
                       'parameters':{'to':'0x'+'1'*40,'value_wei':'1'}}
    if step==3:return {'action':'recall','query':'endurance-sentinel'}
    if step==4:
        if 'PORTAL_ENDURANCE_MEMORY_OK' not in mission['history'][-1]['result']:
            raise AssertionError('Scheduled-run memory recall did not retain the sentinel')
        return {'action':'complete','text':'Memory checked; one simulated transfer recorded.'}
    raise AssertionError('Unexpected endurance mission step')


def worker(root,mid,steps):
    # Same gate contract as mission_runner.main; no work before OS ownership.
    gate=os.environ.get('PORTALAI_MISSION_GATE')
    if not gate:raise RuntimeError('Endurance worker requires a supervisor gate')
    deadline=time.monotonic()+15
    while not Path(gate).exists():
        if time.monotonic()>deadline:raise RuntimeError('Endurance supervisor did not open its gate')
        time.sleep(.05)
    config=json.loads((root/'case.json').read_text())
    if config.get('accounts')!='mock only' or config.get('version')!=2:raise RuntimeError('Endurance account/version contract differs')
    profiles=json.loads((root/'Data/Accounts/profiles.json').read_text())
    if set(profiles)!={'simulation'} or profiles['simulation']['backend']!='mock':
        raise RuntimeError('Endurance only accepts its isolated mock account')
    store=Missions(root);prior=any(m['status']=='complete' for m in store.list())
    store.run(mid,steps=steps,model=lambda m:fixed_action(m,prior))


def audit(root):
    store=Missions(root);missions=store.list()
    if store.load_errors:raise RuntimeError('Unreadable endurance checkpoint')
    review=[m['id'] for m in missions if m['status'] in ('needs_review','budget_exhausted')]
    if review:raise RuntimeError('Endurance action needs review; never replay it: '+','.join(review))
    state=json.loads((root/'Data/Accounts/Simulated/simulation.json').read_text())
    journals=[json.loads(p.read_text()) for p in (root/'Data/Accounts/Journal').glob('*.json')]
    if any(j['status']!='confirmed' for j in journals):raise RuntimeError('Uncertain simulated effect; review required')
    hashes=[r['transaction_hash'] for r in state['transactions']]
    if len(hashes)!=len(set(hashes)) or len(hashes)!=len(journals) or int(state['balance_wei'])!=100000-len(hashes):
        raise AssertionError('Simulated account ledger/idempotency invariant failed')
    complete=[m for m in missions if m['status']=='complete']
    for m in complete:
        sends=[h for h in m['history'] if h['action'].get('operation')=='wallet_send']
        if len(sends)!=1 or m['steps']!=5:raise AssertionError('Completed endurance run differs from expected five actions')
    return {'missions':len(missions),'completed':len(complete),'confirmed_simulated_transfers':len(hashes),
            'balance_wei':state['balance_wei'],'pending_review':review}


def run(case):
    root=case_root(case);config=json.loads((root/'case.json').read_text())
    if config.get('version')!=2:raise RuntimeError('Endurance case uses an older test contract; create a new case')
    if config['status'] in ('complete','stopped','needs_review'):
        raise RuntimeError('This endurance case has ended; inspect its report, then create a new case')
    os.environ.pop('PORTALAI_ACCOUNT_UNLOCK',None)
    from platform_runtime import python_path
    py=python_path(ROOT)
    command=[str(py),'-B',str(Path(__file__).resolve()),'--case',case,'worker']
    supervisor=Supervisor(root,worker_command=command,model_ready=lambda:True)
    previous=json.loads((root/'report.json').read_text()) if (root/'report.json').exists() else {}
    report={'case':case,'status':'running','planner':'fixed; no model inference','accounts':'mock only',
            'requested_hours':config['requested_hours'],'started_at':config['created_at'],
            'observed_seconds':previous.get('observed_seconds',0),'sessions':previous.get('sessions',0)+1,
            'passed':False,'multi_day_completed':False}
    with process_lock(root/'endurance.lock'),process_lock(supervisor.store.base/'supervisor.lock'):
        config['status']='running';atomic_json(root/'case.json',config)
        started=time.monotonic();last_save=0;prior=report['observed_seconds']
        try:
            while time.time()<config['deadline'] and not (root/'STOP').exists():
                if not supervisor.tick():raise RuntimeError('Endurance supervision stopped before its deadline')
                now=time.monotonic()
                if now-last_save>=5:
                    if supervisor.worker is None:
                        with process_lock(supervisor.store.base/'execution.lock'):report['checks']=audit(root)
                    require_space(ROOT,for_outputs=True)
                    report.update(observed_seconds=round(prior+now-started,2),last_heartbeat=time.time())
                    atomic_json(root/'report.json',report);last_save=now
                time.sleep(.5)
            report['status']='stopped' if (root/'STOP').exists() else 'complete'
        except BaseException as exc:
            report.update(status='needs_review',error=type(exc).__name__+': '+str(exc))
            raise
        finally:
            pause_all(root);supervisor.finish_worker(cancelled=True)
            report.update(observed_seconds=round(prior+time.monotonic()-started,2),finished_at=time.time())
            # Deadline can land during an in-flight effect. Never turn cancellation
            # into a pass; an uncertain final action is preserved for review.
            try:
                report['checks']=audit(root)
                report['passed']=report['status']=='complete' and report['checks']['completed']>0
            except Exception as exc:report.update(status='needs_review',passed=False,error=str(exc))
            report['multi_day_completed']=report['passed'] and report['observed_seconds']>=48*3600
            config['status']=report['status'];atomic_json(root/'case.json',config);atomic_json(root/'report.json',report)
    return report


def status(root):
    """Distinguish persisted evidence from a currently running controller."""
    path=root/'report.json'
    if not path.exists():return {'status':'no-report','controller_running':False}
    report=json.loads(path.read_text())
    try:
        with process_lock(root/'endurance.lock'):alive=False
    except OSError:alive=True
    report['controller_running']=alive
    if report.get('status')=='running' and not alive:
        report.update(saved_status='running',status='interrupted',passed=False,multi_day_completed=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case')
    sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('start');p.add_argument('--hours',type=float,default=72);p.add_argument('--background',action='store_true')
    sub.add_parser('run');sub.add_parser('status');sub.add_parser('stop')
    p=sub.add_parser('worker');p.add_argument('worker_command',choices=['run']);p.add_argument('mission');p.add_argument('--steps',type=int,default=1)
    args=parser.parse_args()
    if args.command=='start':
        cfg=create(args.hours);case=cfg['case'];root=case_root(case)
        if args.background:
            env=portable_env(ROOT);env.pop('PORTALAI_ACCOUNT_UNLOCK',None)
            with (root/'controller.log').open('ab') as log:
                proc=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'--case',case,'run'],
                     cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),start_new_session=os.name!='nt')
            print(json.dumps({'case':case,'pid':proc.pid,'report':str(root/'report.json'),'simulated_accounts_only':True}))
        else:print(json.dumps(run(case)))
    else:
        root=case_root(args.case or '')
        if args.command=='run':print(json.dumps(run(args.case)))
        elif args.command=='worker':worker(root,args.mission,args.steps)
        elif args.command=='stop':(root/'STOP').touch();pause_all(root);print('Endurance stop requested; no production mission was changed.')
        else:print(json.dumps(status(root),indent=2))


if __name__=='__main__':main()
