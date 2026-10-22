"""Path representation only; these tests never visit the named network paths."""
import os
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
from portable_pip_paths import pip_path


class PortablePipPathTests(unittest.TestCase):
    def test_relative_path_is_refused(self):
        with self.assertRaises(ValueError):pip_path('unreviewed/relative')

    @unittest.skipUnless(os.name=='nt','Windows path spelling')
    def test_local_absolute_path_is_extended_without_changing_destination(self):
        value=pip_path(Path('C:/synthetic/stage'))
        self.assertEqual(value,'\\\\?\\C:\\synthetic\\stage')

    @unittest.skipUnless(os.name=='nt','Windows path spelling')
    def test_unc_absolute_path_keeps_its_same_share(self):
        self.assertEqual(pip_path(Path('\\\\synthetic-server\\share\\stage')),
                         '\\\\?\\UNC\\synthetic-server\\share\\stage')

    @unittest.skipUnless(os.name=='nt','Windows path spelling')
    def test_already_extended_path_is_idempotent(self):
        value='\\\\?\\C:\\synthetic\\stage'
        self.assertEqual(pip_path(Path(value)),value)


if __name__=='__main__':unittest.main()
