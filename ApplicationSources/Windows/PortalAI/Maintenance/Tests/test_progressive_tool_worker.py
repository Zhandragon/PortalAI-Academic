"""The native worker loads documentation without granting or replaying effects."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import native_chat as chat
from chat_tool_menu import Selection
from test_chat_handoff import panel


def call(identifier,name,arguments):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}


def fixture():
    p=panel();p._tool_selection=Selection()
    p._context_plan=lambda:{'estimated_input':1500,'safety_tokens':500,'checkpoint_reserve':737,'budget':7372}
    p._last_context_meta={'budget':7372}
    return p


class ProgressiveWorkerTests(unittest.TestCase):
    def test_load_then_execute_separate_turns_and_save_discovery_as_read_only(self):
        p=fixture();menus=[]
        replies=[('','',[call('help','tool_help',{'tools':['read_file']})]),
                 ('','',[call('read','read_file',{'path':'fixture.txt'})]),('Done.','',[])]
        def respond(_):
            menus.append({r['function']['name'] for r in chat._request_tools(p)})
            return replies.pop(0)
        with patch.object(p,'stream_completion',side_effect=respond):p.agent_worker('test')
        self.assertNotIn('read_file',menus[0]);self.assertIn('read_file',menus[1])
        p.tool_runtime.execute.assert_called_once_with('read_file',{'path':'fixture.txt'})
        receipt=next(r for r in p.session['messages'] if r.get('name')=='tool_help')
        self.assertFalse(receipt['execution']['effectful']);self.assertTrue(receipt['execution']['dispatched'])
        self.assertEqual(p.session['messages'][-1]['content'],'Done.')

    def test_mixed_discovery_and_action_batch_executes_nothing(self):
        p=fixture()
        with patch.object(p,'stream_completion',return_value=('','',[
                call('help','tool_help',{'tools':['write_file']}),
                call('write','write_file',{'path':'x','content':'x'})])):p.agent_worker('test')
        p.tool_runtime.execute.assert_not_called();self.assertEqual(p._tool_selection.names,())
        self.assertIn('must be called alone',p.session['messages'][-1]['content'])

    def test_unloaded_action_is_not_executed_or_automatically_replayed(self):
        p=fixture()
        with patch.object(p,'stream_completion',return_value=('','',[call('write','write_file',{'path':'x','content':'x'})])) as model:
            p.agent_worker('test')
        model.assert_called_once();p.tool_runtime.execute.assert_not_called()
        self.assertIn('before loading its definition',p.session['messages'][-1]['content'])

    def test_switching_definitions_never_replays_prior_effect(self):
        p=fixture()
        replies=[('','',[call('h1','tool_help',{'tools':['write_file']})]),
                 ('','',[call('w1','write_file',{'path':'x','content':'x'})]),
                 ('','',[call('h2','tool_help',{'tools':['read_file']})]),
                 ('','',[call('h3','tool_help',{'tools':['write_file']})]),
                 ('','',[call('w2','write_file',{'path':'x','content':'x'})]),('Done.','',[])]
        with patch.object(p,'stream_completion',side_effect=replies):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertTrue(any('NOT executed again' in str(r.get('content')) for r in p.session['messages']))

    def test_loading_does_not_reset_checkpoint_progress_allowance(self):
        from chat_task_checkpoint import Cycle
        cycle=Cycle(4);cycle.since_progress=3
        cycle.progress('tool_help',{'tools':['read_file']},'loaded')
        self.assertEqual(cycle.since_progress,3)

    def test_loading_is_inspection_for_bounded_progress_aid(self):
        from task_progress import inspection
        from tool_protocol import read_only_tool_attempt
        self.assertTrue(inspection('tool_help',{'tools':['read_file']}))
        self.assertTrue(read_only_tool_attempt('tool_help',{'tools':['read_file']},ROOT))

    def test_host_coding_burst_can_supply_exact_write_menu_without_broad_loading(self):
        from coding_stall import CodingStall
        p=fixture();p._coding_stall=CodingStall(True);p._coding_stall.phase='implement'
        names={r['function']['name'] for r in chat._request_tools(p)}
        self.assertEqual(names,{'read_file','chat_history','write_file','edit_file'})


if __name__=='__main__':unittest.main()
