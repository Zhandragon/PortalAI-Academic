import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
import local_accounts as accounts
import account_connections as connections
from profile_runtime import ProfileRuntime
from profile_workspace import ProfileWorkspace
from profile_paths import private_path,capture,ProfileLocked,UID_ENV,EPOCH_ENV
PASSWORD='Synthetic profile password only'

class PlainProfiles(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,{},clear=False);env.start();self.addCleanup(env.stop)
        for name in (UID_ENV,EPOCH_ENV):os.environ.pop(name,None)
        kdf=patch.object(accounts,'_KDF_N',1024);kdf.start();self.addCleanup(kdf.stop)
        self.store=accounts.LocalAccounts(self.root);self.addCleanup(self.store.logout)
        self.runtime=ProfileRuntime(self.root,self.store,quiesce=lambda *_:{'stopped':True},lazy_restore=True)
        self.addCleanup(self.release)

    def release(self):
        self.runtime._close_hydration()
        if self.runtime._process_lock is not None:
            self.runtime._process_lock.__exit__(None,None,None);self.runtime._process_lock=None
        connections.clear_session()

    def open(self):
        actor=self.store.bootstrap('Owner',PASSWORD,encrypted=False)
        self.runtime.prepare(actor);return actor

    def write(self,text='Plain user content'):
        path=private_path(self.root,'Data/Chat/example.txt');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        return path

    def test_plain_close_and_reopen_keep_readable_files_and_new_epoch(self):
        with patch('profile_workspace._crypto',side_effect=AssertionError('Plain profile invoked encryption')):
            actor=self.open();epoch=capture(self.root);path=self.write()
            receipt=self.runtime.close(actor,writers_stopped=True)
            self.assertFalse(receipt['encrypted']);self.assertEqual(path.read_text(),'Plain user content')
            with self.assertRaises(ProfileLocked):capture(self.root)
            actor=self.store.login('Owner',PASSWORD);self.runtime.prepare(actor)
            self.assertNotEqual(epoch,capture(self.root));self.assertEqual(private_path(self.root,'Data/Chat/example.txt'),path)
            self.assertIsNone(self.runtime._hydration)
            self.runtime.close(actor,writers_stopped=True)

    def test_plain_profile_does_not_block_another_standard_user(self):
        admin=self.open();row=self.store.create_user(admin,'Other',PASSWORD,admin_password=PASSWORD)
        path=self.write();self.runtime.close(admin,writers_stopped=True)
        user=self.store.login('Other',PASSWORD);self.runtime.prepare(user)
        self.assertNotEqual(private_path(self.root,'Data/Chat/example.txt'),path)
        self.runtime.close(user,writers_stopped=True);self.assertTrue(path.exists())

    def test_interrupted_plain_session_keeps_latest_work(self):
        actor=self.open();path=self.write('latest unsnapshotted work');self.release()
        self.runtime.session=None;self.runtime.epoch=None
        for name in (UID_ENV,EPOCH_ENV):os.environ.pop(name,None)
        fresh=self.store.login('Owner',PASSWORD);self.runtime.prepare(fresh)
        self.assertEqual(path.read_text(),'latest unsnapshotted work')
        self.runtime.close(fresh,writers_stopped=True)

    def test_unchanged_recovery_reuses_blobs_and_detects_corruption(self):
        actor=self.open();self.write();workspace=ProfileWorkspace(self.root,actor)
        first=workspace.snapshot();second=workspace.snapshot();self.assertEqual(first['generation'],second['generation'])
        manifest=workspace.manifest();blob=workspace.blob_path(manifest,manifest['files'][0])
        self.assertIn(b'Plain user content',blob.read_bytes());blob.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):workspace.verify()
        with self.assertRaises(ValueError):self.runtime.close(actor,writers_stopped=True)
        self.assertTrue(actor.active)

    def test_external_plain_edits_and_deletions_are_not_overwritten(self):
        actor=self.open();path=self.write();self.runtime.close(actor,writers_stopped=True)
        path.unlink();actor=self.store.login('Owner',PASSWORD);self.runtime.prepare(actor)
        self.assertFalse(path.exists());self.runtime.close(actor,writers_stopped=True)

    def test_plain_connections_really_store_plaintext_and_remain_context_bound(self):
        actor=self.open();data={'version':1,'profiles':{},'secrets':{'example':{'token':'synthetic-visible-token'}},'setups':{}}
        connections.write(self.root,actor,data)
        path=private_path(self.root,connections.PLAINTEXT_RELATIVE)
        self.assertIn('synthetic-visible-token',path.read_text());self.assertEqual(connections.read(self.root),data)
        self.assertFalse(private_path(self.root,connections.RELATIVE).exists())
        connections.clear_session()
        with self.assertRaises(PermissionError):connections.read(self.root)
        connections.unlock_session(self.root,actor);self.runtime.close(actor,writers_stopped=True)

    def test_account_free_workspace_can_save_and_reopen(self):
        actor=self.store.bootstrap_without_account();self.runtime.prepare(actor);path=self.write('shared')
        self.runtime.close(actor,writers_stopped=True)
        actor=self.store.login_without_account();self.runtime.prepare(actor)
        self.assertTrue(actor.anonymous);self.assertEqual(path.read_text(),'shared')
        self.runtime.close(actor,writers_stopped=True)

    def test_admin_preview_export_and_explicit_reset_support_closed_plaintext(self):
        from admin_profile_access import inspect_profile,preview_text,export_profile
        from profile_reset import ResetCoordinator,CONFIRMATION_PHRASE
        import zipfile
        actor=self.open();self.write('verified plain export');uid=actor.user_id
        self.runtime.close(actor,writers_stopped=True);admin=self.store.login('Owner',PASSWORD)
        self.assertFalse(inspect_profile(self.store,admin,uid)['encrypted'])
        self.assertEqual(preview_text(self.store,admin,uid,'Data/Chat/example.txt')['text'],'verified plain export')
        target=self.root/'export.zip'
        self.assertTrue(export_profile(self.store,admin,uid,'history',target)['verified'])
        with zipfile.ZipFile(target) as archive:self.assertEqual(archive.read('Data/Chat/example.txt'),b'verified plain export')
        reset=ResetCoordinator(self.root,self.store);plan=reset.plan(admin,writer_check=lambda:True)
        token=reset.request_confirmation(admin,plan,admin_password=PASSWORD,typed_confirmation=CONFIRMATION_PHRASE,writer_check=lambda:True)
        result=reset.execute(admin,plan,token,admin_password=PASSWORD,new_username='Replacement',new_password=PASSWORD,writer_check=lambda:True)
        self.assertTrue(result['reset']);self.assertTrue(target.exists())

    def test_interrupted_plaintext_harvest_recovers_before_removing_original(self):
        from profile_migration import SessionHarvest
        actor=self.open();self.write();source=self.root/'Logs/synthetic.log'
        source.parent.mkdir(parents=True);source.write_text('retained diagnostic')
        harvest=SessionHarvest(self.root,actor);original=Path.unlink
        def fail(path,*args,**kwargs):
            if path==source:raise OSError('simulated removal interruption')
            return original(path,*args,**kwargs)
        with patch.object(Path,'unlink',fail),self.assertRaises(OSError):harvest.run(writers_stopped=True)
        self.assertTrue(source.exists());self.assertTrue(harvest.run(writers_stopped=True)['verified'])
        self.assertFalse(source.exists());self.runtime.close(actor,writers_stopped=True)

if __name__=='__main__':unittest.main(verbosity=2)
