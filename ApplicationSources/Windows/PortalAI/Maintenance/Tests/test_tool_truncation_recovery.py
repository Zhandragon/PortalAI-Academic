"""Bounded format recovery with synthetic model frames; no real media generation."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(Path(__file__).parent)]
import native_chat as chat
from tool_protocol import read_only_tool_attempt
from test_tool_protocol_recovery import fixture, call, PRINTED

def truncated():return chat.TruncatedToolBatch("Qwen ended a tool response with finish reason 'length'; the entire batch was withheld.")

class TruncatedToolRecoveryTests(unittest.TestCase):
    def test_one_fresh_call_with_thinking_disabled_and_options_restored(self):
        p=fixture();p._completion_overrides={'temperature':0.2,'chat_template_kwargs':{'other':True}}
        original=copy.deepcopy(p._completion_overrides);seen=[];fresh=call('fresh','one authorized fixture action')
        responses=[truncated(),('','',[fresh]),('Done from saved result.','',[])]
        def respond(api):
            seen.append((copy.deepcopy(api),copy.deepcopy(p._completion_overrides)))
            result=responses.pop(0)
            if isinstance(result,Exception):raise result
            return result
        with patch.object(p,'stream_completion',side_effect=respond):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once_with('shell',{'command':'one authorized fixture action'})
        self.assertFalse(seen[1][1]['chat_template_kwargs']['enable_thinking'])
        self.assertTrue(seen[1][1]['chat_template_kwargs']['other'])
        self.assertIn('No tools from that response were executed',seen[1][0][-1]['content'])
        self.assertEqual(p._completion_overrides,original)
        self.assertEqual(p.session['messages'][-1]['content'],'Done from saved result.')

    def test_second_truncation_stops_without_dispatch(self):
        p=fixture()
        with patch.object(p,'stream_completion',side_effect=truncated()) as stream:p.agent_worker('test')
        self.assertEqual(stream.call_count,2);p.tool_runtime.execute.assert_not_called()
        self.assertIn("'length'",p.session['messages'][-1]['content'])

    def test_truncation_and_printed_protocol_share_one_retry_budget(self):
        p=fixture()
        with patch.object(p,'stream_completion',side_effect=[truncated(),(PRINTED,'',[])]) as stream:p.agent_worker('test')
        self.assertEqual(stream.call_count,2);p.tool_runtime.execute.assert_not_called()
        self.assertIn('still returned tool syntax',p.session['messages'][-1]['content'])

    def test_prior_effect_or_uncertain_failure_blocks_automatic_correction(self):
        for failure in (False,True):
            with self.subTest(failure=failure):
                p=fixture()
                if failure:p.tool_runtime.execute.side_effect=TimeoutError('uncertain effect')
                with patch.object(p,'stream_completion',side_effect=[('','',[call('first','first effect')]),truncated()]) as stream:
                    p.agent_worker('test')
                self.assertEqual(stream.call_count,2);p.tool_runtime.execute.assert_called_once()
                self.assertIn('Automatic format retry was blocked',p.session['messages'][-1]['content'])

    def test_read_only_page_history_allows_fresh_correction(self):
        p=fixture();page={'id':'page','type':'function','function':{'name':'web','arguments':json.dumps({'action':'read','arguments':{'url':'https://example.com'}})}}
        with patch.object(p,'stream_completion',side_effect=[('','',[page]),truncated(),('','',[call('fresh','next authorized action')]),('Done.','',[])]):
            p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)
        self.assertEqual(p.session['messages'][-1]['content'],'Done.')

    def test_repaired_call_cannot_repeat_previous_page_action(self):
        p=fixture();page={'id':'page','type':'function','function':{'name':'web','arguments':json.dumps({'action':'read','arguments':{'url':'https://example.com'}})}}
        again={**page,'id':'other'}
        with patch.object(p,'stream_completion',side_effect=[('','',[page]),truncated(),('','',[again])]):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertIn('repeated a previously attempted action',p.session['messages'][-1]['content'])

    def test_read_classification_does_not_extend_to_browser_writes_or_downloads(self):
        self.assertTrue(read_only_tool_attempt('web',{'action':'read','arguments':{'document':'cached'}},ROOT))
        for action in ('download','api','click','fill','navigate','unknown'):
            self.assertFalse(read_only_tool_attempt('web',{'action':action},ROOT))

    def test_cancel_or_revoked_login_prevents_corrected_dispatch(self):
        for revoke in (False,True):
            with self.subTest(revoke=revoke):
                p=fixture();active={'value':True};responses=[truncated(),('','',[call('fresh','new action')])]
                def check():
                    if not active['value']:raise PermissionError('login ended')
                def respond(_api):
                    result=responses.pop(0)
                    if isinstance(result,Exception):raise result
                    if revoke:active['value']=False
                    else:p.cancel_event.set()
                    return result
                p._check_login=check
                with patch.object(p,'stream_completion',side_effect=respond):p.agent_worker('test')
                p.tool_runtime.execute.assert_not_called()

    def test_correction_requires_admitted_context(self):
        p=fixture();p._last_context_meta={'budget':100};p.api_messages=lambda:([],99)
        with patch.object(p,'stream_completion',side_effect=truncated()) as stream:p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_not_called()
        self.assertIn('does not fit',p.session['messages'][-1]['content'])

    def test_real_sse_partial_arguments_are_never_extracted_or_executed(self):
        p=fixture();fresh=call('fresh','use the authorized fixture result')
        partial={'id':'partial','type':'function','function':{'name':'shell','arguments':'{"command":"NEVER_EXECUTE'}}
        connections=[]
        for delta,finish in (({'tool_calls':[{'index':0,**partial}]},'length'),
                             ({'tool_calls':[{'index':0,**fresh}]},'tool_calls'),
                             ({'content':'Result checked.'},'stop')):
            response=Mock(status=200)
            response.readline.side_effect=[b'data: '+json.dumps({'choices':[{'delta':delta,'finish_reason':finish}]}).encode()+b'\n',b'']
            conn=Mock();conn.getresponse.return_value=response;connections.append(conn)
        with patch.object(p,'_wait_for_model',return_value=True),patch.object(chat,'model_id',return_value='fixture'), \
             patch.object(chat.http.client,'HTTPConnection',side_effect=connections):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once_with('shell',{'command':'use the authorized fixture result'})
        payload=json.loads(connections[1].request.call_args.kwargs['body'])
        self.assertFalse(payload['chat_template_kwargs']['enable_thinking'])
        self.assertNotIn('NEVER_EXECUTE',json.dumps(payload))
        self.assertNotIn('NEVER_EXECUTE',json.dumps(p.session))
        self.assertEqual(p.session['messages'][-1]['content'],'Result checked.')

if __name__=='__main__':unittest.main()
