"""Actual encrypted temp workspaces and OS locks; no production Data mutation."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
from profile_runtime import ProfileRuntime
from profile_workspace import ProfileWorkspace
from profile_paths import capture, private_path, ProfileLocked

OWNER = '1'*32
USER = '2'*32
GUEST = '3'*32


class AccountsFixture:
    def __init__(self):
        self.users = {OWNER: ('admin', b'a'*32), USER: ('user', b'b'*32), GUEST: ('guest', b'c'*32)}

    def login(self, uid):
        role, key = self.users[uid]
        return SimpleNamespace(user_id=uid, role=role, active=True, profile_key=key)

    def validate_session(self, session):
        if not session.active or session.user_id not in self.users:
            raise PermissionError('invalid fixture session')

    def logout(self, session):
        session.active = False

    def profile_session(self, admin, uid):
        self.validate_session(admin)
        if admin.role != 'admin': raise PermissionError('not admin')
        return self.login(uid)


class ProfileRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.backend = AccountsFixture()
        self.env = patch.dict(os.environ, {}, clear=False); self.env.start()
        os.environ.pop('PORTALAI_PROFILE_ID', None); os.environ.pop('PORTALAI_PROFILE_EPOCH', None)
        self.controllers = []

    def tearDown(self):
        # Test-only simulated process termination releases descriptors. Production
        # never exposes this shortcut and keeps the lock on failed verification.
        for runtime in self.controllers:
            if runtime._process_lock is not None:
                runtime._process_lock.__exit__(None, None, None)
                runtime._process_lock = None
        self.env.stop(); self.tmp.cleanup()

    def runtime(self, **kwargs):
        kwargs.setdefault('quiesce', Mock(return_value={'stopped': True}))
        runtime = ProfileRuntime(self.root, self.backend, **kwargs)
        self.controllers.append(runtime)
        return runtime

    def crash_release(self, runtime):
        runtime._process_lock.__exit__(None, None, None); runtime._process_lock = None
        os.environ.pop('PORTALAI_PROFILE_ID', None); os.environ.pop('PORTALAI_PROFILE_EPOCH', None)

    def test_prepare_close_and_reopen_preserve_verified_content_and_change_epoch(self):
        owner = self.backend.login(OWNER); runtime = self.runtime()
        receipt = runtime.prepare(owner); first_epoch = receipt['epoch']
        output = private_path(self.root, 'Outputs/result.txt')
        output.parent.mkdir(parents=True); output.write_text('private test result')
        closed = runtime.close(owner, writers_stopped=True)
        self.assertTrue(closed['sealed']); self.assertFalse(output.exists())
        self.assertFalse(owner.active); self.assertIsNone(runtime._process_lock)
        with self.assertRaises(ProfileLocked): capture(self.root)
        fresh_login = self.backend.login(OWNER)
        ready = runtime.prepare(fresh_login)
        self.assertNotEqual(ready['epoch'], first_epoch)
        self.assertEqual(output.read_text(), 'private test result')
        runtime.close(fresh_login, writers_stopped=True)

    def test_missing_or_negative_quiescence_cannot_open_or_seal(self):
        for callback in (None, Mock(return_value=True), Mock(return_value={'stopped': False})):
            runtime = self.runtime(quiesce=callback)
            with self.assertRaises(RuntimeError): runtime.prepare(self.backend.login(OWNER))
            self.assertFalse((self.root/'Private/active-session.json').exists())
            runtime.release_closed()
        runtime = self.runtime(); owner = self.backend.login(OWNER); runtime.prepare(owner)
        runtime.quiesce = Mock(return_value={'stopped': False})
        with self.assertRaises(RuntimeError): runtime.close(owner, writers_stopped=True)
        self.assertTrue(owner.active); self.assertIsNotNone(runtime._process_lock)
        self.assertEqual(json.loads(runtime.marker.read_text())['state'], 'open')

    def test_os_lock_prevents_two_controllers_even_for_same_user(self):
        first = self.runtime(); first.prepare(self.backend.login(OWNER))
        second = self.runtime()
        with self.assertRaisesRegex(RuntimeError, 'Another PortalAI controller'):
            second.prepare(self.backend.login(OWNER))

    def test_guest_cannot_bypass_owner_crash_plaintext(self):
        old = self.runtime(); owner = self.backend.login(OWNER); old.prepare(owner)
        file = private_path(self.root, 'Data/Chat/secret.txt')
        file.parent.mkdir(parents=True); file.write_text('private fixture')
        self.crash_release(old)
        runtime = self.runtime()
        with self.assertRaises(PermissionError): runtime.prepare(self.backend.login(GUEST))
        self.assertEqual(file.read_text(), 'private fixture')
        runtime.quiesce.assert_not_called()

    def test_owner_recovers_crash_and_reopens_without_replaying_any_jobs(self):
        old = self.runtime(); old.prepare(self.backend.login(USER))
        file = private_path(self.root, 'Data/Chat/kept.txt')
        file.parent.mkdir(parents=True); file.write_text('checkpoint')
        self.crash_release(old)
        runtime = self.runtime(); user = self.backend.login(USER)
        self.assertTrue(runtime.prepare(user)['ready'])
        self.assertEqual(file.read_text(), 'checkpoint')
        runtime.quiesce.assert_called_once()
        runtime.close(user, writers_stopped=True)

    def test_admin_seals_another_users_crash_before_opening_own_workspace(self):
        old = self.runtime(); old.prepare(self.backend.login(USER))
        file = private_path(self.root, 'Outputs/user.txt')
        file.parent.mkdir(parents=True); file.write_text('user output')
        self.crash_release(old)
        runtime = self.runtime(); admin = self.backend.login(OWNER)
        runtime.prepare(admin)
        self.assertFalse(file.exists())
        self.assertEqual(capture(self.root)[0], OWNER)
        recovered = ProfileWorkspace(self.root, self.backend.login(USER)).verify()
        self.assertEqual(recovered['files'][0]['path'], 'Outputs/user.txt')
        runtime.close(admin, writers_stopped=True)

    def test_legacy_files_block_every_account_but_empty_bootstrap_log_after_sealing_is_allowed(self):
        legacy = self.root/'Data/Chat/old.json'; legacy.parent.mkdir(parents=True); legacy.write_text('{}')
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, 'Legacy private files'):
            runtime.prepare(self.backend.login(GUEST))
        legacy.unlink()
        initial = self.backend.login(GUEST)
        runtime.prepare(initial)
        runtime.close(initial, writers_stopped=True)
        log = self.root/'ControlCenter/PortableAI_Crash.log'; log.parent.mkdir(); log.touch()
        guest = self.backend.login(GUEST)
        runtime.prepare(guest)
        runtime.close(guest, writers_stopped=True)

    def test_corrupt_marker_never_gets_overwritten_by_guest_login(self):
        marker = self.root/'Private/active-session.json'; marker.parent.mkdir(); marker.write_text('{broken')
        runtime = self.runtime()
        with self.assertRaisesRegex(RuntimeError, 'marker is corrupt'):
            runtime.prepare(self.backend.login(GUEST))
        self.assertEqual(marker.read_text(), '{broken')

    def test_failed_seal_keeps_controller_key_marker_and_existing_plaintext(self):
        runtime = self.runtime(); owner = self.backend.login(OWNER); runtime.prepare(owner)
        file = private_path(self.root, 'Outputs/result.txt'); file.parent.mkdir(parents=True); file.write_text('keep')
        with patch.object(ProfileWorkspace, 'seal', side_effect=RuntimeError('verification failed')):
            with self.assertRaisesRegex(RuntimeError, 'verification failed'):
                runtime.close(owner, writers_stopped=True)
        self.assertTrue(owner.active); self.assertIsNotNone(runtime._process_lock)
        self.assertEqual(file.read_text(), 'keep')
        self.assertEqual(json.loads(runtime.marker.read_text())['state'], 'closing')
        with self.assertRaises(ProfileLocked): capture(self.root)

    def test_password_replacement_keeps_same_workspace_but_rejects_another_user(self):
        runtime = self.runtime(); owner = self.backend.login(OWNER); runtime.prepare(owner)
        new = self.backend.login(OWNER); owner.active = False
        runtime.replace_session(new)
        self.assertIs(runtime.session, new)
        with self.assertRaises(PermissionError): runtime.replace_session(self.backend.login(USER))
        runtime.close(new, writers_stopped=True)

    def test_crash_logs_harvest_after_owner_authentication_before_legacy_check(self):
        old = self.runtime(); old.prepare(self.backend.login(USER))
        self.crash_release(old)
        log = self.root/'ControlCenter/PortableAI_Crash.log'
        log.parent.mkdir(); log.write_text('crash evidence')
        calls = []
        def harvest(owner):
            calls.append(owner.user_id)
            target = ProfileWorkspace(self.root, owner).workspace/'Data/LegacyRecovery/log.txt'
            target.parent.mkdir(parents=True); target.write_bytes(log.read_bytes()); log.unlink()
            return {'verified': True}
        runtime = self.runtime(harvest=harvest)
        with self.assertRaises(PermissionError): runtime.prepare(self.backend.login(GUEST))
        self.assertEqual(calls, [])
        user = self.backend.login(USER); runtime.prepare(user)
        self.assertEqual(calls, [USER]); self.assertFalse(log.exists())
        runtime.harvest = None; runtime.close(user, writers_stopped=True)

    def test_harvest_of_sealed_owner_keeps_existing_snapshot_files(self):
        old = self.runtime(); owner = self.backend.login(USER); old.prepare(owner)
        file = private_path(self.root, 'Outputs/original.txt'); file.parent.mkdir(parents=True); file.write_text('original')
        old.close(owner, writers_stopped=True)
        log = self.root/'ControlCenter/PortableAI_Crash.log'; log.parent.mkdir(); log.write_text('leftover')
        def harvest(session):
            workspace = ProfileWorkspace(self.root, session)
            target = workspace.workspace/'Data/LegacyRecovery/new.txt'; target.parent.mkdir(parents=True)
            target.write_text('new'); log.unlink(); return {'verified': True}
        runtime = self.runtime(harvest=harvest); fresh = self.backend.login(USER)
        runtime.prepare(fresh)
        self.assertEqual(file.read_text(), 'original')
        runtime.harvest = None; runtime.close(fresh, writers_stopped=True)

    def test_failed_admin_recovery_retains_authorizing_key_and_child(self):
        old = self.runtime(); old.prepare(self.backend.login(USER)); self.crash_release(old)
        runtime = self.runtime(harvest=Mock(side_effect=RuntimeError('harvest failed')))
        admin = self.backend.login(OWNER)
        with self.assertRaisesRegex(RuntimeError, 'harvest failed'): runtime.prepare(admin)
        self.assertTrue(runtime.retains_session(admin)); self.assertTrue(admin.active)
        self.assertTrue(runtime._recovery_sessions[0].active)
        with self.assertRaises(RuntimeError): runtime.release_closed()


if __name__ == '__main__': unittest.main()
