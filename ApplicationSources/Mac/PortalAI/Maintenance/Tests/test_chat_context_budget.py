"""Context admission and UI distinctions without Tk, files, or model requests."""
import copy
import json
import queue
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,MagicMock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import native_chat as chat


def panel():
    p=chat.NativeChat.__new__(chat.NativeChat)
    p.settings={**chat.DEFAULT_SETTINGS,'max_output_tokens':1024}
    p.session={'id':'fixture','messages':[{'role':'user','content':'A short question'}],
               'context_state':{'summary':'','cursor':0,'summarized_turns':0}}
    p.store=SimpleNamespace(save_session=Mock())
    p.system_prompt=lambda:'Small system instructions'
    p.memory=SimpleNamespace(context_for=lambda *_args,**_kw:'')
    p._persistent_memory_query=lambda:''
    p._runtime_session_context=lambda _memory:'Synthetic runtime context'
    p._runtime_context_limit=lambda:8192
    return p


class ContextBudgetTests(unittest.TestCase):
    def test_image_cost_respects_minimum_with_old_settings_and_multiple_files(self):
        p=panel();p.settings['image_context_tokens']=900
        p._resolve_private_reference=lambda value:Path(value)
        m={'role':'user','content':'Describe','attachments':[
            {'name':'one.png','path':'one.png'},{'name':'two.png','path':'two.png'}]}
        text='Describe\n[Attached image: one.png | one.png]\n[Attached image: two.png | two.png]'
        self.assertEqual(p._message_cost(m)-chat.estimate_tokens(text),2048)
        p.effort=SimpleNamespace(active_plan={'model':{'image_min_tokens':2048}})
        self.assertEqual(p._message_cost(m)-chat.estimate_tokens(text),4096)
        self.assertEqual(p.settings['image_context_tokens'],900)

    def test_estimated_input_excludes_separate_output_and_safety_reserves(self):
        p=panel();first=p._context_plan()
        p.settings['max_output_tokens']=2048;second=p._context_plan()
        self.assertEqual(first['estimated_input'],second['estimated_input'])
        self.assertEqual(first['estimated_sent'],first['estimated_input']+1024+500+first['checkpoint_reserve'])
        self.assertEqual(second['estimated_sent'],second['estimated_input']+2048+500+second['checkpoint_reserve'])
        self.assertEqual(second['model_limit'],8192)

    def test_oversized_current_message_fails_before_api_serialization_without_mutation(self):
        p=panel();p.session['messages'][0]['content']='large input '*20000
        original=copy.deepcopy(p.session)
        with patch.object(p,'_api_row') as serialize:
            with self.assertRaisesRegex(RuntimeError,'current request does not fit'):p.api_messages()
        serialize.assert_not_called();self.assertEqual(p.session,original)

    def test_reply_ceiling_larger_than_context_is_adapted_without_changing_preferences(self):
        p=panel();p.settings['max_output_tokens']=8192
        p.api_messages()
        self.assertLess(p._admitted_output_tokens(),8192)
        self.assertGreaterEqual(p._admitted_output_tokens(),256)
        self.assertEqual(p._last_context_meta['estimated_sent'],7372)
        self.assertEqual(p.settings['max_output_tokens'],8192)

    def test_reported_62_token_overflow_adapts_real_payload_after_effort_overrides(self):
        p=panel();p.effort=SimpleNamespace(active_options={'max_tokens':2048})
        delta=4886-p._context_plan()['estimated_input']
        self.assertGreater(delta,0)
        p.session['messages'][0]['content']+='x'*(4*delta)
        original=copy.deepcopy(p.session)
        api,estimated=p.api_messages()
        self.assertEqual(p._last_context_meta['estimated_input'],4886)
        self.assertEqual(estimated,7372)
        self.assertEqual(p._admitted_output_tokens(),1986-p._last_context_meta['checkpoint_reserve'])
        p.cancel_event=threading.Event();p.active_http=chat.ActiveHTTP();p.ev=queue.Queue()
        p._completion_overrides={'max_tokens':8192}
        response=Mock(status=200)
        response.readline.side_effect=[b'data: {"choices":[{"delta":{"content":"Done"},"finish_reason":"stop"}]}\n']
        connection=Mock(sock=None);connection.getresponse.return_value=response
        with patch.object(p,'_response_watch',return_value=MagicMock()), \
             patch.object(chat,'model_id',return_value='synthetic-small-model'), \
             patch.object(chat.http.client,'HTTPConnection',return_value=connection):
            self.assertEqual(p._stream_completion_once(api),('Done','',[]))
        payload=json.loads(connection.request.call_args.kwargs['body'])
        self.assertEqual(payload['max_tokens'],1986-p._last_context_meta['checkpoint_reserve'])
        self.assertEqual(payload['messages'][-1]['content'],original['messages'][0]['content'])
        self.assertEqual(p.session,original)
        self.assertEqual(p.effort.active_options['max_tokens'],2048)

    def test_tool_evidence_remains_and_next_turn_reclaims_reply_capacity(self):
        p=panel();p.settings['max_output_tokens']=2048
        p.session['messages'] += [
            {'role':'assistant','content':'','tool_calls':[{'id':'done','type':'function',
                'function':{'name':'generate_image','arguments':'{"prompt":"A teapot"}'}}]},
            {'role':'tool','tool_call_id':'done','content':'Already generated output.png'}]
        delta=5500-p._context_plan()['estimated_input']
        p.session['messages'][0]['content']+='x'*(4*delta)
        original=copy.deepcopy(p.session)
        api,_=p.api_messages()
        self.assertEqual(p._admitted_output_tokens(),1372-p._last_context_meta['checkpoint_reserve'])
        self.assertEqual(api[-1]['content'],'Already generated output.png')
        self.assertEqual(api[-1]['tool_call_id'],'done')
        self.assertEqual(p.session,original)
        p.session['messages'].append({'role':'user','content':'Thank you'})
        p.api_messages()
        self.assertEqual(p._admitted_output_tokens(),2048)
        self.assertEqual(p.session['messages'][:-1],original['messages'])

    def test_current_input_must_leave_minimum_reply_room_and_full_safety_margin(self):
        for remaining in (255,256):
            p=panel();p.settings['max_output_tokens']=2048
            target=7372-500-remaining-p._context_plan()['checkpoint_reserve']
            delta=target-p._context_plan()['estimated_input']
            p.session['messages'][0]['content']+='x'*(4*delta)
            if remaining==255:
                with self.assertRaisesRegex(RuntimeError,'current request does not fit'):p.api_messages()
            else:
                p.api_messages();self.assertEqual(p._admitted_output_tokens(),256)

    def test_admitted_cap_is_not_inherited_by_another_chat(self):
        p=panel();p._last_context_meta={'session_id':'another','output_reserve':256}
        self.assertEqual(p._admitted_output_tokens(),1024)

    def test_explicit_small_context_budget_is_enforced(self):
        p=panel();p.settings['context_budget_tokens']=2500
        p.session['messages'][0]['content']='input '*4000
        with self.assertRaisesRegex(RuntimeError,'2,500-token'):p.api_messages()

    def test_summary_request_cannot_overflow_or_make_a_network_call(self):
        p=panel()
        with patch.object(p,'_wait_for_model') as wait,patch.object(chat.http.client,'HTTPConnection') as http:
            with self.assertRaisesRegex(RuntimeError,'summary input exceeds'):
                p._single_completion([{'role':'user','content':'large '*20000}],max_tokens=1200)
        wait.assert_not_called();http.assert_not_called()

    def test_only_complete_old_turns_are_omitted_and_saved_history_remains(self):
        p=panel();p.session['messages']=[
            {'role':'user','content':'old turn '*2500},
            {'role':'assistant','content':'old answer'},
            {'role':'user','content':'Current question'},
            {'role':'assistant','content':'Current answer'}]
        original=copy.deepcopy(p.session)
        api,_=p.api_messages()
        self.assertEqual([row['content'] for row in api if row['role'] in ('user','assistant')],['Current question','Current answer'])
        self.assertEqual(p.session,original)

    def test_label_separates_worker_input_estimate_capacity_and_reply_cap_without_io(self):
        p=panel();p.token_lbl=Mock();p.COL={'bad':'bad','gold':'gold','muted':'muted'}
        p._model_context_limit=8192
        p._last_context_meta={'session_id':'fixture','estimated_input':5000,'model_limit':8192}
        with patch.object(p,'_context_plan',side_effect=AssertionError('No prompt rebuild on UI')), \
             patch.object(chat,'model_props',side_effect=AssertionError('No HTTP on UI')):
            p.update_token_label()
        label=p.token_lbl.configure.call_args.kwargs['text']
        self.assertIn('Last input est. ~5,000',label)
        self.assertIn('context 8,192',label);self.assertIn('reply cap 1,024',label)
        self.assertNotIn(' · out ',label)

    def test_before_first_send_label_does_not_claim_history_is_full_model_input(self):
        p=panel();p.token_lbl=Mock();p.COL={'bad':'bad','gold':'gold','muted':'muted'}
        p.update_token_label()
        label=p.token_lbl.configure.call_args.kwargs['text']
        self.assertIn('History est.',label);self.assertIn('context unknown',label)

    def test_label_shows_admitted_reply_cap(self):
        p=panel();p.token_lbl=Mock();p.COL={'bad':'bad','gold':'gold','muted':'muted'}
        p._last_context_meta={'session_id':'fixture','estimated_input':5000,'model_limit':8192,'output_reserve':512}
        p.update_token_label()
        self.assertIn('reply cap 512',p.token_lbl.configure.call_args.kwargs['text'])


if __name__=='__main__':unittest.main()
