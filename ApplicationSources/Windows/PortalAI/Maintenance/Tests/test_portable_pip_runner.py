"""The shim changes only installed RECORD path spelling, then restores pip."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Tools'))
from portable_pip_runner import normalized_record_paths


class PipRecordPathTests(unittest.TestCase):
    def fixture(self):
        def original(record_path, lib_dir):
            return os.path.join(lib_dir, record_path)
        return SimpleNamespace(_record_to_fs_path=original), original

    @unittest.skipUnless(os.name == 'nt', 'Windows extended path test')
    def test_relocated_script_and_nested_library_paths(self):
        wheel, original = self.fixture()
        lib = '\\\\?\\C:\\synthetic\\pip-target\\lib\\python'
        with normalized_record_paths(wheel, '26.2.1', windows=True):
            self.assertEqual(wheel._record_to_fs_path('../../bin/numba', lib),
                             '\\\\?\\C:\\synthetic\\pip-target\\bin\\numba')
            self.assertEqual(wheel._record_to_fs_path('package/deep/file.py', lib),
                             lib+'\\package\\deep\\file.py')
        self.assertIs(wheel._record_to_fs_path, original)

    def test_restores_on_failure(self):
        wheel, original = self.fixture()
        with self.assertRaisesRegex(ValueError, 'fixture'):
            with normalized_record_paths(wheel, '26.2.1', windows=True):
                raise ValueError('fixture')
        self.assertIs(wheel._record_to_fs_path, original)

    def test_unreviewed_pip_fails_before_mutation(self):
        wheel, original = self.fixture()
        with self.assertRaisesRegex(RuntimeError, 'reviewed bundled pip'):
            with normalized_record_paths(wheel, '999', windows=True):
                self.fail('must not enter')
        self.assertIs(wheel._record_to_fs_path, original)

    def test_changed_helper_signature_fails_closed(self):
        wheel = SimpleNamespace(_record_to_fs_path=lambda path: path)
        with self.assertRaisesRegex(RuntimeError, 'helper has changed'):
            with normalized_record_paths(wheel, '26.2.1', windows=True):
                self.fail('must not enter')

    def test_non_windows_is_unmodified(self):
        wheel, original = self.fixture()
        with normalized_record_paths(wheel, 'any', windows=False):
            self.assertIs(wheel._record_to_fs_path, original)


if __name__ == '__main__':
    unittest.main()
