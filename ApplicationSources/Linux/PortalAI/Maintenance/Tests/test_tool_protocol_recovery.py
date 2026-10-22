"""Format-only inference repair; printed commands are never executed or replayed."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(Path(__file__).parent)]
import native_chat as chat
from test_chat_handoff import panel

PRINTED = '''<tool_call>
<function=shell>
<parameter=command>
.\\Tools\\portable_python.cmd Agent\\ai_tools.py autoedit "Outputs/WebImages/example.jpg" "change the color of her shirt" --target "shirt"
</parameter>
</function>
</tool_call>'''


def call(identifier, command):
    return {'id':identifier, 'type':'function', 'function':{'name':'shell', 'arguments':json.dumps({'command':command})}}


def fixture():
    result = panel()
    result.root = ROOT
    result.settings['tool_step_limit'] = 6
    result._last_context_meta = {'budget':8192}
    result.session['messages'][0]['content'] = 'Change the shirt color in the supplied photo.'
    return result


class ToolTextRecoveryTests(unittest.TestCase):
    def test_exact_reported_xml_requires_fresh_api_call_not_extracted_command(self):
        p=fixture(); actual=call('fresh', 'fresh authorized fixture command')
        with patch.object(p,'stream_completion',side_effect=[(PRINTED,'',[]), ('','',[actual]), ('Done from result.','',[])]) as stream:
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once_with('shell', {'command':'fresh authorized fixture command'})
        correction=stream.call_args_list[1].args[0][-1]
        self.assertEqual(correction['role'],'system')
        self.assertNotIn('example.jpg',correction['content'])
        self.assertNotIn(PRINTED,[row.get('content') for row in p.session['messages']])
        self.assertTrue(next(row for row in p.session['messages'] if row.get('tool_calls'))['tool_protocol_repaired'])
        self.assertEqual(p.session['messages'][-1]['content'],'Done from result.')

    def test_repeated_printed_xml_stops_after_one_correction_without_tools(self):
        p=fixture()
        with patch.object(p,'stream_completion',return_value=(PRINTED,'',[])) as stream:p.agent_worker('test')
        self.assertEqual(stream.call_count,2);p.tool_runtime.execute.assert_not_called()
        self.assertIn('still returned tool syntax',p.session['messages'][-1]['content'])

    def test_new_edit_after_completed_search_is_allowed_without_replaying_search(self):
        p=fixture();p.session['messages'][0]['content']='Find a photo, then change the shirt color.'
        search=call('search','python Agent/web_tools.py image-search "specific person"')
        edit=call('edit','python Agent/ai_tools.py autoedit "Outputs/found.jpg" "blue shirt"')
        with patch.object(p,'stream_completion',side_effect=[('','',[search]),(PRINTED,'',[]),('','',[edit]),('Edited.','',[])]):
            p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)
        self.assertEqual([args.args[1]['command'] for args in p.tool_runtime.execute.call_args_list],
                         [json.loads(search['function']['arguments'])['command'],json.loads(edit['function']['arguments'])['command']])

    def test_correction_after_prior_effect_cannot_replay_a_new_id_or_spelling(self):
        p=fixture();first=call('first','one effect');replay=call('new-id','one effect')
        replay['function']['arguments']=json.dumps({'command':'one effect '})
        with patch.object(p,'stream_completion',side_effect=[('','',[first]),(PRINTED,'',[]),('','',[replay,call('other','new effect')])]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count,2)
        p.tool_runtime.execute.assert_called_once()
        self.assertIn('Automatic format retry was blocked',p.session['messages'][-1]['content'])
        self.assertEqual(sum(row['role']=='tool' for row in p.session['messages']),1)

    def test_stalled_image_lookup_still_allows_corrected_autoedit_once(self):
        p=fixture();p.session['messages'][0]['content']='Find a photo then edit the downloaded candidate.'
        p.tool_runtime.execute.side_effect=['{"success":true,"images":[]}']*4+['{"success":true,"path":"Outputs/edited.jpg"}']
        edit=call('edit','python Agent/ai_tools.py autoedit "Outputs/found.jpg" "blue shirt"')
        responses=[('','',[call('s1','python Agent/web_tools.py image-search "first query"')]),
                   ('','',[call('s2','python Agent/web_tools.py image-search "broader query"')]),
                   ('','',[call('s3','python Agent/web_tools.py image-search "event date query"')]),
                   ('','',[call('s4','python Agent/web_tools.py image-search "alternate source query"')]),
                   (PRINTED,'',[]),('','',[edit]),('Edited.','',[])]
        seen=[]
        def respond(api):
            seen.append((p._reply_without_tools,copy.deepcopy(api)))
            return responses.pop(0)
        with patch.object(p,'stream_completion',side_effect=respond):p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,5)
        self.assertTrue(all(not disabled for disabled,_api in seen))
        self.assertIn('Other requested actions',seen[4][1][-1]['content'])
        self.assertEqual(p.session['messages'][-1]['content'],'Edited.')

    def test_search_guidance_and_format_repair_share_the_same_context_budget(self):
        p=fixture();p._last_context_meta={'budget':100};p.api_messages=lambda:([],0)
        p.tool_runtime.execute.return_value='{"images":[]}'
        # Each 60-token note fits separately; both together must be rejected.
        with patch.object(chat,'estimate_tokens',return_value=60), \
             patch.object(p,'stream_completion',side_effect=[('','',[call('s','python Agent/web_tools.py image-search "query"')]),(PRINTED,'',[])]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count,2);p.tool_runtime.execute.assert_called_once()
        self.assertIn('does not fit',p.session['messages'][-1]['content'])

    def test_unknown_effect_from_failed_tool_is_not_replayed(self):
        p=fixture();p.tool_runtime.execute.side_effect=TimeoutError('effect uncertain')
        with patch.object(p,'stream_completion',side_effect=[('','',[call('first','uncertain effect')]),(PRINTED,'',[]),('','',[call('retry','uncertain effect')])]):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertIn('Automatic format retry was blocked',p.session['messages'][-1]['content'])

    def test_cancel_during_correction_prevents_tool_execution(self):
        p=fixture();responses=[(PRINTED,'',[]),('','',[call('corrected','new action')])]
        def respond(_api):
            if len(responses)==1:p.cancel_event.set()
            return responses.pop(0)
        with patch.object(p,'stream_completion',side_effect=respond) as stream:p.agent_worker('test')
        self.assertEqual(stream.call_count,2);p.tool_runtime.execute.assert_not_called()

    def test_login_revoked_during_correction_prevents_tool_execution(self):
        p=fixture();active={'value':True};responses=[(PRINTED,'',[]),('','',[call('corrected','new action')])]
        def check():
            if not active['value']:raise PermissionError('login ended')
        def respond(_api):
            if len(responses)==1:active['value']=False
            return responses.pop(0)
        p._check_login=check
        with patch.object(p,'stream_completion',side_effect=respond) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count,2)
        p.tool_runtime.execute.assert_not_called()
        self.assertTrue(any('login ended' in str(row) for row in p.ev.queue))

    def test_cancelled_reply_does_not_trigger_correction(self):
        p=fixture()
        def cancelled(_api):p.cancel_event.set();return PRINTED,'',[]
        with patch.object(p,'stream_completion',side_effect=cancelled) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called()

    def test_ended_login_cannot_start_correction(self):
        p=fixture();active={'value':True}
        def check():
            if not active['value']:raise PermissionError('login ended')
        def respond(_api):
            active['value']=False;return PRINTED,'',[]
        p._check_login=check
        with patch.object(p,'stream_completion',side_effect=respond) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called()
        self.assertTrue(any('login ended' in str(row) for row in p.ev.queue))

    def test_protocol_example_is_ordinary_text_without_execution(self):
        p=fixture();p.session['messages'][0]['content']='Show an example XML tool call without running it.'
        with patch.object(p,'stream_completion',return_value=(PRINTED,'',[])) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called()
        self.assertEqual(p.session['messages'][-1]['content'],PRINTED)

    def test_insufficient_context_refuses_correction_before_request(self):
        p=fixture();p._last_context_meta={'budget':100};p.api_messages=lambda:([],99)
        with patch.object(p,'stream_completion',return_value=(PRINTED,'',[])) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called()
        self.assertIn('does not fit',p.session['messages'][-1]['content'])

    def test_second_format_failure_later_in_turn_is_not_retried_again(self):
        p=fixture()
        with patch.object(p,'stream_completion',side_effect=[(PRINTED,'',[]),('','',[call('first','authorized effect')]),(PRINTED,'',[])]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count,3);p.tool_runtime.execute.assert_called_once()
        self.assertIn('single format-repair attempt is exhausted',p.session['messages'][-1]['content'])

    def test_invalid_structured_batch_remains_rejected_without_format_retry(self):
        p=fixture();invalid=call('broken','effect');invalid['function']['arguments']='{broken'
        with patch.object(p,'stream_completion',return_value=('', '', [invalid])) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called()

    def test_fragmented_real_sse_content_is_corrected_to_structured_sse(self):
        p=fixture();actual=call('structured','one safe fixture action')
        responses=[]
        batches=[[
            {'choices':[{'delta':{'content':PRINTED[:40]}}]},
            {'choices':[{'delta':{'content':PRINTED[40:]},'finish_reason':'stop'}]}],
            [{'choices':[{'delta':{'tool_calls':[{'index':0,**actual}]},'finish_reason':'tool_calls'}]}],
            [{'choices':[{'delta':{'content':'Result checked.'},'finish_reason':'stop'}]}]]
        for batch in batches:
            response=Mock(status=200)
            response.readline.side_effect=[*(b'data: '+json.dumps(row).encode()+b'\n' for row in batch),b'']
            connection=Mock();connection.getresponse.return_value=response;responses.append(connection)
        with patch.object(p,'_wait_for_model',return_value=True),patch.object(chat,'model_id',return_value='fixture'), \
             patch.object(chat.http.client,'HTTPConnection',side_effect=responses):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once_with('shell',{'command':'one safe fixture action'})
        self.assertEqual(p.session['messages'][-1]['content'],'Result checked.')


if __name__=='__main__':unittest.main()
