"""Read-only directory recovery, using only temporary synthetic directories."""
import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Agent'))
import profile_migration as migration


class ReadonlyDirectoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.directory = self.root / 'Outputs/nested'
        self.directory.mkdir(parents=True)
        self.before = self.directory.stat(follow_symlinks=False)
        self.attributes = 0x80031  # Pinned, archive, directory and read-only.
        self.inode = self.before.st_ino
        self.lib = MagicMock()
        def set_attributes(path, attributes):
            self.assertEqual(path, str(self.directory))
            self.attributes = attributes
            return True
        self.lib.SetFileAttributesW.side_effect = set_attributes

    def fixture(self):
        from contextlib import ExitStack
        stack = ExitStack()
        real_stat = Path.stat
        def stat(path, *, follow_symlinks=True):
            if path == self.directory and not follow_symlinks:
                return SimpleNamespace(st_dev=self.before.st_dev, st_ino=self.inode,
                    st_mode=self.before.st_mode, st_file_attributes=self.attributes)
            return real_stat(path, follow_symlinks=follow_symlinks)
        stack.enter_context(patch.object(migration, 'os', SimpleNamespace(name='nt', walk=os.walk)))
        stack.enter_context(patch.object(ctypes, 'WinDLL', return_value=self.lib, create=True))
        stack.enter_context(patch.object(Path, 'stat', stat))
        return stack

    def clear(self):
        return migration._windows_clear_readonly_empty_directory(self.root, self.directory, self.before)

    def test_only_readonly_bit_changes_other_attributes_preserved(self):
        with self.fixture():
            self.assertTrue(self.clear())
        self.lib.SetFileAttributesW.assert_called_once_with(str(self.directory), 0x80030)
        self.assertTrue(self.directory.is_dir())

    def test_replaced_directory_is_never_modified(self):
        self.inode += 1
        with self.fixture(), self.assertRaisesRegex(RuntimeError, 'identity changed'):
            self.clear()
        self.lib.SetFileAttributesW.assert_not_called()

    def test_reparse_attribute_is_never_modified(self):
        self.attributes |= 0x400
        with self.fixture(), self.assertRaises((PermissionError, RuntimeError)):
            self.clear()
        self.lib.SetFileAttributesW.assert_not_called()

    def test_new_file_blocks_attribute_change(self):
        private = self.directory / 'late.txt'
        private.write_bytes(b'keep')
        with self.fixture(), self.assertRaisesRegex(RuntimeError, 'writer created'):
            self.clear()
        self.lib.SetFileAttributesW.assert_not_called()
        self.assertEqual(private.read_bytes(), b'keep')

    def test_without_readonly_does_not_mask_permission_failure(self):
        self.attributes &= ~0x1
        with self.fixture():
            self.assertFalse(self.clear())
        self.lib.SetFileAttributesW.assert_not_called()

    def test_late_file_after_attribute_change_remains_intact(self):
        def set_and_write(path, attributes):
            self.attributes = attributes
            (self.directory / 'late.txt').write_bytes(b'keep')
            return True
        self.lib.SetFileAttributesW.side_effect = set_and_write
        with self.fixture(), self.assertRaisesRegex(RuntimeError, 'writer created'):
            self.clear()
        self.assertEqual((self.directory / 'late.txt').read_bytes(), b'keep')

    def test_retry_permission_error_is_not_suppressed(self):
        with self.fixture(), patch.object(Path, 'rmdir', side_effect=PermissionError('ACL denies deletion')) as remove:
            with self.assertRaisesRegex(RuntimeError, 'directory cleanup'):
                migration._remove_empty_legacy_directories(self.root)
        self.assertEqual(remove.call_count, 2)
        self.assertTrue(self.directory.exists())

    @unittest.skipUnless(os.name == 'nt', 'Native Windows directory attributes')
    def test_native_readonly_workspace_seal_retains_verified_recovery(self):
        from profile_workspace import ProfileWorkspace
        store = ProfileWorkspace(self.root, SimpleNamespace(user_id='a'*32, profile_key=b'k'*32))
        folder = store.workspace / 'Music/ACE-Step-1.5/.cache/torchinductor/private-label'
        folder.mkdir(parents=True)
        source = folder / 'cache.bin'
        source.write_bytes(b'synthetic compiler fixture')
        lib = ctypes.WinDLL('kernel32', use_last_error=True)
        from ctypes import wintypes
        lib.SetFileAttributesW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
        lib.SetFileAttributesW.restype = wintypes.BOOL
        original = folder.stat().st_file_attributes
        self.assertTrue(lib.SetFileAttributesW(str(folder), original | 1))
        try:
            result = store.seal(writers_stopped=True)
            self.assertTrue(result['sealed'])
            self.assertFalse(folder.exists())
            self.assertFalse((store.base / 'seal-pending.json').exists())
            self.assertEqual(len(store.verify()['files']), 1)
            store.restore()
            self.assertEqual(source.read_bytes(), b'synthetic compiler fixture')
        finally:
            if folder.exists():
                lib.SetFileAttributesW(str(folder), original)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows directory attributes')
    def test_native_readonly_empty_directory_cleanup(self):
        lib = ctypes.WinDLL('kernel32', use_last_error=True)
        from ctypes import wintypes
        lib.SetFileAttributesW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD)
        lib.SetFileAttributesW.restype = wintypes.BOOL
        original = self.directory.stat().st_file_attributes
        self.assertTrue(lib.SetFileAttributesW(str(self.directory), original | 1))
        try:
            with self.assertRaises(PermissionError):
                self.directory.rmdir()
            migration._remove_empty_legacy_directories(self.root)
            self.assertFalse(self.directory.exists())
            self.assertTrue((self.root / 'Outputs').is_dir())
        finally:
            if self.directory.exists():
                lib.SetFileAttributesW(str(self.directory), original)


if __name__ == '__main__':
    unittest.main()
