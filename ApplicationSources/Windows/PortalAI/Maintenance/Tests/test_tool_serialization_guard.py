"""General JSON framing and verified-download recovery; no model or live account."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(Path(__file__).parent)]
import native_chat as chat
from tool_protocol import ToolArgumentStream, verified_inert_download
from test_tool_protocol_recovery import fixture, call

VERIFIED=json.dumps({'ok':True,'result':{'path':'Outputs/source.png','bytes':123,
    'sha256':'a'*64,'download_verified':True,'executed':False}})

def download(identifier='download'):
    return {'id':identifier,'type':'function','function':{'name':'web',
        'arguments':json.dumps({'action':'download','arguments':{'url':'https://example.com/source.png'}})}}


class ToolSerializationTests(unittest.TestCase):
    def test_formatting_loop_is_bounded_across_frames(self):
        guard=ToolArgumentStream();guard.feed('{"action":')
        for _ in range(32):guard.feed(' '*8)
        with self.assertRaisesRegex(ValueError,'formatting whitespace'):guard.feed('\n')

    def test_large_file_contents_and_escaped_quotes_are_not_formatting(self):
        raw=json.dumps({'content':' '*10000+'"quoted"\\path\n'+('x'*100000),
                        'data':[{'value':'{]'}]})
        guard=ToolArgumentStream()
        for char in raw:guard.feed(char)
        guard.feed('\n\t ')
        self.assertTrue(guard.complete)

    def test_second_object_is_not_accepted_as_part_of_first_call(self):
        guard=ToolArgumentStream();guard.feed('{"action":"read"}')
        with self.assertRaisesRegex(ValueError,'after its complete'):guard.feed('\n{')

    def test_incomplete_json_is_never_made_complete_by_the_guard(self):
        guard=ToolArgumentStream();guard.feed('{"content":"unfinished')
        self.assertFalse(guard.complete)

    def test_literal_control_characters_inside_strings_fail_immediately(self):
        for char in ('\n','\r','\t','\x00'):
            guard=ToolArgumentStream();guard.feed('{"url":"https://example.com/')
            with self.assertRaisesRegex(ValueError,'control character'):guard.feed(char)

    def test_escape_validation_spans_frames_and_preserves_valid_unicode(self):
        for raw in ('{"text":"\\x','{"text":"\\u12Z'):
            guard=ToolArgumentStream()
            with self.assertRaisesRegex(ValueError,'escape'):
                for char in raw:guard.feed(char)
        guard=ToolArgumentStream()
        for char in r'{"text":"\\/\b\f\n\r\t\u4e2d\ud83d\ude00"}':guard.feed(char)
        self.assertTrue(guard.complete)

    def test_escaped_quote_loop_in_a_field_name_stops_early(self):
        guard=ToolArgumentStream()
        raw='{"action":"search","arguments":{"limit":8,"query' + ('\\"}'*100)
        with self.assertRaisesRegex(ValueError,'member name'):
            for char in raw:guard.feed(char)

    def test_nested_member_names_bounded_but_string_values_are_not(self):
        for raw in ('{"outer":{"'+'a'*257, '{"items":[{"'+'a'*257):
            with self.subTest(raw=raw[:20]),self.assertRaisesRegex(ValueError,'member name'):
                guard=ToolArgumentStream();guard.feed(raw)
        guard=ToolArgumentStream()
        guard.feed(json.dumps({'items':['a'*10000,{'text':'\\"}'*1000}], 'text':'b'*10000}))
        self.assertTrue(guard.complete)

    def test_mismatched_containers_fail_before_dispatch(self):
        for raw in ('{"x":[}', '{]'):
            with self.assertRaisesRegex(ValueError,'Mismatched'):
                ToolArgumentStream().feed(raw)

    def test_download_receipt_requires_actual_return_and_verification(self):
        args={'action':'download'};execution={'dispatched':True,'outcome':'returned'}
        self.assertTrue(verified_inert_download('web',args,VERIFIED,execution))
        for result in ('ERROR: timeout','{}',VERIFIED.replace('true','false'),VERIFIED.replace('"executed": false','"executed": true')):
            self.assertFalse(verified_inert_download('web',args,result,execution))
        self.assertFalse(verified_inert_download('web',args,VERIFIED,dict(execution,outcome='uncertain')))
        self.assertFalse(verified_inert_download('shell',args,VERIFIED,execution))

    def test_verified_download_allows_one_fresh_unresolved_step(self):
        p=fixture();p.tool_runtime.execute.side_effect=[VERIFIED,'fixture result']
        replies=[('','',[download()]),chat.TruncatedToolBatch('serialization limit'),
                 ('','',[call('next','next authorized fixture action')]),('Done.','',[])]
        with patch.object(p,'stream_completion',side_effect=replies):p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)
        self.assertEqual(p.session['messages'][-1]['content'],'Done.')
        result=next(m for m in p.session['messages'] if m.get('name')=='web')
        self.assertTrue(result['execution']['effectful'])

    def test_repair_cannot_repeat_the_completed_download(self):
        p=fixture();p.tool_runtime.execute.return_value=VERIFIED
        replies=[('','',[download()]),chat.TruncatedToolBatch('serialization limit'),('','',[download('again')])]
        with patch.object(p,'stream_completion',side_effect=replies):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertIn('repeated a previously attempted action',p.session['messages'][-1]['content'])

    def test_failed_download_keeps_retry_blocked(self):
        for result in ('ERROR: timeout',json.dumps({'ok':False}),json.dumps({'ok':True,'result':{'path':'unknown'}})):
            with self.subTest(result=result):
                p=fixture();p.tool_runtime.execute.return_value=result
                with patch.object(p,'stream_completion',side_effect=[('','',[download()]),chat.TruncatedToolBatch('limit')]) as stream:
                    p.agent_worker('test')
                self.assertEqual(stream.call_count,2)
                self.assertIn('Automatic format retry was blocked',p.session['messages'][-1]['content'])

    def test_verified_download_does_not_clear_an_earlier_unsafe_action(self):
        p=fixture();p.tool_runtime.execute.side_effect=['effect result',VERIFIED]
        replies=[('','',[call('effect','arbitrary effect')]),('','',[download()]),chat.TruncatedToolBatch('limit')]
        with patch.object(p,'stream_completion',side_effect=replies):p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)
        self.assertIn('Automatic format retry was blocked',p.session['messages'][-1]['content'])


if __name__=='__main__':unittest.main()
