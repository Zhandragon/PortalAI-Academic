"""Migration and interruption checks using synthetic temporary installations."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Agent'))
from profile_migration import LegacyMigration, SessionHarvest, legacy_inventory, PLAN_PATH
from profile_workspace import ProfileWorkspace
import profile_migration


class Session:
    user_id='a'*32
    role='admin'
    profile_key=b'k'*32


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.session=Session()
        self.migration=LegacyMigration(self.root,self.session)
        self.store=self.migration.store

    def tearDown(self):self.temp.cleanup()

    def write(self,path,data=b'synthetic private data'):
        target=self.root/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        return target

    def seed(self):
        self.write('Data/Chat/one.json',b'chat')
        self.write('Outputs/image.png',b'image')
        self.write('Logs/old.log',b'log')
        self.write('Backups/old.zip',b'old recovery archive')
        self.write('Agent/.runtime/request.json',b'private prompt')
        self.write('Agent/.runtime/qwen_last_stop.json',b'public lifecycle')
        self.write('LLM/models/keep.gguf',b'unchanged weight')
        return legacy_inventory(self.root)

    def run_migration(self,plan=None):
        plan=plan or legacy_inventory(self.root)
        return self.migration.run(plan['digest'],writers_stopped=True)

    def test_verified_migration_retains_models_and_shared_lifecycle(self):
        plan=self.seed();receipt=self.run_migration(plan)
        self.assertTrue(receipt['sealed']);self.assertEqual(receipt['files'],5)
        self.assertEqual(legacy_inventory(self.root)['files'],[])
        self.assertEqual(self.store.inventory(),[])
        self.store.restore()
        for row in plan['files']:
            self.assertEqual((self.store.workspace/row['target']).stat().st_size,row['bytes'])
        self.assertEqual((self.root/'LLM/models/keep.gguf').read_bytes(),b'unchanged weight')
        self.assertTrue((self.root/'Agent/.runtime/qwen_last_stop.json').exists())

    def test_stop_gate_and_changed_digest_keep_every_original(self):
        plan=self.seed()
        with self.assertRaises(RuntimeError):self.migration.run(plan['digest'])
        self.write('Data/new.txt')
        with self.assertRaises(RuntimeError):self.run_migration(plan)
        self.assertTrue(all((self.root/row['source']).exists() for row in plan['files']))

    def test_failed_encryption_never_removes_originals(self):
        plan=self.seed()
        with patch.object(self.store,'snapshot',side_effect=RuntimeError('synthetic encryption failure')):
            with self.assertRaises(RuntimeError):self.run_migration(plan)
        self.assertTrue(all((self.root/row['source']).exists() for row in plan['files']))
        self.assertTrue(self.migration.recover_copy(plan['digest'],writers_stopped=True)['sealed'])

    def test_missing_plan_crash_window_recovers_only_exact_original_inventory(self):
        plan=self.seed();original=profile_migration.atomic_json
        def fail(path,value):
            if Path(path)==self.store.workspace/PLAN_PATH:raise OSError('power lost before plan write')
            return original(path,value)
        with patch.object(profile_migration,'atomic_json',side_effect=fail):
            with self.assertRaises(OSError):self.run_migration(plan)
        self.assertTrue(self.migration.recover_copy(plan['digest'],writers_stopped=True)['sealed'])

    def test_missing_harvest_plan_rebuilds_recorded_token_mapping(self):
        self.write('Logs/new.log');harvest=SessionHarvest(self.root,self.session);original=profile_migration.atomic_json
        def fail(path,value):
            if Path(path).name.startswith('harvest-') and Path(path).parent.name=='ProfileMigration':
                raise OSError('power lost before harvest plan write')
            return original(path,value)
        with patch.object(profile_migration,'atomic_json',side_effect=fail):
            with self.assertRaises(OSError):harvest.run(writers_stopped=True)
        self.assertTrue(harvest.run(writers_stopped=True)['verified'])

    def test_interrupted_copy_retries_only_verified_prefix(self):
        plan=self.seed();original=self.migration._copy_one
        def interrupt(row):
            if row['source']=='Data/Chat/one.json':
                partial=self.store.workspace/(row['target']+'.portal-copy-part')
                partial.parent.mkdir(parents=True,exist_ok=True);partial.write_bytes(b'ch')
                raise OSError('synthetic interrupted file copy')
            return original(row)
        with patch.object(self.migration,'_copy_one',side_effect=interrupt):
            with self.assertRaises(OSError):self.run_migration(plan)
        self.assertTrue(self.migration.recover_copy(plan['digest'],writers_stopped=True)['sealed'])
        self.store.restore();self.assertEqual((self.store.workspace/'Data/Chat/one.json').read_bytes(),b'chat')

    def test_changed_copy_prefix_fails_closed(self):
        plan=self.seed()
        with patch.object(self.migration,'_copy_one',side_effect=OSError('stop before copies')):
            with self.assertRaises(OSError):self.run_migration(plan)
        partial=self.store.workspace/'Data/Chat/one.json.portal-copy-part'
        partial.parent.mkdir(parents=True,exist_ok=True);partial.write_bytes(b'changed')
        with self.assertRaises(RuntimeError):self.migration.recover_copy(plan['digest'],writers_stopped=True)
        self.assertTrue(partial.exists());self.assertTrue((self.root/'Data/Chat/one.json').exists())

    def test_unplanned_file_before_commit_keeps_originals(self):
        plan=self.seed();original=self.store.snapshot
        def new_file():
            receipt=original();self.write('Outputs/new-after-inventory.txt');return receipt
        with patch.object(self.store,'snapshot',side_effect=new_file):
            with self.assertRaisesRegex(RuntimeError,'New or changed'):self.run_migration(plan)
        self.assertTrue(all((self.root/row['source']).exists() for row in plan['files']))
        self.assertFalse(self.migration.complete.exists())

    def test_unplanned_file_during_commit_does_not_report_success(self):
        plan=self.seed();original=Path.unlink;injected=False
        def inject(path,*args,**kwargs):
            nonlocal injected
            result=original(path,*args,**kwargs)
            if path==self.root/'Outputs/image.png' and not injected:
                injected=True;self.write('Outputs/unexpected.txt')
            return result
        with patch.object(Path,'unlink',inject):
            with self.assertRaisesRegex(RuntimeError,'writer created'):self.run_migration(plan)
        self.assertTrue(self.migration.journal.exists());self.assertFalse(self.migration.complete.exists())
        self.assertEqual(len(self.store.verify()['files']),len(plan['files'])+1)

    def test_interrupted_commit_recovers_complete_authenticated_plan(self):
        plan=self.seed();original=Path.unlink
        def fail(path,*args,**kwargs):
            if path==self.root/'Outputs/image.png':raise OSError('synthetic loss of power')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):
            with self.assertRaises(OSError):self.run_migration(plan)
        receipt=self.migration.recover_verified(writers_stopped=True)
        self.assertTrue(receipt['sealed']);self.assertFalse(self.migration.journal.exists())
        self.store.restore();self.assertEqual((self.store.workspace/'Outputs/image.png').read_bytes(),b'image')

    def test_source_and_target_scope_tamper_rejected(self):
        plan=self.seed()
        with patch.object(self.migration,'_copy_one',side_effect=OSError('stop before copies')):
            with self.assertRaises(OSError):self.run_migration(plan)
        for source,target in [('LLM/models/keep.gguf','Data/stolen'),('Outputs/image.png','../escape')]:
            bad=json.loads(json.dumps(plan));bad['files'][0].update(source=source,target=target)
            (self.store.workspace/PLAN_PATH).write_text(json.dumps(bad))
            with self.assertRaises(ValueError):self.migration.recover_copy(plan['digest'],writers_stopped=True)
        self.assertEqual((self.root/'LLM/models/keep.gguf').read_bytes(),b'unchanged weight')

    def test_harvest_preserves_existing_workspace_and_can_recover_copy(self):
        self.store.workspace.mkdir(parents=True)
        (self.store.workspace/'Data').mkdir();(self.store.workspace/'Data/important.txt').write_bytes(b'prior private files')
        self.write('Logs/new.log',b'new diagnostic')
        harvest=SessionHarvest(self.root,self.session)
        with patch.object(harvest.store,'snapshot',side_effect=OSError('synthetic interrupted harvest')):
            with self.assertRaises(OSError):harvest.run(writers_stopped=True)
        receipt=harvest.run(writers_stopped=True)
        self.assertTrue(receipt['verified']);self.assertFalse(receipt['sealed'])
        self.assertEqual((self.store.workspace/'Data/important.txt').read_bytes(),b'prior private files')
        self.assertFalse((self.root/'Logs/new.log').exists())
        self.assertTrue(any(row['path'].endswith('/Logs/new.log') for row in self.store.verify()['files']))

    def test_harvest_verified_recovery_uses_own_plan_without_sealing(self):
        self.write('Logs/new.log');harvest=SessionHarvest(self.root,self.session);original=Path.unlink
        def fail(path,*args,**kwargs):
            if path==self.root/'Logs/new.log':raise OSError('synthetic interrupt')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail):
            with self.assertRaises(OSError):harvest.run(writers_stopped=True)
        receipt=harvest.run(writers_stopped=True)
        self.assertTrue(receipt['verified']);self.assertFalse(receipt['sealed'])
        self.assertTrue(harvest.store.inventory())


if __name__=='__main__':unittest.main()
