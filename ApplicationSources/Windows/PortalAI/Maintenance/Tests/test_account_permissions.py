"""Trusted request gates with real account sessions, temporary roots only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import local_accounts as accounts
from account_permissions import require_admin, can_admin
from settings_page import save_storage_settings
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings

PASSWORD = 'synthetic admin boundary password'


class AccountPermissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Portal permissions test ')
        self.root = Path(self.temp.name)
        self.kdf = patch.object(accounts, '_KDF_N', 1024); self.kdf.start()
        self.env = patch.dict(os.environ, {}, clear=False); self.env.start()
        self.store = accounts.LocalAccounts(self.root)
        self.admin = self.store.bootstrap('Owner', PASSWORD)

    def tearDown(self):
        self.store.logout(); self.env.stop(); self.kdf.stop(); self.temp.cleanup()

    def active(self, session):
        epoch = 'a'*32
        (self.root/'Private/active-session.json').write_text(json.dumps(
            {'user_id':session.user_id,'epoch':epoch,'state':'open'}))
        os.environ['PORTALAI_PROFILE_ID'] = session.user_id
        os.environ['PORTALAI_PROFILE_EPOCH'] = epoch

    def test_legacy_retains_existing_behavior_and_authenticated_admin_is_accepted(self):
        legacy = self.root/'unused'; legacy.mkdir()
        self.assertIsNone(require_admin(legacy))
        self.active(self.admin)
        self.assertIs(require_admin(self.root,self.admin), self.admin)

    def test_missing_forged_guest_standard_and_delegated_authority_are_denied(self):
        user = self.store.create_user(self.admin,'Member',PASSWORD,admin_password=PASSWORD)
        member = self.store.login('Member',PASSWORD)
        guest = self.store.login_guest()
        delegated = self.store.profile_session(self.admin,self.admin.user_id)
        for session in (None, {'role':'admin','active':True}, SimpleNamespace(role='admin',active=True), member, guest, delegated):
            with self.subTest(session=type(session).__name__):
                self.active(session if isinstance(session,accounts.Session) else self.admin)
                with self.assertRaises(PermissionError): require_admin(self.root,session)
                self.assertFalse(can_admin(self.root,session))

    def test_authenticated_but_inactive_or_foreign_admin_is_denied(self):
        with self.assertRaises(PermissionError): require_admin(self.root,self.admin)
        self.active(self.admin)
        other = self.root/'OtherInstall'; store = accounts.LocalAccounts(other)
        admin = store.bootstrap('Other',PASSWORD)
        try:
            with self.assertRaises(PermissionError): require_admin(self.root,admin)
        finally: store.logout()
        self.store.logout(self.admin)
        with self.assertRaises(PermissionError): require_admin(self.root,self.admin)

    def test_session_getter_follows_authenticated_password_replacement(self):
        self.active(self.admin); current = [self.admin]
        self.assertIs(require_admin(self.root,lambda:current[0]),self.admin)
        old = self.admin
        current[0] = self.store.change_password(old,PASSWORD,'synthetic new administrator password')
        self.assertIs(require_admin(self.root,lambda:current[0]),current[0])
        with self.assertRaises(PermissionError): require_admin(self.root,old)

    def test_shared_settings_reject_before_reading_or_writing_policy(self):
        guest = self.store.login_guest(); self.active(guest)
        with patch('settings_page.load_policy') as load, patch('settings_page.atomic_json') as write:
            with self.assertRaises(PermissionError): save_storage_settings(self.root,{},session=guest)
        load.assert_not_called(); write.assert_not_called()

    def test_mission_and_schedule_public_requests_reject_before_creating_any_ui(self):
        guest = self.store.login_guest(); self.active(guest)
        with patch('tkinter.Toplevel') as popup:
            for handler in (show_mission_settings,show_schedule_settings):
                with self.assertRaises(PermissionError): handler(None,self.root,{},session=guest)
        popup.assert_not_called()

    def test_account_missions_require_tracked_job_gate_even_for_admin(self):
        self.active(self.admin)
        with patch('tkinter.Toplevel') as popup:
            with self.assertRaisesRegex(RuntimeError,'tracked background'):
                show_mission_settings(None,self.root,{},session=self.admin)
        popup.assert_not_called()

    def test_effort_preferences_are_private_per_user_and_never_change_shared_policy(self):
        import effort_policy
        shared = self.root/'Agent/hardware_profiles.json'; shared.parent.mkdir()
        shared.write_text('{"effort":{"chat":"deep","tools":"deep"},"selection":"auto"}')
        before = shared.read_bytes()
        self.active(self.admin)
        self.assertEqual(effort_policy.load_preferences(self.root), {'chat':'balanced','tools':'balanced'})
        effort_policy.save_preferences(self.root,chat='deep')
        guest = self.store.login_guest(); self.active(guest)
        self.assertEqual(effort_policy.load_preferences(self.root), {'chat':'balanced','tools':'balanced'})
        effort_policy.save_preferences(self.root,tools='fast')
        self.active(self.admin)
        self.assertEqual(effort_policy.load_preferences(self.root), {'chat':'deep','tools':'balanced'})
        self.assertEqual(shared.read_bytes(),before)

    def test_locked_account_effort_cannot_fall_back_to_shared_preferences(self):
        import effort_policy
        with self.assertRaises(PermissionError): effort_policy.load_preferences(self.root)
        with self.assertRaises(PermissionError): effort_policy.save_preferences(self.root,chat='fast')


if __name__ == '__main__': unittest.main()
