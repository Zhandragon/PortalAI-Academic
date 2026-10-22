"""Public web access for authenticated accounts, using literal argv and temp roots."""
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import native_chat as chat
from account_tool_policy import registered_media_argv, WEB_COMMANDS
from local_accounts import Session
from profile_paths import UID_ENV, EPOCH_ENV, ProfileLocked


class WebCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.boot = self.root/'Runtime/python.exe'

    def test_every_registered_web_command_preserves_literal_inputs(self):
        cases = {
            'search': ['search', 'astronomy from blogs and forums', '--limit', '12', '--fresh'],
            'fetch': ['fetch', 'https://arbitrary.example/article?x=1&y=2', '--max-chars', '50000'],
            'research': ['research', 'independent sources', '--fetch-count', '5', '--limit', '8'],
            'image-search': ['image-search', 'a red panda', '--page-limit', '8'],
            'image': ['image', 'a lighthouse', '--page-limit', '1'],
            'download-image': ['download-image', 'https://cdn.example/photo.png?x=1&y=2', '--name', 'public photo'],
            'selftest': ['selftest'],
        }
        self.assertEqual(set(cases), WEB_COMMANDS)
        for args in cases.values():
            with self.subTest(command=args[0]), patch('chat_model_switch._argv', side_effect=shlex.split):
                command = 'python Agent/web_tools.py ' + shlex.join(args)
                argv = registered_media_argv(command, self.root, self.boot)
                self.assertEqual(argv, [str(self.boot), str(self.root/'Agent/web_tools.py'), *args])

    def test_windows_wrapper_and_script_are_portable_to_posix_tokenization(self):
        command = r'.\Tools\portable_python.cmd Agent\web_tools.py search "quoted query with spaces"'
        with patch('chat_model_switch._argv', side_effect=shlex.split):
            argv = registered_media_argv(command, self.root, self.boot)
        self.assertEqual(argv[-2:], ['search', 'quoted query with spaces'])

    def test_web_cannot_select_host_or_other_profile_output_paths(self):
        for args in ('image a --output C:/outside',
                     'download-image https://example.com/a.png --output-root Private/Users/other',
                     'fetch https://example.com --output Data/stolen.txt',
                     'research x --config C:/host.json'):
            with self.subTest(args=args), self.assertRaises(PermissionError):
                registered_media_argv('python Agent/web_tools.py ' + args, self.root, self.boot)

    def test_shell_chaining_code_execution_unknown_and_malformed_flags_are_denied(self):
        for command in (
            'python Agent/web_tools.py search test & whoami',
            'python Agent/web_tools.py search test; whoami',
            'python Agent/web_tools.py search test | more',
            'python -c "print(1)"',
            'python Agent/local_accounts.py status',
            'python Agent/web_tools.py exec whoami',
            'python Agent/web_tools.py search " "',
            'python Agent/web_tools.py search test --lim 3',
            'python Agent/web_tools.py search test --limit NaN',
            'python Agent/web_tools.py search test --limit 9999999',
            'python Agent/web_tools.py image test --page-limit -1',
            'python Agent/web_tools.py research test --fetch-count 6',
            'python Agent/web_tools.py fetch https://example.com --max-chars 9999999',
            'python Agent/web_tools.py search test\nwhoami',
            'python Agent/web_tools.py search test\x00ignored',
        ):
            with self.subTest(command=command), self.assertRaises(PermissionError):
                registered_media_argv(command, self.root, self.boot)


class WebAccountRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name); self.uid = 'a'*32; self.epoch = 'b'*32
        (self.root/'Private').mkdir()
        self.marker = self.root/'Private/active-session.json'
        self.state = {'user_id': self.uid, 'epoch': self.epoch, 'state': 'open'}
        self.marker.write_text(json.dumps(self.state))
        env = patch.dict(os.environ, {UID_ENV:self.uid, EPOCH_ENV:self.epoch, 'PORTALAI_ACCOUNT_UNLOCK':'synthetic-secret'})
        env.start(); self.addCleanup(env.stop)

    def runtime(self, role):
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        session = Mock(spec=Session, user_id=self.uid, active=True, profile_key=b'k'*32, role=role)
        runtime.bind_account(session)
        return runtime

    def test_standard_and_guest_web_use_no_shell_and_keep_private_environment(self):
        for role in ('user', 'guest'):
            runtime = self.runtime(role)
            process = Mock(returncode=0); process.communicate.return_value = ('{"success":true}', '')
            with patch.object(chat.subprocess, 'Popen', return_value=process) as popen, \
                 patch.object(runtime, '_start_linux', return_value=process) as linux:
                self.assertEqual(runtime.execute('shell', {'command':'python Agent/web_tools.py search "ordinary arbitrary topic"'}), '{"success":true}')
            call = popen.call_args if os.name == 'nt' else linux.call_args
            self.assertIs(call.kwargs['shell'], False)
            self.assertEqual(call.args[0][-2:], ['search', 'ordinary arbitrary topic'])
            self.assertEqual(call.args[0][1], str(self.root/'Agent/web_tools.py'))
            env = call.kwargs['env'] if os.name == 'nt' else call.args[1]
            self.assertEqual(env[UID_ENV], self.uid); self.assertEqual(env[EPOCH_ENV], self.epoch)
            self.assertNotIn('PORTALAI_ACCOUNT_UNLOCK', env)
            self.assertTrue(Path(env['TEMP']).is_relative_to(self.root/'Private/Users'/self.uid/'Workspace'))
            if os.name == 'nt':
                self.assertEqual(Path(call.kwargs['cwd']), self.root/'Private/Users'/self.uid/'Workspace')

    def test_revoked_login_cannot_launch_a_registered_web_command(self):
        runtime = self.runtime('guest')
        self.marker.write_text(json.dumps({**self.state, 'state':'closed'}))
        with patch.object(chat.subprocess, 'Popen') as popen, patch.object(runtime, '_start_linux') as linux:
            with self.assertRaises(ProfileLocked):
                runtime.shell('python Agent/web_tools.py search test')
        popen.assert_not_called(); linux.assert_not_called()

    def test_profile_environment_without_authenticated_account_cannot_launch(self):
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        with patch.object(chat.subprocess, 'Popen') as popen, patch.object(runtime, '_start_linux') as linux:
            with self.assertRaises(PermissionError):
                runtime.shell('python Agent/web_tools.py search test')
        popen.assert_not_called(); linux.assert_not_called()


class WebPromptTests(unittest.TestCase):
    def setUp(self):
        policy = patch('runtime_policy.load_effective_policy', return_value={})
        policy.start(); self.addCleanup(policy.stop)

    def test_compact_and_normal_prompts_explain_real_image_links_and_broad_search(self):
        for limit in (8192, 32768):
            panel = SimpleNamespace(root=ROOT, settings={'use_master_instructions':True},
                                    store=SimpleNamespace(custom_instructions=lambda:''),
                                    _runtime_context_limit=lambda:limit)
            prompt = chat.NativeChat.system_prompt(panel)
            self.assertIn('Agent\\web_tools.py search', prompt)
            self.assertIn('image-search', prompt)
            self.assertIn('image_url and page_url', prompt)
            self.assertIn('not limited to Wikipedia', prompt)
            if limit == 8192:
                self.assertLess(len(prompt), 5000)
                self.assertNotIn('Use list_dir/read_file to find', prompt)


if __name__ == '__main__': unittest.main()
