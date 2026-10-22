"""Diagnostic selectors must describe actual scope and preserve failure evidence."""
from contextlib import redirect_stdout
from datetime import datetime, timezone, timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import diagnostic_catalog as catalog
import component_smoke as smoke
import component_diagnostics as diagnostics
import maintenance_reports as reports
import fresh_machine_validator as readiness
import linux_system_test as linux
import media_stack_verify as media
import platform_runtime
import reference_current
import dependency_check
import storage_current


class Catalog(unittest.TestCase):
    def test_all_choices_roundtrip_to_one_report_key(self):
        keys=[]
        for name in catalog.CHOICES:
            entry=catalog.resolve(name)
            self.assertEqual(catalog.resolve(entry['argument']),entry)
            keys.append(entry['report_key'])
        self.assertEqual(len(keys),len(set(keys)))
        for old,new in [('FLUX Image','flux'),('Wan/VACE Video','vace'),('Web Tools','web'),
                        ('Media Editing','media_editing'),('Music Understanding','music_understanding')]:
            self.assertEqual(catalog.resolve(old)['report_key'],'diagnostic_'+new)

    def test_unknown_fails_before_linux_generic_checks(self):
        with patch.object(smoke,'os',SimpleNamespace(name='posix')),patch.object(linux,'rows') as generic:
            rows=smoke.component_rows(ROOT,'not-a-real-component')
        self.assertEqual(rows[0]['status'],'FAIL');generic.assert_not_called()

    def test_current_generic_foundation_sources_present(self):
        for key in catalog.SOURCE_ONLY:
            rows=catalog.source_rows(ROOT,key)
            self.assertTrue(all(row['status']=='PASS' for row in rows),rows)
            self.assertTrue(all('Presence only' in row['detail'] for row in rows))

    def test_selected_structural_components_never_probe_a_model(self):
        with patch.object(smoke,'probe_qwen') as probe,patch.object(smoke,'run') as execute:
            for key in catalog.SOURCE_ONLY:
                self.assertTrue(smoke.run_suite(ROOT,key)['rows'])
        probe.assert_not_called();execute.assert_not_called()

    def test_structural_musetalk_does_not_import_runtime(self):
        with tempfile.TemporaryDirectory() as folder,patch('musetalk_runtime.probe') as probe:
            smoke.component_rows(Path(folder),'MuseTalk',science_functional=False)
        probe.assert_not_called()

    def test_open_ports_are_not_positive_ownership_evidence(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(smoke,'_port',return_value=True):
            for name in ('ComfyUI','Media Preview'):
                rows=smoke.component_rows(Path(folder),name,science_functional=False)
                observed=[r for r in rows if 'port observation' in r['label']]
                self.assertEqual(len(observed),1)
                self.assertEqual(observed[0]['status'],'WARN')
                self.assertIn('ownership',observed[0]['detail'].lower())

    def test_qwen_conflict_is_failure(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(smoke,'probe_qwen',return_value={'state':'conflict'}):
            rows=smoke.component_rows(Path(folder),'Qwen',science_functional=False)
        self.assertEqual(rows[0]['status'],'FAIL')

    def test_cli_and_gui_share_canonical_report_key(self):
        with tempfile.TemporaryDirectory() as folder:
            for label in ('FLUX Image','Wan/VACE Video','Web Tools','Media Editing','Music Understanding'):
                with patch.object(sys,'argv',['diagnostic','--root',folder,'--component',label,'--structural-only']), \
                     patch.object(diagnostics,'detect',return_value={}),patch.object(diagnostics,'probe_qwen',return_value={}), \
                     patch.object(diagnostics,'smoke_suite',return_value={'counts':{'FAIL':0},'rows':[]}), \
                     patch.object(diagnostics,'handoff_state',return_value={}),patch.object(diagnostics,'gpu',return_value='not sampled'), \
                     patch.object(diagnostics,'rotate') as save,redirect_stdout(io.StringIO()):
                    self.assertEqual(diagnostics.main(),0)
                    self.assertEqual(save.call_args.args[1],catalog.resolve(label)['report_key'])
                    self.assertIn('No media/model generation',save.call_args.args[3]['coverage'])

    def test_linux_target_does_not_run_all_imports_or_vm(self):
        with patch.object(dependency_check,'check') as imports,patch('vm_runner.preflight') as vm:
            rows=linux.rows(ROOT,'Media Preview',imports=True)
        imports.assert_not_called();vm.assert_not_called()
        self.assertFalse(any('Secure VM' in row['label'] for row in rows))
        self.assertTrue(any('Media Preview source' in row['label'] for row in rows))

    def test_linux_selected_media_import_is_labeled_shared_cpu(self):
        with patch.object(dependency_check,'platform_checks',return_value=(
                ('Linux media CPU import check','python',(),()),('Science Workbench','python',(),()))), \
             patch.object(dependency_check,'check',return_value={'status':'PASS','label':'import','detail':'fixture'}) as check:
            rows=linux.rows(ROOT,'MuseTalk',imports=True)
        self.assertEqual(check.call_count,1)
        self.assertEqual(check.call_args.args[1][0],'Linux media CPU import check')
        self.assertTrue(any('Shared CPU media imports' in row['detail'] for row in rows))

    def test_reference_audit_covers_latest_gui_profile_modules(self):
        for path in ('Agent/chat_budgets.py','Agent/profile_hydration.py','ControlCenter/chat_zoom.py',
                     'ControlCenter/native_media_player.py','Tools/diagnostic_catalog.py',
                     'Scientific/coupled_physics.py','Scientific/coupled_physics_tool.py','Scientific/physics_viewer.py'):
            self.assertIn(path,reference_current.CRITICAL)

    def test_foundation_imports_include_current_budgets_and_hydration(self):
        entry=next(row for row in dependency_check.CHECKS if row[0]=='Foundation')
        self.assertTrue({'chat_budgets','chat_progress','profile_hydration','profile_lazy_state'}.issubset(entry[3]))


class Reports(unittest.TestCase):
    def test_malformed_saved_report_is_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'Data/Maintenance/fixture_latest.json';target.parent.mkdir(parents=True)
            target.write_text('[]')
            self.assertEqual(reports.saved_status(Path(folder),'fixture')[0],'UNVERIFIED')

    def test_success_exit_does_not_hide_fail_or_warn_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            for status in ('FAIL','WARN'):
                report=reports.save(Path(folder),'fixture','fixture',{'counts':{status:1}},0)
                self.assertEqual(report['status'],status)
                self.assertEqual(reports.saved_status(Path(folder),'fixture')[0],status)

    def test_old_saved_success_exit_with_failure_counts_is_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'Data/Maintenance/fixture_latest.json';target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'returncode':0,'status':'PASS','counts':{'FAIL':1}}))
            self.assertEqual(reports.saved_status(Path(folder),'fixture')[0],'FAIL')

    def test_envelope_carries_fresh_warning_status(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def child(*args,**kwargs):
                reports.save(root,'fixture','fresh warning',{'counts':{'WARN':2}},0)
                return SimpleNamespace(returncode=0,stdout='finished with warnings',stderr='')
            with patch.object(reports.subprocess,'run',side_effect=child):
                result=reports.run_tool(root,'fixture.py',[],'fixture','Fixture',1)
            self.assertEqual(result['status'],'WARN')
            self.assertEqual(reports.saved_status(root,'fixture_run')[0],'WARN')

    def test_missing_fresh_detail_does_not_reuse_prior_warning(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);reports.save(root,'fixture','old',{'counts':{'WARN':1}},0)
            with patch.object(reports.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='invocation complete',stderr='')):
                result=reports.run_tool(root,'fixture.py',[],'fixture','Fixture',1)
            saved=json.loads((root/'Data/Maintenance/fixture_run_latest.json').read_text())
            self.assertEqual(result['status'],'PASS');self.assertNotIn('detailed_report_key',saved)

    def test_fresh_report_cannot_override_failed_process(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def child(*args,**kwargs):
                reports.save(root,'fixture','done',{},0)
                return SimpleNamespace(returncode=2,stdout='failed after save',stderr='')
            with patch.object(reports.subprocess,'run',side_effect=child):
                result=reports.run_tool(root,'fixture.py',[],'fixture','Fixture',1)
            self.assertEqual(result['status'],'FAIL')

    def test_readiness_uses_authenticated_report_writer(self):
        with patch.object(reports,'save',return_value={}) as save:
            readiness.rotate(ROOT,'fixture',{'counts':{'FAIL':0}})
        self.assertEqual(save.call_args.args[1],'fresh_machine_validation')

    def test_linux_readiness_resolves_only_bundled_linux_paths(self):
        linux_os=SimpleNamespace(name='posix')
        with patch.object(platform_runtime,'os',linux_os),patch.object(readiness,'os',linux_os), \
             patch.object(platform_runtime.sys,'platform','linux'):
            paths=dict(readiness.required_paths(ROOT))
        self.assertEqual(paths['Portable Python'],ROOT/'Runtime/LinuxPython/run-python')
        self.assertEqual(paths['FFmpeg'],ROOT/'Runtime/FFmpeg/linux-x64/bin/ffmpeg')
        self.assertEqual(paths['Science package layer'],ROOT/'Runtime/LinuxPackages/science')

    def test_media_verifier_has_explicit_structural_scope(self):
        with patch.object(sys,'argv',['verify','--root',str(ROOT)]),patch.object(media,'rotate') as save,redirect_stdout(io.StringIO()):
            media.main()
        report=save.call_args.args[2]
        self.assertIn('Structural route/file presence only',report['coverage'])
        labels={row['label'] for row in report['rows']}
        self.assertIn('Native small-video route',labels);self.assertIn('Inline media controls',labels)

    def test_storage_reserve_failure_cannot_report_success(self):
        data={'storage':{'allowed':False},'scan_errors':[]}
        with patch.object(sys,'argv',['storage','--root',str(ROOT)]), \
             patch.object(storage_current,'audit',return_value=data),patch.object(storage_current,'render',return_value='fixture'), \
             patch.object(storage_current,'save') as save,redirect_stdout(io.StringIO()):
            self.assertEqual(storage_current.main(),1)
        self.assertEqual(save.call_args.args[3]['counts']['FAIL'],1)
        self.assertEqual(save.call_args.args[4],1)


if __name__=='__main__':unittest.main()
