"""Per-login GUI paths and stale-worker fences; every file lives in a temp bundle."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent')]
import native_chat as chat
from persistent_memory import PersistentMemory
from profile_context import CapturedProfile
from profile_paths import ProfileLocked
import maintenance_cleanup as cleanup
from local_accounts import Session

UID = '1'*32
OTHER = '2'*32
EPOCH = 'a'*32


def bind_account(runtime, role='admin'):
    authenticated = Mock(spec=Session)
    authenticated.user_id = UID
    authenticated.active = True
    authenticated.profile_key = b'k'*32
    authenticated.role = role
    runtime.bind_account(authenticated)
    return authenticated


class ProfileGUIPathsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop('PORTALAI_PROFILE_ID', None)
        os.environ.pop('PORTALAI_PROFILE_EPOCH', None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def login(self, uid=UID, epoch=EPOCH):
        registry = self.root/'Private/Accounts/initialized.json'
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text('{}')
        marker = self.root/'Private/active-session.json'
        marker.write_text(json.dumps({'user_id': uid, 'epoch': epoch, 'state': 'open'}))
        os.environ['PORTALAI_PROFILE_ID'] = uid
        os.environ['PORTALAI_PROFILE_EPOCH'] = epoch
        return self.root/'Private/Users'/uid/'Workspace'

    def test_chat_and_memory_stores_never_read_legacy_or_another_users_history(self):
        legacy = self.root/'Data/Chat/Sessions'
        legacy.mkdir(parents=True)
        (legacy/'legacy.json').write_text(json.dumps({'id': 'legacy', 'messages': [{'content': 'private old text'}]}))
        workspace = self.login()
        store = chat.ChatStore(self.root)
        self.assertEqual(store.sessions, workspace/'Data/Chat/Sessions')
        self.assertEqual(store.list_sessions(), [])
        row = store.new_session()
        memory = PersistentMemory(self.root)
        self.assertEqual(memory.base, workspace/'Data/Memory')
        memory.save()
        self.assertTrue(memory.path.exists())
        self.assertFalse((self.root/'Data/Memory').exists())
        self.login(OTHER)
        other = chat.ChatStore(self.root)
        self.assertEqual(other.list_sessions(), [])
        for action in (store.list_sessions, lambda: store.save_session(row), memory.save,
                       lambda: memory.context_for(row['id'], 'private'), memory.stats):
            with self.assertRaises(ProfileLocked): action()

    def test_legacy_object_cannot_adopt_later_login(self):
        store = chat.ChatStore(self.root)
        context = CapturedProfile(self.root)
        self.login()
        with self.assertRaises(ProfileLocked): store.new_session()
        with self.assertRaises(ProfileLocked): context.resolve('Data/Chat/settings.json')

    def test_locked_standalone_chat_fails_before_store_construction(self):
        self.login()
        os.environ.pop('PORTALAI_PROFILE_ID')
        os.environ.pop('PORTALAI_PROFILE_EPOCH')
        with self.assertRaises(ProfileLocked): chat.ChatStore(self.root)
        with self.assertRaises(ProfileLocked): chat.NativeChat(self.root)

    def test_profile_cannot_read_other_profile_even_when_user_selects_it_as_attachment(self):
        self.login()
        store = chat.ChatStore(self.root); row = store.new_session()
        other = self.root/'Private/Users'/OTHER/'Workspace/Data/secret.txt'
        other.parent.mkdir(parents=True); other.write_text('other account')
        with self.assertRaises(ProfileLocked): store.copy_attachment(row['id'], other)
        with self.assertRaises(ValueError): store.load_session('../outside')

    def test_explicit_external_attachment_is_copied_into_current_profile(self):
        workspace = self.login()
        store = chat.ChatStore(self.root); row = store.new_session()
        with tempfile.TemporaryDirectory() as outside:
            source = Path(outside)/'user selected.txt'; source.write_text('fixture')
            attachment = store.copy_attachment(row['id'], source)
        copied = self.root/attachment['path']
        self.assertTrue(copied.is_relative_to(workspace))
        self.assertEqual(copied.read_text(), 'fixture')

    def test_legacy_media_reference_resolves_without_history_rewrite(self):
        workspace = self.login()
        panel = chat.NativeChat.__new__(chat.NativeChat)
        panel.root = self.root; panel.store = chat.ChatStore(self.root)
        original = {'path': 'Outputs/picture.png'}
        self.assertEqual(panel._resolve_private_reference(original['path']), workspace/'Outputs/picture.png')
        self.assertEqual(original, {'path': 'Outputs/picture.png'})
        with self.assertRaises(ProfileLocked):
            panel._resolve_private_reference(f'Private/Users/{OTHER}/Workspace/Outputs/picture.png')

    def test_tool_file_and_environment_routes_stay_with_captured_login(self):
        workspace = self.login()
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        bind_account(runtime)
        runtime.write_file('Outputs/tool.txt', 'one account')
        self.assertEqual((workspace/'Outputs/tool.txt').read_text(), 'one account')
        env = runtime._effort_env({'PORTALAI_PROFILE_ID': OTHER, 'PORTALAI_PROFILE_EPOCH': 'b'*32})
        self.assertEqual(env['PORTALAI_PROFILE_ID'], UID)
        self.assertEqual(env['PORTALAI_PROFILE_EPOCH'], EPOCH)
        self.login(OTHER)
        with self.assertRaises(ProfileLocked): runtime.read_file('Outputs/tool.txt')
        with self.assertRaises(ProfileLocked): runtime.shell('echo should-not-start')
        with self.assertRaises(ProfileLocked): runtime._effort_env({})

    def test_account_shell_uses_private_cwd_but_preserves_packaged_tool_arguments(self):
        workspace = self.login()
        boot = self.root/'Runtime/BootstrapPython/python.exe'
        boot.parent.mkdir(parents=True); boot.touch()
        with patch.object(chat, 'bootstrap_python', return_value=str(boot)):
            runtime = chat.ToolRuntime(self.root, {'tool_timeout_seconds': 10})
        bind_account(runtime)
        process = Mock(returncode=0); process.communicate.return_value = ('done', '')
        with patch.object(chat.subprocess, 'Popen', return_value=process) as popen, \
             patch.object(runtime, '_start_linux', return_value=process) as linux:
            runtime.shell('python Agent/ai_tools.py image "a blue cube" --steps 31')
        if os.name == 'nt':
            self.assertEqual(popen.call_args.kwargs['cwd'], str(workspace))
            forwarded = popen.call_args.args[0]
        else:
            self.assertEqual(runtime._working_directory(), workspace)
            self.assertIs(linux.call_args.kwargs['shell'], True)
            forwarded = linux.call_args.args[0]
        self.assertIn(str(self.root/'Agent/ai_tools.py'), forwarded)
        self.assertTrue(forwarded.endswith(' image "a blue cube" --steps 31'))

    def test_missing_account_binding_denies_tool_dispatch_and_lookalike_session(self):
        self.login()
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        with self.assertRaises(PermissionError): runtime.execute('list_dir', {'path': '.'})
        with self.assertRaises(PermissionError): runtime.bind_account({'role': 'admin', 'user_id': UID})

    def test_standard_account_reads_own_files_but_cannot_launch_arbitrary_shell_or_edit(self):
        workspace = self.login()
        own = workspace/'Outputs/read.txt'; own.parent.mkdir(parents=True); own.write_text('own result')
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        account = bind_account(runtime, 'user')
        self.assertEqual(runtime.read_file('Outputs/read.txt'), 'own result')
        for command in ('powershell -Command Get-Content secret.txt', 'python -c "print(1)"',
                        'python Agent/ai_tools.py image test & echo stolen', 'python Agent/science_tools.py --request-file x'):
            with self.assertRaises(PermissionError): runtime.shell(command)
        with self.assertRaises(PermissionError): runtime.write_file('Outputs/edit.txt', 'changed')
        with self.assertRaises(PermissionError): runtime.read_file('Agent/config.json')
        with self.assertRaises(PermissionError): runtime.science('calc', {'expression': '1+1'})
        account.active = False
        with self.assertRaises(PermissionError): runtime.read_file('Outputs/read.txt')

    def test_registered_guest_media_uses_argv_and_never_a_host_shell(self):
        workspace = self.login()
        with patch.object(chat, 'bootstrap_python', return_value=str(self.root/'fixture-python')):
            runtime = chat.ToolRuntime(self.root, {})
        bind_account(runtime, 'guest')
        process = Mock(returncode=0); process.communicate.return_value = ('generated fixture', '')
        with patch.object(chat.subprocess, 'Popen', return_value=process) as popen, \
             patch.object(runtime, '_start_linux', return_value=process) as linux:
            result = runtime.shell('python Agent/ai_tools.py image "a blue cube" --steps 31')
        self.assertEqual(result, 'generated fixture')
        call = popen.call_args if os.name == 'nt' else linux.call_args
        self.assertEqual(call.args[0][-4:], ['image', 'a blue cube', '--steps', '31'])
        self.assertIs(call.kwargs['shell'], False)
        self.assertEqual(runtime._working_directory(), workspace)
        if os.name == 'nt': self.assertEqual(popen.call_args.kwargs['cwd'], str(workspace))

    def test_registered_windows_prefix_is_portable_to_posix_tokenization(self):
        import shlex
        from account_tool_policy import registered_media_argv
        with patch('chat_model_switch._argv', side_effect=shlex.split):
            argv = registered_media_argv(r'.\Tools\portable_python.cmd Agent\ai_tools.py image "a blue cube"',
                                         self.root, self.root/'fixture-python')
        self.assertEqual(argv[-2:], ['image', 'a blue cube'])

    def test_cleanup_only_empties_active_outputs_and_never_shared_or_other_data(self):
        workspace = self.login()
        current = workspace/'Outputs/this.txt'; current.parent.mkdir(parents=True); current.write_text('this')
        other = self.root/'Private/Users'/OTHER/'Workspace/Outputs/other.txt'
        other.parent.mkdir(parents=True); other.write_text('other')
        legacy = self.root/'Outputs/legacy.txt'; legacy.parent.mkdir(parents=True); legacy.write_text('legacy')
        preview = cleanup.preview_cleanup(self.root, 'outputs')
        self.assertEqual(preview['targets'][0]['path'], str(workspace/'Outputs'))
        result = cleanup.execute_cleanup(self.root, 'outputs')
        self.assertTrue(result['success'])
        self.assertFalse(current.exists())
        self.assertEqual(other.read_text(), 'other')
        self.assertEqual(legacy.read_text(), 'legacy')

    def test_private_web_cleanup_does_not_delete_shared_agent_caches(self):
        workspace = self.login()
        private = workspace/'Cache/Web/cache.json'; private.parent.mkdir(parents=True); private.write_text('{}')
        shared = self.root/'Agent/.webcache/shared.json'; shared.parent.mkdir(parents=True); shared.write_text('{}')
        cleanup.execute_cleanup(self.root, 'webcache')
        self.assertFalse(private.exists())
        self.assertTrue(shared.exists())


if __name__ == '__main__': unittest.main()
