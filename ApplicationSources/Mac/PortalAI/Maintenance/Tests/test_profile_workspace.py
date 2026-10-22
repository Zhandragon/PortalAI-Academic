"""Synthetic encrypted-profile recovery tests; never open production user data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
from profile_workspace import ProfileWorkspace
from profile_paths import (private_path, resolve_reference, capture, ProfileLocked,
                           UID_ENV, EPOCH_ENV, workspace_root, enabled)


class FakeSession:
    def __init__(self, uid='a'*32, key=b'k'*32):
        self.user_id = uid
        self.profile_key = key


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.session = FakeSession()
        self.store = ProfileWorkspace(self.root, self.session)
        self.store.workspace.mkdir(parents=True)
        self.env = patch.dict(os.environ, {UID_ENV: '', EPOCH_ENV: ''})
        self.env.start()
        os.environ.pop(UID_ENV); os.environ.pop(EPOCH_ENV)

    def tearDown(self):
        self.env.stop(); self.temp.cleanup()

    def write(self, relative, data=b'private synthetic content'):
        path = self.store.workspace / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_roundtrip_chunked_binary_and_unicode(self):
        content = os.urandom(2*1024*1024+117)
        path = self.write('Outputs/Images/synthetic.bin', content)
        self.write('Data/Chat/Sessions/one.json', json.dumps({'text':'synthetic 東京'}).encode())
        expected = self.store.inventory()
        report = self.store.seal(writers_stopped=True)
        self.assertTrue(report['sealed']); self.assertFalse(path.exists())
        self.assertEqual(expected, [{k:r[k] for k in ('path','bytes','sha256')} for r in self.store.verify()['files']])
        self.assertTrue(self.store.restore()['ready'])
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(self.store.inventory(), expected)

    def test_wrong_key_or_tamper_never_deletes_workspace(self):
        path = self.write('Data/Chat/Sessions/one.json')
        self.store.snapshot()
        bad = ProfileWorkspace(self.root, FakeSession(key=b'x'*32))
        with self.assertRaises(Exception): bad.verify()
        self.assertTrue(path.exists())
        row = self.store.manifest()['files'][0]
        blob = self.store.vault / self.store.manifest()['generation'] / row['blob']
        data = bytearray(blob.read_bytes()); data[-17] ^= 1; blob.write_bytes(data)
        with self.assertRaises(Exception): self.store.verify()
        self.assertTrue(path.exists())

    def test_seal_requires_positive_stop_gate(self):
        path = self.write('Outputs/one.txt')
        with self.assertRaises(RuntimeError): self.store.seal()
        self.assertTrue(path.exists())

    def test_interrupted_seal_preserves_complete_snapshot(self):
        first = self.write('Outputs/a.txt', b'first')
        second = self.write('Outputs/b.txt', b'second')
        original = Path.unlink
        def fail_once(path, *args, **kwargs):
            if path == second: raise OSError('synthetic interrupted seal')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_once):
            with self.assertRaises(OSError): self.store.seal(writers_stopped=True)
        self.assertFalse(first.exists()); self.assertTrue(second.exists())
        generation = self.store.manifest()['generation']
        result = self.store.seal(writers_stopped=True)
        self.assertEqual(result['generation'], generation)
        self.store.restore()
        self.assertEqual(first.read_bytes(), b'first'); self.assertEqual(second.read_bytes(), b'second')

    def test_new_files_block_interrupted_seal_recovery(self):
        self.write('Outputs/a.txt'); self.write('Outputs/b.txt')
        self.store.snapshot()
        state = {'user_id':self.session.user_id,'generation':self.store.manifest()['generation']}
        (self.store.base/'seal-pending.json').write_text(json.dumps(state))
        surprise = self.write('Outputs/new.txt')
        with self.assertRaises(RuntimeError): self.store.seal(writers_stopped=True)
        self.assertTrue(surprise.exists())

    def test_restore_never_overwrites_existing_data(self):
        path = self.write('Outputs/a.txt', b'old')
        self.store.seal(writers_stopped=True)
        self.write('Outputs/a.txt', b'new')
        with self.assertRaises(RuntimeError): self.store.restore()
        self.assertEqual(path.read_bytes(), b'new')

    def test_export_is_explicit_and_does_not_overwrite(self):
        self.write('Outputs/a.txt', b'export data'); self.store.snapshot()
        destination = self.root/'Export/a.txt'
        self.store.export_file('Outputs/a.txt', destination)
        self.assertEqual(destination.read_bytes(), b'export data')
        with self.assertRaises(FileExistsError): self.store.export_file('Outputs/a.txt',destination)
        with self.assertRaises(ValueError): self.store.export_file('../a',self.root/'outside')
        with self.assertRaises(ValueError): self.store.export_file('Outputs/a.txt',self.root/'Private/leak')

    def test_hardlink_refused(self):
        path=self.write('Outputs/a.txt')
        try: os.link(path,self.root/'alias')
        except OSError: self.skipTest('filesystem does not support hardlinks')
        with self.assertRaises(ValueError): self.store.snapshot()

    def test_unchanged_workspace_reuses_verified_snapshot(self):
        self.write('Outputs/private-label/a.txt')
        first=self.store.snapshot()
        again=self.store.snapshot()
        self.assertTrue(again['reused']);self.assertEqual(first['generation'],again['generation'])
        sealed=self.store.seal(writers_stopped=True)
        self.assertEqual(first['generation'],sealed['generation'])
        self.assertFalse((self.store.workspace/'Outputs/private-label').exists())
        self.store.restore()
        self.assertTrue((self.store.workspace/'Outputs/private-label/a.txt').exists())

    def activate(self):
        base=self.root/'Private/Accounts';base.mkdir(parents=True)
        (base/'initialized.json').write_text('{}')
        state={'user_id':self.session.user_id,'epoch':'b'*32,'state':'open'}
        (self.root/'Private/active-session.json').write_text(json.dumps(state))
        os.environ[UID_ENV]=self.session.user_id;os.environ[EPOCH_ENV]='b'*32

    def test_legacy_paths_and_cross_user_rejection(self):
        self.activate()
        expected=self.store.workspace/'Outputs/a.txt'
        self.assertEqual(private_path(self.root,'Outputs/a.txt'),expected)
        self.assertEqual(resolve_reference(self.root,'Outputs/a.txt'),expected)
        self.assertEqual(resolve_reference(self.root,self.root/'Outputs/a.txt'),expected)
        self.assertEqual(resolve_reference(self.root,expected),expected)
        other=workspace_root(self.root,'c'*32)/'Outputs/a.txt'
        with self.assertRaises(ProfileLocked):resolve_reference(self.root,other)
        with self.assertRaises(ValueError):private_path(self.root,'Outputs/../../Agent/hardware_profiles.json')

    def test_locked_and_revoked_paths_fail_closed(self):
        self.activate();context=capture(self.root)
        (self.root/'Private/active-session.json').write_text(json.dumps({'state':'closed'}))
        with self.assertRaises(ProfileLocked):private_path(self.root,'Data/Chat',context=context)
        os.environ.pop(UID_ENV);os.environ.pop(EPOCH_ENV)
        with self.assertRaises(ProfileLocked):private_path(self.root,'Outputs')

    def test_legacy_installation_keeps_original_paths(self):
        legacy = self.root / 'separate-legacy-install'
        legacy.mkdir()
        self.assertIsNone(capture(legacy))
        self.assertEqual(private_path(legacy,'Outputs'),legacy/'Outputs')

    def test_deleted_registry_does_not_unlock_surviving_profiles(self):
        with self.assertRaises(ProfileLocked): private_path(self.root,'Outputs')

    def test_recovery_only_registry_and_reset_evidence_keep_login_gate(self):
        isolated=self.root/'separate-bundle';base=isolated/'Private/Accounts';base.mkdir(parents=True)
        (base/'registry.lock').touch();self.assertFalse(enabled(isolated))
        for name in ('registry-recovery.json','registry-write-pending.json','unknown-state.bin'):
            file=base/name;file.write_bytes(b'evidence')
            self.assertTrue(enabled(isolated))
            with self.assertRaises(ProfileLocked):private_path(isolated,'Outputs')
            file.unlink()
        (isolated/'Private/Reset').mkdir();self.assertTrue(enabled(isolated))

    def test_ads_and_windows_reserved_paths_refused(self):
        self.activate()
        for name in ('Outputs/a:stream','Data/CON.txt','Outputs/name.','Data/trailing '):
            with self.subTest(name=name):
                with self.assertRaises(ValueError): private_path(self.root,name)

    def test_moved_drive_reference_only_same_bundle_name(self):
        self.activate()
        path = 'Z:/previous/' + self.root.name + '/Outputs/old.png'
        self.assertEqual(resolve_reference(self.root,path),self.store.workspace/'Outputs/old.png')
        with self.assertRaises(ProfileLocked):resolve_reference(self.root,'Z:/unrelated/Data/secret.txt')


if __name__=='__main__': unittest.main()
