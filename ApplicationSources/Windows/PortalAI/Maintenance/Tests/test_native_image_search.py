"""Native image lookup preserves bounded providers, evidence and account guards."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import web_capabilities as web
import web_tools
from web_tool_api import TOOL
from image_lookup_policy import ImageLookupCycle
from tool_protocol import read_only_tool_attempt
from chat_evidence import project

def result():
    return {'query':'red bicycle','provider':'fixture','result_type':'image_candidates',
            'images':[{'image_url':'https://images.example/image'+str(i)+'.jpg',
                       'page_url':'https://example.org/photo/'+str(i),'title':'Red bicycle '+str(i)} for i in range(4)],
            'provider_errors':[],'network_requests':2,'exact_match_verified':False}

class NativeImageSearchTests(unittest.TestCase):
    def test_existing_bounded_provider_is_used_without_browser_for_every_role(self):
        for role in ('admin','user','guest'):
            profile=Mock();session=web.WebSession(ROOT,profile,role)
            with patch.object(web_tools,'image_search',return_value=result()) as lookup,patch.object(session,'_start',side_effect=AssertionError('No browser')):
                row=session.run({'action':'image_search','query':'red bicycle','limit':3})
            lookup.assert_called_once_with('red bicycle',page_limit=3,candidate_limit=3)
            self.assertEqual(row['images'],result()['images'])
            self.assertEqual(row['kind'],'image_candidates')
            self.assertFalse(row['exact_match_verified'])
            self.assertGreaterEqual(profile.check.call_count,2)

    def test_image_candidates_keep_source_pairs_without_redundant_search_snippets(self):
        session=web.WebSession(ROOT,Mock())
        value={**result(),'search_results':[{'url':'https://example.org/other','snippet':'unfetched'}]}
        with patch.object(web_tools,'image_search',return_value=value):
            row=session.run({'action':'image_search','query':'red bicycle'})
        self.assertNotIn('search_results',row)
        self.assertEqual(row['images'],value['images'])
        value['images']=[]
        with patch.object(web_tools,'image_search',return_value=value):
            row=session.run({'action':'image_search','query':'red bicycle'})
        self.assertEqual(row['search_results'],value['search_results'])

    def test_native_web_schema_closes_protocol_fields_but_preserves_http_data(self):
        from web_tool_api import validate_call
        parameters=TOOL['function']['parameters']
        self.assertFalse(parameters['additionalProperties'])
        self.assertFalse(parameters['properties']['arguments']['additionalProperties'])
        validate_call('download',{'url':'https://images.example/subject.jpg','purpose':'person_photo'})
        validate_call('request',{'url':'https://example.org/api','headers':{'X-Custom':'value'},'json':{'arbitrary key':{'nested':'data'}}})
        with self.assertRaisesRegex(ValueError,'Unknown web argument'):
            validate_call('download',{'purpose':'person_photo','url": ':', '})

    def test_unknown_protocol_fields_fail_before_starting_a_worker(self):
        from web_tool_api import WebClient
        client=WebClient(Mock())
        with patch.object(client,'_start') as start:
            with self.assertRaisesRegex(ValueError,'Unknown web argument'):
                client.call('download',{'urll':'https://example.org/image.jpg'})
            with self.assertRaisesRegex(ValueError,'Missing web argument'):
                client.call('download',{'purpose':'person_photo'})
            start.assert_not_called()

    def test_native_schema_preserves_all_documented_web_action_arguments(self):
        props=TOOL['function']['parameters']['properties']['arguments']['properties']
        expected='query limit fresh url site parameter max_chars document kind offset format pointer table tag provider max_bytes purpose find link_offset pdf_page page selector role name frame index value key x y method headers json body timeout'.split()
        self.assertEqual(set(expected),set(props))

    def test_invalid_input_does_not_start_network_work(self):
        session=web.WebSession(ROOT,Mock())
        with patch.object(web_tools,'image_search') as lookup:
            for values in ({},{'query':''},{'query':1},{'query':'x','limit':True},{'query':'x','limit':9},{'query':'x','limit':0}):
                with self.subTest(values=values),self.assertRaises(ValueError):session.run({'action':'image_search',**values})
            lookup.assert_not_called()

    def test_revoked_login_cannot_return_candidates(self):
        profile=Mock();profile.check.side_effect=[None,PermissionError('login ended')]
        session=web.WebSession(ROOT,profile)
        with patch.object(web_tools,'image_search',return_value=result()),self.assertRaises(PermissionError):
            session.run({'action':'image_search','query':'red bicycle'})

    def test_provider_denial_is_not_converted_to_success(self):
        session=web.WebSession(ROOT,Mock())
        with patch.object(web_tools,'image_search',side_effect=web_tools.WebAccessError('provider denied')),self.assertRaises(web_tools.WebAccessError):
            session.run({'action':'image_search','query':'red bicycle'})

    def test_native_lookup_activates_existing_elapsed_and_count_limits(self):
        cycle=ImageLookupCycle('a request without lookup keywords')
        args={'action':'image_search','arguments':{'query':'red bicycle'}}
        self.assertIsNone(cycle.before('web',args));self.assertTrue(cycle.active)
        cycle.record('web',args,json.dumps({'ok':True,'result':result()}))
        self.assertEqual(cycle.searches,1)
        self.assertIn('https://images.example/image0.jpg',cycle.links)
        self.assertIsNotNone(cycle.before('web',args))
        cycle.started_at-=cycle.MAX_SECONDS+1
        self.assertIsNotNone(cycle.before('web',{'action':'image_search','arguments':{'query':'yellow watering can'}}))
        self.assertIsNone(cycle.before('media_tool',{'command':'edit','arguments':['input.png','add a basket']}))

    def test_image_search_is_read_only_but_download_is_still_effectful(self):
        self.assertTrue(read_only_tool_attempt('web',{'action':'image_search'},ROOT))
        self.assertFalse(read_only_tool_attempt('web',{'action':'download'},ROOT))

    def test_compaction_preserves_exact_image_and_source_pairs(self):
        value=result();value['provider_errors']=['details '*3000]
        for name,body in [('web',{'ok':True,'result':value}),('shell',value)]:
            text=project({'name':name,'content':json.dumps(body)},7,500)
            view=json.loads(text)
            self.assertEqual(view['kind'],'image_candidates')
            self.assertTrue(view['images'])
            for image in view['images']:
                self.assertIn(image['image_url'],[r['image_url'] for r in value['images']])
                index=int(image['image_url'].split('image')[-1].split('.')[0])
                self.assertEqual(image['page_url'],value['images'][index]['page_url'])
            self.assertGreater(view['omitted_images'],0)
            self.assertLessEqual(len(text),500)

    def test_failed_lookup_is_not_projected_as_image_evidence(self):
        raw=json.dumps({'ok':False,'result':result(),'error':'failure '+('x'*2000)})
        self.assertNotIn('"kind":"image_candidates"',project({'name':'web','content':raw},3,400))

    def test_native_schema_and_help_expose_direct_image_lookup(self):
        self.assertIn('image_search',TOOL['function']['description'])
        self.assertIn('image_search',web.WebSession(ROOT,Mock()).run({'action':'help'})['actions'])

    def test_find_preserves_image_metadata_without_refetching(self):
        session=web.WebSession(ROOT,Mock())
        candidate={'image_url':'https://images.example/subject.jpg','alt':'Subject'}
        session.documents['fixture']={'document':'fixture','url':'https://example.org/page',
            'text':'The subject is here.','images':[candidate],'image_urls':[candidate['image_url']],
            'image_note':'Unverified candidates'}
        with patch.object(web,'_request_bytes',side_effect=AssertionError('No repeat fetch')):
            for query in ('subject','absent'):
                row=session._read({'document':'fixture','find':query})
                self.assertEqual(row['images'],[candidate]);self.assertEqual(row['find_mode'],'literal_text')

    def test_large_article_uses_native_read_size_cap(self):
        html=b'<html><meta property="og:image" content="https://images.example/subject.jpg">'+b' '*(2_100_000)+b'</html>'
        with patch.object(web_tools,'_request_bytes',return_value=(html,'https://example.org/article','text/html')) as request:
            rows=web_tools._page_image_candidates('https://example.org/article')
        self.assertEqual(rows[0]['image_url'],'https://images.example/subject.jpg')
        self.assertEqual(request.call_args.kwargs['max_bytes'],16*1024**2)

    def test_fallback_page_budget_uses_distinct_hosts_before_duplicate_hosts(self):
        pages=[{'url':'https://same.example/one'},{'url':'https://same.example/two'},
               {'url':'https://second.example/page'},{'url':'https://third.example/page'}]
        seen=[]
        with patch.object(web_tools,'web_search',return_value={'provider':'fixture','results':pages}), \
             patch.object(web_tools,'WebState',return_value=Mock()), \
             patch.object(web_tools,'_page_image_candidates',side_effect=lambda url:seen.append(url) or []):
            web_tools._page_metadata_images('ordinary object',page_limit=3)
        self.assertEqual(seen,[pages[i]['url'] for i in (0,2,3)])

if __name__=='__main__':unittest.main()
