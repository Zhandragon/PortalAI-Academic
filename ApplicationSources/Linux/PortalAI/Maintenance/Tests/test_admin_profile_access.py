"""Administrator profile inspection/export: real crypto, temporary roots only."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import local_accounts as accounts
import admin_profile_access as access
from profile_workspace import ProfileWorkspace

PASSWORD = 'synthetic profile access password'


class AdminProfileAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='Portal admin export ')
        self.root = Path(self.tmp.name)
        self.kdf = patch.object(accounts,'_KDF_N',1024); self.kdf.start()
        self.store = accounts.LocalAccounts(self.root)
        self.admin = self.store.bootstrap('Owner',PASSWORD)
        self.row = self.store.create_user(self.admin,'Member',PASSWORD,admin_password=PASSWORD)
        self.user = self.store.login('Member',PASSWORD)
        self.workspace = ProfileWorkspace(self.root,self.user)
        self.files = {'Data/Chat/Sessions/one.json':b'{"content":"synthetic chat"}',
                      'Outputs/result.txt':b'synthetic result', 'Data/Missions/checkpoint.json':b'{}'}
        for relative,data in self.files.items():
            path = self.workspace.workspace/relative; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(data)
        self.workspace.seal(writers_stopped=True)
        self.destination = self.root/'member-export.zip'

    def tearDown(self):
        self.store.logout(); self.kdf.stop(); self.tmp.cleanup()

    def test_inspect_and_preview_use_sealed_data_without_activating_target_workspace(self):
        result = access.inspect_profile(self.store,self.admin,self.user.user_id)
        self.assertTrue(result['verified_manifest']); self.assertEqual(result['username'],'Member')
        self.assertEqual({row['path'] for row in result['files']},set(self.files))
        preview = access.preview_text(self.store,self.admin,self.user.user_id,'Outputs/result.txt')
        self.assertTrue(preview['verified']); self.assertEqual(preview['text'],'synthetic result')
        self.assertEqual(self.workspace.inventory(),[])
        self.assertFalse((self.root/'Private/active-session.json').exists())

    def test_exports_selected_and_all_rows_with_verified_plaintext_receipt(self):
        for kind,wanted in (('history',{'Data/Chat/Sessions/one.json'}),('outputs',{'Outputs/result.txt'}),('all',set(self.files))):
            path = self.root/(kind+'.zip')
            result = access.export_profile(self.store,self.admin,self.user.user_id,kind,path)
            self.assertTrue(result['verified']); self.assertTrue(result['plaintext'])
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(set(archive.namelist()),wanted|{'PortalAI-export-manifest.json'})
                for name in wanted:self.assertEqual(archive.read(name),self.files[name])
        self.assertEqual(self.workspace.inventory(),[])

    def test_standard_guest_forged_and_revoked_sessions_never_authorize_export(self):
        for actor in (self.user,self.store.login_guest(),{'role':'admin'}):
            with self.assertRaises(PermissionError):
                access.export_profile(self.store,actor,self.user.user_id,'all',self.destination)
        self.store.logout(self.admin)
        with self.assertRaises(PermissionError):access.inspect_profile(self.store,self.admin,self.user.user_id)
        self.assertFalse(self.destination.exists())

    def test_outputs_include_other_members_benchmarks_and_video_projects_only(self):
        self.workspace.restore()
        additions = {'Benchmarks/render/result.png': b'synthetic benchmark image',
                     'Patch/Videos/Clipchamp/project.clipchamp': b'synthetic member video project',
                     'Patch/Videos/Clipchamp/input.wav': b'synthetic project audio',
                     'Logs/private.txt': b'private log is not an output',
                     'Cache/Web/page.json': b'private cached page is not an output',
                     'Data/Memory/private.json': b'private memory is not an output'}
        for relative, data in additions.items():
            path = self.workspace.workspace/relative
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
        self.workspace.seal(writers_stopped=True)
        with self.assertRaises(PermissionError):
            access.export_profile(self.store,self.user,self.user.user_id,'outputs',self.destination)
        self.assertFalse(self.destination.exists())
        result = access.export_profile(self.store,self.admin,self.user.user_id,'outputs',self.destination)
        wanted = {'Outputs/result.txt', 'Benchmarks/render/result.png',
                  'Patch/Videos/Clipchamp/project.clipchamp', 'Patch/Videos/Clipchamp/input.wav'}
        self.assertTrue(result['verified']); self.assertEqual(result['user_id'],self.user.user_id)
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(set(archive.namelist()),wanted|{'PortalAI-export-manifest.json'})
            for name in wanted:self.assertEqual(archive.read(name),{**self.files,**additions}[name])
        self.assertEqual(self.workspace.inventory(),[])

    def test_live_or_interrupted_profile_is_not_exported_from_stale_snapshot(self):
        self.workspace.restore()
        with self.assertRaises(RuntimeError):access.inspect_profile(self.store,self.admin,self.user.user_id)
        with self.assertRaises(RuntimeError):access.export_profile(self.store,self.admin,self.user.user_id,'all',self.destination)
        self.assertTrue((self.workspace.workspace/'Outputs/result.txt').exists())

    def test_orphaned_restore_intent_is_not_treated_as_a_sealed_profile(self):
        (self.workspace.base/'restore-inflight.enc').write_bytes(b'synthetic interrupted intent')
        with self.assertRaisesRegex(RuntimeError, 'Recover and seal'):
            access.inspect_profile(self.store,self.admin,self.user.user_id)

    def test_empty_but_lazy_active_workspace_is_not_a_sealed_snapshot(self):
        self.workspace.restore()
        for relative in ('Data/Chat/Sessions/one.json', 'Data/Missions/checkpoint.json'):
            (self.workspace.workspace/relative).unlink()
        self.workspace.seal(writers_stopped=True)
        self.workspace.restore(lazy=True)
        self.assertEqual(self.workspace.inventory(), [])
        self.assertTrue((self.workspace.base/'hydration.enc').exists())
        with self.assertRaisesRegex(RuntimeError, 'Recover and seal'):
            access.inspect_profile(self.store,self.admin,self.user.user_id)
        with self.assertRaisesRegex(RuntimeError, 'Recover and seal'):
            access.preview_text(self.store,self.admin,self.user.user_id,'Outputs/result.txt')
        with self.assertRaisesRegex(RuntimeError, 'Recover and seal'):
            access.export_profile(self.store,self.admin,self.user.user_id,'outputs',self.destination)
        self.assertFalse(self.destination.exists())
        self.workspace.seal(writers_stopped=True)
        result=access.export_profile(self.store,self.admin,self.user.user_id,'outputs',self.destination)
        self.assertTrue(result['verified'])
        with zipfile.ZipFile(self.destination) as archive:
            self.assertEqual(archive.read('Outputs/result.txt'),self.files['Outputs/result.txt'])

    def test_preview_size_and_unknown_relative_are_bounded(self):
        with self.assertRaises(ValueError):access.preview_text(self.store,self.admin,self.user.user_id,'Outputs/result.txt',max_bytes=3)
        with self.assertRaises(FileNotFoundError):access.preview_text(self.store,self.admin,self.user.user_id,'../../Agent/tool.py')
        with self.assertRaises(ValueError):access.preview_text(self.store,self.admin,self.user.user_id,'Outputs/result.txt',max_bytes=2**30)

    def test_corrupted_ciphertext_cannot_produce_preview_or_retained_export(self):
        manifest = self.workspace.manifest()
        row = next(row for row in manifest['files'] if row['path']=='Outputs/result.txt')
        blob = self.workspace.vault/manifest['generation']/row['blob']
        raw = bytearray(blob.read_bytes()); raw[-17] ^= 1; blob.write_bytes(raw)
        with self.assertRaises(Exception):access.preview_text(self.store,self.admin,self.user.user_id,row['path'])
        with self.assertRaises(Exception):access.export_profile(self.store,self.admin,self.user.user_id,'outputs',self.destination)
        self.assertFalse(self.destination.exists())

    def test_export_never_overwrites_or_writes_under_private_storage(self):
        self.destination.write_bytes(b'keep existing file')
        with self.assertRaises(ValueError):access.export_profile(self.store,self.admin,self.user.user_id,'all',self.destination)
        self.assertEqual(self.destination.read_bytes(),b'keep existing file')
        with self.assertRaises(ValueError):access.export_profile(self.store,self.admin,self.user.user_id,'all',self.root/'Private/export.zip')

    def test_admin_revocation_during_export_removes_own_partial_result(self):
        original = access._stream_file
        def revoke(*args):
            self.store.logout(self.admin)
            return original(*args)
        with patch.object(access,'_stream_file',side_effect=revoke):
            with self.assertRaises(PermissionError):access.export_profile(self.store,self.admin,self.user.user_id,'all',self.destination)
        self.assertFalse(self.destination.exists())


if __name__ == '__main__': unittest.main()
