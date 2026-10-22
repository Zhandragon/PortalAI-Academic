"""Real local sockets/OS locks with disposable mission records; no model needed."""
import http.server
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'Agent')]
from profile_paths import UID_ENV,EPOCH_ENV
from mission_runner import Missions,process_lock
from mission_schedule import Schedules
from mission_supervisor import Supervisor,arm,read_policy,disarm
from mission_memory import Memory
from chat_priority import Foreground,active,planning_json,YieldToChat

class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'Agent').mkdir();(self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.env=patch.dict(os.environ,{},clear=False);self.env.start();os.environ.pop(UID_ENV,None);os.environ.pop(EPOCH_ENV,None)
        self.store=Missions(self.root);self.fg=None;self.threads=[]
    def tearDown(self):
        if self.fg:self.fg.close()
        for t in self.threads:t.join(3)
        self.env.stop();self.temp.cleanup()
    def thread(self,fn):
        t=threading.Thread(target=fn,daemon=True);t.start();self.threads.append(t);return t
    def wait(self,fn):
        end=time.monotonic()+4
        while not fn() and time.monotonic()<end:time.sleep(.01)
        self.assertTrue(fn())
    def claim(self):
        self.fg=Foreground(self.root);self.cancel=threading.Event();self.notices=[]
        self.thread(lambda:self.fg.acquire(self.cancel,lambda:None,self.notices.append));self.wait(lambda:active(self.root))
    def test_current_tool_finishes_once_then_checkpoints_before_chat(self):
        m=self.store.create('Finish two explicit fixture steps');arm(self.root,m['id'])
        begun=threading.Event();finish=threading.Event();returned=[]
        def tool(m,a):begun.set();finish.wait(3);return 'Fixture result with output path and completed effect'
        with patch.object(self.store,'execute',side_effect=tool) as execute:
            worker=self.thread(lambda:returned.append(self.store.run(m['id'],steps=5,model=lambda m:{'action':'note','text':'fixture'})))
            self.assertTrue(begun.wait(2));self.claim();time.sleep(.05);self.assertFalse(self.fg.acquired)
            finish.set();self.wait(lambda:self.fg.acquired);worker.join(2);execute.assert_called_once()
        saved=self.store.load(m['id']);self.assertTrue(saved['chat_paused']);self.assertEqual(saved['steps'],1);self.assertIsNone(saved['pending_action']);self.assertTrue(read_policy(self.store,m['id'])['enabled'])
        notes=Memory(self.store,saved).recall('Fixture result');self.assertTrue(notes);self.assertIn('completed_records',notes[0]['text'])
        self.fg.close();final=self.store.run(m['id'],model=lambda m:{'action':'complete','summary':'continued once'})
        self.assertEqual(final['status'],'complete');self.assertEqual(final['steps'],2);self.assertEqual(len(final['history']),2)
    def test_planning_socket_is_interrupted_without_action_or_budget_use(self):
        begun=threading.Event();release=threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']));begun.set();release.wait(4)
                try:self.send_response(200);self.end_headers();self.wfile.write(b'{"action":"note","text":"must not execute"}')
                except OSError:pass
            def log_message(self,*args):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        self.thread(server.serve_forever)
        try:
            m=self.store.create('A plan which should yield');result=[]
            with patch.object(self.store,'execute') as execute:
                worker=self.thread(lambda:result.append(self.store.run(m['id'],model=lambda m:planning_json(self.root,'http://127.0.0.1:'+str(server.server_port)+'/plan',{'fixture':True}))))
                self.assertTrue(begun.wait(2));self.claim();self.wait(lambda:self.fg.acquired);worker.join(2);execute.assert_not_called()
            self.assertEqual(result[0]['steps'],0);self.assertEqual(result[0]['history'],[]);self.assertTrue(result[0]['chat_paused'])
        finally:release.set();server.shutdown();server.server_close()
    def test_schedules_do_not_materialize_until_chat_releases(self):
        schedules=Schedules(self.root);s=schedules.create('One due fixture run');schedules.enable(s['id'])
        self.claim();self.wait(lambda:self.fg.acquired);schedules.tick();self.assertIsNone(schedules.load(s['id'])['active_run'])
        supervisor=Supervisor(self.root,model_ready=lambda:False);self.assertTrue(supervisor.tick());self.assertEqual(supervisor.last_state,'paused_for_chat')
        self.fg.close();schedules.tick();run=schedules.load(s['id']);self.assertEqual(run['runs_started'],1);self.assertIsNotNone(run['active_run']);schedules.tick();self.assertEqual(schedules.load(s['id'])['runs_started'],1)
    def test_pending_effect_never_becomes_automatic_resume(self):
        m=self.store.create('Uncertain fixture action');m['pending_action']={'action':'shell','command':'fixture'};self.store.save(m)
        self.claim();self.wait(lambda:self.fg.acquired);self.fg.close()
        with patch.object(self.store,'execute') as execute:
            result=self.store.run(m['id']);execute.assert_not_called()
        self.assertEqual(result['status'],'needs_review');self.assertIsNotNone(result['pending_action'])
    def test_manual_stop_during_chat_stays_stopped(self):
        m=self.store.create('Respect explicit stop');arm(self.root,m['id']);self.claim();self.wait(lambda:self.fg.acquired)
        disarm(self.root,m['id']);self.fg.close();self.assertFalse(read_policy(self.store,m['id'])['enabled'])
        with patch.object(self.store,'execute') as execute:self.store.run(m['id']);execute.assert_not_called()
        self.assertEqual(self.store.load(m['id'])['status'],'paused')
    def test_cancelled_admission_releases_both_leases(self):
        with process_lock(self.store.base/'execution.lock'):
            self.claim();self.assertFalse(self.fg.acquired);self.cancel.set()
            for t in self.threads:t.join(1)
        self.fg.close();self.assertFalse(active(self.root))
        with process_lock(self.store.base/'execution.lock'):pass
    def test_priority_is_scoped_to_this_portable_root(self):
        self.claim();self.wait(lambda:self.fg.acquired)
        other=self.root/'other';other.mkdir();self.assertFalse(active(other));self.assertTrue(active(self.root))
    def test_memory_failure_requires_review_without_effect(self):
        m=self.store.create('Full memory fixture');self.fg=Foreground(self.root)
        with process_lock(self.store.base/'direct-chat.lock'),patch.object(Memory,'remember',side_effect=OSError('fixture storage full')),patch.object(self.store,'execute') as execute:
            result=self.store.run(m['id']);execute.assert_not_called()
        self.assertEqual(result['status'],'needs_review');self.assertIn('checkpoint',result['error'])

    def test_native_chat_holds_priority_through_reply_and_releases_on_error(self):
        sys.path.insert(0,str(ROOT/'Maintenance/Tests'))
        from test_chat_handoff import panel
        for failure in (False,True):
            p=panel();p.root=self.root
            def reply(messages):
                self.assertTrue(active(self.root))
                with self.assertRaises(OSError):
                    with process_lock(self.store.base/'execution.lock'):pass
                if failure:raise RuntimeError('fixture reply failure')
                return 'Fixture answer','',[]
            with patch.object(p,'stream_completion',side_effect=reply):p.agent_worker('test')
            self.assertFalse(active(self.root));self.assertEqual(list(p.ev.queue)[-1][0],'done')
            self.assertEqual(any(e[0]=='error' for e in list(p.ev.queue)),failure)
            p._fixture_directory.cleanup()

    def test_remote_delivery_ack_precedes_wait_and_cancel_releases_priority(self):
        sys.path.insert(0,str(ROOT/'Maintenance/Tests'))
        from test_chat_handoff import panel
        p=panel();p.root=self.root;ack=threading.Event()
        admission=Mock();admission.worker_ready.side_effect=lambda cancel:ack.set() or True
        with process_lock(self.store.base/'execution.lock'),patch.object(p,'stream_completion') as stream:
            worker=self.thread(lambda:p.agent_worker('test',remote_admission=admission))
            self.assertTrue(ack.wait(1));self.wait(lambda:active(self.root))
            admission.worker_prepared.assert_not_called();stream.assert_not_called()
            p.cancel_event.set();worker.join(2);self.assertFalse(worker.is_alive())
        self.assertFalse(active(self.root));self.assertEqual(list(p.ev.queue)[-1][0],'done')
        p._fixture_directory.cleanup()

if __name__=='__main__':unittest.main()
