"""Behavioral coverage for stall recovery, real byte receipts and worker gates."""
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
from coding_stall import CodingStall, write_receipt
import native_chat as chat
from test_chat_handoff import panel

RETURNED = {'dispatched': True, 'outcome': 'returned'}


class Clock:
    now = 0
    def __call__(self): return self.now


def inspected(cycle, count=8):
    for _ in range(count):
        cycle.observe('read_file', {'path':'Agent/example.py'},
            json.dumps({'path':'Agent/example.py', 'text':'def example(): return 1'}), RETURNED)


class CodingStallTests(unittest.TestCase):
    def cycle(self, armed=True):
        clock = Clock(); cycle = CodingStall(armed, clock=clock)
        return cycle, clock

    def active(self):
        c,t = self.cycle(); inspected(c); t.now=301; c.tick()
        self.assertTrue(c.implementing)
        return c,t

    def test_opt_in_is_strict_and_default_off(self):
        for armed in (False, None, 'true', 1):
            c,t=self.cycle(armed); inspected(c); t.now=1000
            self.assertIsNone(c.tick()); self.assertFalse(c.implementing)

    def test_requires_both_elapsed_time_and_completed_inspections(self):
        c,t=self.cycle(); inspected(c,7); t.now=300
        self.assertIsNone(c.tick()); inspected(c,1); self.assertTrue(c.tick())
        c,t=self.cycle(); inspected(c,100); t.now=299
        self.assertIsNone(c.tick()); t.now=300; self.assertTrue(c.tick())

    def test_discovery_without_source_bytes_cannot_trigger_blind_write(self):
        c,t=self.cycle()
        for _ in range(10):c.observe('source_search', {}, '{}', RETURNED)
        t.now=1000; self.assertIsNone(c.tick())

    def test_failed_reads_and_tool_prose_do_not_arm_or_claim_progress(self):
        c,t=self.cycle()
        for result in ('ERROR: blocked', '{"success": false}', '{"path":"x.py","text":"source"}'):
            for _ in range(10):c.observe('read_file',{},result,{'dispatched':False})
        t.now=1000;self.assertIsNone(c.tick());self.assertEqual(c.inspections,0)

    def test_burst_allows_two_reference_reads_but_blocks_broad_exploration(self):
        c,t=self.active()
        self.assertIsNone(c.before('read_file',{}));self.assertIsNone(c.before('chat_history',{}))
        self.assertIn('NOT executed',c.before('read_file',{}))
        self.assertIn('NOT executed',c.before('web',{}))
        self.assertIn('NOT executed',c.before('shell',{}))
        self.assertIsNone(c.before('edit_file',{}))
        self.assertEqual({r['function']['name'] for r in c.menu(chat.TOOLS)}, {'edit_file','write_file'})

    def test_two_failed_writes_return_to_review_without_claiming_progress(self):
        c,t=self.active()
        for _ in range(2):
            c.before('edit_file',{});c.observe('edit_file',{},'ERROR: old text not found',RETURNED)
        self.assertFalse(c.implementing);self.assertEqual(c.changed_writes,0)
        self.assertIsNone(c.tick());self.assertEqual(c.menu(chat.TOOLS),chat.TOOLS)
        t.now+=301;self.assertIsNone(c.tick())
        inspected(c);self.assertTrue(c.tick())

    def test_six_invalid_calls_and_time_expiry_are_bounded(self):
        c,t=self.active()
        for _ in range(6):
            c.before('source_search',{});c.observe('source_search',{},'NOT executed',{'dispatched':False})
        self.assertFalse(c.implementing)
        c,t=self.active();t.now+=120;c.tick();self.assertFalse(c.implementing)

    def test_changed_code_releases_burst_and_requires_review(self):
        c,t=self.active()
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'new_test.py';p.write_bytes(b'assert 1 == 1\n')
            c.before('write_file',{});c.observe('write_file',{},write_receipt(p,None),RETURNED)
        self.assertFalse(c.implementing);self.assertEqual(c.changed_writes,1)
        self.assertIn('test',c.guidance());self.assertIn('not proof',c.guidance())

    def test_noop_docs_checkpoint_shell_and_replayed_results_are_not_code_progress(self):
        with tempfile.TemporaryDirectory() as td:
            for name,suffix,old,execution in (
                ('write_file','.py',b'x=1',RETURNED),
                ('write_file','.txt',None,RETURNED),
                ('shell','.py',None,RETURNED),
                ('chat_checkpoint','.py',None,RETURNED),
                ('edit_file','.py',None,{'dispatched':False, 'outcome':'not_executed'})):
                c,t=self.active();p=Path(td)/('file'+suffix);p.write_bytes(b'x=1')
                c.observe(name,{},write_receipt(p,old),execution)
                self.assertEqual(c.changed_writes,0);self.assertTrue(c.implementing)

    def test_receipt_compares_actual_bytes_including_empty_creation(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.py';p.write_bytes(b'')
            self.assertTrue(json.loads(write_receipt(p,None))['changed'])
            self.assertFalse(json.loads(write_receipt(p,b''))['changed'])
            p.write_bytes(b'one');self.assertTrue(json.loads(write_receipt(p,b'two'))['changed'])

    def test_request_scoped_and_no_permission_grant(self):
        c,t=self.active();self.assertIn('read-only',c.guidance())
        self.assertIn('no additional authority',c.guidance())
        fresh=CodingStall();self.assertEqual(fresh.events,[]);self.assertFalse(fresh.implementing)


def call(i,name,args):
    return {'id':str(i),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


class WorkerStallTests(unittest.TestCase):
    def test_real_worker_gates_loop_then_releases_after_observed_write(self):
        p=panel();p._request_tool_scope='maintenance'
        p.session['messages'][0].update(content='Implement the code improvement.',coding_stall_recovery=True)
        p.settings['tool_call_limit']=30
        clock=Clock();observed=[];number=0
        def model(_):
            nonlocal number
            number+=1
            if number<=8:
                clock.now=number*45
                return '', '', [call(number,'read_file',{'path':'Agent/x.py'})]
            observed.append(p._coding_stall.implementing)
            if number==9:return '', '', [call(number,'source_search',{'query':'another distraction'})]
            if number==10:return '', '', [call(number,'edit_file',{'path':'Agent/x.py','old':'a','new':'b'})]
            return 'Patch is a draft; review and tests still required.', '', []
        def execute(name,args):
            if name=='read_file':return json.dumps({'path':'Agent/x.py','text':'a'})
            if name=='edit_file':return json.dumps({'success':True,'changed':True,'bytes':1,'path':'Agent/x.py','before_sha256':'a'*64,'sha256':'b'*64})
            self.fail('Broad search was dispatched during burst')
        p.tool_runtime.execute.side_effect=execute
        with patch('coding_stall.time.monotonic',clock),patch.object(p,'stream_completion',side_effect=model):
            p.agent_worker('test')
        self.assertEqual(observed,[True,True,False])
        blocked=next(r for r in p.session['messages'] if r.get('name')=='source_search')
        self.assertFalse(blocked['execution']['dispatched'])
        self.assertEqual(p.session['context_state']['last_run']['coding_stall']['changed_writes'],1)
        self.assertIsNone(p._coding_stall)

    def test_no_request_marker_means_no_stall_gate(self):
        p=panel();p._request_tool_scope='maintenance';states=[]
        def model(_):
            states.append(p._coding_stall.armed)
            return 'Read-only inspection completed.', '', []
        with patch.object(p,'stream_completion',side_effect=model):p.agent_worker('test')
        self.assertEqual(states,[False]);p.tool_runtime.execute.assert_not_called()

    def test_stop_after_activation_does_not_start_write_or_new_inference(self):
        p=panel();p._request_tool_scope='maintenance';p.session['messages'][0]['coding_stall_recovery']=True
        def model(_):
            p.cancel_event.set()
            return '', '', [call(1,'write_file',{'path':'x.py','content':'x=1'})]
        with patch.object(p,'stream_completion',side_effect=model) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called();self.assertIsNone(p._coding_stall)


class RuntimeWriteReceiptTests(unittest.TestCase):
    def test_real_runtime_noop_create_edit_and_failed_edit(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.py'
            rt=SimpleNamespace(_account_role=lambda:'admin',safe_path=lambda _:p)
            created=json.loads(chat.ToolRuntime.write_file(rt,'x.py','x=1\n'))
            self.assertTrue(created['changed']);self.assertIsNone(created['before_sha256'])
            unchanged=json.loads(chat.ToolRuntime.write_file(rt,'x.py','x=1\n'))
            self.assertFalse(unchanged['changed'])
            edited=json.loads(chat.ToolRuntime.edit_file(rt,'x.py','x=1','x=2'))
            self.assertTrue(edited['changed']);self.assertEqual(p.read_text(),'x=2\n')
            self.assertEqual(created['sha256'],edited['before_sha256'])
            unchanged=json.loads(chat.ToolRuntime.edit_file(rt,'x.py','x=2','x=2'))
            self.assertFalse(unchanged['changed'])
            with self.assertRaises(ValueError):chat.ToolRuntime.edit_file(rt,'x.py','invented','wrong')
            self.assertEqual(p.read_text(),'x=2\n')

    def test_non_admin_and_late_role_change_cannot_write(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x.py';p.write_text('a')
            for roles in (['user'], ['admin','user']):
                it=iter(roles);rt=SimpleNamespace(_account_role=lambda:next(it),safe_path=lambda _:p)
                with self.assertRaises(PermissionError):chat.ToolRuntime.write_file(rt,'x.py','b')
                self.assertEqual(p.read_text(),'a')

    def test_empty_new_file_is_not_productive_progress(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'empty.py';p.write_bytes(b'')
            c=CodingStall(True);c.observe('write_file',{},write_receipt(p,None),RETURNED)
            self.assertEqual(c.changed_writes,0)

    def test_active_guidance_and_menu_are_counted_in_context_budget(self):
        from test_chat_context_budget import panel as budget_panel
        p=budget_panel();p._request_tool_scope='maintenance';p.settings['max_output_tokens']=4096
        p.root=ROOT;p.settings['use_master_instructions']=False;p.store.custom_instructions=lambda:''
        p.system_prompt=lambda:chat.NativeChat.system_prompt(p)
        clock=Clock();p._coding_stall=CodingStall(True,clock=clock)
        inspected(p._coding_stall);clock.now=301;p._coding_stall.tick()
        api,_=p.api_messages()
        self.assertIn('Coding stall recovery is active',api[0]['content'])
        self.assertLessEqual(p._last_context_meta['estimated_sent'],p._last_context_meta['budget'])
        self.assertNotIn('web',{r['function']['name'] for r in chat._request_tools(p)})

    def test_change_receipt_survives_evidence_projection(self):
        from chat_evidence import reported_fields
        row={'role':'tool','content':json.dumps({'path':'x.py','success':True,'changed':False,
                                              'before_sha256':'a'*64,'sha256':'a'*64,'bytes':1})}
        fields=dict(reported_fields(row))
        self.assertEqual(fields['changed'],'False');self.assertEqual(fields['sha256'],'a'*64)


if __name__ == '__main__':unittest.main()
