"""Synthetic active-chat rollover; no models, missions, accounts or real tools."""
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
import native_chat as chat
from chat_budgets import generation_options, response_limits
from chat_effort_ui import completion_options
from chat_model_switch import _result
from profile_paths import ProfileLocked
from test_chat_handoff import panel, CALL
from test_chat_context_budget import panel as context_panel


def fixture(budget=16000):
    p = panel()
    p._last_context_meta = {'budget': budget}
    p._reply_without_tools = False
    p._continuation_remaining = 2
    p._runtime_context_limit = lambda: 16384
    return p


def responses(p, rows, record):
    def respond(api):
        record.append({'api': copy.deepcopy(api), 'options': copy.deepcopy(getattr(p, '_completion_overrides', None)),
                       'no_tools': p._reply_without_tools})
        reason, content, thinking, calls = rows.pop(0)
        p._last_finish_reason = reason
        return content, thinking, calls
    return respond


class ReasoningContinuationTests(unittest.TestCase):
    def test_answer_only_policy_rejects_server_tool_batch_before_any_execution(self):
        p = fixture(); p._reply_without_tools = True
        response = Mock(status=200)
        response.readline.side_effect = [b'data: ' + json.dumps({'choices': [{'delta': {
            'tool_calls': [{'index': 0, **CALL}]}, 'finish_reason': 'tool_calls'}]}).encode() + b'\n']
        conn = Mock(); conn.getresponse.return_value = response
        with patch.object(chat, 'model_id', return_value='synthetic'), \
             patch.object(chat.http.client, 'HTTPConnection', return_value=conn):
            with self.assertRaisesRegex(chat.InvalidToolBatch, 'answer-only'):
                p._stream_completion_once(p.session['messages'])
        p.tool_runtime.execute.assert_not_called()

    def test_partial_visible_output_rolls_over_and_is_saved_without_reemission(self):
        p = fixture(); seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', 'Let me check that.', 'A useful intermediate discovery.', []),
                ('stop', 'The complete answer is 1591.', '', [])], seen)):
            result = p._completion_with_continuation(p.session['messages'][:], 4000, {})
        self.assertEqual(result[0], 'The complete answer is 1591.')
        self.assertEqual(p.session['messages'][-1]['content'], 'Let me check that.')
        self.assertIn('Let me check that.', json.dumps(seen[1]['api']))
        self.assertFalse(any(event[0] == 'content' for event in p.ev.queue), 'Already-streamed partial text must not be emitted a second time')

    def test_saved_projection_survives_tool_stage_and_later_continue_without_resending_raw_reasoning(self):
        p = fixture(); seen = []; raw = 'Detailed intermediate hypothesis. ' * 600
        with patch.object(p, '_single_completion', return_value='Compact discovery ABC-42; next inspect the confirmed output.'), \
             patch.object(p, 'stream_completion', side_effect=responses(p, [
                 ('length', '', raw, []), ('tool_calls', '', '', [CALL])], seen)):
            result = p._completion_with_continuation(p.session['messages'][:], 4000, {})
        self.assertEqual(result[2], [CALL])
        p.session['messages'].extend([
            {'role': 'assistant', 'content': '', 'tool_calls': [CALL]},
            {'role': 'tool', 'tool_call_id': CALL['id'], 'content': 'Confirmed ALREADY_DONE output'}])
        q = context_panel(); q.session = json.loads(json.dumps(p.session))
        q.user_api_message = lambda message: {'role': 'user', 'content': message['content']}
        for followup in (False, True):
            if followup: q.session['messages'].append({'role': 'user', 'content': 'continue'})
            api, estimated = q.api_messages()
            serialized = json.dumps(api)
            self.assertIn('Test', serialized); self.assertIn('ABC-42', serialized)
            self.assertIn('Confirmed ALREADY_DONE', serialized); self.assertNotIn(raw, serialized)
            self.assertLess(estimated, q._last_context_meta['budget'])
        self.assertEqual(q.session['messages'][1]['reasoning'], raw)
        summary_input = q._summary_transcript(q.session['messages'])
        self.assertIn('ABC-42', summary_input); self.assertIn('fallible', summary_input)
        self.assertNotIn(raw, summary_input)

    def test_superseded_checkpoint_is_preserved_for_review_but_not_counted_or_sent(self):
        p = fixture(); seen = []; raw = 'Intermediate reasoning detail. ' * 700
        with patch.object(p, '_single_completion', side_effect=['First compact note.', 'Combined compact note.']), \
             patch.object(p, 'stream_completion', side_effect=responses(p, [
                 ('length', '', raw, []), ('length', '', raw, []), ('stop', 'Final.', '', [])], seen)):
            p._completion_with_continuation(p.session['messages'][:], 4000, {})
        older, current = p.session['messages'][-2:]
        self.assertEqual(older['reasoning'], raw); self.assertEqual(current['reasoning'], raw)
        self.assertIsNone(p._api_row(older)); self.assertEqual(p._message_cost(older), 0)
        self.assertIn('Combined compact note.', p._api_row(current)['content'])
        transcript = p._summary_transcript(p.session['messages'])
        self.assertNotIn('First compact note.', transcript); self.assertIn('Combined compact note.', transcript)

    def test_exhausted_reasoning_retains_original_task_and_resumes_once(self):
        p = fixture(); original = copy.deepcopy(p.session['messages']); seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', 'Unfinished discovery: identifier ABC-42.', []),
                ('stop', 'The answer using ABC-42.', 'Checked conclusion.', [])], seen)):
            value = p._completion_with_continuation(original, 4000, {})
        self.assertEqual(value[0], 'The answer using ABC-42.')
        self.assertEqual(seen[1]['api'][:len(original)], original)
        self.assertIn('ABC-42', json.dumps(seen[1]['api']))
        normalized = chat._normalize_qwen_messages(seen[1]['api'])
        self.assertEqual(normalized[-1]['role'], 'user', 'The checkpoint must not become an assistant prefill')
        self.assertIn('host continuation control', normalized[-1]['content'])
        self.assertNotIn('host continuation control', json.dumps(p.session))
        checkpoint = p.session['messages'][-1]
        self.assertTrue(checkpoint['continuation_checkpoint'])
        self.assertTrue(checkpoint['incomplete']); self.assertNotIn('tool_calls', checkpoint)
        self.assertEqual(checkpoint['reasoning'], 'Unfinished discovery: identifier ABC-42.')
        self.assertEqual(p.store.save_session.call_count, 2); p.tool_runtime.execute.assert_not_called()

    def test_two_rollovers_reserve_final_answer_and_disable_tools(self):
        p = fixture(); seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', 'First inference discovery.', []),
                ('length', '', 'Second inference refinement.', []),
                ('stop', 'Final answer.', '', [])], seen)):
            result = p._completion_with_continuation(p.session['messages'][:], 4000, {})
        self.assertEqual(result[0], 'Final answer.')
        self.assertFalse(seen[1]['no_tools']); self.assertTrue(seen[2]['no_tools'])
        self.assertEqual(seen[2]['options'], {'chat_template_kwargs': {'enable_thinking': False}})
        self.assertIn('First inference discovery.', json.dumps(seen[2]['api']))
        self.assertIn('Second inference refinement.', json.dumps(seen[2]['api']))
        self.assertEqual(p._continuation_remaining, 0)
        self.assertFalse(p._reply_without_tools); self.assertIsNone(p._completion_overrides)

    def test_compaction_replaces_working_note_only_and_preserves_tool_evidence(self):
        p = fixture(6000); seen = []; reasoning = 'A long intermediate hypothesis. ' * 300
        original = [*p.session['messages'], {'role': 'assistant', 'content': '', 'tool_calls': [CALL]},
                    {'role': 'tool', 'tool_call_id': CALL['id'], 'content': 'ALREADY_DONE exact output'}]
        saved = copy.deepcopy(original)
        with patch.object(p, '_single_completion', return_value='Compact working discovery ABC-42.') as compact, \
             patch.object(p, 'stream_completion', side_effect=responses(p, [
                 ('length', '', reasoning, []), ('stop', 'Answer from saved output.', '', [])], seen)):
            p._completion_with_continuation(original, 4800, {'unsafe_attempted': True})
        compact.assert_called_once()
        self.assertEqual(original, saved)
        self.assertEqual(seen[1]['api'][:len(original)], original)
        self.assertIn('Compact working discovery', json.dumps(seen[1]['api']))
        self.assertFalse(seen[1]['no_tools'])
        self.assertEqual(p.session['messages'][-1]['reasoning'], reasoning)
        p.tool_runtime.execute.assert_not_called()

    def test_failed_compaction_keeps_checkpoint_without_another_inference(self):
        p = fixture(6000); seen = []
        with patch.object(p, '_single_completion', side_effect=RuntimeError('truncated summary')), \
             patch.object(p, 'stream_completion', side_effect=responses(p, [
                 ('length', '', 'Long working note. '*600, [])], seen)) as stream:
            with self.assertRaisesRegex(RuntimeError, 'truncated summary'):
                p._completion_with_continuation(p.session['messages'][:], 4800, {})
        stream.assert_called_once(); self.assertTrue(p.session['messages'][-1]['continuation_checkpoint'])

    def test_context_room_is_admitted_before_continuing(self):
        p = fixture(5000); seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', 'Working note.', []), ('stop', 'Complete answer.', '', [])], seen)) as stream:
            result=p._completion_with_continuation(p.session['messages'][:], 4950, {})
        self.assertEqual(result[0],'Complete answer.')
        self.assertLess(p._last_context_meta['output_reserve'],2048)
        self.assertGreaterEqual(p._last_context_meta['output_reserve'],256)
        self.assertEqual(stream.call_count,2); p.tool_runtime.execute.assert_not_called()

    def test_token_exhaustion_is_required_not_an_ordinary_empty_response(self):
        for reason in ('stop', None):
            p = fixture(); seen = []
            with patch.object(p, 'stream_completion', side_effect=responses(p, [(reason, '', 'A thought.', [])], seen)) as stream:
                p._completion_with_continuation(p.session['messages'][:], 4000, {})
            stream.assert_called_once(); p.store.save_session.assert_not_called()

    def test_effectful_tool_cannot_be_reissued_by_continuation(self):
        p = fixture(); seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', 'Reasoning after an existing effect.', []), ('tool_calls', '', '', [CALL])], seen)):
            args=json.loads(CALL['function']['arguments'])
            state={'unsafe_attempted':True,'attempted_actions':{('shell',json.dumps(args,sort_keys=True,ensure_ascii=True))}}
            with self.assertRaisesRegex(chat.InvalidToolBatch, 'withheld'):
                p._completion_with_continuation(p.session['messages'][:], 4000, state)
        self.assertFalse(seen[1]['no_tools']); p.tool_runtime.execute.assert_not_called()

    def test_even_identical_read_only_action_is_not_automatically_replayed(self):
        p = fixture(); seen = []; args = json.loads(CALL['function']['arguments'])
        state = {'attempted_actions': {('shell', json.dumps(args, sort_keys=True, ensure_ascii=True))}}
        with patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', 'Working note.', []), ('tool_calls', '', '', [CALL])], seen)):
            with self.assertRaisesRegex(chat.InvalidToolBatch, 'repeated'):
                p._completion_with_continuation(p.session['messages'][:], 4000, state)
        p.tool_runtime.execute.assert_not_called()

    def test_stop_during_compaction_cancels_resumption(self):
        p = fixture(6000); seen = []
        def compact(*_args, **_kwargs):
            p.cancel_event.set(); return 'Small note.'
        with patch.object(p, '_single_completion', side_effect=compact), \
             patch.object(p, 'stream_completion', side_effect=responses(p, [
                 ('length', '', 'Long working note. '*600, [])], seen)) as stream:
            self.assertEqual(p._completion_with_continuation(p.session['messages'][:], 4800, {}), ('', '', []))
        stream.assert_called_once(); self.assertIsNone(p._continuation_deadline)

    def test_revoked_profile_does_not_save_checkpoint_or_resume(self):
        p = fixture(); active = {'value': True}
        def check():
            if not active['value']: raise ProfileLocked('login ended')
        def respond(_api):
            active['value'] = False; p._last_finish_reason = 'length'
            return '', 'A thought.', []
        p._check_login = check
        with patch.object(p, 'stream_completion', side_effect=respond) as stream:
            with self.assertRaises(ProfileLocked): p._completion_with_continuation(p.session['messages'][:], 4000, {})
        stream.assert_called_once(); p.store.save_session.assert_not_called()

    def test_exhausted_rollovers_save_last_checkpoint_and_report_blocker(self):
        p = fixture(); p._continuation_remaining = 0; seen = []
        with patch.object(p, 'stream_completion', side_effect=responses(p, [('length', '', 'Last thought.', [])], seen)) as stream:
            with self.assertRaisesRegex(RuntimeError, 'bounded reasoning continuations'):
                p._completion_with_continuation(p.session['messages'][:], 4000, {})
        stream.assert_called_once(); self.assertEqual(p.store.save_session.call_count, 2)


class BudgetTests(unittest.TestCase):
    def test_cached_admitted_model_receives_updated_budgets_without_changing_plan(self):
        plan = {'model': {'id': 'qwen27-q4', 'context_tokens': 32768},
                'completion_options': {'max_tokens': 2048, 'chat_template_kwargs': {}}, 'max_tool_rounds': 12}
        original = copy.deepcopy(plan)
        result = _result('balanced', plan, False)
        self.assertFalse(result['changed']); self.assertEqual(plan, original)
        self.assertEqual(result['completion_options'], generation_options('balanced', 32768))

    def test_profiles_control_actual_reasoning_and_generated_token_allowance(self):
        self.assertEqual(generation_options('fast', 8192)['max_tokens'], 1024)
        self.assertEqual(generation_options('balanced', 8192)['max_tokens'], 2048)
        self.assertEqual(generation_options('balanced', 32768)['max_tokens'], 4096)
        self.assertEqual(generation_options('deep', 2048)['max_tokens'], 1024)
        self.assertEqual(generation_options('balanced', 32768)['chat_template_kwargs']['reasoning_effort'], 'low')
        self.assertEqual(generation_options('deep', 32768)['chat_template_kwargs']['reasoning_effort'], 'xhigh')

    def test_completion_allowlist_keeps_effort_but_cannot_override_tools(self):
        options = generation_options('balanced', 32768)
        self.assertEqual(completion_options({'completion_options': {**options, 'tools': [], 'tool_choice': 'none'}}), options)

    def test_wait_budget_increases_with_output_and_slow_execution_but_stays_finite(self):
        base = response_limits(chat.DEFAULT_SETTINGS, 2048, profile='balanced')
        deep = response_limits(chat.DEFAULT_SETTINGS, 8192, profile='deep')
        slow = response_limits(chat.DEFAULT_SETTINGS, 8192, profile='deep', slow=True)
        self.assertGreater(deep[1], base[1]); self.assertGreater(slow[1], deep[1])
        self.assertLessEqual(slow[1], 1800); self.assertEqual(slow[0], 300)

    def test_summary_turn_disables_thinking_and_rejects_truncation(self):
        for finish in ('length', 'stop'):
            p = fixture(); response = Mock(status=200)
            response.read.return_value = json.dumps({'choices': [{'finish_reason': finish, 'message': {'content': 'Summary text.'}}]}).encode()
            conn = Mock(); conn.getresponse.return_value = response
            with patch.object(p, '_wait_for_model', return_value=True), patch.object(chat, 'model_id', return_value='synthetic'), \
                 patch.object(chat.http.client, 'HTTPConnection', return_value=conn):
                if finish == 'length':
                    with self.assertRaisesRegex(RuntimeError, 'did not finish cleanly'):
                        p._single_completion([{'role': 'user', 'content': 'Older history.'}], max_tokens=256)
                else:
                    self.assertEqual(p._single_completion([{'role': 'user', 'content': 'Older history.'}], max_tokens=256), 'Summary text.')
            payload = json.loads(conn.request.call_args.kwargs['body'])
            self.assertEqual(payload['chat_template_kwargs'], {'enable_thinking': False})


if __name__ == '__main__': unittest.main()
