"""Failed lazy startup and real credential replacement; temporary profiles only."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
import local_accounts as accounts
import profile_hydration as hydration
from profile_paths import UID_ENV,EPOCH_ENV,ProfileLocked,capture,private_path
from profile_runtime import ProfileRuntime
from profile_workspace import ProfileWorkspace
from test_profile_runtime import AccountsFixture,OWNER


class _FailedEnvironment(dict):
    def update(self,*args,**kwargs):
        incoming=dict(*args,**kwargs)
        if hydration.PORT_ENV in incoming:
            # Exercise failure after partial environment publication too.
            self[hydration.PORT_ENV]=incoming[hydration.PORT_ENV]
            self[hydration.TOKEN_ENV]=incoming[hydration.TOKEN_ENV]
            raise OSError('synthetic environment publication failure')
        return super().update(incoming)


class StartupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{},clear=False);self.env.start()
        for name in (UID_ENV,EPOCH_ENV,hydration.PORT_ENV,hydration.TOKEN_ENV,hydration.OWNER_ENV):
            os.environ.pop(name,None)
        self.backend=AccountsFixture();self.session=self.backend.login(OWNER)
        self.runtime=ProfileRuntime(self.root,self.backend,lazy_restore=True,
            quiesce=lambda *_:{'stopped':True},legacy_check=lambda _:{'clean':True})
        self.store=ProfileWorkspace(self.root,self.session)
        path=self.store.workspace/'Outputs/deferred.txt';path.parent.mkdir(parents=True)
        path.write_bytes(b'synthetic dormant bytes');self.store.seal(writers_stopped=True)

    def tearDown(self):
        try:
            if self.runtime._hydration is not None:self.runtime._hydration.close()
            if self.runtime._process_lock is not None:
                self.runtime._process_lock.__exit__(None,None,None)
        finally:self.env.stop();self.temp.cleanup()

    def assert_locked_recoverable(self):
        self.assertIs(self.runtime.session,self.session)
        self.assertTrue(self.session.active)
        self.assertEqual(len(self.session.profile_key),32)
        self.assertIsNotNone(self.runtime._process_lock)
        self.assertEqual(json.loads(self.runtime.marker.read_text())['state'],'opening')
        self.assertNotIn(UID_ENV,os.environ);self.assertNotIn(EPOCH_ENV,os.environ)
        with self.assertRaises(ProfileLocked):capture(self.root)
        self.assertTrue((self.store.base/'hydration.enc').exists())

    def test_constructor_failure_retains_keys_and_later_verified_close(self):
        with patch.object(hydration,'HydrationBroker',side_effect=OSError('synthetic listener failure')):
            with self.assertRaisesRegex(OSError,'listener failure'):self.runtime.prepare(self.session)
        self.assert_locked_recoverable();self.assertIsNone(self.runtime._hydration)
        self.assertTrue(self.runtime.close(self.session,writers_stopped=True)['sealed'])
        self.assertFalse((self.store.base/'hydration.enc').exists())
        fresh=self.backend.login(OWNER)
        self.assertEqual(len(ProfileWorkspace(self.root,fresh).verify()['files']),1)

    def test_partial_environment_failure_stops_real_listener_before_rethrow(self):
        brokers=[];construct=hydration.HydrationBroker
        def create(*args,**kwargs):
            broker=construct(*args,**kwargs);brokers.append(broker);return broker
        with patch.object(os,'environ',_FailedEnvironment(os.environ)):
            with patch.object(hydration,'HydrationBroker',side_effect=create):
                with self.assertRaisesRegex(OSError,'publication failure'):self.runtime.prepare(self.session)
            self.assert_locked_recoverable()
            self.assertIsNone(self.runtime._hydration)
            self.assertFalse(brokers[0].thread.is_alive());self.assertFalse(brokers[0].accepting)
            self.assertNotIn(hydration.PORT_ENV,os.environ);self.assertNotIn(hydration.TOKEN_ENV,os.environ)
            self.assertNotIn(hydration._identity(self.root),hydration._BROKERS)
            self.runtime.close(self.session,writers_stopped=True)

    def test_failed_cleanup_retains_paused_broker_for_retry(self):
        close=hydration.HydrationBroker.close
        with patch.object(os,'environ',_FailedEnvironment(os.environ)):
            with patch.object(hydration.HydrationBroker,'close',side_effect=OSError('synthetic delayed close')):
                with self.assertRaisesRegex(OSError,'publication failure'):self.runtime.prepare(self.session)
            self.assert_locked_recoverable()
            broker=self.runtime._hydration
            self.assertIsNotNone(broker);self.assertFalse(broker.accepting)
            with self.assertRaises(ProfileLocked):broker.check()
            self.assertTrue(self.runtime.close(self.session,writers_stopped=True)['sealed'])
            self.assertFalse(broker.thread.is_alive());self.assertIsNone(self.runtime._hydration)


class RealCredentialHydrationTests(unittest.TestCase):
    def test_password_replacement_uses_new_real_session_and_same_profile_key(self):
        # Reduce only this synthetic fixture's Scrypt work; production policy and
        # authenticated credential envelopes are unchanged and never accessed.
        with tempfile.TemporaryDirectory() as folder,patch.object(accounts,'_KDF_N',1024),patch.dict(os.environ,{},clear=False):
            for name in (UID_ENV,EPOCH_ENV,hydration.PORT_ENV,hydration.TOKEN_ENV,hydration.OWNER_ENV):
                os.environ.pop(name,None)
            root=Path(folder);backend=accounts.LocalAccounts(root)
            old_password='synthetic old administrator passphrase'
            new_password='synthetic new administrator passphrase'
            session=backend.bootstrap('Owner',old_password)
            store=ProfileWorkspace(root,session)
            target=store.workspace/'Outputs/after-password.txt';target.parent.mkdir(parents=True)
            target.write_bytes(b'synthetic archived output');store.seal(writers_stopped=True)
            runtime=ProfileRuntime(root,backend,lazy_restore=True,
                quiesce=lambda *_:{'stopped':True},legacy_check=lambda _:{'clean':True})
            try:
                runtime.prepare(session);broker=runtime._hydration;key=session.profile_key
                updated=backend.change_password(session,old_password,new_password)
                self.assertFalse(session.active);self.assertEqual(updated.profile_key,key)
                with self.assertRaises(accounts.AuthenticationError):broker.check()
                self.assertFalse(target.exists())
                runtime.replace_session(updated)
                self.assertIs(runtime._hydration,broker)
                self.assertIs(broker.check(),updated)
                self.assertEqual(private_path(root,'Outputs/after-password.txt').read_bytes(),b'synthetic archived output')
                self.assertTrue(runtime.close(updated,writers_stopped=True)['sealed'])
                self.assertFalse(target.exists());self.assertFalse(broker.thread.is_alive())
                fresh=backend.login('Owner',new_password)
                self.assertEqual(len(ProfileWorkspace(root,fresh).verify()['files']),1)
            finally:
                if runtime._hydration is not None:runtime._hydration.close()
                if runtime._process_lock is not None:runtime._process_lock.__exit__(None,None,None)
                backend.logout()


if __name__=='__main__':unittest.main()
