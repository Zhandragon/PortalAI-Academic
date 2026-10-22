"""Windows path-length portability with real encrypted synthetic workspaces."""
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
from portable_fs import Path, native_path, walk
from profile_paths import _contained, _relative, ProfileLocked
from profile_workspace import ProfileWorkspace
from test_profile_workspace import FakeSession


@unittest.skipUnless(os.name == 'nt', 'Windows extended-path filesystem behavior')
class PortableProfilePathsTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='Portal-path-test-')).resolve()
        self.addCleanup(shutil.rmtree, native_path(self.base))
        self.root = self.base/'short'
        self.root.mkdir()
        self.session = FakeSession()

    def test_canonical_comparisons_and_device_namespace_refusal(self):
        self.assertEqual(self.root, pathlib.Path(str(self.root)))
        self.assertEqual(Path(os.fspath(self.root)).resolve(), self.root)
        self.assertFalse(str(self.root).startswith('\\\\?\\'))
        self.assertEqual(os.fspath(self.root), str(self.root))
        self.assertTrue(native_path(self.root).startswith('\\\\?\\'))
        self.assertEqual(str(Path(r'\\?\UNC\server\share\folder')), r'\\server\share\folder')
        for value in (r'\\?\GLOBALROOT\Device\HarddiskVolume1', r'\\.\PhysicalDrive0'):
            with self.subTest(value=value), self.assertRaises(ValueError): Path(value)

    def test_relocated_long_profile_roundtrip_and_interrupted_lazy_restore(self):
        store = ProfileWorkspace(self.root, self.session)
        relative = 'Data/' + 'x'*60 + '/payload.bin'
        target = store.workspace/relative
        target.parent.mkdir(parents=True); target.write_bytes(b'portable encrypted fixture')
        deferred = store.workspace/'Outputs'/('y'*60)/'saved.bin'
        deferred.parent.mkdir(parents=True); deferred.write_bytes(b'deferred fixture')
        inventory = store.inventory()
        store.seal(writers_stopped=True)
        moved = self.base/('relocated-'+'z'*95)
        self.root.rename(moved)
        store = ProfileWorkspace(moved, self.session)
        target = store.workspace/relative
        self.assertGreater(len(str(target)), 260)
        from profile_lazy_state import publish_no_replace
        with patch('profile_lazy_state.publish_no_replace', side_effect=OSError('synthetic power loss')):
            with self.assertRaises(OSError): store.restore(lazy=True)
        self.assertTrue(store.restore(lazy=True)['ready'])
        self.assertEqual(target.read_bytes(), b'portable encrypted fixture')
        self.assertTrue(store.restore()['ready'])
        self.assertEqual(store.inventory(), inventory)
        self.assertTrue(all(not folder.startswith('\\\\?\\') for folder, _, _ in walk(store.workspace)))
        self.assertTrue(store.seal(writers_stopped=True)['sealed'])
        self.assertEqual(store.inventory(), [])
        self.assertTrue(store.restore()['ready'])
        self.assertEqual(store.inventory(), inventory)

    def test_containment_and_invalid_windows_names_remain_rejected(self):
        with self.assertRaises(ProfileLocked): _contained(self.root, self.base/'outside')
        with self.assertRaises(ProfileLocked): _contained(self.root, self.root/'..'/'outside')
        for value in ('Data/../outside', 'Data/name.', 'Data/name ', 'Data/NUL', 'Data/x:stream'):
            with self.subTest(value=value), self.assertRaises(ValueError): _relative(value)


if __name__ == '__main__': unittest.main()
