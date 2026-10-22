"""Linux import diagnostics must use the same repaired native layer precedence."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent')]
import dependency_check


class Layers(unittest.TestCase):
    def test_linux_checks_put_compat_before_older_media_native_module(self):
        with patch.object(dependency_check,'os',SimpleNamespace(name='posix')):
            checks=dependency_check.platform_checks()
        media=next(row for row in checks if row[0]=='Linux media CPU import check')
        self.assertEqual(media[1],'Runtime/LinuxPython/run-python')
        self.assertLess(media[2].index('Runtime/LinuxPackages/kornia_compat'),media[2].index('Runtime/LinuxPackages/media'))
        self.assertIn('kornia_rs',media[3])
        for row in checks:
            self.assertFalse(any('Windows' in path or '.exe' in path for path in (row[1],*row[2])))

    def test_windows_check_inventory_is_unchanged(self):
        with patch.object(dependency_check,'os',SimpleNamespace(name='nt')):
            self.assertIs(dependency_check.platform_checks(),dependency_check.CHECKS)


if __name__=='__main__':unittest.main()
