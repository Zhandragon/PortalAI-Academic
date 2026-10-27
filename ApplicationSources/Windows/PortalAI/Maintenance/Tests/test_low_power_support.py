import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
from low_power_support import supported_model, guidance, missing_source_hint
from source_map import source_map

class SupportTests(unittest.TestCase):
    def test_missing_public_path_suggests_exact_filename_without_reading_code(self):
        import maintenance_tools
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Agent').mkdir();(root/'Tools').mkdir()
            (root/'Agent/lookup.py').write_text('raise AssertionError("must not execute")')
            (root/'Agent/not_lookup.py').write_text('x=1')
            runtime=SimpleNamespace(root=root,settings={'low_power_support':True},_account_role=lambda:'admin')
            for identifier in ('Qwen3-4B-Q4_K_M.gguf','Qwen3-1.7B-Q8_0.gguf'):
                with patch('native_chat.model_id',return_value=identifier):
                    reply=json.loads(maintenance_tools.execute(runtime,'source_map',{'path':'Tools/lookup.py'}))
                self.assertFalse(reply['ok']);self.assertFalse(reply['automatic_retry'])
                self.assertEqual([x['path'] for x in reply['candidates']],['Agent/lookup.py'])
                self.assertNotIn('raise AssertionError',json.dumps(reply))
    def test_suggestions_require_enabled_setting_and_actual_small_model(self):
        import maintenance_tools
        with tempfile.TemporaryDirectory() as tmp:
            runtime=SimpleNamespace(root=Path(tmp),settings={},_account_role=lambda:'admin')
            with patch('native_chat.model_id') as query:
                with self.assertRaises(FileNotFoundError):maintenance_tools.execute(runtime,'source_map',{'path':'Tools/lookup.py'})
                query.assert_not_called()
            runtime.settings['low_power_support']=True
            for identifier in ('Qwen3.8-27B-Q4_K_M.gguf','unknown'):
                with patch('native_chat.model_id',return_value=identifier),patch('source_map.source_map',side_effect=FileNotFoundError) as lookup:
                    with self.assertRaises(FileNotFoundError):maintenance_tools.execute(runtime,'source_map',{'path':'Tools/lookup.py'})
                    lookup.assert_called_once()
    def test_suggestions_never_expand_permission_denials_or_private_paths(self):
        import maintenance_tools
        with tempfile.TemporaryDirectory() as tmp:
            runtime=SimpleNamespace(root=Path(tmp),settings={'low_power_support':True},_account_role=lambda:'admin')
            with patch('native_chat.model_id') as query:
                for path in ('Private/lookup.py','../Agent/lookup.py'):
                    with self.assertRaises(PermissionError):maintenance_tools.execute(runtime,'source_map',{'path':path})
                query.assert_not_called()
            self.assertIsNone(missing_source_hint(runtime,'qwen4-q4','Private/lookup.py'))
            runtime._account_role=lambda:'guest'
            with self.assertRaises(PermissionError):missing_source_hint(runtime,'qwen4-q4','Tools/lookup.py')
    def test_suggestion_scope_and_stop_are_rechecked_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime=SimpleNamespace(root=Path(tmp),_account_role=Mock(side_effect=['admin','guest']),_cancel_epoch=0)
            result={'items':[],'scan_truncated':False,'next_offset':None}
            with patch('source_map.source_map',return_value=json.dumps(result)):
                with self.assertRaises(PermissionError):missing_source_hint(runtime,'qwen4-q4','Tools/lookup.py')
            runtime._account_role=lambda:'admin'
            def stopped(*a,**kw):runtime._cancel_epoch+=1;return json.dumps(result)
            with patch('source_map.source_map',side_effect=stopped):
                with self.assertRaisesRegex(RuntimeError,'cancelled'):missing_source_hint(runtime,'qwen1.7-q8','Tools/lookup.py')
    def test_suggestion_candidates_and_scan_status_are_bounded(self):
        runtime=SimpleNamespace(root=Path('.'),_account_role=lambda:'admin')
        rows=[{'path':f'Agent/folder{i}/lookup.py','bytes':1} for i in range(12)]
        with patch('source_map.source_map',return_value=json.dumps({'items':rows,'scan_truncated':False,'next_offset':None})):
            result=json.loads(missing_source_hint(runtime,'qwen4-q4','Tools/lookup.py'))
        self.assertEqual(len(result['candidates']),8);self.assertTrue(result['scan_truncated'])
    def test_actual_small_model_names_and_larger_unknown_models(self):
        for value in ('Qwen3-1.7B-Q8_0.gguf','Qwen3-4B-Q4_K_M.gguf','Qwen3.8-4B-Abliterated-Q4_K_M.gguf','qwen4-q4','qwen1.7-q8'):
            self.assertTrue(supported_model(value),value)
        for value in ('Qwen3.8-27B-Abliterated-Q4_K_M.gguf','qwen27-q4','unknown','Qwen-14B.gguf'):
            self.assertFalse(supported_model(value),value)
    def test_empty_search_receipts_trigger_general_navigation_guidance(self):
        rows=[{'role':'tool','name':'source_search','content':'{"matches":[]}'}]*2
        self.assertIn('Host observation',guidance('Qwen3-4B.gguf',rows))
        self.assertNotIn('Host observation',guidance('Qwen3-4B.gguf',[{'role':'user','content':'{"matches":[]}'}]*2))
        self.assertEqual(guidance('Qwen3-27B.gguf',rows),'')
    def test_native_prompt_requires_enabled_setting_and_current_small_model(self):
        import native_chat
        panel=native_chat.NativeChat.__new__(native_chat.NativeChat);panel.root=ROOT
        panel.settings={'use_master_instructions':False,'low_power_support':True}
        panel.session={'messages':[]};panel.store=SimpleNamespace(custom_instructions=lambda:'')
        panel._request_tool_scope='maintenance'
        with patch.object(native_chat,'model_id',return_value='Qwen3-1.7B-Q8_0.gguf'):
            self.assertIn('low-power model support is active',panel.system_prompt())
        with patch.object(native_chat,'model_id',return_value='Qwen3.8-27B-Q4_K_M.gguf'):
            self.assertNotIn('low-power model support is active',panel.system_prompt())
        panel.settings['low_power_support']=False
        with patch.object(native_chat,'model_id') as query:
            self.assertNotIn('low-power model support is active',panel.system_prompt());query.assert_not_called()
    def test_textual_tool_calls_do_not_become_working_summaries(self):
        from test_chat_reasoning_continuation import fixture
        from test_chat_summary_recovery import summary_response
        from chat_summary_recovery import IncompleteSummary
        panel=fixture()
        with summary_response(panel,finish='stop',content='<tool_call><function=source_search>{}</function></tool_call>'):
            with self.assertRaises(IncompleteSummary) as caught:
                panel._single_completion([{'role':'user','content':'Summarize saved results'}],max_tokens=256)
        self.assertEqual(caught.exception.reason,'tool_markup_in_summary')
    def test_support_and_full_tool_menu_fit_normal_small_model_context(self):
        import native_chat
        from test_chat_context_recovery import small_panel, exchange
        for name in ('Qwen3-1.7B-Q8_0.gguf','Qwen3-4B-Q4_K_M.gguf'):
            panel=small_panel();panel.root=ROOT
            panel.settings['low_power_support']=True
            panel.store.custom_instructions=lambda:'Inspect the host and explain what you find.'
            panel.system_prompt=lambda:native_chat.NativeChat.system_prompt(panel)
            panel.memory.chat_included=lambda _:True;panel.memory.config={}
            panel._runtime_session_context=lambda memory='':native_chat.NativeChat._runtime_session_context(panel,memory)
            exchange(panel)
            panel.session['messages'].append({'role':'user','content':'Explain the directory listing.'})
            with patch.object(native_chat,'model_id',return_value=name),patch('runtime_policy.load_effective_policy',return_value={}):
                panel.compact_context_if_needed();api,estimate=panel.api_messages()
            self.assertLessEqual(estimate,7372)
            self.assertIn('low-power model support is active',json.dumps(api))
    def test_map_discovers_files_and_exact_nested_unicode_offsets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Agent').mkdir();(root/'ControlCenter').mkdir()
            source='# café\nclass Reader:\n    def load(self):\n        return 3\n'
            (root/'Agent/reader.py').write_text(source,encoding='utf-8',newline='\n')
            runtime=SimpleNamespace(root=root,_account_role=lambda:'admin')
            rows=json.loads(source_map(runtime,query='reader'))['items']
            self.assertEqual(rows,[{'path':'Agent/reader.py','bytes':len(source.encode())}])
            outline=json.loads(source_map(runtime,path='Agent/reader.py',query='load'))
            item=outline['items'][0];self.assertEqual(item['symbol'],'Reader.load')
            self.assertTrue(source[item['offset']:item['end_offset']].lstrip().startswith('def load'))
            self.assertEqual(len(outline['sha256']),64)
    def test_map_rejects_guest_private_paths_and_role_revocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Agent').mkdir();(root/'Agent/a.py').write_text('x=1')
            runtime=SimpleNamespace(root=root,_account_role=lambda:'guest')
            with self.assertRaises(PermissionError):source_map(runtime)
            runtime._account_role=lambda:'admin'
            for path in ('Private','../Agent',str(root/'Agent')):
                with self.assertRaises(PermissionError):source_map(runtime,path=path)
            runtime._account_role=Mock(side_effect=['admin','admin','guest'])
            with self.assertRaises(PermissionError):source_map(runtime)

if __name__=='__main__':unittest.main()
