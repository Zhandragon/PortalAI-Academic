"""Incremental ciphertext and partial-workspace crash tests; synthetic roots only."""
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
import profile_lazy_state as lazy_state
import profile_workspace as core
from profile_workspace import ProfileWorkspace
from test_profile_workspace import FakeSession


class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = ProfileWorkspace(self.root, FakeSession())
        self.files = {'Data/Chat/one.json': b'operational', 'Outputs/a.bin': b'first',
                      'Outputs/tree/b.bin': b'second', 'User Folder/project/c.txt': b'project',
                      'Data/LegacyRecovery/old.zip': b'archive', 'Data/SessionRecovery/r.txt': b'recovery'}
        for name, data in self.files.items(): self.write(name, data)

    def write(self, relative, data):
        path = self.store.workspace/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def rewrite(self, manifest):
        _, _, _, AESGCM = core._crypto()
        nonce = secrets.token_bytes(12)
        data = json.dumps(manifest).encode()
        core._atomic_bytes(self.store.vault/manifest['generation']/'manifest.enc',
            nonce+AESGCM(self.store._key()).encrypt(nonce,data,self.store._aad('manifest')))

    def seal_lazy(self):
        self.store.seal(writers_stopped=True)
        return self.store.restore(lazy=True)

    def test_changed_only_encrypts_and_refs_are_immutable_without_hardlinks(self):
        first = self.store.snapshot()
        old = self.store.manifest()
        old_bytes = {row['path']: self.store.blob_path(old,row).read_bytes() for row in old['files']}
        self.write('Outputs/a.bin', b'changed')
        self.write('Outputs/new.bin', b'new')
        (self.store.workspace/'Outputs/tree/b.bin').unlink()
        with patch.object(self.store,'_encrypt_file',wraps=self.store._encrypt_file) as encrypt:
            second = self.store.snapshot()
        self.assertEqual(encrypt.call_count,2)
        self.assertEqual((second['encrypted_files'],second['reused_files']),(2,4))
        manifest = self.store.verify()
        self.assertEqual(manifest['version'],2)
        for row in manifest['files']:
            blob = self.store.blob_path(manifest,row)
            self.assertEqual(blob.stat().st_nlink,1)
            if row['path'] not in ('Outputs/a.bin','Outputs/new.bin'):
                self.assertEqual(row['blob_generation'],first['generation'])
                self.assertEqual(blob.read_bytes(),old_bytes[row['path']])
        self.assertNotIn('Outputs/tree/b.bin',{row['path'] for row in manifest['files']})
        self.assertTrue((self.store.vault/first['generation']).is_dir())

    def test_v1_read_verify_export_and_incremental_conversion(self):
        first = self.store.snapshot(); manifest = self.store.manifest()
        manifest['version']=1
        for row in manifest['files']: row.pop('blob_generation')
        self.rewrite(manifest)
        self.assertEqual(self.store.verify()['version'],1)
        self.store.export_file('Outputs/a.bin',self.root/'export.bin')
        self.assertEqual((self.root/'export.bin').read_bytes(),b'first')
        self.store.seal(writers_stopped=True)
        self.store.restore(lazy=True)
        self.store.materialize('Outputs/a.bin')
        self.write('Outputs/a.bin',b'new first')
        result=self.store.snapshot()
        self.assertEqual(result['encrypted_files'],1)
        rows={row['path']:row for row in self.store.verify()['files']}
        self.assertEqual(rows['Outputs/tree/b.bin']['blob_generation'],first['generation'])

    def test_repeated_snapshots_flatten_blob_generation_references(self):
        first=self.store.snapshot()
        self.write('Outputs/a.bin',b'changed one');self.store.snapshot()
        self.write('Outputs/a.bin',b'changed two');self.store.snapshot()
        row=next(row for row in self.store.verify()['files'] if row['path']=='Outputs/tree/b.bin')
        self.assertEqual(row['blob_generation'],first['generation'])
        self.assertEqual(len([p for p in self.store.vault.iterdir() if p.is_dir()]),3)

    def test_reused_corruption_blocks_pointer_and_plaintext_deletion(self):
        self.store.snapshot(); manifest=self.store.manifest()
        pointer=(self.store.vault/'current.enc').read_bytes()
        row=next(row for row in manifest['files'] if row['path']=='Outputs/tree/b.bin')
        blob=self.store.blob_path(manifest,row)
        data=bytearray(blob.read_bytes());data[-1]^=1;blob.write_bytes(data)
        self.write('Outputs/a.bin',b'new')
        with self.assertRaises(Exception):self.store.seal(writers_stopped=True)
        self.assertEqual((self.store.vault/'current.enc').read_bytes(),pointer)
        self.assertEqual((self.store.workspace/'Outputs/a.bin').read_bytes(),b'new')
        self.assertFalse((self.store.base/'seal-pending.json').exists())

    def test_invalid_blob_generation_and_foreign_identity_rejected(self):
        self.store.snapshot(); original=self.store.manifest()
        for value in (None,'../outside','A'*32,'f'*31):
            manifest=json.loads(json.dumps(original));manifest['files'][0]['blob_generation']=value
            self.rewrite(manifest)
            with self.assertRaises(ValueError):self.store.manifest()
        self.rewrite(original)
        foreign={**original,'user_id':'c'*32}
        with self.assertRaises(ValueError):self.store.blob_path(foreign,original['files'][0])

    def test_space_admission_counts_only_changed_ciphertext_and_manifest(self):
        self.store.snapshot()
        self.write('Outputs/a.bin',b'new')
        config=self.root/'Agent/hardware_profiles.json';config.parent.mkdir();config.write_text('{}')
        with patch.object(core,'require_space') as reserve:self.store.snapshot()
        self.assertEqual(reserve.call_args.args[1],3+1024**2)

    def test_lazy_policy_encrypts_ledger_and_restores_only_operational_data(self):
        result=self.seal_lazy()
        self.assertEqual(result['pending_files'],5)
        self.assertEqual([row['path'] for row in self.store.inventory()],['Data/Chat/one.json'])
        ledger=(self.store.base/'hydration.enc').read_bytes()
        for value in ('Outputs','LegacyRecovery','SessionRecovery','project'):
            self.assertNotIn(value.encode(),ledger)
        self.assertEqual(set(self.store.pending()['paths']),set(self.files)-{'Data/Chat/one.json'})
        self.assertTrue(lazy_state.is_deferred_path('outputs/a.bin'))
        self.assertFalse(lazy_state.is_deferred_path('Data/Chat/one.json'))

    def test_exact_subtree_all_and_deleted_materialized_file_stays_deleted(self):
        self.seal_lazy()
        self.assertEqual(self.store.materialize('Outputs/tree')['materialized'],0)
        self.assertEqual(self.store.materialize('Outputs/tree',recursive=True)['materialized'],1)
        self.assertEqual(self.store.materialize('Outputs/a.bin')['materialized'],1)
        (self.store.workspace/'Outputs/a.bin').unlink()
        self.assertEqual(self.store.materialize('Outputs/a.bin')['materialized'],0)
        self.assertEqual(self.store.materialize()['materialized'],3)
        self.assertEqual(self.store.pending()['files'],0)
        self.assertFalse((self.store.workspace/'Outputs/a.bin').exists())

    @unittest.skipUnless(os.name=='nt','Windows filename matching')
    def test_windows_reference_case_uses_canonical_manifest_name(self):
        self.seal_lazy()
        self.assertEqual(self.store.materialize('outputs/A.BIN')['materialized'],1)
        self.assertEqual((self.store.workspace/'Outputs/a.bin').read_bytes(),b'first')

    def test_partial_snapshot_seal_retains_deferred_and_hydrated_deletion(self):
        self.seal_lazy(); baseline=self.store.pending()['generation']
        self.store.materialize('Outputs/a.bin')
        (self.store.workspace/'Outputs/a.bin').unlink()
        self.write('Data/Chat/one.json',b'edited');self.write('Outputs/new.bin',b'new')
        result=self.store.snapshot()
        self.assertEqual(result['encrypted_files'],2)
        self.assertEqual(self.store.pending()['generation'],baseline)
        self.write('Data/Chat/one.json',b'edited again')
        self.store.seal(writers_stopped=True)
        self.assertFalse((self.store.base/'hydration.enc').exists())
        self.store.restore()
        self.assertFalse((self.store.workspace/'Outputs/a.bin').exists())
        self.assertEqual((self.store.workspace/'Outputs/tree/b.bin').read_bytes(),b'second')
        self.assertEqual((self.store.workspace/'Data/Chat/one.json').read_bytes(),b'edited again')

    def test_explicit_new_pending_name_refuses_overwrite_then_snapshot_adopts(self):
        self.seal_lazy(); path=self.write('Outputs/a.bin',b'replacement')
        with self.assertRaises(FileExistsError):self.store.materialize('Outputs/a.bin')
        self.store.snapshot()
        self.assertNotIn('Outputs/a.bin',self.store.pending()['paths'])
        path.unlink();self.store.seal(writers_stopped=True);self.store.restore()
        self.assertFalse(path.exists())

    def test_cancel_before_publish_preserves_intent_and_pending(self):
        self.seal_lazy(); calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls==3:raise RuntimeError('synthetic cancellation')
        with self.assertRaisesRegex(RuntimeError,'cancellation'):
            self.store.materialize('Outputs/a.bin',check=check)
        self.assertIsNotNone(self.store._hydration().inflight)
        self.assertFalse((self.store.workspace/'Outputs/a.bin').exists())
        self.assertEqual(self.store.materialize('Outputs/a.bin')['materialized'],1)
        self.assertFalse(list(self.store.workspace.rglob('*.part')))

    def test_cancel_after_publish_recovery_proves_bytes_and_does_not_rewrite(self):
        self.seal_lazy(); calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls==4:raise RuntimeError('synthetic cancellation')
        with self.assertRaises(RuntimeError):self.store.materialize('Outputs/a.bin',check=check)
        target=self.store.workspace/'Outputs/a.bin';self.assertEqual(target.read_bytes(),b'first')
        stamp=target.stat().st_mtime_ns
        self.assertEqual(self.store.materialize('Outputs/a.bin')['materialized'],0)
        self.assertEqual(target.stat().st_mtime_ns,stamp)

    def test_changed_published_inflight_file_blocks_recovery_and_seal(self):
        self.seal_lazy();calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls==4:raise RuntimeError('cancel')
        with self.assertRaises(RuntimeError):self.store.materialize('Outputs/a.bin',check=check)
        target=self.write('Outputs/a.bin',b'changed after publication')
        with self.assertRaisesRegex(ValueError,'changed before recovery'):
            self.store.seal(writers_stopped=True)
        self.assertEqual(target.read_bytes(),b'changed after publication')

    def test_interrupted_decryption_removes_only_proven_temp_and_retries(self):
        self.seal_lazy(); original=self.store._decrypt_file
        def decrypt(source,relative,key,target=None,**kwargs):
            result=original(source,relative,key,target,**kwargs)
            if relative=='Outputs/a.bin':raise OSError('synthetic interruption')
            return result
        with patch.object(self.store,'_decrypt_file',side_effect=decrypt):
            with self.assertRaises(OSError):self.store.materialize('Outputs/a.bin')
        state=self.store._hydration();temp=self.store.workspace/state.inflight['temporary']
        self.assertEqual(temp.read_bytes(),b'first')
        self.store.materialize('Outputs/a.bin')
        self.assertFalse(temp.exists())

    def test_altered_temporary_identity_refuses_cleanup(self):
        self.seal_lazy();calls=0
        def check():
            nonlocal calls
            calls+=1
            if calls==3:raise RuntimeError('cancel')
        with self.assertRaises(RuntimeError):self.store.materialize('Outputs/a.bin',check=check)
        state=self.store._hydration();temp=self.store.workspace/state.inflight['temporary']
        state.inflight['identity'][1]+=1;state.save()
        with self.assertRaisesRegex(ValueError,'identity changed'):self.store.materialize('Outputs/a.bin')
        self.assertTrue(temp.exists())

    def test_lazy_initial_final_inventory_cannot_be_mutated_into_ready(self):
        self.store.seal(writers_stopped=True)
        original=lazy_state.HydrationState.materialize
        def materialize(state,*args,**kwargs):
            result=original(state,*args,**kwargs)
            (self.store.workspace/'Data/Chat/one.json').write_bytes(b'mutated')
            return result
        with patch.object(lazy_state.HydrationState,'materialize',materialize):
            with self.assertRaisesRegex(RuntimeError,'final verification'):self.store.restore(lazy=True)
        self.assertFalse(self.store._hydration().ready)
        with self.assertRaisesRegex(RuntimeError,'final verification'):self.store.seal(writers_stopped=True)

    def test_lazy_initial_resume_verifies_existing_ciphertext_and_missing_published(self):
        self.store.seal(writers_stopped=True)
        original=lazy_state.HydrationState.verify_initial_inventory
        with patch.object(lazy_state.HydrationState,'verify_initial_inventory',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):self.store.restore(lazy=True)
        self.assertFalse(self.store._hydration().ready)
        path=self.store.workspace/'Data/Chat/one.json';path.unlink()
        with self.assertRaisesRegex(RuntimeError,'final verification'):self.store.restore(lazy=True)
        self.write('Data/Chat/one.json',b'operational')
        manifest=self.store.manifest();row=next(r for r in manifest['files'] if r['path']=='Data/Chat/one.json')
        blob=self.store.blob_path(manifest,row);value=bytearray(blob.read_bytes());value[-1]^=1;blob.write_bytes(value)
        with self.assertRaises(Exception):self.store.restore(lazy=True)
        self.assertFalse(self.store._hydration().ready)

    def test_partial_initial_failure_can_seal_without_hydrating_deferred(self):
        self.store.seal(writers_stopped=True)
        with patch.object(self.store,'_decrypt_file',side_effect=OSError('before publication')):
            with self.assertRaises(OSError):self.store.restore(lazy=True)
        with patch.object(self.store,'_encrypt_file',wraps=self.store._encrypt_file) as encrypt:
            result=self.store.seal(writers_stopped=True)
        self.assertEqual(encrypt.call_count,0)
        self.assertTrue(result['sealed']);self.assertEqual(len(self.store.verify()['files']),6)

    def test_seal_ledger_removed_before_journal_and_resume_preserves_snapshot(self):
        self.seal_lazy(); journal=self.store.base/'seal-pending.json'; original=Path.unlink
        def unlink(path,*args,**kwargs):
            if path==journal:raise OSError('after ledger removal')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',unlink):
            with self.assertRaises(OSError):self.store.seal(writers_stopped=True)
        self.assertFalse((self.store.base/'hydration.enc').exists());self.assertTrue(journal.exists())
        with self.assertRaisesRegex(RuntimeError,'Interrupted sealing'):self.store.snapshot()
        with self.assertRaisesRegex(RuntimeError,'Interrupted sealing'):self.store.materialize()
        self.store.seal(writers_stopped=True);self.store.restore()
        self.assertEqual({r['path'] for r in self.store.inventory()},set(self.files))

    def test_tampered_ledger_refused_and_no_plaintext_removed(self):
        self.seal_lazy();ledger=self.store.base/'hydration.enc'
        value=bytearray(ledger.read_bytes());value[-1]^=1;ledger.write_bytes(value)
        with self.assertRaises(Exception):self.store.seal(writers_stopped=True)
        self.assertTrue((self.store.workspace/'Data/Chat/one.json').exists())

    def test_late_writer_not_overwritten_by_exclusive_publication(self):
        self.seal_lazy();original=lazy_state.publish_no_replace
        def publish(source,destination):
            destination.write_bytes(b'late writer')
            return original(source,destination)
        with patch.object(lazy_state,'publish_no_replace',side_effect=publish):
            with self.assertRaises(FileExistsError):self.store.materialize('Outputs/a.bin')
        self.assertEqual((self.store.workspace/'Outputs/a.bin').read_bytes(),b'late writer')

    def test_manifest_metadata_does_not_stat_unrelated_blob_but_access_rechecks(self):
        self.store.snapshot()
        with patch.object(self.store,'blob_path',side_effect=AssertionError('metadata touched blob')):
            self.store.manifest()
        with patch.object(self.store,'blob_path',side_effect=ValueError('linked blob')):
            with self.assertRaisesRegex(ValueError,'linked blob'):self.store.verify()


class ExclusivePublicationTests(unittest.TestCase):
    def test_posix_renameat2_uses_no_replace_and_reports_existing(self):
        class Rename:
            def __call__(self,*args):
                self.args=args
                return -1
        rename=Rename()
        fake_os=types.SimpleNamespace(name='posix',fsencode=os.fsencode,strerror=os.strerror)
        with patch.object(lazy_state,'os',fake_os), patch.object(lazy_state.ctypes,'CDLL',return_value=types.SimpleNamespace(renameat2=rename)), patch.object(lazy_state.ctypes,'get_errno',return_value=17):
            with self.assertRaises(FileExistsError):lazy_state.publish_no_replace('source','destination')
        self.assertEqual(rename.args,(-100,b'source',-100,b'destination',1))

    def test_posix_without_exclusive_primitive_fails_closed(self):
        fake_os=types.SimpleNamespace(name='posix')
        with patch.object(lazy_state,'os',fake_os),patch.object(lazy_state.ctypes,'CDLL',return_value=object()):
            with self.assertRaisesRegex(RuntimeError,'renameat2'):lazy_state.publish_no_replace('a','b')


if __name__=='__main__':unittest.main()
