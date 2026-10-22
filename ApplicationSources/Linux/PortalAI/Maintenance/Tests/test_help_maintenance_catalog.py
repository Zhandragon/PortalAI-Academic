"""Help navigation, current menu callbacks and honest new-feature coverage."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent')]
import help_catalog as help
import diagnostic_catalog as diagnostics
import installed_feature_checks as features
import dependency_check

class HelpCatalogTests(unittest.TestCase):
    def test_every_topic_belongs_to_one_visible_category(self):
        self.assertEqual(set(help.CATEGORIES),{r['category'] for r in help.TOPICS.values()})
        for rec in help.TOPICS.values():self.assertTrue(rec['title'] and rec['body'])
    def test_categories_filter_and_sort_titles(self):
        for category in ('All topics',*help.CATEGORIES):
            keys=help.filtered_topic_keys(category=category)
            titles=[help.TOPICS[k]['title'].casefold() for k in keys if k!='quick_start']
            self.assertEqual(titles,sorted(titles))
            if category!='All topics':self.assertTrue(all(help.TOPICS[k]['category']==category for k in keys))
        self.assertEqual(help.filtered_topic_keys()[0],'quick_start')
    def test_search_finds_new_features_and_empty_result(self):
        for query,key in [('offline demucs','demucs'),('HA Recovery','recovery'),('2B','small_vision'),('CPU MusicGen','musicgen')]:
            self.assertIn(key,help.filtered_topic_keys(query))
        self.assertEqual(help.filtered_topic_keys('nonexistent_493727'),[])
    def test_every_button_help_and_legacy_alias_resolves(self):
        for label,key in help.ACTION_TOPICS.items():self.assertEqual(help.action_topic(label),key);self.assertIn(key,help.TOPICS)
        for alias,key in help.TOPIC_ALIASES.items():self.assertEqual(help.canonical_topic(alias),key);self.assertIn(key,help.TOPICS)
    def test_specific_delete_help_does_not_resolve_to_memory(self):
        self.assertEqual(help.action_topic('Delete All Conversations + Memory'),'delete_conversations')
    def test_diagnostic_labels_are_sorted_and_unique(self):
        self.assertEqual(diagnostics.CHOICES[-1],'All')
        self.assertEqual(list(diagnostics.CHOICES[:-1]),sorted(diagnostics.CHOICES[:-1],key=str.casefold))
        self.assertEqual(len(diagnostics.CHOICES),len(set(diagnostics.CHOICES)))
        for key in features.FEATURES:self.assertEqual(diagnostics.resolve(key)['argument'],key)
    def test_optional_assets_warn_but_missing_code_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            result=features.rows(root,'musicgen');self.assertEqual([r['status'] for r in result],['FAIL','WARN'])
            for rel in features.FEATURES['musicgen'][1]:p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# source')
            result=features.rows(root,'musicgen');self.assertEqual([r['status'] for r in result],['PASS','WARN'])
    def test_feature_check_never_reads_connections_or_starts_a_process(self):
        with tempfile.TemporaryDirectory() as d,patch('subprocess.run') as run,patch.object(Path,'read_bytes',side_effect=AssertionError('not a content scan')):
            result=features.rows(Path(d)/'PortalAI','home_assistant')
        run.assert_not_called();self.assertTrue(result)
        self.assertTrue(all('Connections/' not in r['detail'] for r in result))
    def test_new_full_imports_are_separate_layers_and_no_codec_requirement(self):
        rows={r[0]:r for r in dependency_check.CHECKS}
        self.assertIn('Account runtime libraries',rows)
        self.assertIn('Windows music understanding / Demucs',rows)
        self.assertEqual(rows['Isolated Radeon packages'][2],('Runtime/AMDPython/packages',))
        self.assertFalse(any('torchcodec' in r[3] for r in rows.values()))
        self.assertIn('mmaudio.eval_utils',rows['MMAudio'][3])

    def test_account_wheel_inventory_accepts_current_and_retained_legacy_layout(self):
        for folder in ('Runtime/AccountPython/wheelhouse','Cache/account-runtime-wheelhouse'):
            with tempfile.TemporaryDirectory() as d:
                root=Path(d);assets=[]
                for name in ('cryptography','eth-account'):
                    relative=folder+'/'+name+'.whl';p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
                    assets.append({'name':name,'wheel':relative,'bytes':7,'sha256':'0'*64})
                receipt=root/'Maintenance/Imports/account-runtime-lock.json';receipt.parent.mkdir(parents=True)
                receipt.write_text(json.dumps({'assets':assets}),encoding='utf-8')
                self.assertEqual(features.account_repair_wheels(root)['status'],'PASS')
                p.write_bytes(b'truncated')
                self.assertEqual(features.account_repair_wheels(root)['status'],'WARN')
                assets[0]['wheel']='../../outside.whl'
                receipt.write_text(json.dumps({'assets':assets}),encoding='utf-8')
                self.assertEqual(features.account_repair_wheels(root)['status'],'FAIL')

    def test_all_features_report_without_optional_payloads(self):
        with tempfile.TemporaryDirectory() as d:
            rows=features.rows(Path(d)/'PortalAI')
        for title,_,_ in features.FEATURES.values():
            self.assertTrue(any(row['label']==title+' source' for row in rows))
        self.assertFalse(any(row['status']=='PASS' for row in rows))

def gui_functions(names,namespace):
    tree=ast.parse((ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8'))
    functions={node.name:node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name in names}
    module=ast.Module(body=[functions[name] for name in names],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),'actual_gui_functions','exec'),namespace)

class ContextMenuTests(unittest.TestCase):
    def test_new_component_names_reach_specific_diagnostic_not_generic_music_or_qwen(self):
        ns={};gui_functions(('_component_from_text',),ns)
        for text,expected in [('Qwen3-VL 2B Standard','small_vision'),('MusicGen CPU','musicgen'),
                              ('Music understanding / MOSS','music_understanding'),('Native FLUX Klein','native_flux'),
                              ('Portable Recovery','recovery'),('FFmpeg','ffmpeg'),('Radeon adapters','radeon'),
                              ('Small Vision (2B / 4B)','small_vision')]:
            component,topic=ns['_component_from_text'](text)
            self.assertEqual(diagnostics.resolve(component)['argument'],expected)
            self.assertIn(help.canonical_topic(topic),help.TOPICS)
    def namespace(self):
        ns={'action_topic':help.action_topic,'exit_in_progress':False,'account_gate':None,'native_chat_panel':None,
            '_text_edit_items':lambda w:[], '_component_from_text':lambda t:(None,None),
            '_topic_title':{k:r['title'] for k,r in help.TOPICS.items()},'_help_command':lambda *a:Mock(),
            '_show_full_launcher_menu':Mock(),'app':Mock()}
        for name in ('start_components','run_system_test','diagnose','stop_components','minimize_to_tray',
                     'begin_exit_portableai','show_or_run_fresh_machine_validator','show_or_run_media_stack_verify',
                     'show_or_run_component_diagnostic','show_or_run_storage_audit','open_maintenance_folder',
                     'show_general_cleanup_panel','run_root_hygiene_now','show_dependency_probe_panel',
                     'show_or_run_root_reference_audit','show_maintenance_delete_confirm'):ns[name]=Mock(name=name)
        gui_functions(('_menu_item','_context_topic','_context_items'),ns)
        return ns
    def test_current_labels_dispatch_correct_callback_and_help(self):
        cases=[('Safe Cleanup Plan','show_general_cleanup_panel','cleanup'),('Root-only Cleanup','run_root_hygiene_now','declutter'),
               ('Reference Integrity','show_or_run_root_reference_audit','reference'),('Maintenance Reports','open_maintenance_folder','reports'),
               ('Run selected','show_or_run_component_diagnostic','diagnostics'),('Full diagnosis','diagnose','diagnostics'),
               ('Exit PortalAI','begin_exit_portableai','exit'),('Stop all components','stop_components','stop')]
        for text,callback,topic in cases:
            ns=self.namespace();items,key=ns['_context_items'](None,text,'maintenance')
            self.assertEqual(key,topic);ns[callback].assert_not_called();items[0]['command']();ns[callback].assert_called_once()
    def test_context_deletion_opens_confirmation(self):
        ns=self.namespace();items,key=ns['_context_items'](None,'Delete All Outputs','maintenance')
        ns['show_maintenance_delete_confirm'].assert_not_called();items[0]['command']()
        ns['show_maintenance_delete_confirm'].assert_called_once_with('outputs');self.assertEqual(key,'delete_outputs')
    def test_queued_menu_action_refuses_after_account_lock_or_exit(self):
        ns=self.namespace();items,_=ns['_context_items'](None,'Startup','controls')
        ns['account_gate']=Mock(locked=True);items[0]['command']();ns['start_components'].assert_not_called()
        ns['account_gate']=None;ns['exit_in_progress']=True;items[0]['command']();ns['start_components'].assert_not_called()

class OwnedWorkerCoverageTests(unittest.TestCase):
    def test_stop_selects_new_owned_workers_and_preserves_foreign_and_gui(self):
        spec=importlib.util.spec_from_file_location('current_stop',ROOT/'Launchers/Stop_PortableAI.py')
        stop=importlib.util.module_from_spec(spec);spec.loader.exec_module(stop)
        names=['Agent/music_cpu_entry.py','Agent/radeon_edit_entry.py','Agent/audio_inpaint_amd_entry.py',
               'MusicUnderstanding/runtime_driver.py','MusicUnderstanding/clap_worker.py','Scientific/protein_design_worker.py']
        rows=[{'ProcessId':10000+i,'ExecutablePath':str(ROOT/'Runtime/BootstrapPython/python.exe'),
               'CommandLine':str(ROOT/rel),'Name':'python.exe'} for i,rel in enumerate(names)]
        rows+=[{'ProcessId':11000,'ExecutablePath':'C:/unrelated/python.exe','CommandLine':str(ROOT/names[0])},
               {'ProcessId':11001,'ExecutablePath':str(ROOT/'Runtime/BootstrapPython/python.exe'),'CommandLine':str(ROOT/'ControlCenter/PortableAI_GUI.py')}]
        with patch.object(stop,'cim_processes',return_value=rows):pids,_=stop.portable_process_pids(ROOT)
        self.assertEqual(pids,set(range(10000,10000+len(names))))

if __name__=='__main__':unittest.main()
