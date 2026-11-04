import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
import local_accounts as accounts
import account_connections as connections
from account_privacy import PrivacyChange
from profile_runtime import ProfileRuntime
from profile_workspace import ProfileWorkspace
from profile_paths import private_path,UID_ENV,EPOCH_ENV
OLD='Synthetic old administrator password'
NEW='Synthetic new administrator password'
CONTENT='Recoverable synthetic personal content'

class PrivacyConversion(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        env=patch.dict(os.environ,{},clear=False);env.start();self.addCleanup(env.stop)
        for name in (UID_ENV,EPOCH_ENV):os.environ.pop(name,None)
        kdf=patch.object(accounts,'_KDF_N',1024);kdf.start();self.addCleanup(kdf.stop)
        crypto=patch('mission_accounts.activate',lambda *_:accounts._crypto());crypto.start();self.addCleanup(crypto.stop)
        self.stores=[];self.runtimes=[];self.addCleanup(self.release)

    def release(self):
        connections.clear_session()
        for runtime in self.runtimes:
            runtime._close_hydration()
            if runtime._process_lock is not None:runtime._process_lock.__exit__(None,None,None);runtime._process_lock=None
        for store in self.stores:store.logout()

    def runtime(self,store):
        runtime=ProfileRuntime(self.root,store,quiesce=lambda *_:{'stopped':True},lazy_restore=True)
        self.runtimes.append(runtime);return runtime

    def initialize(self,encrypted=True):
        store=accounts.LocalAccounts(self.root);self.stores.append(store)
        actor=store.bootstrap('Owner',OLD,encrypted=encrypted);runtime=self.runtime(store);runtime.prepare(actor)
        path=private_path(self.root,'Data/Chat/example.txt');path.parent.mkdir(parents=True,exist_ok=True);path.write_text(CONTENT)
        self.data={'version':1,'profiles':{},'secrets':{'test':{'token':'synthetic-conversion-token'}},'setups':{}}
        connections.write(self.root,actor,self.data);self.uid=actor.user_id
        runtime.close(actor,writers_stopped=True);return store

    def change(self,encrypted,password_required=True,fault=None):
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True},fault=fault)
        return converter.apply('Owner',OLD,self.uid,new_password=NEW if password_required else '',encrypted=encrypted,password_required=password_required)

    def assert_open(self,password,encrypted):
        store=accounts.LocalAccounts(self.root);self.stores.append(store);actor=store.login('Owner',password)
        self.assertEqual(actor.encrypted,encrypted);runtime=self.runtime(store);runtime.prepare(actor)
        self.assertEqual(private_path(self.root,'Data/Chat/example.txt').read_text(),CONTENT)
        self.assertEqual(connections.read(self.root),self.data)
        runtime.close(actor,writers_stopped=True)

    def test_encrypted_to_plain_preserves_data_and_connections(self):
        self.initialize();receipt=self.change(False,False);self.assertTrue(receipt['verified'])
        self.assert_open('',False)
        self.assertIn(CONTENT,(self.root/'Private/Users'/self.uid/'Workspace/Data/Chat/example.txt').read_text())

    def test_plain_to_encrypted_protects_historical_plaintext_too(self):
        self.initialize(False);receipt=self.change(True);self.assertTrue(receipt['verified'])
        self.assertFalse((self.root/'Private/privacy-change.json').exists())
        for path in (self.root/'Private').rglob('*'):
            if path.is_file() and path.stat().st_size<2*1024**2:
                self.assertNotIn(CONTENT.encode(),path.read_bytes(),str(path))
                self.assertNotIn(b'synthetic-conversion-token',path.read_bytes(),str(path))
        self.assert_open(NEW,True)

    def test_interrupted_preparation_rolls_back_original(self):
        self.initialize(False)
        def fault(stage):
            if stage=='building':raise OSError('injected interruption')
        with self.assertRaises(OSError):self.change(True,fault=fault)
        self.assertEqual(accounts.LocalAccounts(self.root).status()['state'],'recovery_required')
        result=PrivacyChange(self.root,writer_check=lambda:{'stopped':True}).recover('Owner',OLD,action='rollback')
        self.assertTrue(result['rolled_back']);self.assert_open(OLD,False)

    def test_interrupted_profile_swap_rolls_back_without_losing_original(self):
        self.initialize(False)
        def fault(stage):
            if stage=='new-profile-installed':raise OSError('injected interruption')
        with self.assertRaises(OSError):self.change(True,fault=fault)
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        converter.recover('Owner',OLD,action='rollback');self.assert_open(OLD,False)

    def test_committed_change_finishes_after_staging_was_removed(self):
        self.initialize(False)
        def fault(stage):
            if stage=='staging-removed':raise OSError('injected interruption')
        with self.assertRaises(OSError):self.change(True,fault=fault)
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        with self.assertRaises((accounts.AuthenticationError,accounts.RecoveryRequired)):
            converter.recover('Owner',OLD,action='rollback')
        self.assertTrue(converter.recover('Owner',NEW,action='finish')['verified']);self.assert_open(NEW,True)

    def test_wrong_password_and_no_shutdown_do_not_create_transaction(self):
        self.initialize()
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':False})
        with self.assertRaises(RuntimeError):converter.apply('Owner',OLD,self.uid,new_password=NEW,encrypted=False,password_required=True)
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        with self.assertRaises(accounts.AuthenticationError):converter.apply('Owner','wrong',self.uid,new_password=NEW,encrypted=False,password_required=True)
        self.assertFalse((self.root/'Private/privacy-change.json').exists())

    def test_repeated_conversion_reuses_history_instead_of_nested_vault_copies(self):
        self.initialize(False);self.change(True)
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        converter.apply('Owner',NEW,self.uid,new_password='',encrypted=False,password_required=False)
        self.assert_open('',False)
        workspace=self.root/'Private/Users'/self.uid/'Workspace'
        objects=list((workspace/'Data/PrivacyHistory/objects').glob('*.data'))
        self.assertLessEqual(len(objects),8)
        self.assertFalse((workspace/'Data/PrivacyRecovery').exists())
        self.assertTrue(any(CONTENT.encode()==p.read_bytes() for p in objects))
        self.assertFalse(any(p.name=='registry.json' for p in (workspace/'Data/PrivacyHistory').rglob('*')))

    def test_administrator_can_convert_a_member_without_changing_admin_credentials(self):
        store=self.initialize();admin=store.login('Owner',OLD)
        row=store.create_user(admin,'Member',OLD,admin_password=OLD)
        member=store.login('Member',OLD);runtime=self.runtime(store);runtime.prepare(member)
        output=private_path(self.root,'Outputs/member.txt');output.parent.mkdir(parents=True,exist_ok=True);output.write_text('member data')
        runtime.close(member,writers_stopped=True)
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        converter.apply('Owner',OLD,row['user_id'],new_password='',encrypted=False,password_required=False)
        restarted=accounts.LocalAccounts(self.root);self.stores.append(restarted)
        self.assertTrue(restarted.login('Owner',OLD).encrypted)
        member=restarted.login('Member','');runtime=self.runtime(restarted);runtime.prepare(member)
        self.assertEqual(private_path(self.root,'Outputs/member.txt').read_text(),'member data')
        runtime.close(member,writers_stopped=True)

    def test_partial_postcommit_cleanup_resumes_from_verified_history(self):
        self.initialize(False)
        original=PrivacyChange._remove_owned_tree
        state={'failed':False}
        def partial(converter,path,stage):
            if path.name=='OldProfile' and not state['failed']:
                state['failed']=True;next(p for p in path.rglob('*') if p.is_file()).unlink()
                raise OSError('injected partial cleanup')
            return original(converter,path,stage)
        with patch.object(PrivacyChange,'_remove_owned_tree',partial),self.assertRaises(OSError):self.change(True)
        converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        self.assertTrue(converter.recover('Owner',NEW,action='finish')['verified']);self.assert_open(NEW,True)

    def test_existing_profile_can_enter_and_leave_account_free_startup(self):
        self.initialize();converter=PrivacyChange(self.root,writer_check=lambda:{'stopped':True})
        converter.apply('Owner',OLD,self.uid,new_password='',encrypted=False,password_required=False,anonymous=True,start_without_account=True)
        store=accounts.LocalAccounts(self.root);self.stores.append(store)
        actor=store.login_without_account();self.assertTrue(actor.anonymous);store.logout()
        converter.apply('Owner','',self.uid,new_password=NEW,encrypted=True,password_required=True)
        self.assertIsNone(accounts.LocalAccounts(self.root).status()['auto_profile'])
        self.assert_open(NEW,True)

    def test_unreferenced_vault_files_prevent_loss_and_allow_rollback(self):
        self.initialize();store=accounts.LocalAccounts(self.root);self.stores.append(store)
        actor=store.login('Owner',OLD);workspace=ProfileWorkspace(self.root,actor)
        extra=workspace.vault/workspace.manifest()['generation']/('f'*32+'.enc');extra.write_bytes(b'unknown historical evidence')
        with self.assertRaises(accounts.RecoveryRequired):self.change(False)
        self.assertEqual(extra.read_bytes(),b'unknown historical evidence')
        PrivacyChange(self.root,writer_check=lambda:{'stopped':True}).recover('Owner',OLD,action='rollback')
        self.assertEqual(extra.read_bytes(),b'unknown historical evidence')

    def test_conversion_rotates_registry_master_and_preserves_other_admin_login(self):
        store=self.initialize();admin=store.login('Owner',OLD);old_master=bytes(admin._master)
        row=store.create_user(admin,'Second admin',OLD,role='admin',admin_password=OLD)
        old_second=store.login('Second admin',OLD);other_key=old_second.profile_key;store.logout()
        self.change(True)
        restarted=accounts.LocalAccounts(self.root);self.stores.append(restarted)
        second=restarted.login('Second admin',OLD)
        self.assertEqual(second.profile_key,other_key);self.assertNotEqual(bytes(second._master),old_master)
        with self.assertRaises(accounts.RecoveryRequired):restarted._private(restarted._read(),old_master)
        self.assertEqual(len(restarted.list_users(second)),3)
        self.assert_open(NEW,True)

if __name__=='__main__':unittest.main(verbosity=2)
