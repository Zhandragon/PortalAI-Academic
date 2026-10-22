import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import profile_diagnostics as diagnostics
from profile_paths import UID_ENV,EPOCH_ENV


class DiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{UID_ENV:'a'*32,EPOCH_ENV:'b'*32});self.env.start()

    def tearDown(self):
        diagnostics.suspend();self.env.stop();self.temp.cleanup()

    def test_prelogin_keeps_real_account_backend_fresh_without_writes(self):
        from local_accounts import LocalAccounts
        self.assertEqual(LocalAccounts(self.root).status()['state'],'fresh')
        diagnostics.prepare(self.root)
        self.assertFalse(diagnostics.record('before authentication'))
        self.assertEqual(LocalAccounts(self.root).status()['state'],'fresh')
        self.assertEqual(list(self.root.iterdir()),[])

    def test_prelogin_never_discards_existing_legacy_evidence(self):
        from local_accounts import LocalAccounts
        path=self.root/'ControlCenter/PortableAI_Crash.log';path.parent.mkdir()
        path.write_text('existing private evidence\n')
        diagnostics.prepare(self.root)
        self.assertEqual(path.read_text(),'existing private evidence\n')
        self.assertEqual(LocalAccounts(self.root).status()['state'],'recovery_required')

    def test_prelogin_stderr_still_redacts_locked_account_details(self):
        base=self.root/'Private/Accounts';base.mkdir(parents=True)
        (base/'registry.json').write_text('damaged existing registry')
        diagnostics.prepare(self.root)
        capture=io.StringIO()
        with patch('profile_diagnostics.sys.stderr',capture):diagnostics.stderr('private crash detail')
        self.assertNotIn('private crash detail',capture.getvalue())
        self.assertIn('Sign in',capture.getvalue())
        self.assertEqual((base/'registry.json').read_text(),'damaged existing registry')

    def test_prepare_closes_an_old_diagnostic_handle(self):
        os.environ.pop(UID_ENV);os.environ.pop(EPOCH_ENV)
        diagnostics.resume(self.root)
        diagnostics.prepare(self.root)
        path=self.root/'ControlCenter/PortableAI_Crash.log'
        path.unlink()
        self.assertFalse(diagnostics.record('late prelogin callback'))
        self.assertFalse(path.exists())

    def test_legacy_append_preserves_crash_evidence(self):
        os.environ.pop(UID_ENV);os.environ.pop(EPOCH_ENV)
        path=self.root/'ControlCenter/PortableAI_Crash.log';path.parent.mkdir();path.write_text('old evidence\n')
        diagnostics.resume(self.root);self.assertTrue(diagnostics.record('new evidence'))
        diagnostics.suspend()
        self.assertEqual(path.read_text(),'old evidence\nnew evidence\n')

    def test_locked_no_shared_log_then_private_logging_and_suspend(self):
        base=self.root/'Private';base.mkdir();marker=base/'active-session.json'
        marker.write_text(json.dumps({'state':'closed','user_id':'a'*32,'epoch':'b'*32}))
        diagnostics.resume(self.root)
        self.assertFalse(diagnostics.record('private must not leak'))
        self.assertFalse((self.root/'ControlCenter/PortableAI_Crash.log').exists())
        marker.write_text(json.dumps({'state':'open','user_id':'a'*32,'epoch':'b'*32}))
        diagnostics.resume(self.root);self.assertTrue(diagnostics.record('owner details'))
        path=base/('Users/'+'a'*32+'/Workspace/Logs/ControlCenter_Crash.log')
        diagnostics.suspend();path.unlink()  # Open faulthandler descriptor blocks this on Windows.
        self.assertFalse(diagnostics.record('late callback'))
        self.assertFalse(path.exists())

    def test_epoch_revocation_rejects_stale_writer(self):
        base=self.root/'Private';base.mkdir();marker=base/'active-session.json'
        marker.write_text(json.dumps({'state':'open','user_id':'a'*32,'epoch':'b'*32}))
        diagnostics.resume(self.root)
        marker.write_text(json.dumps({'state':'closed','user_id':'a'*32,'epoch':'b'*32}))
        self.assertFalse(diagnostics.record('stale exception'))


if __name__=='__main__':unittest.main()
