"""Account cryptography/lifecycle tests: synthetic credentials and temporary roots only."""
import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
import local_accounts as accounts

OWNER_PASSWORD = "test owner passphrase only"
USER_PASSWORD = "test member passphrase only"
NEW_PASSWORD = "test replacement passphrase only"


class LocalAccountTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="Portal account test ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Exercise real bundled AES-GCM/Scrypt, with a smaller test-only work
        # factor. Stored work factors are still strictly checked against policy.
        work = patch.object(accounts, "_KDF_N", 1024)
        work.start(); self.addCleanup(work.stop)
        self.now = 1000.0
        self.store = accounts.LocalAccounts(self.root, clock=lambda: self.now)
        self.addCleanup(self.store.logout)

    def initialized(self, pending=()):
        self.admin = self.store.bootstrap("TestOwner", OWNER_PASSWORD, pending_users=pending)
        return self.admin

    def user(self):
        self.initialized()
        row = self.store.create_user(self.admin, "Member", USER_PASSWORD, admin_password=OWNER_PASSWORD)
        return row, self.store.login("Member", USER_PASSWORD)

    def raw(self):
        return json.loads(self.store.registry_path.read_text())

    def write_raw(self, data):
        self.store.registry_path.write_text(json.dumps(data), encoding="utf-8")

    def test_fresh_status_is_read_only_and_bootstrap_adds_owner_and_guest(self):
        self.assertEqual(self.store.status()["state"], "fresh")
        self.assertFalse((self.root / "Private").exists())
        admin = self.initialized()
        self.assertEqual(admin.role, "admin")
        self.assertEqual({row["role"] for row in self.store.status()["users"]}, {"admin", "guest"})
        self.assertEqual(self.store.status()["state"], "locked")

    def test_production_kdf_is_strong_and_embedded_parameters_cannot_be_lowered(self):
        with patch.object(accounts, "_KDF_N", 131072):
            self.initialized()
            data = self.raw()
            self.assertEqual(data["slots"][self.admin.user_id]["password"]["kdf"]["n"], 131072)
            data["slots"][self.admin.user_id]["password"]["kdf"]["n"] = 2
            self.write_raw(data)
            self.assertEqual(self.store.status()["state"], "recovery_required")
            with self.assertRaises(accounts.RecoveryRequired): self.store.login("TestOwner", OWNER_PASSWORD)

    def test_password_and_master_key_are_not_stored_plaintext_or_in_session_repr(self):
        self.initialized()
        raw = self.store.registry_path.read_text()
        self.assertNotIn(OWNER_PASSWORD, raw)
        self.assertNotIn(base64.b64encode(bytes(self.admin._master)).decode(), raw)
        self.assertNotIn(OWNER_PASSWORD, repr(self.admin))
        self.assertNotIn(base64.b64encode(self.admin.profile_key).decode(), raw)

    def test_restart_is_locked_and_does_not_accept_foreign_store_session(self):
        self.initialized()
        restarted = accounts.LocalAccounts(self.root)
        self.assertEqual(restarted.status()["state"], "locked")
        with self.assertRaises(accounts.AuthenticationError): restarted.data_key(self.admin)
        self.assertEqual(restarted.login("TestOwner", OWNER_PASSWORD).profile_key, self.admin.profile_key)
        restarted.logout()

    def test_wrong_password_and_pending_account_fail(self):
        self.initialized(pending=("PendingMember",))
        with self.assertRaises(accounts.AuthenticationError): self.store.login("TestOwner", "wrong password")
        with self.assertRaises(accounts.AuthenticationError): self.store.login("PendingMember", USER_PASSWORD)
        pending = next(row for row in self.store.status()["users"] if row["username"] == "PendingMember")
        self.assertTrue(pending["pending"])
        self.assertEqual(pending["role"], "user")

    def test_persistent_guest_is_public_but_cannot_access_admin_or_user_key(self):
        row, member = self.user()
        guest = self.store.login_guest(); key = guest.profile_key
        self.assertEqual(guest.role, "guest")
        self.store.logout(guest)
        self.assertEqual(self.store.login_guest().profile_key, key)
        self.assertNotEqual(key, member.profile_key)
        with self.assertRaises(accounts.AuthorizationError): self.store.list_users(self.store.login_guest())
        with self.assertRaises(accounts.AuthorizationError): self.store.profile_session(member, self.admin.user_id)
        with self.assertRaises(accounts.AuthorizationError): self.store.change_password(self.store.login_guest(), "", NEW_PASSWORD)

    def test_admin_can_access_each_profile_but_delegation_does_not_grant_admin_actions(self):
        row, member = self.user()
        delegated = self.store.profile_session(self.admin, row["user_id"])
        self.assertEqual(delegated.profile_key, member.profile_key)
        with self.assertRaises(accounts.AuthorizationError): self.store.list_users(delegated)
        self.store.logout(self.admin)
        self.assertFalse(delegated.active)
        with self.assertRaises(accounts.AuthenticationError): _ = delegated.profile_key
        self.assertTrue(member.active)

    def test_admin_reauthentication_is_required_before_create(self):
        self.initialized()
        before = self.store.registry_path.read_bytes()
        with self.assertRaises(accounts.AuthenticationError):
            self.store.create_user(self.admin, "Member", USER_PASSWORD, admin_password="wrong password")
        self.assertEqual(self.store.registry_path.read_bytes(), before)

    def test_standard_user_cannot_create_promote_or_reset(self):
        row, member = self.user()
        with self.assertRaises(accounts.AuthorizationError):
            self.store.create_user(member, "Other", USER_PASSWORD, admin_password=USER_PASSWORD)
        with self.assertRaises(accounts.AuthorizationError):
            self.store.promote(member, member.user_id, admin_password=USER_PASSWORD, target_password=USER_PASSWORD)
        with self.assertRaises(accounts.AuthorizationError):
            self.store.request_confirmation(member, "password-reset", self.admin.user_id, admin_password=USER_PASSWORD)

    def test_promotion_requires_both_passwords_and_preserves_profile_data_key(self):
        row, member = self.user(); key = member.profile_key
        with self.assertRaises(accounts.AuthenticationError):
            self.store.promote(self.admin, member.user_id, admin_password=OWNER_PASSWORD, target_password="wrong password")
        self.store.promote(self.admin, member.user_id, admin_password=OWNER_PASSWORD, target_password=USER_PASSWORD)
        self.assertFalse(member.active)
        promoted = self.store.login("Member", USER_PASSWORD)
        self.assertEqual(promoted.role, "admin")
        self.assertEqual(promoted.profile_key, key)
        self.assertEqual(self.store.profile_session(promoted, self.admin.user_id).profile_key, self.admin.profile_key)

    def test_standard_user_self_password_change_keeps_key_and_admin_registry_integrity(self):
        row, member = self.user(); key = member.profile_key
        encrypted_registry = self.raw()["registry"]
        changed = self.store.change_password(member, USER_PASSWORD, NEW_PASSWORD)
        self.assertEqual(changed.profile_key, key)
        self.assertFalse(member.active)
        self.assertEqual(self.raw()["registry"], encrypted_registry)
        with self.assertRaises(accounts.AuthenticationError): self.store.login("Member", USER_PASSWORD)
        self.assertEqual(self.store.login("Member", NEW_PASSWORD).profile_key, key)
        fresh_admin = self.store.login("TestOwner", OWNER_PASSWORD)
        self.assertEqual(self.store.profile_session(fresh_admin, row["user_id"]).profile_key, key)

    def test_admin_self_password_change_preserves_master_and_all_profile_keys(self):
        row, member = self.user(); key = member.profile_key
        updated = self.store.change_password(self.admin, OWNER_PASSWORD, NEW_PASSWORD)
        self.assertFalse(self.admin.active)
        self.assertEqual(self.store.profile_session(updated, row["user_id"]).profile_key, key)
        self.assertEqual(self.store.login("TestOwner", NEW_PASSWORD).role, "admin")

    def test_password_change_revokes_sessions_in_other_store(self):
        row, member = self.user()
        other = accounts.LocalAccounts(self.root)
        old = other.login("Member", USER_PASSWORD)
        self.store.change_password(member, USER_PASSWORD, NEW_PASSWORD)
        self.assertFalse(old.active)
        with self.assertRaises(accounts.AuthenticationError): _ = old.profile_key
        other.logout()

    def test_password_reset_needs_one_use_confirmation_and_keeps_existing_key(self):
        row, member = self.user(); key = member.profile_key
        token = self.store.request_confirmation(self.admin, "password-reset", row["user_id"], admin_password=OWNER_PASSWORD)
        self.store.reset_password(self.admin, row["user_id"], NEW_PASSWORD,
                                  admin_password=OWNER_PASSWORD, confirmation_token=token)
        self.assertFalse(member.active)
        self.assertEqual(self.store.login("Member", NEW_PASSWORD).profile_key, key)
        with self.assertRaises(accounts.AuthorizationError):
            self.store.reset_password(self.admin, row["user_id"], USER_PASSWORD,
                                      admin_password=OWNER_PASSWORD, confirmation_token=token)

    def test_admin_enrollment_of_pending_account_requires_confirmation(self):
        self.initialized(pending=("PendingMember",))
        row = next(row for row in self.store.list_users(self.admin) if row["pending"])
        key = self.store.profile_session(self.admin, row["user_id"]).profile_key
        token = self.store.request_confirmation(self.admin, "password-reset", row["user_id"], admin_password=OWNER_PASSWORD)
        updated = self.store.reset_password(self.admin, row["user_id"], USER_PASSWORD,
                                            admin_password=OWNER_PASSWORD, confirmation_token=token)
        self.assertFalse(updated["pending"])
        self.assertEqual(self.store.login("PendingMember", USER_PASSWORD).profile_key, key)

    def test_confirmation_expires_and_is_bound_to_action_session_and_target(self):
        row, member = self.user()
        token = self.store.request_confirmation(self.admin, "password-reset", member.user_id,
                                                admin_password=OWNER_PASSWORD, ttl_seconds=10)
        self.now += 11
        with self.assertRaises(accounts.AuthorizationError):
            self.store.reset_password(self.admin, member.user_id, NEW_PASSWORD,
                                      admin_password=OWNER_PASSWORD, confirmation_token=token)
        token = self.store.request_confirmation(self.admin, "start-fresh", admin_password=OWNER_PASSWORD)
        with self.assertRaises(accounts.AuthorizationError):
            self.store.consume_confirmation(self.admin, token, "password-reset", member.user_id)
        with self.assertRaises(accounts.AuthorizationError):
            self.store.consume_confirmation(self.admin, token, "start-fresh")

    def test_temporary_enrollment_is_explicit_authenticated_and_preserves_key(self):
        self.initialized(pending=("PendingMember",))
        row = next(row for row in self.store.list_users(self.admin) if row["pending"])
        key = self.store.profile_session(self.admin, row["user_id"]).profile_key
        token = self.store.request_confirmation(self.admin, "password-reset", row["user_id"], admin_password=OWNER_PASSWORD)
        with self.assertRaises(ValueError):
            self.store.reset_password(self.admin, row["user_id"], "test123", admin_password=OWNER_PASSWORD,
                                      confirmation_token=token)
        with self.assertRaises(ValueError):
            self.store.reset_password(self.admin, row["user_id"], "test123", admin_password=OWNER_PASSWORD,
                                      confirmation_token=token, temporary_password="yes")
        with self.assertRaises(accounts.AuthenticationError):
            self.store.reset_password(self.admin, row["user_id"], "test123", admin_password="wrong",
                                      confirmation_token=token, temporary_password=True)
        updated = self.store.reset_password(self.admin, row["user_id"], "test123", admin_password=OWNER_PASSWORD,
                                            confirmation_token=token, temporary_password=True)
        self.assertTrue(updated["temporary_password"])
        self.assertFalse(updated["pending"])
        member = self.store.login("PendingMember", "test123")
        self.assertEqual(member.profile_key, key)
        changed = self.store.change_password(member, "test123", NEW_PASSWORD)
        self.assertEqual(changed.profile_key, key)
        self.assertFalse(next(r for r in self.store.list_users(self.admin) if r["user_id"] == row["user_id"])["temporary_password"])
        with self.assertRaises(accounts.AuthenticationError): self.store.login("PendingMember", "test123")

    def test_temporary_member_promotion_preserves_temporary_status(self):
        self.initialized(pending=("PendingMember",))
        row = next(row for row in self.store.list_users(self.admin) if row["pending"])
        token = self.store.request_confirmation(self.admin, "password-reset", row["user_id"], admin_password=OWNER_PASSWORD)
        self.store.reset_password(self.admin, row["user_id"], "test123", admin_password=OWNER_PASSWORD,
                                  confirmation_token=token, temporary_password=True)
        member = self.store.login("PendingMember", "test123"); key = member.profile_key
        result = self.store.promote(self.admin, row["user_id"], admin_password=OWNER_PASSWORD, target_password="test123")
        self.assertTrue(result["temporary_password"])
        self.assertFalse(member.active)
        promoted = self.store.login("PendingMember", "test123")
        self.assertEqual(promoted.role, "admin")
        self.assertEqual(promoted.profile_key, key)

    def test_confirmation_revoked_on_target_password_change_and_logout(self):
        row, member = self.user()
        token = self.store.request_confirmation(self.admin, "password-reset", member.user_id, admin_password=OWNER_PASSWORD)
        self.store.change_password(member, USER_PASSWORD, NEW_PASSWORD)
        with self.assertRaises(accounts.AuthorizationError):
            self.store.reset_password(self.admin, member.user_id, USER_PASSWORD,
                                      admin_password=OWNER_PASSWORD, confirmation_token=token)
        token = self.store.request_confirmation(self.admin, "start-fresh", admin_password=OWNER_PASSWORD)
        self.store.logout(self.admin)
        replacement = self.store.login("TestOwner", OWNER_PASSWORD)
        with self.assertRaises(accounts.AuthorizationError): self.store.consume_confirmation(replacement, token, "start-fresh")

    def test_start_fresh_confirmation_only_authorizes_never_wipes(self):
        self.initialized()
        data = self.root / "Private/Users" / self.admin.user_id / "vault.bin"
        data.parent.mkdir(parents=True); data.write_bytes(b"synthetic encrypted payload")
        token = self.store.request_confirmation(self.admin, "start-fresh", admin_password=OWNER_PASSWORD)
        result = self.store.consume_confirmation(self.admin, token, "start-fresh")
        self.assertFalse(result["performed"])
        self.assertTrue(data.exists())
        self.assertTrue(self.store.registry_path.exists())

    def test_missing_registry_or_marker_never_reopens_bootstrap(self):
        self.initialized()
        self.store.registry_path.unlink()
        self.assertEqual(self.store.status()["state"], "recovery_required")
        with self.assertRaises(accounts.RecoveryRequired): self.store.bootstrap("Replacement", NEW_PASSWORD)

    def test_corrupt_registry_fails_closed(self):
        self.initialized(); self.store.registry_path.write_text("{broken")
        self.assertEqual(self.store.status()["state"], "recovery_required")
        with self.assertRaises(accounts.RecoveryRequired): self.store.bootstrap("Replacement", NEW_PASSWORD)
        with self.assertRaises(accounts.RecoveryRequired): self.store.login_guest()

    def test_pending_reset_journal_blocks_all_ordinary_account_access(self):
        self.initialized()
        pending = self.root / 'Private/Reset/transaction.json'
        pending.parent.mkdir(parents=True); pending.write_text('{"phase":"synthetic pending"}')
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired): self.store.login('TestOwner', OWNER_PASSWORD)
        with self.assertRaises(accounts.RecoveryRequired): self.store.login_guest()
        with self.assertRaises(accounts.RecoveryRequired): _ = self.admin.profile_key
        with self.assertRaises(accounts.RecoveryRequired): self.store.bootstrap('Replacement', NEW_PASSWORD)

    def test_pending_reset_without_registry_never_reopens_bootstrap(self):
        pending = self.root / 'Private/Reset/transaction.json'
        pending.parent.mkdir(parents=True); pending.write_text('{}')
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired): self.store.bootstrap('Replacement', NEW_PASSWORD)

    def test_populated_install_requires_explicit_reviewed_inventory(self):
        path = self.root / "Data/Chat/history.json"
        path.parent.mkdir(parents=True); path.write_text('{"synthetic":"history"}')
        self.assertEqual(self.store.status()["state"], "recovery_required")
        with self.assertRaises(accounts.RecoveryRequired): self.store.bootstrap("TestOwner", OWNER_PASSWORD)
        inventory = self.store.private_inventory()
        path.write_text('{"synthetic":"changed history"}')
        with self.assertRaises(accounts.RecoveryRequired):
            self.store.initialize_existing("TestOwner", OWNER_PASSWORD, inventory["digest"])
        inventory = self.store.private_inventory()
        admin = self.store.initialize_existing("TestOwner", OWNER_PASSWORD, inventory["digest"])
        self.assertEqual(admin.role, "admin")
        self.assertTrue(path.exists())

    def test_residual_private_cache_or_user_folder_never_means_fresh(self):
        for relative in ("Cache/MediaEdit/retained.bin", "User Folder/private.txt", "OpenWebUI/data/chat.db"):
            path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"synthetic")
            self.assertEqual(self.store.status()["state"], "recovery_required")
            with self.assertRaises(accounts.RecoveryRequired): self.store.bootstrap("TestOwner", OWNER_PASSWORD)
            path.unlink()

    def test_backup_only_private_evidence_is_not_a_fresh_install(self):
        for relative in ('Backups/old/Data/Chat/history.json','Maintenance/Reports/old.json'):
            path = self.root/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(b'synthetic private evidence')
            self.assertEqual(self.store.status()['state'],'recovery_required')
            with self.assertRaises(accounts.RecoveryRequired): self.initialized()
            self.assertIn(relative,[row['path'] for row in self.store.private_inventory()['files']])
            path.unlink()

    def test_shared_runtime_stop_and_configuration_alone_do_not_block_fresh_setup(self):
        path = self.root/'Agent/.runtime/qwen_last_stop.json'
        path.parent.mkdir(parents=True); path.write_text('{}')
        (path.parent/'control_center_theme.json').write_text('{"theme":"light"}')
        self.assertEqual(self.store.private_inventory()['files'],[])
        self.assertEqual(self.store.status()['state'],'fresh')
        self.initialized()

    def test_old_lifecycle_marker_prevents_reinitialization_after_account_files_are_missing(self):
        marker = self.root/'Private/active-session.json'; marker.parent.mkdir(); marker.write_text('{}')
        self.assertEqual(self.store.status()['state'],'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired): self.initialized()

    def test_partial_initialization_remains_recovery_required(self):
        with patch.object(self.store, "_save", side_effect=OSError("simulated full disk")):
            with self.assertRaises(OSError): self.initialized()
        self.assertTrue(self.store.marker_path.exists())
        self.assertFalse(self.store.registry_path.exists())
        self.assertEqual(self.store.status()["state"], "recovery_required")
        with self.assertRaises(accounts.RecoveryRequired): self.initialized()

    def test_atomic_password_failure_preserves_old_login_and_key(self):
        row, member = self.user(); original = self.store.registry_path.read_bytes(); key = member.profile_key
        with patch.object(accounts.os, "replace", side_effect=OSError("simulated interrupted replacement")):
            with self.assertRaises(OSError): self.store.change_password(member, USER_PASSWORD, NEW_PASSWORD)
        self.assertEqual(self.store.registry_path.read_bytes(), original)
        self.assertEqual(self.store.login("Member", USER_PASSWORD).profile_key, key)
        self.assertFalse(list(self.store.base.glob("*.tmp")))

    def test_registry_ciphertext_and_role_tampering_rejects_authorization(self):
        row, member = self.user(); data = self.raw()
        altered = copy.deepcopy(data)
        altered["registry"]["ciphertext"] = base64.b64encode(b"tampered payload").decode()
        self.write_raw(altered)
        with self.assertRaises(accounts.RecoveryRequired): self.store.login("TestOwner", OWNER_PASSWORD)
        altered = copy.deepcopy(data)
        altered["slots"][row["user_id"]]["role"] = "admin"
        altered["slots"][row["user_id"]]["master_access"] = copy.deepcopy(data["slots"][self.admin.user_id]["master_access"])
        self.write_raw(altered)
        with self.assertRaises((accounts.AuthenticationError, accounts.RecoveryRequired)):
            self.store.login("Member", USER_PASSWORD)

    def test_intact_member_envelope_can_recover_own_key_if_only_master_ciphertext_is_damaged(self):
        row, member = self.user(); key = member.profile_key
        data = self.raw()
        data['registry']['ciphertext'] = base64.b64encode(b'synthetic damaged master registry').decode()
        self.write_raw(data)
        with self.assertRaises(accounts.RecoveryRequired): self.store.login('TestOwner', OWNER_PASSWORD)
        recovered = self.store.login('Member', USER_PASSWORD)
        self.assertEqual(recovered.profile_key, key)
        with self.assertRaises(accounts.AuthorizationError): self.store.list_users(recovered)

    def test_credential_rewrap_cannot_change_admin_authenticated_identity(self):
        row, member = self.user(); data = self.raw(); slot = data["slots"][member.user_id]
        # Even a holder of its own DEK cannot rewrite the protected registry identity.
        slot["username"] = "RenamedWithoutApproval"
        slot["credential_mac"] = accounts._encode(accounts._credential_mac(slot, member.profile_key))
        self.write_raw(data)
        with self.assertRaises(accounts.RecoveryRequired): self.store.login("TestOwner", OWNER_PASSWORD)

    def test_invalid_names_ids_and_duplicate_casefold_names_do_not_create_paths(self):
        self.initialized()
        for name in ("../escape", "C:\\escape", "a/b", " trailing ", "Guest", "testowner"):
            with self.assertRaises(ValueError):
                self.store.create_user(self.admin, name, USER_PASSWORD, admin_password=OWNER_PASSWORD)
        with self.assertRaises(ValueError): self.store.profile_session(self.admin, "../escape")

    def test_sessions_remain_active_for_long_missions_until_logout_by_default(self):
        self.initialized(); key = self.admin.profile_key
        self.now += 30 * 24 * 3600
        self.assertTrue(self.admin.active)
        self.assertEqual(self.admin.profile_key, key)
        self.store.logout(self.admin)
        self.assertFalse(self.admin.active)
        with self.assertRaises(accounts.AuthenticationError): _ = self.admin.profile_key

    def test_optional_expiry_is_explicit_and_revokes_handle(self):
        self.initialized()
        expiring = accounts.LocalAccounts(self.root, clock=lambda: self.now, session_seconds=60)
        session = expiring.login("TestOwner", OWNER_PASSWORD)
        self.now += 61
        self.assertFalse(session.active)
        expiring.logout()

    def test_short_password_only_allowed_by_explicit_temporary_initialization(self):
        with self.assertRaises(ValueError): self.store.bootstrap("TestOwner", "short")
        session = self.store.bootstrap("TestOwner", "short", temporary_password=True)
        self.assertTrue(session.temporary_password)
        with self.assertRaises(ValueError): self.store.change_password(session, "short", "shorter")
        changed = self.store.change_password(session, "short", NEW_PASSWORD)
        self.assertFalse(changed.temporary_password)

    def test_parallel_store_updates_are_serialized_without_lost_users(self):
        self.initialized()
        other = accounts.LocalAccounts(self.root)
        admin2 = other.login("TestOwner", OWNER_PASSWORD)
        errors = []
        def create(store, session, name):
            try: store.create_user(session, name, USER_PASSWORD, admin_password=OWNER_PASSWORD)
            except Exception as exc: errors.append(exc)
        threads = [threading.Thread(target=create, args=(self.store, self.admin, "Member1")),
                   threading.Thread(target=create, args=(other, admin2, "Member2"))]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(errors)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual({row["username"] for row in self.store.list_users(self.admin)},
                         {"TestOwner", "Guest", "Member1", "Member2"})
        other.logout()


if __name__ == "__main__":
    unittest.main()
