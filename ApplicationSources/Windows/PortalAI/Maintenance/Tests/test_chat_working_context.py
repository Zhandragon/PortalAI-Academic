"""Large multi-tool conversations retain exact evidence and account boundaries."""
import copy
import json
import queue
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
import native_chat as chat
import chat_evidence as evidence
from test_chat_context_budget import panel
from test_chat_handoff import panel as worker_panel, CALL
from test_chat_reasoning_continuation import responses

def fixture():
    p = panel(); p.ev = queue.Queue(); p.cancel_event = threading.Event()
    p.user_api_message = lambda m: {'role': 'user', 'content': m['content']}
    p._runtime_context_limit = lambda: 32768
    return p

class WorkingContextTests(unittest.TestCase):
    def tool_turn(self, p, count=24):
        for n in range(count):
            call = {'id': f'call_{n}', 'type': 'function', 'function': {'name': 'shell', 'arguments': json.dumps({'command': f'job {n}'})}}
            p.session['messages'].extend([
                {'role': 'assistant', 'content': '', 'reasoning': 'Fallible old reasoning. '*4000, 'tool_calls': [call]},
                {'role': 'tool', 'name': 'shell', 'tool_call_id': call['id'], 'content': json.dumps({
                    'success': True, 'logs': 'large log '*10000, 'files': [f'Outputs/Edited/exact_{n}.png'], 'trailer': 'more logs '*3000})}])

    def test_one_large_turn_fits_and_middle_output_survives_projection(self):
        p = fixture(); self.tool_turn(p); original = copy.deepcopy(p.session)
        api, estimate = p.api_messages()
        serialized = json.dumps(api)
        self.assertLessEqual(estimate, p._last_context_meta['budget'])
        self.assertGreaterEqual(p._last_context_meta['checkpoint_reserve'], 1000)
        self.assertNotIn('Fallible old reasoning.', serialized)
        self.assertIn('Outputs/Edited/exact_23.png', serialized)
        self.assertEqual(p.session, original)
        tool = [row for row in api if row['role'] == 'tool']
        self.assertEqual(len(tool), 24)
        raw = json.loads(p._chat_history({'action': 'read', 'message_id': 48, 'offset': 6000, 'limit': 7000}))
        self.assertEqual(raw['text'], original['messages'][48]['content'][6000:13000])

    def test_artifacts_find_exact_source_even_after_summary_cursor(self):
        p=fixture(); self.tool_turn(p, 3)
        p.session['context_state']['cursor']=5
        result=json.loads(p._chat_history({'action':'artifacts'}))
        self.assertEqual(result['results'][0]['message_id'],6)
        self.assertIn('Outputs/Edited/exact_2.png', str(result))
        search=json.loads(p._chat_history({'action':'search','query':'exact_0.png'}))
        self.assertEqual(search['results'][0]['message_id'],2)

    def test_two_turns_compact_automatically_even_with_six_recent_preference(self):
        p=fixture(); self.tool_turn(p, 12)
        p.session['messages'].append({'role':'user','content':'Continue the unresolved step.'})
        original=copy.deepcopy(p.session['messages']); captured=[]
        def summarize(messages, **kwargs):
            captured.append((messages,kwargs));return 'Twelve completed calls; exact outputs accessible through chat_history. Continue unresolved step.'
        with patch.object(p,'_single_completion',side_effect=summarize):
            self.assertTrue(p.compact_context_if_needed())
        self.assertEqual(p.session['context_state']['cursor'],25)
        self.assertEqual(p.session['messages'],original)
        self.assertLess(chat.estimate_tokens(captured[0][0])+captured[0][1]['max_tokens']+500,29491)

    def test_huge_older_user_turn_does_not_overflow_summary_request(self):
        p=fixture();p.session['messages'][0]['content']='x'*300000
        p.session['messages'].append({'role':'user','content':'Continue.'})
        def summarize(messages,**kw):
            self.assertLess(chat.estimate_tokens(messages)+kw['max_tokens']+500,29491)
            return 'Earlier large input is saved as message 0; inspect exact evidence if needed.'
        with patch.object(p,'_single_completion',side_effect=summarize):self.assertTrue(p.compact_context_if_needed())

    def test_failed_summary_preserves_state_and_raw_evidence(self):
        p=fixture();self.tool_turn(p,12);p.session['messages'].append({'role':'user','content':'Continue'})
        before=copy.deepcopy(p.session)
        with patch.object(p,'_single_completion',side_effect=RuntimeError('offline')):
            self.assertFalse(p.compact_context_if_needed())
        self.assertEqual(p.session,before)

    def test_retrieval_checks_stop_and_login_before_returning(self):
        p=fixture();p.cancel_event.set()
        with self.assertRaisesRegex(RuntimeError,'cancelled'):p._chat_history({'action':'artifacts'})
        p.cancel_event.clear()
        with patch.object(p,'_check_login',side_effect=PermissionError('ended')):
            with self.assertRaises(PermissionError):p._chat_history({'action':'artifacts'})

    def test_real_progress_replenishes_continuations_without_rerunning_actions(self):
        p=worker_panel();p.settings['tool_step_limit']=5;p._last_context_meta={'budget':16000}
        seen=[];stream_rows=[]
        for n in range(4):
            call=copy.deepcopy(CALL);call['id']=f'id{n}';call['function']['arguments']=json.dumps({'command':f'action {n}'})
            stream_rows.extend([('length','','Working discovery.',[]),('tool_calls','','',[call])])
        stream_rows.append(('stop','Finished all four distinct actions.','',[]))
        with patch.object(p,'stream_completion',side_effect=responses(p,stream_rows,seen)):
            p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,4)
        self.assertEqual(p.session['messages'][-1]['content'],'Finished all four distinct actions.')
        self.assertFalse(any(item['no_tools'] for item in seen))

    def test_retrieval_does_not_execute_or_reindex_its_own_copies(self):
        p=worker_panel();call=copy.deepcopy(CALL)
        call['function']={'name':'chat_history','arguments':'{"action":"artifacts"}'}
        with patch.object(p,'stream_completion',side_effect=[('','',[call]),('No artifacts yet.','',[])]):p.agent_worker('test')
        p.tool_runtime.execute.assert_not_called()
        self.assertEqual(json.loads(evidence.execute(p.session,{'action':'artifacts'}))['results'],[])

    def test_repeated_effectful_action_returns_saved_reference_without_reexecution(self):
        for outcome in ('saved output.png', RuntimeError('uncertain timeout')):
            p=worker_panel(); second=copy.deepcopy(CALL);second['id']='call_two'
            if isinstance(outcome,Exception):p.tool_runtime.execute.side_effect=outcome
            else:p.tool_runtime.execute.return_value=outcome
            with patch.object(p,'stream_completion',side_effect=[('','',[CALL]),('','',[second]),('Reviewed saved outcome.','',[])]):
                p.agent_worker('test')
            p.tool_runtime.execute.assert_called_once()
            results=[m['content'] for m in p.session['messages'] if m['role']=='tool']
            self.assertIn('NOT executed again',results[1]);self.assertIn('message_id=2',results[1])

if __name__=='__main__': unittest.main()
