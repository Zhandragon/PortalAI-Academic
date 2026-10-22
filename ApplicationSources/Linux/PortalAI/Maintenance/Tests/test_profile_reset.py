"""Destructive reset/recovery contract, exclusively in synthetic temporary roots."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import local_accounts as accounts
from profile_reset import ResetCoordinator, CONFIRMATION_PHRASE
from profile_workspace import ProfileWorkspace

OLD_PASSWORD = 'synthetic former owner password'
NEW_PASSWORD = 'synthetic replacement owner password'


class ResetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='Portal reset test ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        work = patch.object(accounts, '_KDF_N', 1024)
        work.start(); self.addCleanup(work.stop)
        self.now = 1000.0
        self.store = accounts.LocalAccounts(self.root, clock=lambda: self.now)
        self.addCleanup(self.store.logout)
        self.admin = self.store.bootstrap('FormerOwner', OLD_PASSWORD)
        self.coordinator = ResetCoordinator(self.root, self.store)
        self.writer_check = lambda: True

    def write(self, relative, data=b'synthetic private result'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        return path

    def sealed(self):
        workspace = ProfileWorkspace(self.root, self.admin)
        path = workspace.workspace / 'Outputs/Images/result.bin'
        path.parent.mkdir(parents=True); path.write_bytes(b'synthetic private result')
        workspace.seal(writers_stopped=True)
        return workspace

    def reviewed(self):
        plan = self.coordinator.plan(self.admin, writer_check=self.writer_check)
        token = self.coordinator.request_confirmation(self.admin, plan, admin_password=OLD_PASSWORD,
                    typed_confirmation=CONFIRMATION_PHRASE, writer_check=self.writer_check)
        return plan, token

    def execute(self, plan, token, **kwargs):
        return self.coordinator.execute(self.admin, plan, token, admin_password=OLD_PASSWORD,
                  new_username='ReplacementOwner', new_password=NEW_PASSWORD,
                  writer_check=self.writer_check, **kwargs)

    def interrupt(self, phase):
        plan, token = self.reviewed()
        original = self.coordinator._write_journal
        def write(state, *args, **kwargs):
            original(state, *args, **kwargs)
            if state['phase'] == phase: raise OSError('synthetic crash after ' + phase)
        with patch.object(self.coordinator, '_write_journal', side_effect=write):
            with self.assertRaises(OSError): self.execute(plan, token)
        self.assertEqual(self.coordinator.recovery_status()['phase'], phase)
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired): self.store.login('FormerOwner', OLD_PASSWORD)
        return plan

    def test_completed_reset_replaces_keys_preserves_shared_assets_and_requires_login(self):
        workspace = self.sealed(); old_key = self.admin.profile_key
        shared = [self.write(relative, relative.encode()) for relative in
                  ('LLM/models/model.gguf', 'Runtime/binary.exe', 'Agent/tool.py', 'Master Instructions.txt')]
        expected = {path: path.read_bytes() for path in shared}
        plan, token = self.reviewed()
        self.assertEqual(plan['roots'], ['Private/Accounts', 'Private/Users'])
        self.assertTrue(any(row['path'].startswith('Private/Users/') for row in plan['files']))
        result = self.execute(plan, token, pending_users=('PendingMember',))
        self.assertTrue(result['reset']); self.assertTrue(result['login_required'])
        self.assertIn('not secure physical erasure', result['deletion_limit'])
        self.assertFalse(self.admin.active); self.assertFalse(workspace.vault.exists())
        self.assertEqual({path: path.read_bytes() for path in shared}, expected)
        self.assertFalse(self.coordinator.journal.exists())
        self.assertFalse(any(path.is_dir() for path in self.coordinator.base.iterdir()))
        with self.assertRaises(accounts.AuthenticationError): self.store.login('FormerOwner', OLD_PASSWORD)
        fresh = self.store.login('ReplacementOwner', NEW_PASSWORD)
        self.assertEqual(fresh.role, 'admin'); self.assertNotEqual(fresh.profile_key, old_key)
        self.assertEqual({row['username'] for row in self.store.list_users(fresh)},
                         {'ReplacementOwner', 'Guest', 'PendingMember'})

    def test_other_profile_controller_blocks_reset_before_mutation(self):
        from mission_runner import process_lock
        plan, token = self.reviewed()
        before = self.store.registry_path.read_bytes()
        with process_lock(self.root / 'Private/profile-runtime.lock'):
            with self.assertRaisesRegex(RuntimeError, 'Another PortalAI controller'):
                self.execute(plan, token)
        self.assertEqual(self.store.registry_path.read_bytes(), before)
        self.assertFalse(self.coordinator.journal.exists())

    def test_session_guard_nests_through_execution_and_excludes_other_coordinator(self):
        other = ResetCoordinator(self.root, self.store)
        with self.coordinator.hold_session():
            with self.coordinator.hold_session():
                with self.assertRaisesRegex(RuntimeError, 'Another PortalAI controller'):
                    with other.hold_session(): pass
                plan, token = self.reviewed()
                self.assertTrue(self.execute(plan, token)['reset'])
            with self.assertRaisesRegex(RuntimeError, 'Another PortalAI controller'):
                with other.hold_session(): pass
        with other.hold_session(): pass

    def test_new_owner_opens_after_reset_of_closed_old_runtime(self):
        from profile_runtime import ProfileRuntime
        from profile_migration import SessionHarvest
        runtime = ProfileRuntime(self.root, self.store, quiesce=lambda *_: {'stopped': True},
            harvest=lambda actor: SessionHarvest(self.root, actor).run(writers_stopped=True))
        runtime.prepare(self.admin)
        runtime.close(self.admin, writers_stopped=True)
        self.admin = self.store.login('FormerOwner', OLD_PASSWORD)
        plan, token = self.reviewed()
        self.execute(plan, token)
        owner = self.store.login('ReplacementOwner', NEW_PASSWORD)
        self.assertTrue(runtime.prepare(owner)['ready'])
        self.assertTrue(runtime.close(owner, writers_stopped=True)['sealed'])

    def test_only_admin_fresh_password_and_exact_typed_confirmation_are_accepted(self):
        plan = self.coordinator.plan(self.admin, writer_check=self.writer_check)
        before = self.store.registry_path.read_bytes()
        with self.assertRaises(accounts.AuthorizationError):
            self.coordinator.plan(self.store.login_guest(), writer_check=self.writer_check)
        for password, typed in ((OLD_PASSWORD, 'reset'), ('wrong', CONFIRMATION_PHRASE)):
            with self.assertRaises(PermissionError):
                self.coordinator.request_confirmation(self.admin, plan, admin_password=password,
                              typed_confirmation=typed, writer_check=self.writer_check)
        self.assertEqual(self.store.registry_path.read_bytes(), before)

    def test_expired_or_replayed_confirmation_does_not_reset(self):
        plan, token = self.reviewed(); self.now += 301
        for _ in range(2):
            with self.assertRaises(accounts.AuthorizationError): self.execute(plan, token)
        self.assertTrue(self.admin.active)
        self.assertFalse(self.coordinator.journal.exists())

    def test_plan_tampering_or_data_changes_require_new_review(self):
        workspace = self.sealed(); plan, token = self.reviewed()
        plan['bytes'] += 1
        with self.assertRaises(accounts.RecoveryRequired): self.execute(plan, token)
        plan, token = self.reviewed()
        self.write(str((workspace.workspace / 'Outputs/new.txt').relative_to(self.root)))
        with self.assertRaises(RuntimeError): self.execute(plan, token)
        self.assertFalse(self.coordinator.journal.exists())

    def test_refuses_writers_open_marker_plaintext_legacy_and_links(self):
        with self.assertRaises(RuntimeError): self.coordinator.plan(self.admin, writer_check=lambda: False)
        marker = self.write('Private/active-session.json', b'{"state":"open"}')
        with self.assertRaises(RuntimeError): self.coordinator.plan(self.admin, writer_check=self.writer_check)
        marker.unlink()
        legacy = self.write('Data/Chat/history.json')
        with self.assertRaises(accounts.RecoveryRequired): self.coordinator.plan(self.admin, writer_check=self.writer_check)
        legacy.unlink()
        workspace = ProfileWorkspace(self.root, self.admin)
        plain = self.write(str((workspace.workspace/'Outputs/unsealed.txt').relative_to(self.root)))
        with self.assertRaises(RuntimeError): self.coordinator.plan(self.admin, writer_check=self.writer_check)
        plain.unlink()
        extra = self.write('Private/Users/' + self.admin.user_id + '/unknown-file')
        with self.assertRaises(accounts.RecoveryRequired): self.coordinator.plan(self.admin, writer_check=self.writer_check)
        extra.unlink()
        try: os.link(self.store.registry_path, self.root/'registry-alias')
        except OSError: return
        with self.assertRaises(accounts.RecoveryRequired): self.coordinator.plan(self.admin, writer_check=self.writer_check)

    def test_invalid_new_password_never_changes_old_registry(self):
        plan, token = self.reviewed(); before = self.store.registry_path.read_bytes()
        with self.assertRaises(ValueError):
            self.coordinator.execute(self.admin, plan, token, admin_password=OLD_PASSWORD,
                 new_username='ReplacementOwner', new_password='short', writer_check=self.writer_check)
        self.assertEqual(self.store.registry_path.read_bytes(), before)
        self.assertTrue(self.admin.active)

    def test_precommit_crashes_roll_back_old_data_and_never_auto_replay(self):
        for phase in ('prepared', 'users-staged', 'swapping'):
            with self.subTest(phase=phase):
                # Each interruption is explicitly recovered before the next.
                if not (self.root/'Private/Users'/self.admin.user_id).exists(): self.sealed()
                self.interrupt(phase)
                restarted = ResetCoordinator(self.root)
                self.assertEqual(restarted.recovery_status()['action'], 'rollback')
                with self.assertRaises(PermissionError):
                    restarted.recover('FormerOwner', 'wrong', action='rollback', writer_check=self.writer_check)
                result = restarted.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
                self.assertTrue(result['rolled_back']); self.assertFalse(result['recovery_copies_retained'])
                self.assertFalse(any(path.is_dir() for path in restarted.base.iterdir()))
                self.admin = self.store.login('FormerOwner', OLD_PASSWORD)
                ProfileWorkspace(self.root, self.admin).verify()

    def test_rollback_cleanup_crash_uses_restored_registry_when_transaction_copy_is_partial(self):
        self.sealed(); self.interrupt('users-staged')
        original = Path.unlink; removed = []
        def unlink(path, *args, **kwargs):
            if 'old-root' in path.parts and path.name == 'registry.json' and not removed:
                original(path, *args, **kwargs); removed.append(path)
                raise OSError('synthetic interrupted rollback account cleanup')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            with self.assertRaises(OSError):
                self.coordinator.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        self.assertTrue(removed)
        restarted = ResetCoordinator(self.root)
        self.assertEqual(restarted.recovery_status()['phase'], 'rollback-cleaning')
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        result = restarted.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        self.assertTrue(result['rolled_back']); self.assertFalse(result['recovery_copies_retained'])
        owner = self.store.login('FormerOwner', OLD_PASSWORD)
        ProfileWorkspace(self.root,owner).verify()
        self.assertFalse(any(path.is_dir() for path in restarted.base.iterdir()))

    def test_rollback_cleanup_refuses_changed_restored_bytes_before_removing_transaction(self):
        self.sealed(); self.interrupt('users-staged')
        original = self.coordinator._cleanup
        with patch.object(self.coordinator, '_cleanup', side_effect=OSError('synthetic stopped cleanup')):
            with self.assertRaises(OSError):
                self.coordinator.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        state = self.coordinator._read_journal(); transaction = self.coordinator._tx(state)
        path = next((self.root/'Private/Users').rglob('*.enc'))
        path.write_bytes(b'changed restored ciphertext')
        with self.assertRaises(accounts.RecoveryRequired):
            self.coordinator.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        self.assertTrue(transaction.exists()); self.assertTrue(self.coordinator.journal.exists())

    def test_mid_registry_swap_rolls_back_even_when_active_registry_is_inconsistent(self):
        self.sealed(); plan, token = self.reviewed()
        original = self.coordinator._atomic
        def atomic(path, value):
            if path == self.store.marker_path: raise OSError('synthetic crash between registry and marker')
            return original(path, value)
        with patch.object(self.coordinator, '_atomic', side_effect=atomic):
            with self.assertRaises(OSError): self.execute(plan, token)
        self.assertEqual(self.coordinator.recovery_status()['phase'], 'swapping')
        result = ResetCoordinator(self.root).recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        self.assertTrue(result['rolled_back'])
        self.assertEqual(self.store.login('FormerOwner', OLD_PASSWORD).role, 'admin')

    def test_committed_crash_finishes_with_new_password_and_refuses_rollback(self):
        self.sealed(); self.interrupt('committed')
        restarted = ResetCoordinator(self.root)
        with self.assertRaises(accounts.RecoveryRequired):
            restarted.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        with self.assertRaises(PermissionError):
            restarted.recover('FormerOwner', OLD_PASSWORD, action='finish', writer_check=self.writer_check)
        result = restarted.recover('ReplacementOwner', NEW_PASSWORD, action='finish', writer_check=self.writer_check)
        self.assertTrue(result['reset']); self.assertFalse(restarted.journal.exists())
        self.assertEqual(self.store.login('ReplacementOwner', NEW_PASSWORD).role, 'admin')

    def test_crash_after_cleanup_before_journal_removal_finishes_idempotently(self):
        self.sealed(); self.interrupt('complete')
        restarted = ResetCoordinator(self.root)
        self.assertTrue(restarted.recover('ReplacementOwner', NEW_PASSWORD,
                        action='finish', writer_check=self.writer_check)['reset'])
        self.assertFalse(restarted.recovery_status()['pending'])

    def test_historical_private_copies_use_the_same_migration_guard(self):
        for relative in ('Backups/old/Data/Chat/history.json', 'Agent/.runtime/request.json'):
            path = self.write(relative)
            with self.assertRaises(accounts.RecoveryRequired):
                self.coordinator.plan(self.admin, writer_check=self.writer_check)
            path.unlink()

    def test_completed_harvest_receipt_must_match_authenticated_encrypted_plan(self):
        from profile_migration import SessionHarvest
        workspace = self.sealed(); workspace.restore()
        self.write('Logs/synthetic.log', b'synthetic private diagnostic')
        SessionHarvest(self.root,self.admin).run(writers_stopped=True)
        workspace.seal(writers_stopped=True)
        self.reviewed()
        path = workspace.base/'harvest-last.json'
        receipt = json.loads(path.read_text()); receipt['files'] += 1
        path.write_text(json.dumps(receipt))
        with self.assertRaises(accounts.RecoveryRequired):
            self.coordinator.plan(self.admin,writer_check=self.writer_check)

    def test_interrupted_partial_cleanup_can_finish_without_requiring_missing_files(self):
        self.sealed(); plan, token = self.reviewed(); original = Path.unlink
        state = {'removed': False}
        def unlink(path, *args, **kwargs):
            if 'old-users' in path.parts and not state['removed']:
                original(path, *args, **kwargs); state['removed'] = True
                raise OSError('synthetic interruption after deletion')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            with self.assertRaises(OSError): self.execute(plan, token)
        self.assertTrue(state['removed'])
        restarted = ResetCoordinator(self.root)
        self.assertEqual(restarted.recovery_status()['phase'], 'cleaning')
        self.assertTrue(restarted.recover('ReplacementOwner', NEW_PASSWORD,
                 action='finish', writer_check=self.writer_check)['reset'])

    def test_tampered_journal_and_retired_payload_stop_recovery(self):
        self.sealed(); self.interrupt('committed')
        original = self.coordinator.journal.read_bytes()
        state = json.loads(original); state['plan']['bytes'] += 1
        self.coordinator.journal.write_text(json.dumps(state))
        with self.assertRaises(accounts.RecoveryRequired):
            self.coordinator.recover('ReplacementOwner', NEW_PASSWORD, action='finish', writer_check=self.writer_check)
        self.coordinator.journal.write_bytes(original)
        state = json.loads(original); retired = self.coordinator._tx(state)/'old-users'
        path = next(path for path in retired.rglob('*.enc'))
        path.write_bytes(b'tampered retired ciphertext')
        with self.assertRaises(accounts.RecoveryRequired):
            self.coordinator.recover('ReplacementOwner', NEW_PASSWORD, action='finish', writer_check=self.writer_check)
        self.assertTrue(path.exists()); self.assertTrue(self.coordinator.journal.exists())

    def test_rollback_never_overwrites_new_private_files(self):
        self.sealed(); self.interrupt('users-staged')
        surprise = self.write('Private/Users/' + 'a'*32 + '/Workspace/Outputs/new.txt')
        with self.assertRaises(accounts.RecoveryRequired):
            self.coordinator.recover('FormerOwner', OLD_PASSWORD, action='rollback', writer_check=self.writer_check)
        self.assertTrue(surprise.exists())


if __name__ == '__main__': unittest.main()
