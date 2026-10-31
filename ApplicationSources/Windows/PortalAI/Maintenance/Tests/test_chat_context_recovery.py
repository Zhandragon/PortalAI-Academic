"""Real prompt overhead and small-context recovery without model/tool execution."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('Agent', 'ControlCenter', 'Maintenance/Tests')]
import native_chat as chat
from profile_paths import ProfileLocked
from test_chat_working_context import fixture
from test_chat_rolling_resume import assert_pairs


def small_panel():
    p = fixture()
    p._runtime_context_limit = lambda: 8192
    p.settings['max_output_tokens'] = 2048
    p._single_completion = Mock(side_effect=AssertionError('No model in offline recovery'))
    return p


def exchange(p, text='Directory of D:\\Example\\Workspace\n' + 'folder entry\n'*60, argument='dir'):
    p.session['messages'].extend([
        {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'listing', 'type': 'function',
         'function': {'name': 'shell', 'arguments': json.dumps({'command': argument})}}]},
        {'role': 'tool', 'name': 'shell', 'tool_call_id': 'listing', 'content': text,
         'execution': {'effectful': True, 'dispatched': True, 'outcome': 'returned', 'request_index': 0}}])


class ContextRecoveryTests(unittest.TestCase):
    def test_failed_periodic_summary_keeps_exact_exchanges_while_they_fit(self):
        p=small_panel();p._runtime_context_limit=lambda:32768
        for number in range(14):exchange(p,'Source code body '+str(number),'inspect '+str(number))
        original=copy.deepcopy(p.session)
        self.assertFalse(p._compact_working_turn(p._context_plan()))
        self.assertEqual(p.session,original)
        p._single_completion.assert_called_once()
        self.assertFalse(p._compact_working_turn(p._context_plan()))
        p._single_completion.assert_called_once()

    def test_hard_pressure_retains_recent_complete_pairs_when_they_fit(self):
        p=small_panel()
        for number in range(12):
            exchange(p,'Prior result '+str(number),'inspect '+str(number)+'x'*2000)
            p.session['messages'][-2]['tool_calls'][0]['id']='call-'+str(number)
            p.session['messages'][-1]['tool_call_id']='call-'+str(number)
        exchange(p,'LATEST_EXACT_RESULT','latest-command')
        p.session['messages'][-2]['tool_calls'][0]['id']='latest-call'
        p.session['messages'][-1]['tool_call_id']='latest-call'
        original=copy.deepcopy(p.session['messages'])
        p.compact_context_if_needed();api,estimated=p.api_messages()
        self.assertLessEqual(estimated,7372)
        self.assertTrue(any(row.get('role')=='tool' and row.get('tool_call_id')=='latest-call' and row.get('content')=='LATEST_EXACT_RESULT' for row in api))
        self.assertEqual(p.session['messages'],original);p._single_completion.assert_not_called()

    def test_reported_overflow_recovers_without_inference_or_replaying_a_tool(self):
        p = small_panel()
        p.session['messages'] = [
            {'role': 'user', 'content': 'Inspect your host drive.'},
            {'role': 'assistant', 'content': 'I have not inspected it.'},
            {'role': 'user', 'content': 'Run a directory listing and explain the result.'}]
        exchange(p)
        p.session['messages'][-1]['execution']['request_index'] = 2
        p.session['context_state'] = {'summary': 'User wants to inspect the host drive; no inspection was performed in the first exchange.',
                                      'cursor': 2, 'summarized_turns': 1}
        # Calibrated against the pre-repair planner: exactly 5,927 input tokens.
        # Synthetic fixed host overhead, not copied owner instructions/memory.
        # Keep the reproduced overflow fixed as the public tool menu evolves.
        # The separate real-host test below exercises the full current schema.
        padding = [9508]
        p.system_prompt = lambda: 'Small system instructions' + 'x'*padding[0]
        for _ in range(30):
            delta = p._context_plan()['estimated_input'] - 5800
            if not delta: break
            padding[0] = max(0, padding[0] - delta * 4)
        self.assertEqual(p._context_plan()['estimated_input'], 5800)
        before = copy.deepcopy(p.session['messages'])
        p.compact_context_if_needed()
        api, estimated = p.api_messages()
        self.assertLessEqual(estimated, 7372)
        self.assertGreaterEqual(p._last_context_meta['output_reserve'], 256)
        self.assertEqual(p._last_context_meta['safety_tokens'], 500)
        self.assertEqual(p._last_context_meta['checkpoint_reserve'], 737)
        self.assertEqual(p.session['messages'], before)
        self.assertTrue(any(row['role'] == 'tool' for row in api))
        p._single_completion.assert_not_called()

    def test_current_result_is_not_duplicated_in_resume_note(self):
        p = small_panel(); exchange(p, 'UNIQUE_CURRENT_RESULT')
        api, _ = p.api_messages()
        self.assertEqual(json.dumps(api).count('UNIQUE_CURRENT_RESULT'), 1)

    def test_followup_retains_prior_result_and_omitted_objective(self):
        p = small_panel(); exchange(p, 'UNIQUE_PRIOR_RESULT')
        p.session['messages'].append({'role': 'user', 'content': 'Continue.'})
        p.session['context_state']['cursor'] = 3
        api, _ = p.api_messages()
        self.assertIn('UNIQUE_PRIOR_RESULT', json.dumps(api))

    def test_real_host_prompt_and_tool_schema_fit_small_two_turn_chat(self):
        p = small_panel(); p.root = ROOT
        from chat_tool_menu import Selection
        p._tool_selection = Selection(); p._tool_selection.sync(p); p._tool_selection.names = ('shell',)
        p.store.custom_instructions = lambda: 'Inspect the host and explain what you find.'
        p.system_prompt = lambda: chat.NativeChat.system_prompt(p)
        p.memory.chat_included = lambda _: True; p.memory.config = {}
        p._runtime_session_context = lambda memory='': chat.NativeChat._runtime_session_context(p, memory)
        exchange(p)
        p.session['messages'].append({'role': 'user', 'content': 'What does the directory listing tell you?'})
        exchange(p, 'HOST_DRIVE_RESULT', argument='dir D:\\')
        original = copy.deepcopy(p.session['messages'])
        with patch('runtime_policy.load_effective_policy', return_value={}):
            p.compact_context_if_needed()
            api, estimate = p.api_messages()
        self.assertLessEqual(estimate, 7372)
        self.assertIn('HOST_DRIVE_RESULT', json.dumps(api))
        self.assertEqual(p.session['messages'], original)
        assert_pairs(self, api)

    def test_single_large_completed_exchange_can_checkpoint_without_a_model(self):
        p = small_panel(); exchange(p, 'COMPLETED_RESULT', argument='inspect ' + 'x'*20000)
        original = copy.deepcopy(p.session['messages'])
        p.compact_context_if_needed()
        api, estimated = p.api_messages()
        self.assertLessEqual(estimated, 7372)
        self.assertEqual(p.session['messages'], original)
        self.assertIn('COMPLETED_RESULT', json.dumps(api))
        self.assertIn('message_id=2', json.dumps(api))
        self.assertIn('returned', json.dumps(api))
        p._single_completion.assert_not_called()
        assert_pairs(self, api)

    def test_pending_tool_batch_is_not_compacted_or_replayed(self):
        p = small_panel(); exchange(p, argument='inspect ' + 'x'*20000)
        p.session['messages'].pop()
        before = copy.deepcopy(p.session)
        p.compact_context_if_needed()
        with self.assertRaisesRegex(RuntimeError, 'current request does not fit'):
            p.api_messages()
        self.assertEqual(p.session, before)
        p._single_completion.assert_not_called()

    def test_oversized_user_request_is_preserved_and_still_rejected(self):
        p = small_panel(); p.session['messages'][0]['content'] = 'request '*10000
        exchange(p)
        before = copy.deepcopy(p.session['messages'])
        p.compact_context_if_needed()
        with self.assertRaisesRegex(RuntimeError, 'current request does not fit'):
            p.api_messages()
        self.assertEqual(p.session['messages'], before)

    def test_disabled_auto_compaction_does_not_create_checkpoints(self):
        p = small_panel(); exchange(p, argument='inspect ' + 'x'*20000)
        p.settings['auto_context_management'] = False
        before = copy.deepcopy(p.session)
        self.assertFalse(p.compact_context_if_needed())
        self.assertEqual(p.session, before)

    def test_stop_and_revoked_login_prevent_pressure_checkpoint_commit(self):
        for stopped in (True, False):
            p = small_panel(); exchange(p, argument='inspect ' + 'x'*20000)
            before = copy.deepcopy(p.session)
            if stopped:
                p.cancel_event.set(); p.compact_context_if_needed()
            else:
                with patch.object(p, '_check_login', side_effect=ProfileLocked('ended')):
                    with self.assertRaises(ProfileLocked): p.compact_context_if_needed()
            self.assertEqual(p.session, before)
            p.store.save_session.assert_not_called()

    def test_working_summary_that_grows_context_is_not_committed(self):
        p = small_panel(); exchange(p, 'one'); exchange(p, 'two')
        before = copy.deepcopy(p.session)
        with patch.object(p, '_single_completion', return_value='large summary '*150):
            p._compact_working_turn(p._context_plan(), force=True)
        self.assertEqual(p.session, before)

    def test_large_recalled_memory_and_summary_yield_to_current_request(self):
        p = small_panel()
        p.session['context_state']['summary'] = 'Earlier saved conversation detail. '*900
        p.memory.context_for = lambda *a, **k: 'Optional prior-chat evidence. '*1000
        original = copy.deepcopy(p.session)
        api, estimated = p.api_messages()
        self.assertLessEqual(estimated, 7372)
        self.assertEqual(p.session, original)
        self.assertIn('full memory remains saved', json.dumps(api))
        self.assertIn('Original messages remain available', json.dumps(api))
        self.assertEqual(api[-1]['content'], original['messages'][-1]['content'])

    def test_older_summary_that_expands_the_replaced_history_is_not_committed(self):
        p = small_panel()
        p.session['messages'].extend([
            {'role': 'assistant', 'content': 'A short answer.'},
            {'role': 'user', 'content': 'Continue.'}])
        before = copy.deepcopy(p.session)
        with patch.object(p, '_single_completion', return_value='expanded summary '*100):
            p.compact_context_if_needed(force=True)
        self.assertEqual(p.session, before)

    def test_large_required_instructions_are_never_cut_to_force_admission(self):
        p = small_panel(); p.system_prompt = lambda: 'required instruction '*10000
        before = copy.deepcopy(p.session)
        with self.assertRaisesRegex(RuntimeError, 'current request does not fit'):
            p.api_messages()
        self.assertEqual(p.session, before)

    def test_worker_recovers_between_tool_steps_without_replaying_effects(self):
        from test_chat_handoff import panel as worker_panel
        from test_chat_reasoning_continuation import responses
        p = worker_panel(); context = small_panel()
        del p.api_messages; del p.compact_context_if_needed
        for name in ('memory', 'system_prompt', '_persistent_memory_query',
                     '_runtime_session_context', '_runtime_context_limit', 'user_api_message'):
            setattr(p, name, getattr(context, name))
        p._single_completion = Mock(side_effect=AssertionError('No summarizer needed'))
        p.settings['max_output_tokens'] = 2048
        p.tool_runtime.execute.return_value = 'COMPLETED_ONCE'
        call = {'id': 'large_call', 'type': 'function', 'function': {
            'name': 'shell', 'arguments': json.dumps({'command': 'inspect ' + 'x'*20000})}}
        seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('tool_calls', '', '', [call]),
                ('tool_calls', '', '', [{**call, 'id': 'repeat_call'}]),
                ('stop', 'Finished from the saved result.', '', [])], seen)):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['messages'][-1]['content'], 'Finished from the saved result.')
        self.assertFalse(any(event[0] == 'error' for event in p.ev.queue))
        self.assertIn('COMPLETED_ONCE', json.dumps(seen[1]['api']))
        p._single_completion.assert_not_called()


if __name__ == '__main__':
    unittest.main()
