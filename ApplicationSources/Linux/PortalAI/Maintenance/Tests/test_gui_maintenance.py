"""Guard against destructive cleanup, false-success reports and stale settings."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
import maintenance_reports as reports
import storage_current as storage
import settings_page
import root_archive
import maintenance_cleanup
from lifecycle_control import StartupGate


class MaintenanceTests(unittest.TestCase):
    def test_stop_cancels_a_late_startup_helper(self):
        gate=StartupGate();ticket=gate.ticket();gate.cancel()
        with patch('subprocess.Popen') as launch:
            with self.assertRaises(RuntimeError):gate.launch(ticket,launch)
            launch.assert_not_called()
        marker=object()
        self.assertIs(gate.launch(gate.ticket(),lambda:marker),marker)

    def test_cache_named_link_cannot_delete_models(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);target=root/'LLM/models';target.mkdir(parents=True);(target/'keep.gguf').write_bytes(b'model')
            (root/'Data').mkdir();link=root/'Data/WebCache'
            try:link.symlink_to(target,target_is_directory=True)
            except OSError:self.skipTest('Host does not allow creating test symlinks')
            with self.assertRaises(RuntimeError):maintenance_cleanup.execute_cleanup(root,'webcache')
            self.assertTrue((target/'keep.gguf').exists())

    def test_data_cleanup_scope_leaves_settings_and_missions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for rel in ('Data/Chat/Sessions/a.json','Data/Chat/settings.json','Data/Missions/a/mission.json','Outputs/keep.txt'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            result=maintenance_cleanup.execute_cleanup(root,'conversations')
            self.assertTrue(result['success']);self.assertFalse((root/'Data/Chat/Sessions/a.json').exists())
            self.assertTrue((root/'Data/Chat/settings.json').exists());self.assertTrue((root/'Data/Missions/a/mission.json').exists());self.assertTrue((root/'Outputs/keep.txt').exists())

    def test_failed_report_remains_failed_when_reopened(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);reports.save(root,'check','failed',{},2)
            self.assertEqual(reports.saved_status(root,'check')[0],'FAIL')
            reports.save(root,'check','passed',{},0)
            self.assertEqual(reports.saved_status(root,'check',True)[0],'FAIL')
            self.assertEqual(reports.saved_status(root,'check')[0],'PASS')

    def test_old_report_never_assumed_success(self):
        with tempfile.TemporaryDirectory() as d:self.assertEqual(reports.saved_status(Path(d),'old')[0],'UNVERIFIED')

    def test_timeout_replaces_stale_success(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);reports.save(root,'check_run','previous success',{},0)
            with patch.object(reports.subprocess,'run',side_effect=TimeoutError('test timeout')):
                r=reports.run_tool(root,'test.py',[],'check','Test',1)
            self.assertEqual(r['returncode'],2)
            self.assertEqual(reports.saved_status(root,'check_run')[0],'FAIL')
            self.assertIn('test timeout',(root/'Data/Maintenance/check_run_latest.txt').read_text())

    def test_report_key_cannot_escape(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):reports.save(Path(d),'../escape','x')

    def test_cleanup_only_allowlisted_bytecode(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for rel in ('Agent/__pycache__/safe.pyc','Agent/__pycache__/keep.txt','Runtime/__pycache__/keep.pyc','Data/__pycache__/keep.pyc','Agent/.venv/__pycache__/keep.pyc'):
                p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'data')
            candidates=storage.safe_candidates(root)
            self.assertEqual([x['path'] for x in candidates],['Agent/__pycache__/safe.pyc'])
            results,freed=storage.apply_safe(root,candidates)
            self.assertEqual(freed,4);self.assertTrue(all(x['ok'] for x in results))
            self.assertTrue((root/'Agent/__pycache__/keep.txt').exists())
            self.assertTrue((root/'Runtime/__pycache__/keep.pyc').exists())

    def test_changed_cleanup_candidate_is_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'Agent/__pycache__/test.pyc';p.parent.mkdir(parents=True);p.write_bytes(b'old')
            candidates=storage.safe_candidates(root);p.write_bytes(b'new longer')
            result,freed=storage.apply_safe(root,candidates)
            self.assertFalse(result[0]['ok']);self.assertEqual(freed,0);self.assertTrue(p.exists())

    def test_forged_cleanup_candidate_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'keep.pyc';p.write_bytes(b'keep')
            result,freed=storage.apply_safe(root,[{'path':'keep.pyc','bytes':4}])
            self.assertFalse(result[0]['ok']);self.assertTrue(p.exists())

    def test_hardlinks_not_counted_as_separate_duplicate_storage(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'a';a.write_bytes(b'x'*1024**2);b=root/'b';os.link(a,b)
            groups=storage.duplicate_groups([(a,a.stat()),(b,b.stat())],[])
            self.assertEqual(groups[0]['distinct_file_identities'],1)
            self.assertEqual(groups[0]['separate_file_duplicate_bytes'],0)

    def test_samples_do_not_prove_equality(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=bytearray(2*1024**2);a=root/'a';a.write_bytes(data)
            data[250000]=1;b=root/'b';b.write_bytes(data)
            self.assertEqual(storage.hash_file(a,True),storage.hash_file(b,True))
            self.assertFalse(storage.duplicate_groups([(a,a.stat()),(b,b.stat())],[]))

    def test_root_archive_leaves_user_assets_and_current_instructions(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for n in ('README_v15_138.txt','testimage.jpg','PortalAI.exe','AGENTS.md','PortableAI_Master_Instructions_v45.txt'):(root/n).write_bytes(b'fixture')
            self.assertEqual([p.name for p in root_archive.plan(root)],['README_v15_138.txt'])

    def test_root_archive_requires_verified_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'README_v15_138.txt';p.write_bytes(b'fixture')
            with self.assertRaises(FileNotFoundError):root_archive.archive(root,True)
            self.assertTrue(p.exists())

    def test_model_save_preserves_new_fields_and_reserves(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Agent').mkdir()
            cfg={'models':[],'storage':{'future':'preserved'},'new_field':123,'media':{'future':'preserved'}}
            (root/'Agent/hardware_profiles.json').write_text(json.dumps(cfg))
            with patch.object(settings_page,'inventory',return_value={'models':[{'id':'small','installed':True}]}):
                settings_page.save_settings(root,dict(selection='small',backend='cpu',context_tokens='2048',image_profile='auto',speech_model='base',voice_engine='piper'))
            result=json.loads((root/'Agent/hardware_profiles.json').read_text())
            self.assertEqual(result['new_field'],123);self.assertEqual(result['storage'],cfg['storage']);self.assertEqual(result['media']['future'],'preserved')

    def test_missing_model_is_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'Agent').mkdir();p=root/'Agent/hardware_profiles.json';p.write_text('{}')
            with patch.object(settings_page,'inventory',return_value={'models':[]}):
                with self.assertRaises(ValueError):settings_page.save_settings(root,{'selection':'missing'})
            self.assertEqual(p.read_text(),'{}')


if __name__=='__main__':unittest.main()
