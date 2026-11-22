"""Generated-file destination recovery, using disposable account fixtures only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
import native_chat as chat
from profile_paths import ProfileLocked
import test_profile_gui_paths as fixtures


class GeneratedOutputPathsTests(unittest.TestCase):
    setUp = fixtures.ProfileGUIPathsTests.setUp
    tearDown = fixtures.ProfileGUIPathsTests.tearDown
    login = fixtures.ProfileGUIPathsTests.login

    def runtime(self):
        workspace = self.login()
        (self.root/'Agent').mkdir(exist_ok=True)
        (self.root/'Agent/hardware_profiles.json').write_bytes((ROOT/'Agent/hardware_profiles.json').read_bytes())
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        fixtures.bind_account(runtime)
        return runtime, workspace

    def test_rejected_workspace_root_explains_a_writable_destination_without_writing(self):
        runtime, workspace = self.runtime()
        target = workspace/'windmill_sim.html'
        result = json.loads(runtime.write_file(str(target), '<html>generated</html>'))
        self.assertFalse(result['success'])
        self.assertFalse(result['write_started'])
        self.assertRegex(result['error'], r'Outputs/.*before any file was written')
        self.assertFalse(target.exists())
        self.assertFalse((workspace/'Outputs/windmill_sim.html').exists())

    def test_suggested_relative_destination_writes_exact_content_and_returns_real_path(self):
        runtime, workspace = self.runtime()
        text = '<!doctype html>\n<p>Windmill</p>\n'
        with patch('account_permissions.require_user', return_value=runtime._account_session):
            receipt = json.loads(runtime.write_file('Outputs/windmill_sim.html', text))
        target = workspace/'Outputs/windmill_sim.html'
        self.assertEqual(target.read_text(encoding='utf-8'), text)
        self.assertEqual(Path(receipt['path']), target)
        self.assertTrue(receipt['success'])
        self.assertFalse((self.root/'windmill_sim.html').exists())

    def test_another_profile_is_still_rejected(self):
        runtime, workspace = self.runtime()
        target = self.root/'Private/Users'/fixtures.OTHER/'Workspace/Outputs/windmill.html'
        with self.assertRaises(ProfileLocked):
            runtime.write_file(str(target), 'must not write')
        self.assertFalse(target.exists())

    def test_ended_login_cannot_write_to_suggested_destination(self):
        runtime, workspace = self.runtime()
        self.login(fixtures.OTHER)
        with self.assertRaises(ProfileLocked):
            runtime.write_file('Outputs/windmill.html', 'must not write')
        self.assertFalse((workspace/'Outputs/windmill.html').exists())

    def test_standard_account_still_cannot_edit_files(self):
        runtime, workspace = self.runtime()
        fixtures.bind_account(runtime, role='user')
        with self.assertRaises(PermissionError):
            runtime.write_file('Outputs/windmill.html', 'must not write')
        self.assertFalse((workspace/'Outputs/windmill.html').exists())

    def test_loaded_write_menu_and_workflow_include_output_destination(self):
        from chat_tool_menu import guidance, load, compact_menu
        from test_progressive_tool_worker import fixture
        p = fixture()
        load(p, {'tools':['write_file']}, chat._scoped_tools(p))
        row = next(r for r in chat._request_tools(p) if r['function']['name'] == 'write_file')
        self.assertIn('Outputs/my-app/index.html', row['function']['description'])
        self.assertIn('Outputs/', compact_menu([row])[0]['function']['description'])
        self.assertIn('Outputs/<project>/<filename>', guidance(p, chat._scoped_tools(p)))

    def test_worker_can_correct_destination_after_rejection_without_automatic_replay(self):
        from test_progressive_tool_worker import fixture, call
        runtime, workspace = self.runtime()
        p = fixture()
        p.root = self.root
        p.tool_runtime = runtime
        p.settings['tool_step_limit'] = 0
        content = '<!doctype html>\n<title>Generated fixture</title>\n'
        requests = []
        replies = [('', '', [call('help', 'tool_help', {'tools':['write_file']})]),
                   ('', '', [call('bad', 'write_file', {'path':str(workspace/'index.html'), 'content':content})]),
                   ('', '', [call('corrected', 'write_file', {'path':'Outputs/my-app/index.html', 'content':content})]),
                   ('Saved.', '', [])]
        def respond(messages):
            requests.append(messages)
            return replies.pop(0)
        with patch('account_permissions.require_user', return_value=runtime._account_session), \
             patch.object(p, 'stream_completion', side_effect=respond):
            p.agent_worker('test')
        outcomes = [m for m in p.session['messages'] if m.get('name') == 'write_file']
        self.assertEqual(len(outcomes), 2, (p.session['messages'], list(p.ev.queue)))
        self.assertIn('before any file was written', outcomes[0]['content'])
        self.assertIn('Outputs/', requests[2][-1]['content'])
        self.assertTrue(json.loads(outcomes[1]['content'])['success'])
        self.assertFalse((workspace/'index.html').exists())
        self.assertEqual((workspace/'Outputs/my-app/index.html').read_text(), content)
        self.assertEqual(outcomes[0]['execution']['outcome'], 'returned')
        self.assertFalse(json.loads(outcomes[0]['content'])['success'])
        self.assertTrue(p.session['messages'][-1]['content'].startswith('Saved.'))
        self.assertNotIn('uncertain outcome', p.session['messages'][-1]['content'])

    def test_new_bare_and_project_relative_outputs_cannot_fall_into_application_root(self):
        runtime, workspace = self.runtime()
        for relative in ('windmill.html', 'my-app/index.html'):
            result = json.loads(runtime.write_file(relative, 'not written'))
            self.assertFalse(result['success'])
            self.assertFalse(result['write_started'])
            self.assertIn('Outputs/', result['error'])
            self.assertFalse((self.root/relative).exists())
        self.assertFalse((self.root/'my-app').exists())

    def test_existing_files_public_sources_and_explicit_external_destinations_keep_admin_access(self):
        runtime, workspace = self.runtime()
        old = self.root/'existing.txt'
        old.write_text('old')
        with tempfile.TemporaryDirectory() as outside, \
             patch('account_permissions.require_user', return_value=runtime._account_session):
            targets = [('existing.txt', old), ('Agent/new_module.py', self.root/'Agent/new_module.py'),
                       (str(Path(outside)/'new.txt'), Path(outside)/'new.txt')]
            for value, target in targets:
                self.assertTrue(json.loads(runtime.write_file(value, 'x = 1\n'))['success'])
                self.assertEqual(target.read_text(), 'x = 1\n')

    def test_late_write_errors_are_not_misreported_as_zero_effect(self):
        runtime, workspace = self.runtime()
        def partially_write(*args):
            args[1].write_text('partial')
            raise OSError('fixture interrupted after write')
        with patch('code_projects.write_tracked', side_effect=partially_write):
            with self.assertRaisesRegex(OSError, 'interrupted after write'):
                runtime.write_file('Outputs/partial.txt', 'complete')
        self.assertEqual((workspace/'Outputs/partial.txt').read_text(), 'partial')


if __name__ == '__main__':
    unittest.main()
