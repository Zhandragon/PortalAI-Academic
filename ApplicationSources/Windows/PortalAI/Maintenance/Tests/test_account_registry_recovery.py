"""Failure-injected current-registry redundancy in synthetic temporary roots."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import local_accounts as accounts

OLD = 'synthetic initial administrator password'
NEW = 'synthetic new administrator password'
MEMBER = 'synthetic ordinary member password'


class RegistryRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='Portal registry recovery ')
        self.root=Path(self.tmp.name)
        self.kdf=patch.object(accounts,'_KDF_N',1024);self.kdf.start()
        self.store=accounts.LocalAccounts(self.root)
        self.admin=self.store.bootstrap('Owner',OLD)

    def tearDown(self):
        self.store.logout();self.kdf.stop();self.tmp.cleanup()

    def packet(self):return json.loads(self.store.recovery_path.read_text())

    def fail_mirror(self):
        original=self.store._atomic
        def atomic(path,value):
            if path==self.store.recovery_path:raise OSError('synthetic unavailable mirror')
            return original(path,value)
        return patch.object(self.store,'_atomic',side_effect=atomic)

    def test_initialization_keeps_only_current_encrypted_verified_copy(self):
        packet=self.packet()
        self.assertEqual(packet['sha256'],hashlib.sha256(self.store.registry_path.read_bytes()).hexdigest())
        self.assertEqual(packet['registry'],json.loads(self.store.registry_path.read_text()))
        self.assertNotIn(OLD,self.store.recovery_path.read_text())
        self.assertFalse(self.store.write_pending_path.exists())
        self.assertEqual({p.name for p in self.store.base.iterdir()},
                         {'registry.json','registry-recovery.json','initialized.json','registry.lock'})

    def test_missing_primary_and_marker_require_explicit_admin_recovery_preserving_keys(self):
        key=self.admin.profile_key
        self.store.registry_path.unlink();self.store.marker_path.unlink()
        self.assertEqual(self.store.status()['state'],'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired):self.store.login('Owner',OLD)
        with self.assertRaises(accounts.RecoveryRequired):self.store.bootstrap('Replacement',NEW)
        self.assertTrue(self.store.recover_registry('Owner',OLD)['login_required'])
        self.assertFalse(self.admin.active)
        self.assertEqual(self.store.login('Owner',OLD).profile_key,key)

    def test_corrupt_master_ciphertext_can_be_restored_from_current_encrypted_copy(self):
        original=self.store.registry_path.read_bytes()
        data=json.loads(original);data['registry']['ciphertext']='YmFk'
        self.store.registry_path.write_text(json.dumps(data))
        with self.assertRaises(accounts.RecoveryRequired):self.store.login('Owner',OLD)
        self.assertTrue(self.store.recover_registry('Owner',OLD)['recovered'])
        self.assertEqual(self.store.registry_path.read_bytes(),original)

    def test_wrong_or_nonadmin_recovery_password_does_not_modify_registry(self):
        self.store.create_user(self.admin,'Member',MEMBER,admin_password=OLD)
        self.store.registry_path.write_text('{broken')
        for username,password in (('Owner','wrong'),('Member',MEMBER),('Guest','')):
            with self.assertRaises(PermissionError):self.store.recover_registry(username,password)
            self.assertEqual(self.store.registry_path.read_text(),'{broken')

    def test_postcommit_mirror_failure_returns_valid_new_session_and_recovery_warning(self):
        key=self.admin.profile_key
        with self.fail_mirror():updated=self.store.change_password(self.admin,OLD,NEW)
        self.assertFalse(self.admin.active);self.assertTrue(updated.active)
        self.assertEqual(updated.profile_key,key);self.assertTrue(updated.recovery_warning)
        self.assertTrue(self.store.write_pending_path.exists())
        with self.assertRaises(accounts.RecoveryRequired):self.store.recover_registry('Owner',OLD)
        with self.assertRaises(accounts.AuthenticationError):self.store.login('Owner',OLD)
        repaired=self.store.login('Owner',NEW)
        self.assertFalse(repaired.recovery_warning);self.assertFalse(self.store.write_pending_path.exists())
        self.assertEqual(self.packet()['sha256'],hashlib.sha256(self.store.registry_path.read_bytes()).hexdigest())
        self.store.registry_path.unlink()
        with self.assertRaises(accounts.AuthenticationError):self.store.recover_registry('Owner',OLD)
        self.assertTrue(self.store.recover_registry('Owner',NEW)['recovered'])

    def test_standard_password_mirror_failure_keeps_new_key_and_admin_can_repair(self):
        self.store.create_user(self.admin,'Member',MEMBER,admin_password=OLD)
        member=self.store.login('Member',MEMBER);key=member.profile_key
        with self.fail_mirror():updated=self.store.change_password(member,MEMBER,NEW)
        self.assertEqual(updated.profile_key,key);self.assertTrue(updated.recovery_warning)
        self.store.login('Owner',OLD)
        self.assertFalse(self.store.write_pending_path.exists())
        self.assertEqual(self.store.login('Member',NEW).profile_key,key)

    def test_failed_primary_write_preserves_old_authentication_and_admin_repairs_journal(self):
        original=self.store._atomic;before=self.store.registry_path.read_bytes()
        def atomic(path,value):
            if path==self.store.registry_path:raise OSError('synthetic failed primary replacement')
            return original(path,value)
        with patch.object(self.store,'_atomic',side_effect=atomic):
            with self.assertRaises(OSError):self.store.change_password(self.admin,OLD,NEW)
        self.assertTrue(self.admin.active);self.assertEqual(self.store.registry_path.read_bytes(),before)
        self.assertTrue(self.store.write_pending_path.exists())
        self.store.login('Owner',OLD)
        self.assertFalse(self.store.write_pending_path.exists())

    def test_error_after_primary_replace_does_not_report_old_password_still_current(self):
        original=self.store._atomic
        def atomic(path,value):
            original(path,value)
            if path==self.store.registry_path:raise OSError('synthetic fsync error after replace')
        with patch.object(self.store,'_atomic',side_effect=atomic):
            updated=self.store.change_password(self.admin,OLD,NEW)
        self.assertTrue(updated.active)
        with self.assertRaises(accounts.AuthenticationError):self.store.login('Owner',OLD)
        self.assertTrue(self.store.login('Owner',NEW).active)

    def test_manual_stale_mirror_cannot_rollback_valid_new_primary(self):
        old=self.store.recovery_path.read_bytes()
        self.store.change_password(self.admin,OLD,NEW)
        current=self.store.registry_path.read_bytes();self.store.recovery_path.write_bytes(old)
        with self.assertRaises(accounts.RecoveryRequired):self.store.recover_registry('Owner',OLD)
        self.assertEqual(self.store.registry_path.read_bytes(),current)
        self.store.login('Owner',NEW)
        self.assertEqual(self.packet()['registry'],json.loads(current))

    def test_corrupt_mirror_requires_primary_admin_validation_before_repair(self):
        self.store.create_user(self.admin,'Member',MEMBER,admin_password=OLD)
        self.store.recovery_path.write_text('{broken')
        member=self.store.login('Member',MEMBER)
        self.assertTrue(member.recovery_warning)
        with self.assertRaises(accounts.RecoveryRequired):self.store.change_password(member,MEMBER,NEW)
        self.store.login('Owner',OLD)
        self.assertTrue(self.store._recovery_current(self.store._read()))

    def test_different_valid_instance_cannot_be_replaced_from_foreign_recovery(self):
        foreign=accounts.LocalAccounts(self.root/'Foreign')
        foreign.bootstrap('Other',NEW)
        self.store.recovery_path.write_bytes(foreign.recovery_path.read_bytes())
        before=self.store.registry_path.read_bytes()
        with self.assertRaises(accounts.RecoveryRequired):self.store.recover_registry('Other',NEW)
        self.assertEqual(self.store.registry_path.read_bytes(),before);foreign.logout()


if __name__=='__main__':unittest.main()
