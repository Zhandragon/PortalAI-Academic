"""Real account keys across profile lifecycle, using only synthetic temp roots."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import local_accounts as accounts
from profile_paths import UID_ENV, EPOCH_ENV, private_path, capture, ProfileLocked
from profile_runtime import ProfileRuntime
from profile_workspace import ProfileWorkspace

OWNER_PASSWORD = 'synthetic administrator password'
USER_PASSWORD = 'synthetic regular user password'
CHANGED_PASSWORD = 'synthetic changed user password'


class AccountRuntimeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Portal profile integration ')
        self.root = Path(self.temp.name)
        self.work = patch.object(accounts, '_KDF_N', 1024); self.work.start()
        self.env = patch.dict(os.environ, {}, clear=False); self.env.start()
        os.environ.pop(UID_ENV, None); os.environ.pop(EPOCH_ENV, None)
        self.store = accounts.LocalAccounts(self.root)
        self.admin = self.store.bootstrap('Owner', OWNER_PASSWORD)
        self.member = self.store.create_user(self.admin, 'Member', USER_PASSWORD, admin_password=OWNER_PASSWORD)
        self.runtimes = []

    def tearDown(self):
        for runtime in self.runtimes:
            # Release simulated crashed process handles in this temp-only fixture.
            if runtime._process_lock is not None:
                runtime._process_lock.__exit__(None, None, None)
                runtime._process_lock = None
        self.store.logout(); self.env.stop(); self.work.stop(); self.temp.cleanup()

    def runtime(self, **kwargs):
        kwargs.setdefault('quiesce', lambda *_: {'stopped': True})
        runtime = ProfileRuntime(self.root, self.store, **kwargs)
        self.runtimes.append(runtime)
        return runtime

    def write(self, text):
        target = private_path(self.root, 'Outputs/result.txt')
        target.parent.mkdir(parents=True, exist_ok=True); target.write_text(text)
        return target

    def crash(self, runtime):
        runtime._process_lock.__exit__(None, None, None); runtime._process_lock = None
        os.environ.pop(UID_ENV, None); os.environ.pop(EPOCH_ENV, None)

    def test_clean_logout_then_member_gets_separate_tree_and_cannot_read_owner(self):
        first = self.runtime(); first.prepare(self.admin)
        owner_file = self.write('synthetic owner result')
        first.close(self.admin, writers_stopped=True)
        self.assertFalse(owner_file.exists())
        second = self.runtime(); member = self.store.login('Member', USER_PASSWORD)
        second.prepare(member)
        member_file = self.write('synthetic member result')
        self.assertNotEqual(member_file, owner_file)
        self.assertFalse(owner_file.exists())
        second.close(member, writers_stopped=True)
        owner = self.store.login('Owner', OWNER_PASSWORD); third = self.runtime(); third.prepare(owner)
        self.assertEqual(owner_file.read_text(), 'synthetic owner result')
        self.assertFalse(member_file.exists())
        third.close(owner, writers_stopped=True)

    def test_self_password_change_replacement_keeps_same_live_workspace_sealable(self):
        runtime = self.runtime(); user = self.store.login('Member', USER_PASSWORD)
        runtime.prepare(user); output = self.write('survives password change')
        key = user.profile_key
        updated = self.store.change_password(user, USER_PASSWORD, CHANGED_PASSWORD)
        self.assertFalse(user.active); self.assertEqual(updated.profile_key, key)
        runtime.replace_session(updated)
        runtime.close(updated, writers_stopped=True)
        self.assertFalse(output.exists())
        fresh = self.store.login('Member', CHANGED_PASSWORD); runtime.prepare(fresh)
        self.assertEqual(output.read_text(), 'survives password change')
        runtime.close(fresh, writers_stopped=True)

    def test_clean_admin_member_guest_sequence_with_harvest_installed(self):
        def harvest(_session): return {'verified': True}
        sessions = (self.admin, self.store.login('Member', USER_PASSWORD), self.store.login_guest())
        previous = []
        for session in sessions:
            runtime = self.runtime(harvest=harvest)
            runtime.prepare(session)
            self.assertEqual(capture(self.root)[0], session.user_id)
            self.assertTrue(all(not path.exists() for path in previous))
            previous.append(self.write('synthetic isolated ' + session.username))
            runtime.close(session, writers_stopped=True)
        self.assertTrue(all(not path.exists() for path in previous))

    def test_admin_recovers_other_user_crash_using_wrapped_user_key(self):
        old = self.runtime(); user = self.store.login('Member', USER_PASSWORD)
        old.prepare(user); output = self.write('synthetic crashed result'); self.crash(old)
        guest_runtime = self.runtime()
        with self.assertRaises(PermissionError): guest_runtime.prepare(self.store.login_guest())
        guest_runtime.release_closed()
        recovered = self.runtime(); recovered.prepare(self.admin)
        self.assertFalse(output.exists()); self.assertEqual(capture(self.root)[0], self.admin.user_id)
        delegated = self.store.profile_session(self.admin, self.member['user_id'])
        self.assertEqual(ProfileWorkspace(self.root, delegated).verify()['files'][0]['path'], 'Outputs/result.txt')
        self.store.logout(delegated)
        recovered.close(self.admin, writers_stopped=True)

    def test_failed_seal_keeps_real_keys_and_revokes_captured_profile_access(self):
        runtime = self.runtime(); runtime.prepare(self.admin); output = self.write('preserve on seal failure')
        with patch.object(ProfileWorkspace, 'seal', side_effect=OSError('synthetic unavailable disk')):
            with self.assertRaises(OSError): runtime.close(self.admin, writers_stopped=True)
        self.assertTrue(self.admin.active); self.assertTrue(output.exists())
        self.assertEqual(len(self.admin.profile_key), 32)
        with self.assertRaises(ProfileLocked): capture(self.root)
        runtime.close(self.admin, writers_stopped=True)
        self.assertFalse(output.exists())

    def test_pending_reset_blocks_profile_preparation_even_with_valid_existing_session(self):
        pending = self.root/'Private/Reset/transaction.json'
        pending.parent.mkdir(parents=True); pending.write_text('{}')
        with self.assertRaises(accounts.RecoveryRequired): self.runtime().prepare(self.admin)
        self.assertFalse((self.root/'Private/active-session.json').exists())


if __name__ == '__main__': unittest.main()
