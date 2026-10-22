"""Public Windows runtime wheelhouse scope; no installation or account access."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from repair_public_runtimes import reviewed_wheel_path, PUBLIC_WHEELHOUSES


class PublicRepairPackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='portalai-public-wheel-path-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()

    def test_each_exact_windows_public_layer_is_accepted(self):
        for layer, directory in PUBLIC_WHEELHOUSES.items():
            with self.subTest(layer=layer):
                self.assertEqual(reviewed_wheel_path(self.root,layer,directory+'/fixture.whl'),
                                 self.root/directory/'fixture.whl')

    def test_cross_layer_and_nested_wheelhouses_are_rejected(self):
        for layer, directory in PUBLIC_WHEELHOUSES.items():
            for other, wrong in PUBLIC_WHEELHOUSES.items():
                if other!=layer:
                    with self.subTest(layer=layer,other=other), self.assertRaises(ValueError):
                        reviewed_wheel_path(self.root,layer,wrong+'/fixture.whl')
            with self.assertRaises(ValueError):
                reviewed_wheel_path(self.root,layer,directory+'/sub/fixture.whl')

    def test_legacy_cache_receipts_are_unchanged(self):
        for layer in (*PUBLIC_WHEELHOUSES,'linux-accounts'):
            relative='Cache/retained-wheelhouse/fixture.whl'
            self.assertEqual(reviewed_wheel_path(self.root,layer,relative),self.root/relative)

    def test_unreviewed_runtime_private_and_traversal_paths_fail(self):
        for relative in ('Runtime/Other/fixture.whl','Private/fixture.whl',
                         '../outside.whl','Runtime/AMDPython/wheelhouse/../fixture.whl',
                         'Runtime/AMDPython/wheelhouse/fixture.zip'):
            with self.subTest(path=relative), self.assertRaises(ValueError):
                reviewed_wheel_path(self.root,'amd-runtime',relative)

    def test_windows_paths_do_not_expand_linux_or_unknown_scope(self):
        for name in ('linux-accounts','missing'):
            with self.assertRaises(ValueError):
                reviewed_wheel_path(self.root,name,'Runtime/AMDPython/wheelhouse/fixture.whl')


if __name__=='__main__':unittest.main()
