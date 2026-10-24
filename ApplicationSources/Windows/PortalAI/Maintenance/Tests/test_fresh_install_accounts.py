"""Fresh-install account gates with public startup state and real private evidence."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Agent'))
import local_accounts as accounts
from instance_runtime import InstanceSession
from profile_migration import LegacyMigration, legacy_inventory


class FreshInstallAccountsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='PortalAI fresh installation ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / 'PortalAI'
        self.root.mkdir()
        self.store = accounts.LocalAccounts(self.root)
        self.addCleanup(self.store.logout)
        work = patch.object(accounts, '_KDF_N', 1024)
        work.start()
        self.addCleanup(work.stop)

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding='utf-8')
        return path

    def public_startup(self):
        self.write('Agent/.runtime/stt_runtime.json', {
            'schema': 2, 'status': 'LOCKED_PACKAGE_LAYER',
            'interpreter': 'Runtime/BootstrapPython/python.exe',
            'package_layer': 'SpeechToText/python_packages', 'python': '3.12.14'})
        instance = InstanceSession(self.root, directory=self.root.parent / 'coordination')
        self.addCleanup(instance.close)
        with patch('instance_runtime._available', return_value=True):
            instance.start()
        return instance

    def test_real_startup_metadata_keeps_fresh_status_read_only(self):
        self.public_startup()
        before = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.store.status()['state'], 'fresh')
        self.assertEqual(self.store.private_inventory()['files'], [])
        self.assertFalse((self.root / 'Private').exists())
        after = {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)

    def test_create_first_administrator_after_runtime_startup(self):
        self.public_startup()
        admin = self.store.bootstrap('NewOwner', 'disposable test passphrase')
        self.assertEqual(admin.role, 'admin')
        self.assertEqual(self.store.status()['state'], 'locked')
        self.assertEqual({u['username'] for u in self.store.status()['users']}, {'NewOwner', 'Guest'})

    def test_private_prompt_still_requires_review(self):
        self.public_startup()
        self.write('Agent/.runtime/request.json', {'prompt': 'synthetic private prompt'})
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        self.assertEqual([r['path'] for r in self.store.private_inventory()['files']], ['Agent/.runtime/request.json'])

    def test_nested_metadata_names_are_not_ignored(self):
        self.public_startup()
        for name in ('instance-endpoints.json', 'stt_runtime.json'):
            self.write('Agent/.runtime/jobs/' + name, {'private': 'synthetic data'})
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        self.assertEqual(len(self.store.private_inventory()['files']), 2)

    def test_missing_registry_with_session_evidence_remains_locked(self):
        self.public_startup()
        self.write('Private/active-session.json', {'synthetic': True})
        self.assertEqual(self.store.status()['state'], 'recovery_required')
        with self.assertRaises(accounts.RecoveryRequired):
            self.store.bootstrap('NewOwner', 'disposable test passphrase')

    def test_unknown_account_file_remains_protected(self):
        self.public_startup()
        self.write('Private/Users/synthetic/state.json', {'private': 'retained'})
        self.assertEqual(self.store.status()['state'], 'recovery_required')

    def test_migration_retains_shared_runtime_state(self):
        self.public_startup()
        self.write('Data/Chat/synthetic.json', {'text': 'synthetic private chat'})
        inventory = legacy_inventory(self.root)
        self.assertEqual([r['source'] for r in inventory['files']], ['Data/Chat/synthetic.json'])
        class Session:
            user_id = 'b' * 32
            role = 'admin'
            profile_key = b'k' * 32
        receipt = LegacyMigration(self.root, Session()).run(inventory['digest'], writers_stopped=True)
        self.assertTrue(receipt['sealed'])
        self.assertTrue((self.root / 'Agent/.runtime/instance-endpoints.json').is_file())
        self.assertTrue((self.root / 'Agent/.runtime/stt_runtime.json').is_file())
        self.assertEqual(legacy_inventory(self.root)['files'], [])


if __name__ == '__main__':
    unittest.main()
