"""Execute the real reset adapter only against synthetic temporary roots."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'));sys.path.insert(0,str(ROOT/'ControlCenter'))
from local_accounts import LocalAccounts
from profile_runtime import ProfileRuntime
from account_reset_ui import ResetAdapter


class ResetAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/'portable'; self.root.mkdir()
        self.env=patch.dict(os.environ,{},clear=False);self.env.start()
        os.environ.pop('PORTALAI_PROFILE_ID',None);os.environ.pop('PORTALAI_PROFILE_EPOCH',None)
        self.accounts=LocalAccounts(self.root); self.password='Original-test-password-2026'
        self.session=self.accounts.bootstrap('Original',self.password)
        self.runtime=ProfileRuntime(self.root,self.accounts,quiesce=lambda *_:{'stopped':True})
        self.runtime.prepare(self.session)
        from profile_paths import private_path
        output=private_path(self.root,'Outputs/kept.txt');output.parent.mkdir(parents=True);output.write_text('private original')
        (self.root/'models-sentinel').write_text('keep model')
        self.gate=SimpleNamespace(root=self.root,controller=SimpleNamespace(backend=self.accounts,jobs=Mock()),
            runtime=self.runtime,session=self.session,gui_jobs=Mock(),chat=Mock(),locked=True)
        self.gate.controller.jobs.wait.return_value={'stopped':True}
        self.gate.gui_jobs.wait.return_value={'stopped':True};self.gate.chat.wait_for_writers.return_value={'stopped':True}
        self.gate.close=lambda session=None:self.runtime.close(session or self.session,writers_stopped=True)
        self.shutdown=patch.dict(sys.modules,{'profile_shutdown':SimpleNamespace(verify_stopped=lambda root:{'stopped':True})});self.shutdown.start()
        self.space=patch('runtime_policy.require_space');self.space.start()
        self.adapter=ResetAdapter(self.gate)

    def tearDown(self):
        self.adapter.release()
        if self.runtime._process_lock is not None:
            self.runtime._process_lock.__exit__(None,None,None)
        self.accounts.logout();self.space.stop();self.shutdown.stop();self.env.stop();self.tmp.cleanup()

    def test_wrong_password_cannot_seal_and_plan(self):
        with self.assertRaises(Exception):self.adapter.prepare('wrong-password')
        self.assertIs(self.runtime.session,self.session)
        self.assertIsNone(self.adapter.plan)

    def test_prepare_reauthenticates_after_seal_then_requires_explicit_export_choice(self):
        plan=self.adapter.prepare(self.password)
        self.assertFalse(self.session.active);self.assertTrue(self.adapter.admin.active)
        self.assertIsNone(self.runtime.session)
        self.assertTrue(plan['files'])
        with self.assertRaisesRegex(ValueError,'Export'):
            self.adapter.execute(self.password,'RESET ALL PRIVATE PROFILES','New','New-password-2026','New-password-2026')
        self.assertEqual(self.accounts.status()['state'],'locked')

    def test_verified_backup_then_real_temp_reset_preserves_models(self):
        self.adapter.prepare(self.password)
        backup=Path(self.tmp.name)/'backup.zip';self.assertTrue(self.adapter.export(backup)['verified'])
        with zipfile.ZipFile(backup) as archive:
            manifest=json.loads(archive.read('PortalAI-private-backup-manifest.json'))
            self.assertEqual(manifest['digest'],self.adapter.plan['digest'])
        result=self.adapter.execute(self.password,'RESET ALL PRIVATE PROFILES','Replacement','New-password-2026','New-password-2026')
        self.assertTrue(result['reset']);self.assertEqual((self.root/'models-sentinel').read_text(),'keep model')
        new=self.accounts.login('Replacement','New-password-2026');self.assertEqual(new.role,'admin')
        self.assertTrue(backup.exists())

    def test_full_private_backup_cannot_survive_inside_reset_bundle(self):
        self.adapter.prepare(self.password)
        with self.assertRaisesRegex(ValueError,'outside this PortalAI root'):
            self.adapter.export(self.root/'backup.zip')
        self.assertFalse((self.root/'backup.zip').exists())

    def test_writer_failure_blocks_reset_before_registry_mutation(self):
        self.adapter.prepare(self.password)
        self.gate.chat.wait_for_writers.return_value={'stopped':False}
        before=(self.root/'Private/Accounts/registry.json').read_bytes()
        with self.assertRaises(RuntimeError):
            self.adapter.execute(self.password,'RESET ALL PRIVATE PROFILES','New','New-password-2026','New-password-2026',decline_export=True)
        self.assertEqual((self.root/'Private/Accounts/registry.json').read_bytes(),before)


if __name__=='__main__':unittest.main()
