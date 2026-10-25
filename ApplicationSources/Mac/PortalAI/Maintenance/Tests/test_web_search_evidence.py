"""Search returns usable evidence through native dispatch and chat compaction."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import web_capabilities as web
import web_tools
import chat_evidence
from chat_working_memory import evidence_lines
from tool_protocol import read_only_tool_attempt
from web_tool_api import TOOL


def search_result():
    return {'query': 'fixture product', 'provider': 'fixture', 'cached': False,
            'results': [
                {'title': 'Fixture Product '+str(i),
                 'url': 'https://example.com/products/'+str(i),
                 'snippet': 'Available in blue. '+('Details. '*800)}
                for i in range(6)], 'provider_errors': []}


def message(value, name='web'):
    return {'role': 'tool', 'name': name, 'tool_call_id': 'search_1',
            'content': json.dumps(value)}


class NativeSearchTests(unittest.TestCase):
    def test_native_search_uses_existing_provider_without_starting_browser(self):
        for role in ('admin', 'user', 'guest'):
            with self.subTest(role=role):
                profile = Mock()
                session = web.WebSession(ROOT, profile, role)
                value = search_result()
                with patch.object(web_tools, 'web_search', return_value=value) as search, \
                        patch.object(session, '_start', side_effect=AssertionError('No browser needed')):
                    result = session.run({'action': 'search', 'query': 'fixture product', 'limit': 3})
                search.assert_called_once_with('fixture product', 3, fresh=False)
                self.assertEqual(result['results'], value['results'])
                self.assertEqual(result['kind'], 'search_results')
                self.assertIn('snippets', result['source'].lower())
                self.assertGreaterEqual(profile.check.call_count, 2)

    def test_search_requires_valid_query_limit_and_fresh_boolean(self):
        session = web.WebSession(ROOT, Mock())
        bad = ({}, {'query': ''}, {'query': ' '}, {'query': 42},
               {'query': 'x', 'limit': True}, {'query': 'x', 'limit': 0},
               {'query': 'x', 'limit': 13}, {'query': 'x', 'fresh': 'false'})
        with patch.object(web_tools, 'web_search') as search:
            for args in bad:
                with self.subTest(args=args), self.assertRaises(ValueError):
                    session.run({'action': 'search', **args})
            search.assert_not_called()

    def test_search_rechecks_login_and_propagates_provider_failure(self):
        profile = Mock()
        profile.check.side_effect = [None, PermissionError('login ended')]
        session = web.WebSession(ROOT, profile)
        with patch.object(web_tools, 'web_search', return_value=search_result()):
            with self.assertRaises(PermissionError):
                session.run({'action': 'search', 'query': 'fixture'})
        with patch.object(web_tools, 'web_search', side_effect=web_tools.WebAccessError('provider blocked')):
            with self.assertRaises(web_tools.WebAccessError):
                web.WebSession(ROOT, Mock()).run({'action': 'search', 'query': 'fixture'})

    def test_help_is_discovery_only_and_advertises_search(self):
        result = web.WebSession(ROOT, Mock()).run({'action': 'help'})
        self.assertEqual(result['kind'], 'tool_help')
        self.assertIn('search', result['actions'])
        self.assertIn('no search', result['note'].lower())
        self.assertIn('query', TOOL['function']['parameters']['properties']['arguments']['properties'])

    def test_only_help_and_search_are_new_safe_format_recovery_routes(self):
        for action in ('help', 'search'):
            self.assertTrue(read_only_tool_attempt('web', {'action': action}, ROOT))
        for action in ('click', 'fill', 'request', 'unknown'):
            self.assertFalse(read_only_tool_attempt('web', {'action': action}, ROOT))


class SearchEvidenceTests(unittest.TestCase):
    def test_large_native_and_cli_search_keep_paired_titles_links_and_snippets(self):
        for name, value in (('web', {'ok': True, 'result': search_result()}),
                            ('shell', search_result())):
            row = message(value, name)
            before = copy.deepcopy(row)
            view = chat_evidence.project(row, 2, 1400)
            self.assertLessEqual(len(view), 1400)
            compact = json.loads(view)
            self.assertEqual(compact['kind'], 'search_results')
            self.assertEqual(compact['message_id'], 2)
            self.assertTrue(compact['results'])
            self.assertEqual(compact['results'][0]['url'], 'https://example.com/products/0')
            self.assertIn('Fixture Product 0', compact['results'][0]['title'])
            self.assertIn('Available in blue.', compact['results'][0]['snippet'])
            self.assertIn('snippet', compact['source'].lower())
            self.assertEqual(row, before)

    def test_rolling_checkpoint_keeps_search_details_instead_of_just_ok(self):
        result = message({'ok': True, 'result': search_result()})
        messages = [{'role': 'user', 'content': 'Find fixture product'},
                    {'role': 'assistant', 'tool_calls': [{'id': 'search_1', 'function': {
                        'name': 'web', 'arguments': '{"action":"search","arguments":{"query":"fixture product"}}'}}]},
                    result]
        view = evidence_lines(messages, max_chars=900)
        self.assertIn('https://example.com/products/0', view)
        self.assertIn('Fixture Product 0', view)
        self.assertIn('Available in blue.', view)
        self.assertNotEqual(view.strip().splitlines()[-1], 'ok: True')

    def test_legacy_help_never_becomes_search_success(self):
        row = message({'ok': True, 'result': {'actions': {'read': 'url', 'open': 'url'},
                                             'rules': 'Public HTTP(S) only.'}})
        view = evidence_lines([row], max_chars=700)
        self.assertIn('tool_help', view)
        self.assertIn('no search', view.lower())
        self.assertNotIn('ok: True', view)

    def test_long_urls_are_omitted_whole_and_exact_history_survives(self):
        value = search_result()
        value['results'][0]['url'] = 'https://example.com/' + 'x'*4000
        row = message({'ok': True, 'result': value})
        view = chat_evidence.project(row, 0, 900)
        self.assertLessEqual(len(view), 900)
        compact = json.loads(view)
        for item in compact['results']:
            self.assertIn(item['url'], [r['url'] for r in value['results']])
        recovered = json.loads(chat_evidence.execute({'messages': [row]},
                                {'action': 'read', 'message_id': 0, 'limit': 8000}))
        self.assertEqual(recovered['text'], row['content'][:8000])

    def test_cli_json_with_exit_trailer_and_empty_results_are_honest(self):
        row = message(search_result(), 'shell')
        row['content'] += '\n[exit code 0]'
        self.assertIn('https://example.com/products/0', chat_evidence.project(row, 4, 900))
        empty = message({'ok': True, 'result': {'query': 'nothing', 'results': [], 'provider': 'fixture'}})
        view = evidence_lines([empty], max_chars=700)
        self.assertIn('"result_count":0', view)
        self.assertIn('"results":[]', view)

    def test_generic_search_named_data_and_web_errors_are_not_reclassified(self):
        for value in ({'results': [{'title': 'local file', 'path': 'file.txt'}]},
                      {'ok': False, 'error': 'Search unavailable'},
                      {'results': [{'url': 'https://example.com/'}], 'query': 'local'}):
            row = message(value, 'read_file')
            self.assertEqual(chat_evidence.project(row, 1, 3000), row['content'])

    def test_failed_cli_search_preserves_failure_instead_of_claiming_results(self):
        row = message({'success': False, 'error': 'provider failed', **search_result()}, 'shell')
        self.assertIsNone(chat_evidence.web_evidence(row, 1, 900))
        self.assertIn('success: False', evidence_lines([row], max_chars=700))

    def test_help_then_search_keeps_findings_and_execution_receipts_in_chat(self):
        sys.path.insert(0, str(ROOT/'Maintenance/Tests'))
        from test_chat_handoff import panel
        p = panel()  # Disposable root; never bind fixtures to the owner account.
        calls = [{'id': action, 'type':'function', 'function': {
            'name':'web', 'arguments':json.dumps({'action':action, 'arguments':
                {'query':'fixture product'} if action == 'search' else {}})}} for action in ('help','search')]
        p.tool_runtime.execute.side_effect = [
            json.dumps({'ok':True, 'result':web.WebSession(ROOT, Mock()).run({'action':'help'})}),
            json.dumps({'ok':True, 'result':search_result()})]
        seen = []
        def respond(messages):
            seen.append(copy.deepcopy(messages))
            if len(seen) <= 2:
                return '', '', [calls[len(seen)-1]]
            view = evidence_lines(p.session['messages'], max_chars=1400)
            self.assertIn('https://example.com/products/0', view)
            self.assertIn('Available in blue.', view)
            self.assertIn('no search was performed', view)
            return 'Fixture Product 0: https://example.com/products/0', '', []
        with patch.object(p, 'stream_completion', side_effect=respond):
            p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count, 2)
        self.assertEqual(len(seen), 3)
        rows = [row for row in p.session['messages'] if row.get('role') == 'tool']
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row['execution']['dispatched'] for row in rows))
        self.assertTrue(all(not row['execution']['effectful'] for row in rows))


    def test_invalid_web_action_is_not_read_only(self):
        for action in ([], {}, None, True, 42):
            with self.subTest(action=action):
                self.assertFalse(read_only_tool_attempt('web', {'action': action}, ROOT))

    def test_failed_wrapped_search_preserves_failure(self):
        for status in ('ok', 'success'):
            row = message({'ok': True, 'result': {**search_result(), status: False,
                                                'error': 'provider failed'}})
            self.assertIsNone(chat_evidence.web_evidence(row, 1, 900))
            view = evidence_lines([row], max_chars=900)
            self.assertIn('provider failed', view)
            self.assertNotIn('"kind":"search_results"', view)



if __name__ == '__main__':
    unittest.main()
