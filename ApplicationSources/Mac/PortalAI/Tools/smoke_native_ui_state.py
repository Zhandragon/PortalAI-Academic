"""Real Windows GUI, real disposable login and seal; native read-only HTTP probe."""
import http.client
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent')]


def main():
    from validation_artifacts import ValidationArtifacts
    from smoke_login_continuity import run
    import remote_desktop_input as remote
    import account_gate
    from native_ui_protocol import PROTOCOL, MAX_FRAME, encode, decode, validate_envelope
    artifacts=ValidationArtifacts(ROOT,ROOT/'Maintenance/Validation/NativeUIExporter')
    folder=artifacts.path('endpoints');folder.mkdir(exist_ok=True)
    state={'http_samples_ms':[],'effects_submitted':False,'lock_revoked_old_binding':False}
    original_lock=account_gate.GUIAccountGate.lock

    def install(app,root):
        adapter=remote.InputAdapter(app,folder)
        app._portalai_projection_adapter=adapter
        app._portalai_native_state_folder=folder
        return adapter

    def request(exporter,path,body,token=None):
        start=time.perf_counter()
        conn=http.client.HTTPConnection('127.0.0.1',exporter.server.server_port,timeout=3)
        try:
            conn.request('POST',path,encode(body),{'Authorization':'Bearer '+(token or exporter.token)})
            response=conn.getresponse();raw=response.read(MAX_FRAME+1)
            state['http_samples_ms'].append(round(1000*(time.perf_counter()-start),2))
            return response.status,decode(raw)
        finally:conn.close()

    def bind(exporter):
        generation=uuid.uuid4().hex
        code,value=request(exporter,'/native/v2/bind',{'protocol':PROTOCOL,'generation':generation})
        assert code==200
        return {'protocol':PROTOCOL,'generation':generation,**value['binding']}

    def locked(gate):
        original_lock(gate)
        exporter=getattr(gate.app,'_portalai_native_exporter',None)
        if exporter is not None and state.get('bound'):
            code,value=request(exporter,'/native/v2/snapshot',state['bound'])
            assert code==409 and 'snapshot' not in value
            fresh=bind(exporter);code,value=request(exporter,'/native/v2/snapshot',fresh)
            assert code==200
            snapshot=value['snapshot'];assert snapshot['account']['state']!='ready'
            assert set(snapshot)=={'version','view','epoch','revision','account'}
            assert snapshot['account']['displayName']==''
            state['lock_revoked_old_binding']=True

    def inspector(built,app,destination):
        exporter=app._portalai_native_exporter
        assert exporter.gate.session is built['account_gate'].session
        assert exporter.profile.identity is not None
        assert exporter.token!=app._portalai_projection_adapter.token
        panel=built['native_chat_panel'];settings=built['settings_page']
        # Only this disposable chat's in-memory fixture content; never submit.
        original=json.loads(json.dumps(panel.session))
        panel.session['messages']=[{'role':'user','content':'Synthetic native UI draft fixture'},
            {'role':'assistant','content':'Synthetic display text <img src=x onerror=alert(1)>'}]
        exporter.observe({'telemetry':{'cpu':None,'gpu':None,'ram':25},
            'settings_models':[{'id':'qwen1.7-q8','label':'Synthetic installed model','installed':True}],
            'installed':{'model_qwen1.7-q8':('NOT INSTALLED','synthetic metadata')}})
        exporter.tick();state['bound']=bind(exporter)
        code,value=request(exporter,'/native/v2/snapshot',state['bound'])
        assert code==200;validate_envelope(value)
        snapshot=value['snapshot'];assert snapshot['account']['state']=='ready'
        assert snapshot['account']['displayName']=='StartupFixture'
        assert len(snapshot['chat']['messages'])==2 and snapshot['runtime']['gpu'] is None
        assert snapshot['packages'][0]['id']=='model_qwen1.7-q8'
        assert '<img' in snapshot['chat']['messages'][1]['text']
        assert 'Private' not in encode(value).decode()
        state['real_GUI_read_verified']=True
        state['wire_bytes']=len(encode(value))
        before=snapshot['settings']['backend']
        settings.variables['backend'].set('cpu' if before!='cpu' else 'auto')
        exporter.tick();code,value=request(exporter,'/native/v2/snapshot',state['bound'])
        assert code==200 and value['snapshot']['settings']['backend']==before
        state['unsaved_GUI_draft_not_exported']=True
        code,_=request(exporter,'/native/v2/bind',{'protocol':PROTOCOL,'generation':'wrong-token'},
                       token=app._portalai_projection_adapter.token)
        assert code==409;state['projection_capability_rejected']=True
        # The main thread is deliberately NOT pumping Tk while HTTP executes.
        # Read-state still responds from memory; a stale GUI cache fails closed.
        exporter.published_at-=3
        code,_=request(exporter,'/native/v2/snapshot',state['bound'])
        assert code==409;state['GUI_stall_revokes_view']=True
        exporter.tick();state['bound']=bind(exporter)
        for _ in range(3):
            code,value=request(exporter,'/native/v2/snapshot',state['bound'])
            assert code==200;validate_envelope(value)
        panel.session=original
        state['telemetry_source']='synthetic; normal monitor suppressed by disposable GUI fixture'

    with patch.object(remote,'install',install),patch.object(account_gate.GUIAccountGate,'lock',locked):
        result=run(artifacts.path(),inspector=inspector)
    assert state['lock_revoked_old_binding']
    assert not list(folder.glob('native-gui-*.json'))
    state.pop('bound',None)
    result.update(state);result['endpoint_removed']=True
    artifacts.path('result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
