"""Synthetic migration cleanup tests; no production files or processes."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Agent'))
import profile_migration as migration


class Session:
    user_id = 'a' * 32
    role = 'admin'
    profile_key = b'k' * 32


class EmptyLegacyDirectories(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.migration = migration.LegacyMigration(self.root, Session())

    def write(self, relative, content=b'synthetic data'):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_migration(self):
        plan = migration.legacy_inventory(self.root)
        return self.migration.run(plan['digest'], writers_stopped=True)

    def test_nested_names_removed_declared_roots_and_exact_file_parents_preserved(self):
        files = ('User Folder/Private Project/nested/note.txt',
                 'Patch/Videos/Clipchamp/Project/media.wav',
                 'Maintenance/Archive/old/session/trace.log',
                 'Sandbox/Security/agent_token.txt')
        for relative in files:
            self.write(relative)
        empty = self.root / 'User Folder/Another Private Name/Empty'
        empty.mkdir(parents=True)
        historical_empty = self.root / 'Sandbox/Security/Shared Empty Config Folder'
        historical_empty.mkdir()
        self.write('Patch/shared_source.py', b'source')
        result = self.run_migration()
        self.assertTrue(result['sealed'])
        for relative in ('User Folder', 'Patch/Videos', 'Maintenance/Archive', 'Sandbox/Security'):
            self.assertTrue((self.root / relative).is_dir(), relative)
        for relative in ('User Folder/Private Project', 'User Folder/Another Private Name',
                         'Patch/Videos/Clipchamp', 'Maintenance/Archive/old'):
            self.assertFalse((self.root / relative).exists(), relative)
        self.assertTrue(historical_empty.is_dir())
        self.assertEqual((self.root / 'Patch/shared_source.py').read_bytes(), b'source')
        self.migration.store.restore()
        for relative in files:
            target = migration._source_target(relative)
            self.assertEqual((self.migration.store.workspace / target).read_bytes(), b'synthetic data')

    def test_empty_cleanup_is_idempotent_and_preserves_all_declared_roots(self):
        for scope in migration.PRIVATE_PREFIXES + migration.HISTORICAL_ROOTS:
            (self.root / scope / 'nested/empty').mkdir(parents=True, exist_ok=True)
        migration._remove_empty_legacy_directories(self.root)
        migration._remove_empty_legacy_directories(self.root)
        for scope in migration.PRIVATE_PREFIXES + migration.HISTORICAL_ROOTS:
            self.assertTrue((self.root / scope).is_dir(), scope)
            self.assertFalse((self.root / scope / 'nested').exists(), scope)

    def test_late_file_prevents_rmdir_and_completion_without_deleting_file(self):
        self.write('User Folder/Private Project/original.txt')
        directory = self.root / 'User Folder/Private Project'
        late = directory / 'late.txt'
        original = Path.rmdir
        def inject(path):
            if path == directory:
                late.write_bytes(b'late writer')
            return original(path)
        with patch.object(Path, 'rmdir', inject):
            with self.assertRaisesRegex(RuntimeError, 'directory cleanup'):
                self.run_migration()
        self.assertEqual(late.read_bytes(), b'late writer')
        self.assertTrue(self.migration.journal.exists())
        self.assertFalse(self.migration.complete.exists())
        self.assertEqual(len(self.migration.store.verify()['files']), 2)
        with self.assertRaisesRegex(RuntimeError, 'New or changed'):
            self.migration.recover_verified(writers_stopped=True)
        self.assertEqual(late.read_bytes(), b'late writer')

    def test_interrupted_directory_cleanup_resumes_from_encrypted_plan(self):
        self.write('User Folder/Private Project/nested/note.txt')
        original = Path.rmdir
        def fail(path):
            if path == self.root / 'User Folder/Private Project':
                raise OSError('synthetic power interruption')
            return original(path)
        with patch.object(Path, 'rmdir', fail):
            with self.assertRaisesRegex(RuntimeError, 'directory cleanup'):
                self.run_migration()
        self.assertFalse((self.root / 'User Folder/Private Project/nested').exists())
        self.assertTrue(self.migration.journal.exists())
        self.assertTrue(self.migration.recover_verified(writers_stopped=True)['sealed'])
        self.assertTrue((self.root / 'User Folder').is_dir())
        self.assertFalse((self.root / 'User Folder/Private Project').exists())
        self.migration.store.restore()
        self.assertEqual((self.migration.store.workspace / 'User Folder/Private Project/nested/note.txt').read_bytes(), b'synthetic data')

    def test_late_historical_file_after_cleanup_stops_commit(self):
        self.write('Outputs/job/result.txt')
        original = migration._remove_empty_legacy_directories
        def inject(root):
            original(root)
            self.write('Sandbox/Security/agent_token.txt', b'late token')
        with patch.object(migration, '_remove_empty_legacy_directories', inject):
            with self.assertRaisesRegex(RuntimeError, 'after directory cleanup'):
                self.run_migration()
        self.assertEqual((self.root / 'Sandbox/Security/agent_token.txt').read_bytes(), b'late token')
        self.assertTrue(self.migration.journal.exists())
        self.assertFalse(self.migration.complete.exists())

    def test_late_file_during_workspace_seal_stops_completion(self):
        self.write('Outputs/job/result.txt')
        original = self.migration.store.seal
        def inject(*args, **kwargs):
            result = original(*args, **kwargs)
            self.write('User Folder/new.txt', b'late writer')
            return result
        with patch.object(self.migration.store, 'seal', inject):
            with self.assertRaisesRegex(RuntimeError, 'before completion'):
                self.run_migration()
        self.assertEqual((self.root / 'User Folder/new.txt').read_bytes(), b'late writer')
        self.assertEqual(self.migration.store.inventory(), [])
        self.assertTrue(self.migration.journal.exists())
        self.assertFalse(self.migration.complete.exists())

    def test_link_rejected_without_removing_link_or_target(self):
        target = self.root / 'Shared/Keep'
        target.mkdir(parents=True)
        link = self.root / 'Outputs/Linked'
        link.parent.mkdir()
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            self.skipTest('Directory symlink creation is unavailable: ' + str(error))
        with self.assertRaises(PermissionError):
            migration._remove_empty_legacy_directories(self.root)
        self.assertTrue(link.is_symlink())
        self.assertTrue(target.is_dir())

    def test_unreadable_directory_is_not_silently_skipped(self):
        (self.root / 'Outputs/Private Name').mkdir(parents=True)
        def failed_walk(path, *, onerror, **kwargs):
            onerror(PermissionError('synthetic unreadable folder'))
        with patch.object(migration.os, 'walk', failed_walk):
            with self.assertRaises(PermissionError):
                migration._remove_empty_legacy_directories(self.root)
        self.assertTrue((self.root / 'Outputs/Private Name').is_dir())


if __name__ == '__main__':
    unittest.main()
