"""Lazy chat I/O boundaries using temporary profiles; no model or user data."""
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent')]
import native_chat as chat
import profile_hydration as hydration
from local_accounts import Session
from profile_context import CapturedProfile
from profile_paths import ProfileLocked
from writer_jobs import WriterJobs

UID = '1'*32
EPOCH = 'a'*32


class ChatHydrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in ('PORTALAI_PROFILE_ID', 'PORTALAI_PROFILE_EPOCH', hydration.PORT_ENV,
                    hydration.TOKEN_ENV, hydration.OWNER_ENV):
            os.environ.pop(key, None)
        (self.root/'Private/Accounts').mkdir(parents=True)
        (self.root/'Private/Accounts/initialized.json').write_text('{}')
        self.marker = self.root/'Private/active-session.json'
        self.marker.write_text(json.dumps({'user_id': UID, 'epoch': EPOCH, 'state': 'open'}))
        os.environ['PORTALAI_PROFILE_ID'] = UID
        os.environ['PORTALAI_PROFILE_EPOCH'] = EPOCH
        self.workspace = self.root/'Private/Users'/UID/'Workspace'
        self.workspace.mkdir(parents=True)
        self.jobs = []

    def tearDown(self):
        for group in self.jobs:
            group.close()
            self.assertTrue(group.wait(3)['stopped'])
        self.env.stop()
        self.temp.cleanup()

    def runtime(self, role='admin'):
        boot = self.root/'Runtime/BootstrapPython/python.exe'
        boot.parent.mkdir(parents=True, exist_ok=True)
        boot.touch()
        with patch.object(chat, 'bootstrap_python', return_value=str(boot)):
            runtime = chat.ToolRuntime(self.root, {})
        session = Mock(spec=Session, user_id=UID, active=True, profile_key=b'k'*32, role=role)
        runtime.bind_account(session)
        return runtime

    def panel(self):
        p = chat.NativeChat.__new__(chat.NativeChat)
        p.root = self.root
        p.store = SimpleNamespace(profile=CapturedProfile(self.root), copy_attachment=Mock())
        p.session = {'id': 'synthetic-chat'}
        p.busy = False
        p._closing = False
        p.ev = queue.Queue()
        p._writer_jobs = WriterJobs()
        self.jobs.append(p._writer_jobs)
        p.attach_lbl = Mock()
        p.update_attachment_label = Mock()
        p._notice = Mock()
        p.pending_attachments = []
        return p

    def revoke(self):
        self.marker.write_text(json.dumps({'user_id': UID, 'epoch': EPOCH, 'state': 'closed'}))

    @staticmethod
    def full_calls(mock):
        return [call for call in mock.call_args_list if call.args[1:] == (None,) and call.kwargs.get('recursive')]

    def run_shell(self, runtime, command, materialize):
        process = Mock(returncode=0)
        process.communicate.return_value = ('fixture complete', '')
        with patch.object(hydration, 'materialize', side_effect=materialize) as restore, \
             patch.object(chat.subprocess, 'Popen', return_value=process) as popen, \
             patch.object(runtime, '_start_linux', return_value=process) as linux:
            result = runtime.shell(command)
        return result, restore, popen, linux

    def test_arbitrary_admin_shell_restores_before_launch(self):
        runtime = self.runtime()
        restored = []
        def materialize(root, relative=None, **kw):
            if relative is None:
                restored.append(True)
                (self.workspace/'fixture.txt').write_text('decrypted fixture')
        result, restore, popen, linux = self.run_shell(runtime, 'echo fixture', materialize)
        self.assertEqual(result, 'fixture complete')
        self.assertEqual(len(self.full_calls(restore)), 1)
        self.assertTrue(restored)
        call = popen.call_args if os.name == 'nt' else linux.call_args
        self.assertIs(call.kwargs['shell'], True)

    def test_registered_admin_web_and_media_do_not_restore_whole_workspace(self):
        runtime = self.runtime()
        for command in ('python Agent/web_tools.py image-search "exact pictured object"',
                        'python Agent/web_tools.py fetch https://example.com/page',
                        'python Agent/ai_tools.py image "a blue cube"'):
            with self.subTest(command=command):
                _, restore, _, _ = self.run_shell(runtime, command, lambda *_a, **_kw: None)
                self.assertEqual(self.full_calls(restore), [])

    def test_cancel_during_hydration_prevents_shell_start(self):
        runtime = self.runtime()
        def materialize(_root, relative=None, **_kw):
            if relative is None: runtime.cancel()
        with patch.object(hydration, 'materialize', side_effect=materialize), \
             patch.object(chat.subprocess, 'Popen') as popen, patch.object(runtime, '_start_linux') as linux:
            with self.assertRaisesRegex(RuntimeError, 'cancelled'): runtime.shell('echo fixture')
        popen.assert_not_called()
        linux.assert_not_called()

    def test_revoke_during_hydration_prevents_shell_start(self):
        runtime = self.runtime()
        def materialize(_root, relative=None, **_kw):
            if relative is None: self.revoke()
        with patch.object(hydration, 'materialize', side_effect=materialize), \
             patch.object(chat.subprocess, 'Popen') as popen, patch.object(runtime, '_start_linux') as linux:
            with self.assertRaises(ProfileLocked): runtime.shell('echo fixture')
        popen.assert_not_called()
        linux.assert_not_called()

    def test_nonadmin_arbitrary_shell_denied_before_restore(self):
        runtime = self.runtime('guest')
        with patch.object(hydration, 'materialize') as restore:
            with self.assertRaises(PermissionError): runtime.shell('echo fixture')
        restore.assert_not_called()

    def test_workspace_listing_restores_before_enumeration_and_named_folder_stays_scoped(self):
        runtime = self.runtime('user')
        def materialize(_root, relative=None, **_kw):
            if relative is None: (self.workspace/'restored.txt').write_text('fixture')
        with patch.object(hydration, 'materialize', side_effect=materialize) as restore:
            self.assertIn('restored.txt', runtime.list_dir('.'))
        self.assertEqual(len(self.full_calls(restore)), 1)
        (self.workspace/'Outputs').mkdir()
        with patch.object(hydration, 'materialize') as restore:
            runtime.list_dir('Outputs')
        self.assertEqual(self.full_calls(restore), [])
        self.assertTrue(any(call.args[1:] == ('Outputs',) and call.kwargs.get('recursive') for call in restore.call_args_list))

    def test_revoked_workspace_listing_returns_no_files(self):
        runtime = self.runtime('user')
        def materialize(_root, relative=None, **_kw):
            if relative is None: self.revoke()
        with patch.object(hydration, 'materialize', side_effect=materialize):
            with self.assertRaises(ProfileLocked): runtime.list_dir('.')

    def test_picker_restores_in_worker_then_opens_only_on_completion_thread(self):
        p = self.panel()
        caller = threading.get_ident()
        restoration_threads = []
        def materialize(*_a, **_kw): restoration_threads.append(threading.get_ident())
        with patch.object(hydration, 'materialize', side_effect=materialize) as restore, \
             patch.object(chat.filedialog, 'askopenfilenames', return_value=[]) as dialog:
            p.add_attachments()
            kind, data = p.ev.get(timeout=3)
            dialog.assert_not_called()
            self.assertEqual(kind, 'attachment_picker_ready')
            p._finish_attachment_picker(data)
        self.assertEqual([call.args[1] for call in restore.call_args_list], ['Outputs', 'User Folder'])
        self.assertTrue(all(ident != caller for ident in restoration_threads))
        dialog.assert_called_once()

    def test_picker_cancel_during_restore_is_tracked_and_cannot_open_late(self):
        p = self.panel()
        entered, release = threading.Event(), threading.Event()
        def materialize(*_a, **_kw):
            entered.set()
            self.assertTrue(release.wait(3))
        with patch.object(hydration, 'materialize', side_effect=materialize) as restore, \
             patch.object(chat.filedialog, 'askopenfilenames') as dialog:
            p.add_attachments()
            self.assertTrue(entered.wait(3))
            p.stop_generation()
            p._writer_jobs.close()
            self.assertFalse(p._writer_jobs.wait(0)['stopped'])
            release.set()
            self.assertTrue(p._writer_jobs.wait(3)['stopped'])
            self.assertTrue(p.ev.empty())
        self.assertEqual(restore.call_count, 1)
        dialog.assert_not_called()

    def test_picker_rejects_late_completion_after_close_chat_switch_or_revocation(self):
        for change in ('close', 'chat', 'revoke', 'busy'):
            with self.subTest(change=change):
                p = self.panel()
                with patch.object(hydration, 'materialize'), patch.object(chat.filedialog, 'askopenfilenames') as dialog:
                    p.add_attachments()
                    _, data = p.ev.get(timeout=3)
                    if change == 'close': p._closing = True
                    elif change == 'chat': p.session = {'id': 'different-chat'}
                    elif change == 'revoke': self.revoke()
                    else: p.busy = True
                    p._finish_attachment_picker(data)
                dialog.assert_not_called()
                self.marker.write_text(json.dumps({'user_id': UID, 'epoch': EPOCH, 'state': 'open'}))

    def test_picker_revoke_during_dialog_prevents_copy(self):
        p = self.panel()
        def choose(**_kw):
            self.revoke()
            return [str(self.root/'unused.txt')]
        with patch.object(hydration, 'materialize'), patch.object(chat.filedialog, 'askopenfilenames', side_effect=choose):
            p.add_attachments()
            _, data = p.ev.get(timeout=3)
            p._finish_attachment_picker(data)
        p.store.copy_attachment.assert_not_called()

    def test_picker_restore_failure_never_opens_dialog(self):
        p = self.panel()
        with patch.object(hydration, 'materialize', side_effect=RuntimeError('fixture restore failure')), \
             patch.object(chat.filedialog, 'askopenfilenames') as dialog:
            p.add_attachments()
            _, data = p.ev.get(timeout=3)
            p._finish_attachment_picker(data)
        dialog.assert_not_called()
        self.assertIn('fixture restore failure', p._notice.call_args.args)


if __name__ == '__main__': unittest.main()
