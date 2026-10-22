"""Real crypto/profile epochs in disposable roots; no production accounts/jobs."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import local_accounts
from account_ui import AccountController
from account_switch import authenticate_candidate,seal_for_switch
from profile_runtime import ProfileRuntime
from profile_context import CapturedProfile


class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.env=patch.dict(os.environ,{});self.env.start()
        for key in ('PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH'):os.environ.pop(key,None)
        self.kdf=patch.object(local_accounts,'_KDF_N',1024);self.kdf.start()
        self.backend=local_accounts.LocalAccounts(self.root)
        self.secret='synthetic account password'
        self.old=self.backend.bootstrap('Alice',self.secret)
        self.backend.create_user(self.old,'Bob',self.secret,admin_password=self.secret)
        self.controller=AccountController(self.root,backend=self.backend)
        self.runtime=ProfileRuntime(self.root,self.backend,quiesce=lambda *_:{'stopped':True})
        self.runtime.prepare(self.old)
        self.old_epoch=self.runtime.epoch
        self.profile=CapturedProfile(self.root)
        self.data=self.root/'Private/Users'/self.old.user_id/'Workspace/Data/Chat/private.txt'
        self.data.parent.mkdir(parents=True,exist_ok=True);self.data.write_text('Alice only')
        self.gate=SimpleNamespace(root=self.root,controller=self.controller,session=self.old,locked=False,runtime=self.runtime,
            close=lambda:self.runtime.close(self.old,writers_stopped=True))
    def tearDown(self):
        if self.runtime.session is not None:self.runtime.close(self.runtime.session,writers_stopped=True)
        self.backend.logout();self.kdf.stop();self.env.stop();self.tmp.cleanup()
    def test_wrong_password_and_cancel_preserve_open_profile(self):
        before=(self.root/'Private/active-session.json').read_bytes()
        with self.assertRaises(Exception):authenticate_candidate(self.gate,'Bob','incorrect')
        candidate=authenticate_candidate(self.gate,'Bob',self.secret)
        self.backend.logout(candidate)  # Cancel before committing.
        self.assertTrue(self.old.active);self.assertEqual(self.data.read_text(),'Alice only')
        self.assertEqual(before,(self.root/'Private/active-session.json').read_bytes())
        self.profile.check()
    def test_valid_switch_seals_old_profile_before_next_epoch(self):
        candidate=authenticate_candidate(self.gate,'Bob',self.secret)
        with self.assertRaises(RuntimeError):seal_for_switch(self.gate,candidate)
        self.gate.locked=True
        ticket=seal_for_switch(self.gate,candidate)
        self.assertFalse(self.old.active);self.assertFalse(self.data.exists())
        self.assertEqual(json.loads((self.root/'Private/active-session.json').read_text())['state'],'closed')
        with self.assertRaises(Exception):self.profile.check()
        with self.assertRaises(PermissionError):ticket.take(self.root/'wrong')
        new=ticket.take(self.root)
        with self.assertRaises(PermissionError):ticket.take(self.root)
        self.runtime=ProfileRuntime(self.root,ticket.backend,quiesce=lambda *_:{'stopped':True})
        self.runtime.prepare(new)
        self.assertEqual(new.username,'Bob');self.assertNotEqual(self.runtime.epoch,self.old_epoch)
        self.assertFalse((self.root/'Private/Users'/new.user_id/'Workspace/Data/Chat/private.txt').exists())
    def test_sealing_failure_never_hands_off_or_discards_current_keys(self):
        candidate=authenticate_candidate(self.gate,'Bob',self.secret);self.gate.locked=True
        self.gate.close=Mock(side_effect=RuntimeError('synthetic seal failure'))
        with self.assertRaises(RuntimeError):seal_for_switch(self.gate,candidate)
        self.assertTrue(self.old.active);self.assertEqual(self.data.read_text(),'Alice only')
        self.backend.logout(candidate)
    def test_same_or_revoked_candidate_is_refused_before_sealing(self):
        with self.assertRaises(ValueError):authenticate_candidate(self.gate,'Alice',self.secret)
        candidate=authenticate_candidate(self.gate,'Bob',self.secret);self.backend.logout(candidate)
        self.gate.locked=True;self.gate.close=Mock()
        with self.assertRaises(Exception):seal_for_switch(self.gate,candidate)
        self.gate.close.assert_not_called();self.assertTrue(self.old.active)

if __name__=='__main__':unittest.main()
