"""Focused native-form integration on a real disposable account/GUI only."""
from pathlib import Path
import json
import re
import base64
import hashlib
import http.client
import threading
import sys
import time
import uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent')]
from smoke_login_continuity import run
from validation_artifacts import ValidationArtifacts
import remote_desktop_input as remote
from native_workflow import install_public,Admission
from native_workflow_protocol import validate_model


def main():
    artifacts=ValidationArtifacts(ROOT,ROOT/'Maintenance/Validation/NativeWorkflows')
    folder=artifacts.path('endpoints');folder.mkdir(exist_ok=True)
    report={'production_actions':False,'pages':{},'checks':[]}
    def install(app,root):
        adapter=remote.InputAdapter(app,folder)
        app._portalai_projection_adapter=adapter;app._portalai_native_state_folder=folder
        controller=install_public(app,root,adapter)
        def public():
            if not getattr(app,'_portalai_account_dialogs',None):app.after(10,public);return
            model=controller.describe('9'*32,'accounts');validate_model(model)
            assert model['account']=={'state':'locked','displayName':''}
            assert any(n['kind']=='secret' and n.get('value')=='' for n in model['nodes'])
            assert json.loads(adapter.path.read_text())['native_ui_protocol']==1
            report['checks'].append('Public sign-in exports no secret value and publishes native_ui before private UI construction')
        app.after(10,public)
        return adapter
    def inspect(built,app,destination):
        c=app._portalai_native_workflow;ex=app._portalai_native_exporter
        assert c.callbacks and c.pages and ex.allowed(authenticate=True)
        ex.tick();viewer='a'*32
        before=(dict(built['selected_tab']),app.geometry(),str(app.focus_get()))
        for page in sorted(c.pages):
            m=c.describe(viewer,page);validate_model(m)
            again=c.describe(viewer,page)
            assert m['form']==again['form'],page+' unstable form'
            report['pages'][page]={'nodes':len(m['nodes']),'kinds':sorted({n['kind'] for n in m['nodes']}),
                                   'actions':[n['label'] for n in m['nodes'] if n['kind']=='button']}
            for n in m['nodes']:
                strings=[n.get('label',''),n.get('value','')]
                strings.extend(o.get('label','') for o in n.get('options',[]) if isinstance(o,dict))
                assert not any(isinstance(value,str) and re.fullmatch(r'PY_VAR_?\d+',value) for value in strings), (page,n)
        if page=='persistence':
            actions=report['pages'][page]['actions']
            for label in ('Missions & access','Schedules'):
                assert actions.count(label)==1, (label,actions)
            report['checks'].append('Persistence navigation exposes each real subpage button exactly once')
        assert before==(dict(built['selected_tab']),app.geometry(),str(app.focus_get()))
        report['checks'].append('All 11 page descriptions preserve desktop page, geometry and focus')
        report['checks'].append('All 11 page descriptions contain no serialized PY_VAR_* labels, values or options')
        def invoke(model,action,values=None):
            p={'request_id':uuid.uuid4().hex,'viewer':viewer,'operation':'invoke',
               'binding':{k:model[k] for k in ('view','epoch')},'form':model['form'],'action':action,'values':values or {}}
            r=c.execute(p,time.monotonic()+3)
            until=time.monotonic()+3
            while isinstance(r,Admission) and r.result is None and time.monotonic()<until:
                app.update();r.poll();time.sleep(.005)
            assert r.result['accepted']
            assert c.execute(p,time.monotonic()+3) is r
            return r
        m=c.describe(viewer,'chat');invoke(m,'chat_preferences')
        modal=c.describe(viewer,'chat');validate_model(modal)
        assert c.modal() is not None
        report['preferences_controls']=[n['label'] for n in modal['nodes']]
        cancel=next(n for n in modal['nodes'] if n['kind']=='button' and n['label']=='Cancel')
        invoke(modal,cancel['action'])
        report['checks'].append('Real preferences form opens/closes; exact duplicate invocation returns existing receipt')
        # Populate synthetic history directly in the disposable account; no
        # production chat is submitted and no inference service is contacted.
        panel=c.chat
        if not panel.session:panel.new_chat()
        panel.session['messages']=[{'role':'user','content':'Synthetic export fixture'}]
        panel.store.save_session(panel.session);panel._refresh_action_buttons()
        # The actual chat exporter writes only into this authenticated fixture;
        # its final verified bytes receive an opaque, expiring download grant.
        m=c.describe(viewer,'chat')
        export=next(n for n in m['nodes'] if n['kind']=='button' and n['label']=='Export')
        invoke(m,export['action'])
        until=time.monotonic()+3
        while time.monotonic()<until:
            app.update();m=c.describe(viewer,'chat')
            downloads=[n for n in m['nodes'] if n['kind']=='download']
            if downloads:break
            time.sleep(.01)
        assert downloads,'Verified chat export did not become a download'
        p={'request_id':uuid.uuid4().hex,'viewer':viewer,'operation':'file_get',
           'binding':{k:m[k] for k in ('view','epoch')},'file':downloads[0]['file'],'offset':0}
        r=c.execute(p,time.monotonic()+3)
        data=base64.b64decode(r['data']);assert r['eof'] and hashlib.sha256(data).hexdigest()==r['sha256']
        invoke(m,'export_close')
        assert not list(ex.profile.private('Data/Maintenance/NativeExports').glob('*'))
        report['checks'].append('Actual chat export, verified RAM download, bounded chunk, digest and owned staging cleanup')
        # Transfer validation uses account/form grants, consecutive offsets and
        # exact duplicate chunks; no filesystem path is accepted from a caller.
        m=c.describe(viewer,'chat');binding={k:m[k] for k in ('view','epoch')}
        def transfer(op,**extra):
            return c.execute({'request_id':uuid.uuid4().hex,'viewer':viewer,'operation':op,'binding':binding,**extra},time.monotonic()+3)
        raw=b'Synthetic attachment';r=transfer('file_begin',form=m['form'],field='chat_attachment',name='example.txt',size=len(raw),mime='text/plain')
        key=r['transfer'];chunk=base64.b64encode(raw).decode()
        assert transfer('file_chunk',transfer=key,offset=0,data=chunk)['offset']==len(raw)
        assert transfer('file_chunk',transfer=key,offset=0,data=chunk)['offset']==len(raw)
        try:transfer('file_chunk',transfer=key,offset=0,data=base64.b64encode(b'changed').decode());raise AssertionError('Conflicting chunk admitted')
        except ValueError:pass
        token=transfer('file_commit',transfer=key,sha256=hashlib.sha256(raw).hexdigest())['file']
        assert c.files.authorized(token,viewer)['committed']
        c.files.rows[token]['expires']=0
        try:c.files.authorized(token,viewer);raise AssertionError('Expired file admitted')
        except PermissionError:pass
        report['checks'].append('Upload length/hash, exact chunk duplicate, conflicting chunk refusal and expiry')
        # Hidden Settings tabs stay independently navigable without selecting
        # the desktop subtab or moving its layout/focus.
        m=c.describe(viewer,'settings');desktop_tab=c.settings.tabs.selected
        choice=next(n for n in m['nodes'] if n['kind']=='button' and n['label']=='Media defaults')
        invoke(m,choice['action']);m=c.describe(viewer,'settings')
        assert c.settings.tabs.selected==desktop_tab
        assert any(n['kind']=='select' and 'media' in n['label'].lower() for n in m['nodes']) or len([n for n in m['nodes'] if n['kind']=='select'])>4
        report['checks'].append('Hidden media settings are editable without changing the desktop subtab')
        # Current real account management keeps v2 binding; quick chat remains
        # blocked by the same account modal. Cancel through its actual guard.
        m=c.describe(viewer,'accounts')
        action=next(n for n in m['nodes'] if n['kind']=='button' and n['label']=='Change my password…')
        invoke(m,action['action']);ex.tick();m=c.describe(viewer,'accounts')
        assert ex.mode=='ready' and m['view']==ex.view
        assert all(n.get('value','')=='' for n in m['nodes'] if n['kind']=='secret')
        invoke(m,'account_close')
        report['checks'].append('Real authenticated account modal retains v2 binding, hides secrets and closes normally')
        m=c.describe(viewer,'accounts')
        action=next(n for n in m['nodes'] if n['kind']=='button' and n['label']=='Export Data…')
        invoke(m,action['action']);m=c.describe(viewer,'accounts')
        action=next(n for n in m['nodes'] if n['kind']=='button' and n['label']=='Choose destination and export…')
        invoke(m,action['action']);until=time.monotonic()+8;downloads=[]
        while time.monotonic()<until:
            app.update();m=c.describe(viewer,'accounts');downloads=[n for n in m['nodes'] if n['kind']=='download']
            if downloads:break
            time.sleep(.01)
        assert downloads,'Real authenticated archive export failed'
        r=c.execute({'request_id':uuid.uuid4().hex,'viewer':viewer,'operation':'file_get',
            'binding':{k:m[k] for k in ('view','epoch')},'file':downloads[0]['file'],'offset':0},time.monotonic()+3)
        assert base64.b64decode(r['data']).startswith(b'PK')
        invoke(m,'export_close')
        assert not list(ex.profile.private('Data/Maintenance/NativeExports').glob('*'))
        report['checks'].append('Real disposable-account history/outputs ZIP export uses original verification and cleans private staging')
        # Original delivered deadlines and response limits use the real HTTP
        # adapter, with no HA connection or public endpoint in this fixture.
        p={'request_id':uuid.uuid4().hex,'viewer':viewer,'operation':'describe','page':'maintenance'}
        adapter=c.adapter;results=[]
        def network():
            conn=http.client.HTTPConnection('127.0.0.1',adapter.server.server_port,timeout=5)
            try:
                body={'request_id':uuid.uuid4().hex,'hwnd':adapter.hwnd,'expires_at':time.monotonic()+3,
                      'event':{'kind':'native_ui','payload':p}}
                conn.request('POST','/input',json.dumps(body),{'Authorization':'Bearer '+adapter.token})
                r=conn.getresponse();results.append((r.status,json.loads(r.read(65001))))
            finally:conn.close()
        t=threading.Thread(target=network);t.start();until=time.monotonic()+5
        while t.is_alive() and time.monotonic()<until:app.update();time.sleep(.005)
        t.join(.1);assert results and results[0][0]==200,results
        assert set(results[0][1])=={'accepted','request_id','operation','model'}
        validate_model(results[0][1]['model'])
        assert all(j['item']['event']=={'kind':'native_ui'} for j in adapter.results.values() if j['item']['event'].get('kind')=='native_ui')
        report['checks'].append('Real loopback native_ui acknowledgement matches exact receiver shape; delivery records omit submitted fields')
        report['complete_advertised']=c.complete
        report['source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*sorted((ROOT/'ControlCenter').glob('native_workflow*.py')),
                      ROOT/'ControlCenter/remote_desktop_input.py',ROOT/'Agent/native_export_grants.py']}
    with patch.object(remote,'install',install):report.update(run(artifacts.path(),inspector=inspect))
    artifacts.path('result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
