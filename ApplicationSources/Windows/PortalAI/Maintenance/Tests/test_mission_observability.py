"""Cold schedules, real streaming HTTP, cancellation and readable evidence."""
import http.server,json,os,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from mission_runner import Missions,MissionCancelled
from mission_schedule import Schedules
from mission_supervisor import Supervisor
from mission_activity import Activity,read
from mission_monitor import live_state,render,mission_enabled
from chat_priority import planning_json


class MissionProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);(self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.store=Missions(self.root)

    def test_due_schedule_dispatches_even_when_engine_is_off(self):
        schedules=Schedules(self.root);s=schedules.create('Complete fixture',first_run_at=0,max_runs=1);schedules.enable(s['id'])
        proc=MagicMock(pid=4321);proc.poll.return_value=None
        with patch('mission_supervisor.subprocess.Popen',return_value=proc) as launch,patch('mission_supervisor.WorkerJob'):
            supervisor=Supervisor(self.root,model_ready=lambda:False)
            try:
                self.assertTrue(supervisor.tick());launch.assert_called_once()
                self.assertEqual(supervisor.last_state,'starting_model')
                self.assertTrue(schedules.load(s['id'])['active_run'])
            finally:proc.poll.return_value=0;supervisor.finish_worker()

    def test_new_worker_identity_is_visible_without_waiting_for_heartbeat_interval(self):
        supervisor=Supervisor(self.root,model_ready=lambda:True)
        supervisor.mid='a'*32;supervisor.worker=MagicMock(pid=111)
        supervisor.heartbeat('running')
        supervisor.worker=MagicMock(pid=222);supervisor.heartbeat('running')
        saved=json.loads((supervisor.store.base/'supervisor-status.json').read_text())
        self.assertEqual(saved['worker_pid'],222)

    def test_cold_model_prepares_saved_policy_then_records_real_progress(self):
        m=self.store.create('Complete fixture')
        policy={'selection':'saved-fixture-model'};phases=[]
        def endpoint(root,url,payload=None,**kwargs):
            if url.endswith('/health'):raise ConnectionRefusedError('Cold fixture')
            if url.endswith('/props'):return {'default_generation_settings':{'n_ctx':8192}}
            if url.endswith('/v1/chat/completions'):
                kwargs['on_delta']('{"action":"complete",');phases.append(read(self.store,m['id'])['phase'])
                kwargs['on_delta']('"text":"SCHEDULE_OK"}')
                return {'choices':[{'message':{'content':'{"action":"complete","text":"SCHEDULE_OK"}'}}]}
            self.fail(url)
        def prepare(*args,**kwargs):
            self.assertEqual(kwargs['_policy'],policy);self.assertFalse(kwargs['cancel_event'].is_set())
            kwargs['on_status']('Loading fixture model')
        with patch('chat_priority.planning_json',side_effect=endpoint),patch('mission_context.build_messages',return_value=[]),\
             patch('runtime_policy.load_effective_policy',return_value=policy),patch('chat_model_switch.prepare_chat',side_effect=prepare) as startup:
            result=self.store.run(m['id'])
        startup.assert_called_once();self.assertEqual(result['status'],'complete')
        self.assertEqual(phases,['generating']);activity=read(self.store,m['id'])
        self.assertEqual(activity['phase'],'complete');self.assertGreater(activity['generated_chars'],0)
        self.assertEqual(len(result['history']),1)

    def test_stop_during_cold_start_prevents_planning_and_effects(self):
        m=self.store.create('Do not execute after Stop')
        def prepare(*args,**kwargs):self.store.stop(m['id']);kwargs['cancel_event'].is_set()
        with patch('chat_priority.planning_json',side_effect=ConnectionRefusedError('cold')),\
             patch('runtime_policy.load_effective_policy',return_value={}),patch('chat_model_switch.prepare_chat',side_effect=prepare),\
             patch.object(self.store,'execute') as execute:
            result=self.store.run(m['id'])
        self.assertEqual(result['status'],'paused');self.assertEqual(result['history'],[]);execute.assert_not_called()

    def test_ended_login_during_stream_cannot_execute_or_write_new_activity(self):
        from profile_paths import ProfileLocked
        m=self.store.create('Stop at the captured login boundary')
        def endpoint(root,url,payload=None,**kwargs):
            if url.endswith('/health'):return {'status':'ok'}
            if url.endswith('/props'):return {'default_generation_settings':{'n_ctx':8192}}
            if url.endswith('/v1/chat/completions'):
                before=(self.store.folder(m['id'])/'activity.json').read_bytes()
                with patch('profile_paths.capture',return_value=('different-login','different-epoch')):
                    with self.assertRaises(ProfileLocked):kwargs['on_delta']('must not be saved')
                    kwargs['check_cancel']()
                self.fail('An ended login must abort planning')
            self.fail(url)
        with patch('chat_priority.planning_json',side_effect=endpoint),patch('mission_context.build_messages',return_value=[]),patch.object(self.store,'execute') as execute:
            # The closure is closed only inside the synthetic endpoint, so the
            # runner may persist its error in the original fixture afterwards.
            result=self.store.run(m['id'])
        execute.assert_not_called();self.assertEqual(result['history'],[])
        self.assertNotIn('must not be saved',(self.store.folder(m['id'])/'activity.json').read_text())

    def test_activity_is_bounded_and_does_not_change_execution_checkpoint(self):
        m=self.store.create('Bounded evidence');checkpoint=(self.store.folder(m['id'])/'mission.json').read_bytes()
        activity=Activity(self.store,m)
        for i in range(100):activity.update('phase'+str(i),'message'+str(i),preview='x'*20000,force=True)
        saved=read(self.store,m['id']);self.assertEqual(len(saved['events']),80);self.assertEqual(len(saved['preview']),8000)
        self.assertEqual((self.store.folder(m['id'])/'mission.json').read_bytes(),checkpoint)

    def test_telemetry_io_failure_does_not_replay_a_completed_action(self):
        m=self.store.create('Complete once')
        with patch('mission_activity.atomic_json',side_effect=OSError('fixture recording unavailable')):
            result=self.store.run(m['id'],model=lambda _: {'action':'complete','text':'Done once'})
        self.assertEqual(result['status'],'complete');self.assertEqual(len(result['history']),1)

    def test_damaged_optional_timeline_does_not_block_a_mission(self):
        m=self.store.create('Complete despite a damaged activity record')
        (self.store.folder(m['id'])/'activity.json').write_text(json.dumps({'mission':m['id'],'events':42}))
        result=self.store.run(m['id'],model=lambda _: {'action':'complete','text':'Done once'})
        self.assertEqual(result['status'],'complete');self.assertEqual(len(result['history']),1)

    def test_saved_running_state_is_not_live_execution_proof(self):
        m=self.store.create('Stale');m['status']='running'
        self.assertIn('not executing',live_state(m,{'phase':'generating'},{'alive':False},enabled=True))
        self.assertIn('stale',live_state(m,{'phase':'generating'},{'alive':True,'fresh':False},enabled=True))

    def test_child_status_uses_parent_arming_and_schedule_stop_epoch(self):
        from mission_supervisor import arm,pause_all
        parent=self.store.create('Parent');child=self.store.create('Child',parent=parent['id'],depth=1)
        arm(self.root,parent['id']);self.assertTrue(mission_enabled(self.store,child))
        schedules=Schedules(self.root);s=schedules.create('Scheduled parent',first_run_at=0)
        schedules.enable(s['id']);schedules.tick()
        m=self.store.load(schedules.load(s['id'])['active_run']);self.assertTrue(mission_enabled(self.store,m))
        pause_all(self.root);self.assertFalse(mission_enabled(self.store,m));self.assertFalse(mission_enabled(self.store,child))

    def test_results_show_note_content_and_action_history_has_readable_output(self):
        m=self.store.create('Readable');m['history']=[{'action':{'action':'note','text':'Human-readable finding'},'result':'Note saved','at':1},
            {'action':{'action':'shell','command':'fixture'},'result':'{"exit_code":0,"output":"Actual fixture output"}','at':2}]
        self.assertIn('Human-readable finding',render('Results',m,{},{}))
        history=render('Action history',m,{},{});self.assertIn('Actual fixture output',history);self.assertIn('STEP 2',history)
        self.assertNotIn('{"exit_code"',history)


class StreamingTests(unittest.TestCase):
    setUp=MissionProgressTests.setUp
    def serve(self,tail,initial=None):
        first=threading.Event();release=threading.Event()
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                if not request.get('stream'):self.send_error(400);return
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
                try:
                    self.wfile.write(initial or b'data: {"choices":[{"delta":{"content":"{\\"action\\":\\"complete\\"}"},"finish_reason":null}]}\n\n');self.wfile.flush()
                    first.set();release.wait(5)
                    self.wfile.write(tail);self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):pass
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown);self.addCleanup(release.set)
        return f'http://127.0.0.1:{server.server_port}/v1/chat/completions',first,release

    def test_reasoning_stream_is_visible_but_not_part_of_executable_json(self):
        reasoning='Uncommitted reasoning; {"action":"shell","command":"not an action"}'
        initial=('data: '+json.dumps({'choices':[{'delta':{'reasoning_content':reasoning}}]})+'\n\n').encode()
        tail=b'data: {"choices":[{"delta":{"content":"{\\"action\\":\\"complete\\"}"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
        url,first,release=self.serve(tail,initial);release.set()
        reasoning_parts=[];content=[]
        result=planning_json(self.root,url,{'messages':[]},on_delta=content.append,on_reasoning=reasoning_parts.append)
        self.assertEqual(reasoning_parts,[reasoning]);self.assertEqual(''.join(content),'{"action":"complete"}')
        self.assertEqual(json.loads(result['choices'][0]['message']['content']),{'action':'complete'})

    def test_real_stream_exposes_output_before_completion(self):
        url,first,release=self.serve(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        progress=threading.Event();results=[]
        worker=threading.Thread(target=lambda:results.append(planning_json(self.root,url,{},timeout=5,on_delta=lambda _:progress.set())))
        worker.start()
        try:
            self.assertTrue(progress.wait(3));self.assertEqual(results,[])
            release.set();worker.join(3);self.assertFalse(worker.is_alive())
            self.assertEqual(json.loads(results[0]['choices'][0]['message']['content'])['action'],'complete')
        finally:release.set();worker.join(5)

    def test_truncated_response_cannot_become_an_action(self):
        url,first,release=self.serve(b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\ndata: [DONE]\n\n');release.set()
        with self.assertRaisesRegex(RuntimeError,'incomplete'):planning_json(self.root,url,{},timeout=5,on_delta=lambda _:None)

    def test_stop_interrupts_a_stream_without_waiting_for_model(self):
        url,first,release=self.serve(b'');cancel=threading.Event();errors=[]
        def check():
            if cancel.is_set():raise MissionCancelled('Stopped fixture')
        def run():
            try:planning_json(self.root,url,{},timeout=5,on_delta=lambda _:None,check_cancel=check)
            except Exception as exc:errors.append(exc)
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertTrue(first.wait(3));cancel.set();worker.join(2)
            self.assertFalse(worker.is_alive());self.assertIsInstance(errors[0],MissionCancelled)
        finally:release.set();worker.join(5)


if __name__=='__main__':unittest.main()
