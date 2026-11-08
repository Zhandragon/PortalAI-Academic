import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import coding_model_route as route
import chat_model_switch as switch
import effort_policy
import model_preferences
import runtime_policy
from test_chat_model_switch import Scenario


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'swift.gguf').touch();(self.root/'vision.gguf').touch()
        self.policy={'selection':'qwen27-q4','variant_preference':'uncensored','coding_routing':'automatic',
                     'models':[{'id':route.MODEL_ID,'path':'swift.gguf','projector':'vision.gguf','coding_route_validated':True}]}
        self.messages=[{'role':'user','content':'Fix this Python function and add unit tests.'}]

    def test_bounded_intent_and_followups(self):
        for text in ['Review this SQL query','Build a website with a login page','Explain this code','Debug the failing unit tests']:
            self.assertTrue(route.coding_request([{'role':'user','content':text}]))
        self.assertTrue(route.coding_request(self.messages+[{'role':'user','content':'Okay, do it'}]))
        self.assertFalse(route.coding_request(self.messages+[{'role':'user','content':'What should I cook tonight?'}]))
        self.assertFalse(route.coding_request([{'role':'user','content':'Hello'},{'role':'tool','content':'write Python code'}]))

    def test_request_only_policy_never_mutates_general_selection(self):
        before=copy.deepcopy(self.policy)
        override=route.route_policy(self.root,self.policy,'deep',self.messages)
        self.assertEqual(override['selection'],route.MODEL_ID);self.assertEqual(before,self.policy)
        override['models'].clear();self.assertEqual(before,self.policy)

    def test_unsupported_choices_stay_pinned(self):
        for change in ({'selection':'qwen4-abliterated-q4'},{'selection':'qwen27-standard-q4'},
                       {'selection':route.MODEL_ID},{'coding_routing':'off'}, {'weight_edit_profile':'a'*24}):
            self.assertIsNone(route.route_policy(self.root,{**self.policy,**change},'deep',self.messages))
        self.assertIsNone(route.route_policy(self.root,{**self.policy,'selection':'auto'},'fast',self.messages))

    def test_missing_or_unvalidated_assets_cannot_route(self):
        self.policy['models'][0]['coding_route_validated']=False
        self.assertIsNone(route.route_policy(self.root,self.policy,'deep',self.messages))
        self.policy['models'][0]['coding_route_validated']=True
        (self.root/'vision.gguf').unlink()
        self.assertIsNone(route.route_policy(self.root,self.policy,'deep',self.messages))

    def test_upgrade_discovers_assets_without_replacing_saved_preferences(self):
        catalog=self.root/'catalog.json'
        catalog.write_text(json.dumps(self.policy['models'][0]),encoding='utf-8')
        policy={**self.policy,'models':[]}
        route.register_installed(self.root,policy,catalog)
        self.assertEqual(policy['selection'],'qwen27-q4')
        self.assertEqual(len(policy['models']),1)
        route.register_installed(self.root,policy,catalog)
        self.assertEqual(len(policy['models']),1)
        (self.root/'Agent').mkdir();(self.root/'Agent/academic_policy.py').touch()
        policy['models']=[];route.register_installed(self.root,policy,catalog)
        self.assertEqual(policy['models'],[])

    def test_account_settings_validate_and_preserve_route(self):
        expected='off' if (Path(model_preferences.__file__).parent/'academic_policy.py').is_file() else 'automatic'
        self.assertEqual(model_preferences.personal(self.policy)['coding_routing'],expected)
        self.assertEqual(model_preferences.merge(self.policy,{'coding_routing':'off'})['coding_routing'],'off')
        with self.assertRaises(ValueError):model_preferences.validate({'coding_routing':'surprise'})
        self.assertNotEqual(effort_policy.chat_policy_signature(self.policy),effort_policy.chat_policy_signature({**self.policy,'coding_routing':'off'}))

    def test_exact_50_gib_reserve_can_be_saved_without_hidden_percentage_floor(self):
        from settings_page import validated_storage
        values={'minimum_free_gib':50,'minimum_free_percent':0,'output_reserve_gib':0}
        saved=validated_storage(self.root,{'storage':{}},values)
        self.assertEqual(saved,{'minimum_free_gib':50,'minimum_free_fraction':0,'output_reserve_gib':0})
        for key in values:
            with self.assertRaises(ValueError):validated_storage(self.root,{'storage':{}},{**values,key:-1})

    def test_prepare_returns_ticket_and_finish_restores_once(self):
        model={'id':route.MODEL_ID,'absolute_path':str(self.root/'swift.gguf'),'gpu_layers':65}
        preview={'profiles':{'deep':{'model':model,'can_apply':True,'backend':{'backend':'cuda'}}}}
        result={'profile':'deep','model':model}
        with patch.object(runtime_policy,'load_effective_policy',return_value=self.policy), \
             patch.object(effort_policy,'capabilities',return_value=preview), \
             patch.object(switch,'prepare_chat',return_value=result) as prepare:
            value=switch.prepare_request(self.root,'deep',messages=self.messages,requested_at=123)
            self.assertEqual(prepare.call_args.kwargs['_expected_policy'],self.policy)
            self.assertEqual(prepare.call_args.kwargs['_policy']['selection'],route.MODEL_ID)
            self.assertTrue(prepare.call_args.kwargs['_require_full_gpu'])
            switch.finish_request(self.root,value)
            self.assertEqual(prepare.call_count,2)
            self.assertEqual(prepare.call_args.kwargs['_policy']['selection'],'qwen27-q4')
            self.assertEqual(prepare.call_args.kwargs['requested_at'],123)
            self.assertEqual(prepare.call_args.kwargs['_expected_model'],model['absolute_path'])
            event=threading.Event();event.set()
            self.assertIsNone(switch.finish_request(self.root,value,cancel_event=event))
            self.assertEqual(prepare.call_count,2)

    def test_low_memory_and_failed_launch_fall_back_before_tools(self):
        for layers in (0,65):
            preview={'profiles':{'deep':{'model':{'gpu_layers':layers},'can_apply':True,'backend':{'backend':'cuda'}}}}
            effects=[{'model':{}}] if not layers else [RuntimeError('insufficient memory'),{'model':{}}]
            with patch.object(runtime_policy,'load_effective_policy',return_value=self.policy), \
                 patch.object(effort_policy,'capabilities',return_value=preview), \
                 patch.object(switch,'prepare_chat',side_effect=effects) as prepare:
                value=switch.prepare_request(self.root,'deep',messages=self.messages)
                self.assertNotIn('coding_route',value)
                self.assertEqual(prepare.call_count,1 if not layers else 2)
                self.assertNotIn('_expected_policy',prepare.call_args.kwargs)

    def test_stop_is_not_treated_as_fallback(self):
        preview={'profiles':{'deep':{'model':{'gpu_layers':65},'can_apply':True,'backend':{'backend':'cuda'}}}}
        with patch.object(runtime_policy,'load_effective_policy',return_value=self.policy), \
             patch.object(effort_policy,'capabilities',return_value=preview), \
             patch.object(switch,'prepare_chat',side_effect=switch.PreparationCancelled('stopped')) as prepare:
            with self.assertRaises(switch.PreparationCancelled):switch.prepare_request(self.root,'deep',messages=self.messages)
            prepare.assert_called_once()

    def test_return_fence_leaves_replaced_model_untouched(self):
        with Scenario() as s:
            with self.assertRaises(switch.PreparationCancelled):
                switch.prepare_chat(s.root,'fast',_expected_model=str(s.root/'swift.gguf'))
            s.begin.assert_not_called();s.spawn.assert_not_called()

    def test_route_override_uses_baseline_setting_fence(self):
        with Scenario() as s:
            routed={**self.policy,'selection':route.MODEL_ID}
            with patch.object(runtime_policy,'load_effective_policy',return_value=self.policy):
                self.assertTrue(switch.prepare_chat(s.root,'fast',_policy=routed,_expected_policy=self.policy)['changed'])
            with patch.object(runtime_policy,'load_effective_policy',return_value={**self.policy,'coding_routing':'off'}):
                with self.assertRaises(switch.PreparationCancelled):
                    switch.prepare_chat(s.root,'fast',_policy=routed,_expected_policy=self.policy)

    def test_runtime_gpu_fit_failure_restores_previous_model(self):
        with Scenario() as s:
            s.plan['model']['gpu_layers']=12
            with self.assertRaisesRegex(RuntimeError,'fully fit'):
                switch.prepare_chat(s.root,'fast',_require_full_gpu=True)
            s.restore.assert_called_once();s.spawn.assert_not_called()

if __name__=='__main__':unittest.main()
