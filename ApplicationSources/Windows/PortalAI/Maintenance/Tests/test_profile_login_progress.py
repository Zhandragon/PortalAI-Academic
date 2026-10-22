"""Authenticated restore progress and fresh/resumed integrity, synthetic roots only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
from profile_workspace import ProfileWorkspace
from profile_runtime import ProfileRuntime
from profile_paths import capture, ProfileLocked
from test_profile_runtime import AccountsFixture, OWNER


class LoginProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.backend=AccountsFixture();self.session=self.backend.login(OWNER)
        self.store=ProfileWorkspace(self.root,self.session)
        self.env=patch.dict(os.environ,{},clear=False);self.env.start();self.addCleanup(self.env.stop)
        os.environ.pop('PORTALAI_PROFILE_ID',None);os.environ.pop('PORTALAI_PROFILE_EPOCH',None)
        self.runtimes=[];self.addCleanup(self.release_test_locks)
        for name,data in (('a',b'first'),('b',b'second'),('c',b'last')):
            path=self.store.workspace/'Outputs'/f'{name}.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.store.seal(writers_stopped=True)

    def release_test_locks(self):
        for runtime in self.runtimes:
            if runtime._process_lock is not None:
                runtime._process_lock.__exit__(None,None,None)
                runtime._process_lock=None

    def runtime(self,progress=None):
        runtime=ProfileRuntime(self.root,self.backend,quiesce=Mock(return_value={'stopped':True}),on_progress=progress)
        self.runtimes.append(runtime)
        return runtime

    def corrupt(self,row):
        manifest=self.store.manifest()
        blob=self.store.vault/manifest['generation']/row['blob']
        original=blob.read_bytes();altered=bytearray(original);altered[-1]^=1;blob.write_bytes(altered)
        return blob,original

    def interrupt_after_first(self):
        original=self.store._decrypt_file
        def decrypt(source,relative,key,target=None,**kwargs):
            if relative=='Outputs/b.txt':raise OSError('synthetic interruption')
            return original(source,relative,key,target,**kwargs)
        with patch.object(self.store,'_decrypt_file',side_effect=decrypt):
            with self.assertRaisesRegex(OSError,'synthetic interruption'):self.store.restore()
        self.assertTrue((self.store.base/'restore-pending.json').is_file())
        self.assertEqual((self.store.workspace/'Outputs/a.txt').read_bytes(),b'first')

    def test_fresh_restore_decrypts_once_and_reports_only_safe_aggregate_progress(self):
        events=[];self.store.on_progress=events.append
        with patch.object(self.store,'verify',wraps=self.store.verify) as verify, \
             patch.object(self.store,'_decrypt_file',wraps=self.store._decrypt_file) as decrypt:
            self.assertTrue(self.store.restore()['ready'])
        verify.assert_not_called();self.assertEqual(decrypt.call_count,3)
        self.assertTrue(all(call.args[3] is not None for call in decrypt.call_args_list))
        self.assertTrue(any(e['stage']=='restore' and e.get('completed')==3 for e in events))
        self.assertEqual(events[-1]['stage'],'restore-final')
        for event in events:
            self.assertLessEqual(set(event),{'stage','message','completed','total'})
            text=json.dumps(event);self.assertNotIn('Outputs/',text);self.assertNotIn(self.session.user_id,text)
        self.assertEqual(len(self.store.inventory()),3)

    def test_late_corrupt_blob_retains_opening_identity_key_and_journal_without_login(self):
        self.corrupt(self.store.manifest()['files'][-1])
        events=[];runtime=self.runtime(events.append)
        with self.assertRaises(Exception):runtime.prepare(self.session)
        self.assertTrue(self.session.active);self.assertTrue(runtime.retains_session(self.session))
        self.assertIsNotNone(runtime._process_lock)
        self.assertEqual(json.loads(runtime.marker.read_text())['state'],'opening')
        self.assertTrue((self.store.workspace/'Outputs/a.txt').is_file())
        self.assertFalse((self.store.workspace/'Outputs/c.txt').exists())
        self.assertFalse(list(self.store.workspace.rglob('*.part')))
        self.assertTrue((self.store.base/'restore-pending.json').is_file())
        self.assertNotIn('ready',[e['stage'] for e in events])
        with self.assertRaises(ProfileLocked):capture(self.root)

    def test_resume_still_authenticates_already_restored_blob_before_skipping(self):
        self.interrupt_after_first()
        row=self.store.manifest()['files'][0];blob,original=self.corrupt(row)
        with patch.object(self.store,'verify',wraps=self.store.verify) as verify:
            with self.assertRaises(Exception):self.store.restore()
        verify.assert_called_once()
        self.assertFalse((self.store.workspace/'Outputs/b.txt').exists())
        blob.write_bytes(original)
        self.assertTrue(self.store.restore()['ready'])
        self.assertEqual(len(self.store.inventory()),3)
        self.assertFalse((self.store.base/'restore-pending.json').exists())

    def test_blob_changed_after_manifest_authentication_cannot_publish(self):
        original=self.store._decrypt_file
        def decrypt(source,relative,key,target=None,**kwargs):
            if relative=='Outputs/b.txt':
                data=bytearray(source.read_bytes());data[-1]^=1;source.write_bytes(data)
            return original(source,relative,key,target,**kwargs)
        with patch.object(self.store,'_decrypt_file',side_effect=decrypt):
            with self.assertRaises(Exception):self.store.restore()
        self.assertFalse((self.store.workspace/'Outputs/b.txt').exists())
        self.assertFalse(list(self.store.workspace.rglob('*.part')))
        self.assertTrue((self.store.base/'restore-pending.json').exists())

    def test_final_inventory_rejects_mutated_published_plaintext(self):
        def progress(event):
            if event['stage']=='restore-final':
                (self.store.workspace/'Outputs/a.txt').write_bytes(b'changed')
        self.store.on_progress=progress
        with self.assertRaisesRegex(RuntimeError,'final verification'):self.store.restore()
        self.assertTrue((self.store.base/'restore-pending.json').exists())

    def test_late_identical_file_is_not_adopted_as_restored_in_fresh_transaction(self):
        def progress(event):
            if event['stage']=='restore' and event.get('completed')==0:
                path=self.store.workspace/'Outputs/a.txt';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'first')
        self.store.on_progress=progress
        with self.assertRaisesRegex(FileExistsError,'Another writer'):self.store.restore()
        self.assertTrue((self.store.base/'restore-pending.json').exists())

    def test_progress_errors_or_return_values_cannot_skip_checks_or_open_failed_login(self):
        def broken(_event):raise RuntimeError('synthetic presentation failure')
        runtime=self.runtime(broken)
        self.assertTrue(runtime.prepare(self.session)['ready'])
        runtime.close(self.session,writers_stopped=True)
        fresh=self.backend.login(OWNER);self.corrupt(self.store.manifest()['files'][-1])
        runtime=self.runtime(lambda _event:{'ready':True,'verified':True})
        with self.assertRaises(Exception):runtime.prepare(fresh)
        self.assertTrue(runtime.retains_session(fresh))
        with self.assertRaises(ProfileLocked):capture(self.root)

    def test_unauthenticated_session_cannot_trigger_recovery_or_ready_progress(self):
        events=[];runtime=self.runtime(events.append);self.session.active=False
        with self.assertRaises(PermissionError):runtime.prepare(self.session)
        self.assertEqual(events,[]);runtime.quiesce.assert_not_called()
        self.assertFalse(runtime.marker.exists())


if __name__=='__main__':unittest.main()
