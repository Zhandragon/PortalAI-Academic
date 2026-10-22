"""Public read-only checks must not reopen shared private report directories."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Tools')]
import profile_paths
import scan_portable_source as source
import portable_readiness as readiness
import audit_profile_routing as routing
import reference_current as references


class ReportPaths(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.uid, self.epoch = 'a'*32, 'b'*32
        self.workspace = profile_paths.workspace_root(self.root, self.uid)
        env = patch.dict(os.environ, {}, clear=True)
        env.start(); self.addCleanup(env.stop)

    def session(self, state='open'):
        marker = self.root/'Private/active-session.json'
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({'user_id':self.uid, 'epoch':self.epoch, 'state':state}))
        os.environ.update({profile_paths.UID_ENV:self.uid, profile_paths.EPOCH_ENV:self.epoch})

    def invoke(self, module, *args):
        with redirect_stdout(io.StringIO()):
            return module.main(['--root', str(self.root), *args])

    def test_locked_default_refuses_before_scan_or_hardware_probe(self):
        self.session('closed')
        for module, function in ((source,'scan'), (readiness,'report')):
            with self.subTest(module=module.__name__), patch.object(module,function) as run:
                with self.assertRaises(profile_paths.ProfileLocked): self.invoke(module)
                run.assert_not_called()
        self.assertFalse(self.workspace.exists())
        self.assertFalse((self.root/'Maintenance').exists())

    def test_stdout_is_read_only_while_locked(self):
        self.session('closed')
        for module, function, result in ((source,'scan',{'passed':True}), (readiness,'report',{'synthetic':True})):
            with self.subTest(module=module.__name__), patch.object(module,function,return_value=result), patch.object(module,'atomic_json') as save:
                self.invoke(module, '--stdout')
                save.assert_not_called()
        self.assertFalse(self.workspace.exists())
        self.assertFalse((self.root/'Maintenance').exists())

    def test_saved_reports_belong_to_active_profile(self):
        self.session()
        for module, function, result, name in ((source,'scan',{'passed':True},'source-scan'), (readiness,'report',{'synthetic':True},'portable-readiness')):
            with self.subTest(module=module.__name__), patch.object(module,function,return_value=result), patch.object(readiness,'require_space'):
                self.invoke(module)
            saved=self.workspace/'Data/Maintenance'/f'{name}.json'
            self.assertEqual(json.loads(saved.read_text()), result)
        self.assertFalse((self.root/'Maintenance').exists())
        self.assertFalse((self.root/'Data').exists())

    def test_stale_session_cannot_save_into_new_login(self):
        self.session()
        os.environ[profile_paths.EPOCH_ENV]='c'*32
        for module in (source, readiness):
            with self.subTest(module=module.__name__), self.assertRaises(profile_paths.ProfileLocked): self.invoke(module)

    def test_scan_checks_requested_root_without_executing_source(self):
        agent=self.root/'Agent'; agent.mkdir()
        (agent/'broken.py').write_text('def unfinished(:\n')
        (agent/'never_run.py').write_text('raise AssertionError("must never execute")\n')
        result=source.scan(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual([row['file'] for row in result['errors']], ['Agent/broken.py'])
        self.assertIn('Agent/never_run.py',result['checked'])
        self.assertFalse((self.root/'Data').exists())

    def test_scan_includes_owned_driver_inside_model_component_tree(self):
        path=self.root/'MusicUnderstanding/runtime_driver.py'
        path.parent.mkdir();path.write_text('def unfinished(:\n')
        result=source.scan(self.root)
        self.assertFalse(result['passed'])
        self.assertEqual([row['file'] for row in result['errors']],['MusicUnderstanding/runtime_driver.py'])

    def test_kicad_vendor_tree_is_not_first_party_source(self):
        for relative in ('Tools/KiCad/lib/vendor.py','Tools/KiCad.staging-9.0.2/lib/vendor.py'):
            path=self.root/relative;path.parent.mkdir(parents=True);path.write_text('vendor syntax not owned (')
        adapter=self.root/'Agent/kicad_windows.py';adapter.parent.mkdir();adapter.write_text('raise RuntimeError("never run")')
        result=source.scan(self.root)
        self.assertTrue(result['passed'],result['errors'])
        self.assertEqual(result['checked'],['Agent/kicad_windows.py'])

    def test_routing_review_locked_defaults_refuse_and_stdout_does_not_save(self):
        self.session('closed')
        with patch.object(routing,'ROOT',self.root), patch.object(routing,'audit',return_value={'errors':[]}) as audit, redirect_stdout(io.StringIO()):
            with self.assertRaises(profile_paths.ProfileLocked):routing.main([])
            audit.assert_not_called()
            self.assertEqual(routing.main(['--stdout']),0)
            audit.assert_called_once()
        self.assertFalse(self.workspace.exists())

    def test_routing_review_saves_only_to_signed_in_workspace(self):
        self.session()
        data={'scanned_files':1,'finding_counts':{},'errors':[]}
        with patch.object(routing,'ROOT',self.root), patch.object(routing,'audit',return_value=data), redirect_stdout(io.StringIO()):
            self.assertEqual(routing.main([]),0)
        reports=list((self.workspace/'Data/Maintenance').glob('profile-routing-audit-*.json'))
        self.assertEqual(len(reports),1)
        self.assertEqual(json.loads(reports[0].read_text()),data)
        self.assertFalse((self.root/'Maintenance').exists())

    def test_reference_audit_reports_missing_gui_without_aborting(self):
        result=references.audit(self.root)
        labels={row['label'] for row in result['rows'] if row['status']=='FAIL'}
        self.assertIn('Readable source ControlCenter/native_chat.py',labels)
        self.assertIn('Readable source ControlCenter/PortableAI_GUI.py',labels)
        self.assertIn('Agent/local_accounts.py',labels)
        self.assertIn('Agent/effort_policy.py',labels)
        self.assertGreater(result['counts']['FAIL'],0)


if __name__=='__main__': unittest.main()
