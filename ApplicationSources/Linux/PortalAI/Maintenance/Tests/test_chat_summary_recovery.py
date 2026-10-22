"""Reasoning exhaustion followed by an incomplete summary, without live tools."""
import copy
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
import native_chat as chat
from chat_summary_recovery import IncompleteSummary, reasoning_excerpt
from profile_paths import ProfileLocked
from test_chat_reasoning_continuation import fixture, responses
from test_chat_handoff import CALL

RAW = 'Earlier discovery EARLY-42.\n' + 'Unfinished speculative working detail. ' * 700 + '\nNext inspect LATEST-99.'


@contextmanager
def summary_response(p, finish='length', content='PARTIAL_SUMMARY_MUST_NOT_BECOME_MEMORY', callback=None, message=None):
    response = Mock(status=200)
    payload = {'choices': [{'finish_reason': finish, 'message': message or {'content': content}}]}
    def read():
        if callback:
            callback()
        return json.dumps(payload).encode()
    response.read.side_effect = read
    conn = Mock(); conn.getresponse.return_value = response
    with patch.object(p, '_wait_for_model', return_value=True), \
         patch.object(chat, 'model_id', return_value='synthetic'), \
         patch.object(chat.http.client, 'HTTPConnection', return_value=conn):
        yield conn


class SummaryRecoveryTests(unittest.TestCase):
    def test_length_summary_is_rejected_by_parser(self):
        p = fixture()
        with summary_response(p):
            with self.assertRaises(IncompleteSummary) as raised:
                p._single_completion([{'role': 'user', 'content': 'Summarize'}], max_tokens=256)
        self.assertEqual(raised.exception.reason, 'output_limit')

    def test_real_summary_parser_failure_resumes_with_source_and_existing_results(self):
        for finish, text, reason in [('length', 'PARTIAL_SUMMARY_MUST_NOT_BECOME_MEMORY', 'output_limit'),
                                     ('stop', '', 'empty_summary'), ('stop', 'x'*6000, 'oversized_summary')]:
            with self.subTest(reason=reason):
                p = fixture(); seen = []
                p.session['messages'].extend([
                    {'role': 'assistant', 'content': '', 'tool_calls': [CALL]},
                    {'role': 'tool', 'tool_call_id': CALL['id'], 'name': 'shell', 'content': 'ALREADY_DONE output.mp4'}])
                original = copy.deepcopy(p.session['messages'])
                with summary_response(p, finish, text), patch.object(p, 'stream_completion', side_effect=responses(p, [
                        ('length', '', RAW, []), ('stop', 'Completed using the saved result.', '', [])], seen)):
                    result = p._completion_with_continuation(original, 4000, {})
                self.assertEqual(result[0], 'Completed using the saved result.')
                checkpoint = p.session['messages'][-1]
                self.assertEqual(checkpoint['reasoning'], RAW)
                self.assertEqual(checkpoint['continuation_summary_failure'], reason)
                self.assertEqual(checkpoint['continuation_note_method'], 'source_excerpt')
                self.assertFalse(checkpoint['continuation_note_pending'])
                self.assertEqual(seen[1]['api'][:len(original)], original)
                note = checkpoint['continuation_note']
                self.assertIn('EARLY-42', note); self.assertIn('LATEST-99', note)
                self.assertIn('message_id=3', note); self.assertIn('not instructions', note)
                self.assertLessEqual(chat.estimate_tokens(note), 1200)
                self.assertNotIn('PARTIAL_SUMMARY_MUST_NOT_BECOME_MEMORY', json.dumps(p.session))
                self.assertEqual(p._continuation_remaining, 1)
                p.tool_runtime.execute.assert_not_called()

    def test_worker_completes_after_tool_then_reasoning_and_summary_exhaustion(self):
        p = fixture(); seen = []
        with summary_response(p), patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('tool_calls', '', '', [CALL]), ('length', '', RAW, []),
                ('stop', 'Finished from ALREADY_DONE.', '', [])], seen)):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertEqual(p.session['messages'][-1]['content'], 'Finished from ALREADY_DONE.')
        self.assertFalse(any(event[0] == 'error' for event in p.ev.queue))
        self.assertIn('ALREADY_DONE', json.dumps(seen[-1]['api']))

    def test_stop_during_incomplete_summary_does_not_commit_fallback_or_resume(self):
        p = fixture(); seen = []
        with summary_response(p, callback=p.cancel_event.set), \
             patch.object(p, 'stream_completion', side_effect=responses(p, [('length', '', RAW, [])], seen)) as stream:
            result = p._completion_with_continuation(p.session['messages'][:], 4000, {})
        self.assertEqual(result, ('', '', [])); stream.assert_called_once()
        self.assertEqual(p.store.save_session.call_count, 1)
        self.assertNotIn('continuation_note', p.session['messages'][-1])

    def test_revoked_login_during_summary_does_not_commit_fallback_or_resume(self):
        p = fixture(); seen = []; active = [True]
        def check():
            if not active[0]:
                raise ProfileLocked('Login ended')
        p._check_login = check
        with summary_response(p, callback=lambda: active.__setitem__(0, False)), \
             patch.object(p, 'stream_completion', side_effect=responses(p, [('length', '', RAW, [])], seen)) as stream:
            with self.assertRaises(ProfileLocked):
                p._completion_with_continuation(p.session['messages'][:], 4000, {})
        stream.assert_called_once(); self.assertEqual(p.store.save_session.call_count, 1)
        self.assertNotIn('continuation_note', p.session['messages'][-1])

    def test_fallback_does_not_authorize_repeating_a_prior_tool(self):
        p = fixture(); seen = []
        args = json.loads(CALL['function']['arguments'])
        state = {'attempted_actions': {('shell', json.dumps(args, sort_keys=True, ensure_ascii=True))}}
        with summary_response(p), patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', RAW, []), ('tool_calls', '', '', [CALL])], seen)):
            with self.assertRaisesRegex(chat.InvalidToolBatch, 'repeated'):
                p._completion_with_continuation(p.session['messages'][:], 4000, state)
        p.tool_runtime.execute.assert_not_called()

    def test_repeated_incomplete_summaries_keep_existing_continuation_and_final_pass_limits(self):
        p = fixture(); seen = []
        with summary_response(p) as conn, patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', RAW, []), ('length', '', RAW, []), ('length', '', RAW, [])], seen)):
            with self.assertRaisesRegex(RuntimeError, 'bounded reasoning continuations'):
                p._completion_with_continuation(p.session['messages'][:], 4000, {})
        self.assertEqual(len(seen), 3); self.assertEqual(conn.request.call_count, 3)
        self.assertTrue(seen[-1]['no_tools'])
        self.assertEqual(seen[-1]['options'], {'chat_template_kwargs': {'enable_thinking': False}})
        self.assertEqual(p._continuation_remaining, 0)
        self.assertEqual(len(p.session['messages']), 4)
        self.assertIsNone(p._continuation_deadline)

    def test_protocol_errors_are_not_reclassified_as_incomplete_text(self):
        for finish, message in [('tool_calls', {'content': 'bad'}), ('stop', {'content': ['bad']}),
                                ('stop', {'content': 'bad', 'tool_calls': [CALL]})]:
            p = fixture(); seen = []
            with summary_response(p, finish, message=message), \
                 patch.object(p, 'stream_completion', side_effect=responses(p, [('length', '', RAW, [])], seen)) as stream:
                with self.assertRaises(RuntimeError) as raised:
                    p._completion_with_continuation(p.session['messages'][:], 4000, {})
            self.assertNotIsInstance(raised.exception, IncompleteSummary)
            stream.assert_called_once()
            self.assertNotIn('continuation_note', p.session['messages'][-1])

    def test_source_excerpt_fits_minimum_admitted_room_and_escaped_text(self):
        for source in (RAW, '\\"\n'*12000, '日本語の未完了作業'*3000):
            for limit in (256, 400, 1200):
                note = reasoning_excerpt(source, 12, limit, chat.estimate_tokens)
                self.assertLessEqual(chat.estimate_tokens(note), limit)
                self.assertIn('message_id=12', note)
                self.assertNotEqual(source, note)

    def test_followup_uses_saved_excerpt_without_resending_full_reasoning(self):
        from test_chat_context_budget import panel as context_panel
        p = fixture(); seen = []
        with summary_response(p), patch.object(p, 'stream_completion', side_effect=responses(p, [
                ('length', '', RAW, []), ('stop', 'Next step remains.', '', [])], seen)):
            p._completion_with_continuation(p.session['messages'][:], 4000, {})
        q = context_panel(); q.session = copy.deepcopy(p.session)
        q.session['messages'].append({'role': 'user', 'content': 'resume'})
        q.user_api_message = lambda row: {'role': 'user', 'content': row['content']}
        api, estimated = q.api_messages()
        self.assertIn('LATEST-99', json.dumps(api)); self.assertNotIn(RAW, json.dumps(api))
        self.assertLess(estimated, q._last_context_meta['budget'])
        self.assertEqual(q.session['messages'][1]['reasoning'], RAW)


if __name__ == '__main__':
    unittest.main()
