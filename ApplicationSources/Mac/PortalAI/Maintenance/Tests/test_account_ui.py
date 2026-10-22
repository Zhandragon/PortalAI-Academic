"""Account UI boundaries, using fake storage and no Tk window or real Data writes."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, create_autospec

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent')]
from account_ui import AccountController, AccountUIError, member_rows
from local_accounts import LocalAccounts


def session(role='admin', user_id='owner-id'):
    return SimpleNamespace(username='Zhandragon', user_id=user_id, role=role, active=True)


def controller(state='locked'):
    backend = create_autospec(LocalAccounts, instance=True)
    backend.status.return_value = {'state': state, 'users': [
        {'user_id': 'owner-id', 'username': 'Zhandragon', 'role': 'admin', 'pending': False},
        {'user_id': 'pending-id', 'username': 'KNO3', 'role': 'user', 'pending': True},
        {'user_id': 'guest-id', 'username': 'Guest', 'role': 'guest', 'pending': False}]}
    backend.list_users.return_value = backend.status.return_value['users']
    backend.login.return_value = session()
    backend.login_guest.return_value = session('guest', 'guest-id')
    return AccountController(ROOT, backend), backend


class AccountControllerTests(unittest.TestCase):
    def test_only_verified_fresh_storage_can_bootstrap_and_password_is_explicit(self):
        for state in ('locked', 'recovery_required', 'unexpected'):
            c, backend = controller(state)
            with self.assertRaises(AccountUIError):
                c.bootstrap('ChosenOwner', 'user supplied password', 'user supplied password')
            backend.bootstrap.assert_not_called()
        c, backend = controller('fresh')
        with self.assertRaises(AccountUIError):
            c.bootstrap('ChosenOwner', '', '')
        c.bootstrap('ChosenOwner', 'user supplied password', 'user supplied password')
        backend.bootstrap.assert_called_once_with('ChosenOwner', 'user supplied password', pending_users=())

    def test_invalid_registry_and_user_shapes_fail_closed(self):
        for value in ({'state': 'new'}, None, {'state': 'locked', 'users': 'bad'},
                      {'state': 'locked', 'users': [{'username': 7}]}):
            c, backend = controller()
            backend.status.return_value = value
            self.assertEqual(c.status()['state'], 'recovery_required')
            with self.assertRaises(AccountUIError):
                c.login('Zhandragon', 'test')
            backend.login.assert_not_called()

    def test_no_automatic_login_or_guest_substitution(self):
        c, backend = controller()
        c.status()
        backend.login.assert_not_called()
        backend.login_guest.assert_not_called()
        with self.assertRaises(AccountUIError):
            c.login('Zhandragon', '', guest=True)
        with self.assertRaises(AccountUIError):
            c.login('Zhandragon', '')
        backend.login_guest.assert_not_called()
        self.assertIs(c.login('Guest', guest=True), backend.login_guest.return_value)

    def test_guest_workspace_receives_same_mandatory_prepare_gate(self):
        c, backend = controller()
        guest = c.login('Guest', guest=True)
        prepare = Mock(side_effect=RuntimeError('old private plaintext remains'))
        with self.assertRaises(RuntimeError):
            c.activate(guest, prepare)
        prepare.assert_called_once_with(guest)
        backend.logout.assert_called_once_with(guest)

    def test_workspace_ready_requires_exact_user_receipt(self):
        for receipt in (None, {}, {'ready': True, 'user_id': 'another'}, {'ready': 1, 'user_id': 'owner-id'}):
            c, backend = controller()
            active = session()
            with self.assertRaises(AccountUIError):
                c.activate(active, Mock(return_value=receipt))
            backend.logout.assert_called_once_with(active)
        c, backend = controller(); active = session()
        self.assertIs(c.activate(active, lambda _: {'ready': True, 'user_id': active.user_id}), active)
        backend.logout.assert_not_called()

    def test_missing_workspace_adapter_cannot_unlock(self):
        c, backend = controller(); active = session()
        with self.assertRaisesRegex(AccountUIError, 'not installed'):
            c.activate(active, None)
        backend.logout.assert_called_once_with(active)

    def test_failed_unseal_keeps_recovery_authentication_in_coordinator(self):
        c, backend = controller(); active = session()
        class Coordinator:
            def prepare(self, supplied):
                self.retained = supplied
                raise RuntimeError('restore interrupted')
            def retains_session(self, supplied):
                return supplied is self.retained
        coordinator = Coordinator()
        with self.assertRaisesRegex(AccountUIError, 'recovery did not finish'):
            c.activate(active, coordinator.prepare)
        backend.logout.assert_not_called()

    def test_preparation_failure_before_retention_is_not_reported_as_bad_password(self):
        c, backend = controller(); active = session()
        def prepare(_):
            raise OSError(5, 'private password/path must never be shown')
        with self.assertRaises(AccountUIError) as result:
            c.activate(active, prepare)
        message = str(result.exception)
        self.assertIn('Password accepted', message)
        self.assertIn('OSError', message)
        self.assertNotIn('private password/path', message)
        backend.logout.assert_called_once_with(active)

    def test_standard_user_cannot_create_promote_enroll_or_review_reset(self):
        c, backend = controller(); standard = session('user')
        actions = (
            lambda: c.create_user(standard, 'X', 'new password', 'new password', 'admin password'),
            lambda: c.promote(standard, 'X', 'admin password', 'target password'),
            lambda: c.enroll_pending(standard, 'pending-id', 'new password', 'new password', 'admin password'),
            lambda: c.reset_member(standard, 'member-id', 'new password', 'new password', 'admin password', 'RESET Member'),
            lambda: c.review_start_fresh(standard, 'admin password', 'RESET ALL PRIVATE PROFILES'))
        for action in actions:
            with self.assertRaises(AccountUIError): action()
        backend.create_user.assert_not_called(); backend.promote.assert_not_called()
        backend.request_confirmation.assert_not_called(); backend.login.assert_not_called()

    def test_existing_member_reset_requires_specific_confirmation_and_fresh_admin_password(self):
        c, backend = controller(); admin = session()
        backend.list_users.return_value += [{'user_id':'member-id','username':'Member','role':'user','pending':False}]
        for password, phrase in (('', 'RESET Member'), ('admin password', 'RESET Another')):
            with self.assertRaises(AccountUIError):
                c.reset_member(admin,'member-id','new password','new password',password,phrase)
        backend.request_confirmation.assert_not_called()
        backend.request_confirmation.return_value = 'one-use-token'
        c.reset_member(admin,'member-id','new password','new password','admin password','RESET Member')
        backend.request_confirmation.assert_called_once_with(admin,'password-reset','member-id',admin_password='admin password',ttl_seconds=120)
        backend.reset_password.assert_called_once_with(admin,'member-id','new password',admin_password='admin password',confirmation_token='one-use-token')

    def test_existing_member_reset_rejects_self_guest_pending_and_unknown(self):
        c, backend = controller(); admin = session()
        for uid in ('owner-id','guest-id','pending-id','unknown'):
            with self.assertRaises(AccountUIError):
                c.reset_member(admin,uid,'new password','new password','admin password','RESET Target')
        backend.request_confirmation.assert_not_called(); backend.reset_password.assert_not_called()

    def test_unified_member_picker_includes_pending_and_enrolled_but_not_self_or_guest(self):
        c, backend = controller(); admin=session()
        rows=backend.list_users.return_value+[{'user_id':'member-id','username':'Member','role':'user','pending':False}]
        self.assertEqual([row['username'] for row in member_rows(rows,admin)],['KNO3','Member'])
        self.assertEqual([row['username'] for row in member_rows(rows,admin,pending_only=True)],['KNO3'])
        self.assertEqual([row['username'] for row in member_rows(rows,admin,promote=True)],['Member'])

    def test_unified_member_password_routes_pending_and_preserves_safe_default(self):
        c, backend=controller(); admin=session(); backend.request_confirmation.return_value='token'
        c.set_member_password(admin,'pending-id','new password','new password','admin password','RESET KNO3')
        self.assertNotIn('temporary_password',backend.reset_password.call_args.kwargs)
        self.assertEqual(backend.reset_password.call_args.args,(admin,'pending-id','new password'))
        backend.list_users.return_value[1]['pending']=False
        c.set_member_password(admin,'pending-id','temporary','temporary','admin password','RESET KNO3',temporary_password=True)
        self.assertIs(backend.reset_password.call_args.kwargs['temporary_password'],True)

    def test_unified_member_password_still_requires_confirmation_for_pending(self):
        c, backend=controller()
        with self.assertRaises(AccountUIError):
            c.set_member_password(session(),'pending-id','new password','new password','admin password','RESET Another')
        backend.reset_password.assert_not_called(); backend.request_confirmation.assert_not_called()

    def test_create_and_promote_require_current_admin_password(self):
        c, backend = controller(); admin = session()
        with self.assertRaises(AccountUIError):
            c.create_user(admin, 'New', 'new', 'new', '')
        with self.assertRaises(AccountUIError):
            c.promote(admin, 'another', '', 'target password')
        c.create_user(admin, 'New', '', '', 'admin password', pending=True)
        backend.create_user.assert_called_once_with(admin, 'New', None, role='user', admin_password='admin password')
        c.promote(admin, 'another', 'admin password', 'target password')
        backend.promote.assert_called_once_with(admin, 'another', admin_password='admin password', target_password='target password')

    def test_enrollment_requires_pending_account_and_one_use_confirmation(self):
        c, backend = controller(); admin = session()
        with self.assertRaises(AccountUIError):
            c.enroll_pending(admin, 'owner-id', 'new password', 'new password', 'admin password')
        backend.request_confirmation.assert_not_called()
        backend.request_confirmation.return_value = 'one-use-token'
        c.enroll_pending(admin, 'pending-id', 'new password', 'new password', 'admin password')
        backend.request_confirmation.assert_called_once_with(admin, 'password-reset', 'pending-id', admin_password='admin password', ttl_seconds=120)
        backend.reset_password.assert_called_once_with(admin, 'pending-id', 'new password', admin_password='admin password', confirmation_token='one-use-token')

    def test_password_change_returns_replacement_session(self):
        c, backend = controller(); old = session(); new = session()
        backend.change_password.return_value = new
        self.assertIs(c.change_password(old, 'current password', 'new password', 'new password'), new)
        backend.change_password.assert_called_once_with(old, 'current password', 'new password')

    def test_start_fresh_is_review_only_with_reauthentication_and_typed_confirmation(self):
        c, backend = controller(); active = session()
        with self.assertRaises(AccountUIError):
            c.review_start_fresh(active, 'admin password', 'yes')
        backend.login.assert_not_called()
        result = c.review_start_fresh(active, 'admin password', 'RESET ALL PRIVATE PROFILES')
        self.assertIs(result['executable'], False)
        self.assertIs(result['export_required'], True)
        backend.login.assert_called_once_with('Zhandragon', 'admin password')
        backend.logout.assert_called_once_with(backend.login.return_value)
        with self.assertRaises(AccountUIError): c.start_fresh()

    def test_logout_does_not_discard_keys_before_stop_and_seal_verification(self):
        for receipt in (None, {}, {'stopped': True, 'sealed': False, 'user_id': 'owner-id'},
                        {'stopped': True, 'sealed': True, 'user_id': 'another'}):
            c, backend = controller()
            with self.assertRaises(AccountUIError):
                c.finish_logout(session(), Mock(return_value=receipt))
            backend.logout.assert_not_called()
        c, backend = controller(); active = session()
        seal = Mock(return_value={'stopped': True, 'sealed': True, 'user_id': active.user_id})
        self.assertEqual(c.finish_logout(active, seal), {'exit_required': True})
        backend.logout.assert_called_once_with(active)


if __name__ == '__main__': unittest.main()
