"""Crash recovery may preserve verified ciphertext without rewriting its bodies."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from profile_workspace import ProfileWorkspace
from profile_lazy_state import HydrationState
from test_profile_workspace import FakeSession


class RecoveryWritesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=ProfileWorkspace(self.root,FakeSession())
        for relative,data in [('Data/Settings/example.json',b'{"fixture":true}'),('Outputs/large.bin',b'x'*(8*1024*1024)),('Outputs/other.txt',b'preserve me')]:
            path=self.store.workspace/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        self.expected=self.store.inventory();self.store.seal(writers_stopped=True)

    def partial_restore(self):
        original=self.store._decrypt_file;count=0
        def interrupt(source,relative,key,target=None,**kwargs):
            nonlocal count
            if target is not None:
                count+=1
                if count==2:raise OSError('Synthetic interrupted restore')
            return original(source,relative,key,target,**kwargs)
        with patch.object(self.store,'_decrypt_file',side_effect=interrupt),self.assertRaises(OSError):
            self.store.restore()
        self.assertTrue((self.store.base/'restore-pending.json').exists())
        self.assertEqual(len(self.store.inventory()),1)

    def no_plaintext_writes(self):
        original=self.store._decrypt_file
        def read_only(source,relative,key,target=None,**kwargs):
            self.assertIsNone(target,'Recovery must not write untouched plaintext')
            return original(source,relative,key,target,**kwargs)
        return patch.object(self.store,'_decrypt_file',side_effect=read_only)

    def test_interrupted_restore_seals_without_rewriting_eight_megabyte_output(self):
        self.partial_restore();before=self.store.inventory()
        with self.no_plaintext_writes():
            result=self.store.recover_for_seal(writers_stopped=True)
            self.assertEqual(result['restored_bytes'],0)
            self.assertEqual(result['kept_encrypted_files'],2)
            self.assertEqual(self.store.inventory(),before)
            self.assertTrue(self.store.seal(writers_stopped=True)['sealed'])
        self.store.restore();self.assertEqual(self.store.inventory(),self.expected)

    def test_sealed_harvest_preserves_old_files_without_restoring_them(self):
        with self.no_plaintext_writes():
            self.store.recover_for_seal(writers_stopped=True)
            self.assertEqual(self.store.inventory(),[])
            log=self.store.workspace/'Data/LegacyRecovery/new.txt';log.parent.mkdir(parents=True);log.write_text('new fixture evidence')
            self.store.seal(writers_stopped=True)
        self.store.restore()
        rows=self.store.inventory();self.assertEqual(len(rows),4)
        self.assertEqual([r for r in rows if r['path']!='Data/LegacyRecovery/new.txt'],self.expected)

    def test_transition_repeats_after_ledger_commit_before_journal_removal(self):
        self.partial_restore()
        journal=self.store.base/'restore-pending.json'
        cls=type(journal);original=cls.unlink
        def interrupted(path,*args,**kwargs):
            if path==journal:raise OSError('Synthetic disconnect after ledger commit')
            return original(path,*args,**kwargs)
        with patch.object(cls,'unlink',interrupted),self.assertRaises(OSError):
            self.store.recover_for_seal(writers_stopped=True)
        self.assertTrue(journal.exists());self.assertTrue((self.store.base/'hydration.enc').exists())
        with self.no_plaintext_writes():
            self.store.recover_for_seal(writers_stopped=True)
            self.store.seal(writers_stopped=True)
        self.store.restore();self.assertEqual(self.store.inventory(),self.expected)

    def test_changed_plaintext_blocks_conversion_and_preserves_journal(self):
        self.partial_restore();file=self.store.workspace/'Data/Settings/example.json';file.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'Unexpected workspace'):
            self.store.recover_for_seal(writers_stopped=True)
        self.assertEqual(file.read_bytes(),b'changed')
        self.assertTrue((self.store.base/'restore-pending.json').exists())
        self.assertFalse((self.store.base/'hydration.enc').exists())

    def test_changed_generation_ciphertext_blocks_even_for_unmaterialized_file(self):
        self.partial_restore();manifest=self.store.manifest()
        row=next(r for r in manifest['files'] if r['path']=='Outputs/other.txt')
        blob=self.store.blob_path(manifest,row);data=bytearray(blob.read_bytes());data[-1]^=1;blob.write_bytes(data)
        with self.assertRaises(Exception):self.store.recover_for_seal(writers_stopped=True)
        self.assertTrue((self.store.base/'restore-pending.json').exists())
        self.assertFalse((self.store.base/'hydration.enc').exists())

    def test_failed_durable_ledger_save_preserves_eager_journal(self):
        self.partial_restore();before=self.store.inventory()
        with patch('profile_workspace._atomic_bytes',side_effect=OSError('Synthetic fsync failure')),self.assertRaises(OSError):
            self.store.recover_for_seal(writers_stopped=True)
        self.assertTrue((self.store.base/'restore-pending.json').exists())
        self.assertEqual(self.store.inventory(),before)
        self.store.recover_for_seal(writers_stopped=True)

    def test_does_not_adopt_arbitrary_partial_file(self):
        self.partial_restore();part=self.store.workspace/'Outputs/unowned.part';part.parent.mkdir(exist_ok=True);part.write_bytes(b'unrelated')
        with self.assertRaisesRegex(RuntimeError,'Unexpected workspace'):
            self.store.recover_for_seal(writers_stopped=True)
        self.assertEqual(part.read_bytes(),b'unrelated')

    def test_mismatched_dual_journals_fail_closed(self):
        self.partial_restore();manifest=self.store.manifest();hydration=HydrationState(self.store,manifest=manifest)
        hydration.ready=True;hydration.save()
        with self.assertRaisesRegex(RuntimeError,'final verification'):
            self.store.recover_for_seal(writers_stopped=True)
        self.assertTrue((self.store.base/'restore-pending.json').exists())

    def test_requires_writer_shutdown_and_does_not_change_default_restore(self):
        with self.assertRaisesRegex(RuntimeError,'shutdown'):self.store.recover_for_seal()
        self.store.restore();self.assertEqual(self.store.inventory(),self.expected)


if __name__=='__main__':unittest.main()
