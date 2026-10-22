"""One-time initializer uses synthetic profiles and external recovery targets."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools')]
import local_accounts
from initialize_profiles import provision
from profile_workspace import ProfileWorkspace


class InitializationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();base=Path(self.temp.name)
        self.root=base/'portable';self.root.mkdir()
        (self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{
            'minimum_free_gib':0.01,'minimum_free_fraction':0,'output_reserve_gib':0.01}}))
        self.recovery=base/'external';self.recovery.mkdir()
        path=self.root/'Data/Chat/old.json';path.parent.mkdir(parents=True)
        path.write_text('synthetic old history')
        self.password='synthetic temporary initializer password'
        self.patches=[patch.object(local_accounts,'_KDF_N',1024),
            patch('profile_shutdown.stop_owned',return_value={'stopped':True}),
            patch('profile_shutdown.verify_stopped',return_value={'stopped':True})]
        for item in self.patches:item.start()

    def tearDown(self):
        for item in reversed(self.patches):item.stop()
        self.temp.cleanup()

    def provision(self,**kwargs):
        return provision(self.root,'FixtureAdmin',self.password,pending_users=('FixtureMember',),
                         recovery_directory=self.recovery,**kwargs)

    def test_verified_tree_and_external_encrypted_backup(self):
        receipt=self.provision()
        self.assertTrue(receipt['sealed']);self.assertTrue(receipt['external_recovery_verified'])
        self.assertFalse((self.root/'Data/Chat/old.json').exists())
        accounts=local_accounts.LocalAccounts(self.root);admin=accounts.login('FixtureAdmin',self.password)
        self.addCleanup(accounts.logout)
        store=ProfileWorkspace(self.root,admin)
        self.assertEqual(store.inventory(),[])
        store.restore()
        self.assertEqual((store.workspace/'Data/Chat/old.json').read_text(),'synthetic old history')
        names={row['username']:row for row in receipt['accounts']}
        self.assertEqual(set(names),{'FixtureAdmin','FixtureMember','Guest'})
        self.assertTrue(names['FixtureMember']['pending'])
        with zipfile.ZipFile(receipt['external_recovery_path']) as archive:
            self.assertIn('Private/Accounts/registry.json',archive.namelist())
            self.assertFalse(any('/Workspace/' in name for name in archive.namelist()))

    def test_copy_failure_keeps_sources_and_can_resume(self):
        with patch.object(ProfileWorkspace,'snapshot',side_effect=OSError('synthetic interrupted migration')):
            with self.assertRaises(OSError):self.provision()
        self.assertTrue((self.root/'Data/Chat/old.json').exists())
        receipt=self.provision(resume=True)
        self.assertTrue(receipt['external_recovery_verified']);self.assertTrue(receipt['sealed'])

    def test_external_backup_must_be_outside_bundle(self):
        with self.assertRaises(ValueError):
            provision(self.root,'FixtureAdmin',self.password,recovery_directory=self.root)
        self.assertFalse((self.root/'Private/Accounts/initialized.json').exists())

    def test_incomplete_shutdown_keeps_originals(self):
        with patch('profile_shutdown.stop_owned',return_value={'stopped':False}):
            with self.assertRaises(RuntimeError):self.provision()
        self.assertTrue((self.root/'Data/Chat/old.json').exists())
        self.assertTrue(self.provision(resume=True)['sealed'])

    def test_external_backup_failure_prevents_original_removal(self):
        with patch('account_reset_ui.export_reset_plan',side_effect=OSError('synthetic external drive failure')):
            with self.assertRaises(OSError):self.provision()
        self.assertEqual((self.root/'Data/Chat/old.json').read_text(),'synthetic old history')
        self.assertTrue(self.provision(resume=True)['sealed'])


if __name__=='__main__':unittest.main()
