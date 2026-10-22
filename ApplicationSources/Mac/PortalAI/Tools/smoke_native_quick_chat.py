"""Disposable full GUI/account, actual input queue and submit; fixture inference."""
import copy
import http.client
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent')]
from smoke_login_continuity import run
from validation_artifacts import ValidationArtifacts
from writer_jobs import WriterJobs
THREAD=WriterJobs.thread
import remote_desktop_input as remote


def main():
    artifacts=ValidationArtifacts(ROOT,ROOT/'Maintenance/Validation/NativeQuickChat')
    folder=artifacts.path('endpoints');folder.mkdir(exist_ok=True)
    evidence={'fixture_inference':True,'production_messages_submitted':False}

    def install(app,root):
        adapter=remote.InputAdapter(app,folder)
        app._portalai_projection_adapter=adapter;app._portalai_native_state_folder=folder
        return adapter

    def inspect(built,app,destination):
        panel=built['native_chat_panel'];ex=app._portalai_native_exporter;adapter=app._portalai_projection_adapter
        assert Path(built['root'])!=ROOT
        assert json.loads(adapter.path.read_text())['native_chat_protocol']==1
        assert ex.allowed(authenticate=True)
        original_thread=panel._thread
        panel._thread=lambda **kw: THREAD(panel._writer_jobs,**kw) if kw.get('name')=='PortableAINativeChatAgent' else original_thread(**kw)
        panel.settings['auto_title_chats']=False
        panel.compact_context_if_needed=lambda:False
        panel.api_messages=lambda:(copy.deepcopy(panel.session['messages']),0)
        model={'admit':True,'hold':False,'calls':0}
        def prepare(cancel):
            if not model['admit']:raise RuntimeError('Synthetic model admission refused')
            return True
        panel.effort.prepare_request=prepare
        def complete(*args):
            model['calls']+=1
            if model['hold']:
                if not panel.cancel_event.wait(4):raise TimeoutError('Fixture cancellation missing')
                return '', '', [], False
            return 'Synthetic quick-chat response', '', [], False
        panel._completion_with_tool_repair=complete
        built['show_tab']('controls');app.update()
        panel.prompt.insert('1.0','Local desktop draft retained')
        panel.prompt.mark_set('insert','1.7');panel.prompt.tag_add('sel','1.2','1.5')
        app.focus_force();app.update()

        def surface():
            return (panel.prompt.get('1.0','end'),panel.prompt.index('insert'),
                    tuple(map(str,panel.prompt.tag_ranges('sel'))),str(app.focus_get()),app.geometry(),
                    copy.deepcopy(built.get('selected_tab')))
        before=surface()
        def payload(op='send'):
            ex.tick()
            return {'request_id':uuid.uuid4().hex,'viewer':'1'*32,'operation':op,
                    'binding':{'view':ex.view,'epoch':ex.epoch},'conversation':panel.session['id'],
                    **({'text':'Synthetic quick-chat test'} if op=='send' else {})}
        def request(p,ttl=3):
            values=[];started=time.perf_counter()
            item={'request_id':uuid.uuid4().hex,'hwnd':adapter.hwnd,'expires_at':time.monotonic()+ttl,
                  'event':{'kind':'native_chat','payload':p}}
            def network():
                conn=http.client.HTTPConnection('127.0.0.1',adapter.server.server_port,timeout=6)
                try:
                    conn.request('POST','/input',json.dumps(item),{'Authorization':'Bearer '+adapter.token})
                    response=conn.getresponse();values.append((response.status,json.loads(response.read())))
                finally:conn.close()
            worker=threading.Thread(target=network);worker.start()
            end=time.monotonic()+7
            while worker.is_alive() and time.monotonic()<end:app.update();time.sleep(.005)
            worker.join(.1);assert values,'Missing bounded GUI acknowledgement'
            evidence.setdefault('ack_ms',[]).append(round(1000*(time.perf_counter()-started),1))
            return values[0]
        def idle():
            until=time.monotonic()+4
            while panel.busy and time.monotonic()<until:app.update();time.sleep(.01)
            assert not panel.busy,'Chat did not become idle'
        p=payload();code,reply=request(p)
        assert code==200 and reply['accepted'] and reply['request_id']==p['request_id']
        idle();assert model['calls']==1 and surface()==before
        assert panel.store.load_session(panel.session['id'])['messages'][-1]['content']=='Synthetic quick-chat response'
        code,_=request(p);assert code==200 and model['calls']==1
        code,_=request({**p,'text':'Conflicting text'});assert code==400 and model['calls']==1
        evidence['full_desktop_send_draft_caret_focus_page_preserved']=True
        evidence['duplicate_exactly_once_and_conflict_refused']=True
        for bad,ttl in [({**payload(),'conversation':'different'},3),(payload(),-1),
                        ({**payload(),'binding':{'view':'f'*32,'epoch':'e'*32}},3)]:
            code,_=request(bad,ttl);assert code==400 and surface()==before
        model['admit']=False;code,_=request(payload());assert code==400
        idle();assert model['calls']==1 and surface()==before
        evidence['failed_model_admission_is_error_without_inference']=True
        saved_thread=panel._thread
        def unavailable(**kw):
            if kw.get('name')=='PortableAINativeChatAgent':raise RuntimeError('Synthetic writer start failure')
            return saved_thread(**kw)
        panel._thread=unavailable
        code,_=request(payload());assert code==400
        idle();assert model['calls']==1 and surface()==before
        panel._thread=saved_thread
        evidence['failed_writer_start_is_error_and_releases_busy_state']=True
        model.update(admit=True,hold=True)
        code,_=request(payload());assert code==200 and panel.busy
        calls=model['calls'];code,_=request(payload());assert code==400
        code,_=request({**payload('stop'),'conversation':'different'});assert code==400
        assert not panel.cancel_event.is_set()
        code,_=request(payload('stop'));assert code==200
        idle();assert model['calls']==calls and surface()==before
        evidence['busy_rejected_bound_stop_cancels_actual_worker']=True
        panel._memory_paused_by_stop=True
        ex.tick();assert ex.cache['account']['state']=='ready'
        assert any(m['role']=='assistant' for m in ex.cache['chat']['messages'])
        evidence['native_v2_reflects_fixture_response']=True

    with patch.object(remote,'install',install):
        result=run(artifacts.path(),inspector=inspect)
    result.update(evidence)
    result['endpoint_removed']=not list(folder.glob('*.json'))
    assert result['endpoint_removed']
    artifacts.path('result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
