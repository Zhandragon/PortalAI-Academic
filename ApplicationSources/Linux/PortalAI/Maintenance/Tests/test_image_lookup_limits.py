"""Bounded image search and per-turn chat loops; no live requests/models."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
import web_tools as web
import native_chat as chat
from test_chat_handoff import panel


IMAGE = {'title':'Actual candidate','image_url':'https://example.com/actual.png','page_url':'https://example.com/page'}


class ImageNetworkBudgetTests(unittest.TestCase):
    def setUp(self):
        self.state = Mock(); self.state.cooling.return_value = None
        patched = patch.object(web,'WebState',return_value=self.state); patched.start(); self.addCleanup(patched.stop)
        patched = patch.object(web,'_validate_public_url'); patched.start(); self.addCleanup(patched.stop)

    def test_request_count_and_deadline_limit_without_disabling_general_requests(self):
        now = [0.0]
        with patch.object(web.time,'monotonic',side_effect=lambda:now[0]):
            budget = web.ImageRequestBudget(seconds=5,requests=2)
            self.assertEqual(budget.request_timeout(12),5)
            now[0] = 3
            self.assertEqual(budget.request_timeout(12),2)
            with self.assertRaises(web.ImageLookupLimit):budget.request_timeout(12)
            now[0] = 5
            with self.assertRaises(web.ImageLookupLimit):budget.check()
        self.assertIsNone(web._IMAGE_BUDGET.get())

    def test_slow_response_checks_elapsed_between_chunks(self):
        now = [0.0]
        class SlowResponse(io.BytesIO):
            headers = {'Content-Type':'image/png'}
            def geturl(self):return IMAGE['image_url']
            def read1(self,size):
                now[0] += 2
                return super().read1(size)
        with patch.object(web.time,'monotonic',side_effect=lambda:now[0]):
            token = web._IMAGE_BUDGET.set(web.ImageRequestBudget(seconds=3))
            try:
                with patch.object(web,'_opener') as opener:
                    opener.return_value.open.return_value = SlowResponse(b'x'*(3*65536))
                    with self.assertRaises(web.ImageLookupLimit):web._request_bytes(IMAGE['image_url'])
                    self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],3)
            finally:web._IMAGE_BUDGET.reset(token)
        self.assertEqual(now[0],4)

    def test_budget_stop_preserves_earlier_candidates_and_does_not_cool_down_provider(self):
        with patch.object(web,'_duckduckgo_images',return_value=[IMAGE]), \
             patch.object(web,'_page_metadata_images',side_effect=web.ImageLookupLimit()), \
             patch.object(web,'_wikipedia_lead_images') as wiki, \
             patch.object(web,'_wikimedia_commons_images') as commons:
            result = web.image_search('specific image')
        self.assertEqual(result['image_urls'],[IMAGE['image_url']])
        self.assertTrue(result['lookup_limited']);self.assertFalse(result['exact_match_verified'])
        wiki.assert_not_called();commons.assert_not_called();self.state.block.assert_not_called()
        self.assertIsNone(web._IMAGE_BUDGET.get())

    def test_download_failures_stop_after_three_candidates_with_actual_urls(self):
        candidates = [{**IMAGE,'image_url':f'https://example.com/{n}.png'} for n in range(10)]
        found = {'images':candidates,'image_urls':[row['image_url'] for row in candidates],'provider':'fixture'}
        with patch.object(web,'image_search',return_value=found), \
             patch.object(web,'download_public_image',side_effect=ValueError('not an image')) as download:
            with self.assertRaises(web.WebAccessError) as error:web.find_and_download_image('specific image')
        self.assertEqual(download.call_count,3)
        self.assertEqual(error.exception.details['attempted_downloads'],3)
        self.assertEqual(error.exception.details['image_urls'],found['image_urls'])
        self.assertFalse(error.exception.details['exact_match_verified'])

    def test_search_and_download_share_one_elapsed_budget(self):
        now = [0.0]; budgets = []
        def search(*_args,**_kwargs):
            budgets.append(web._IMAGE_BUDGET.get()); now[0] = 46
            return {'images':[IMAGE],'image_urls':[IMAGE['image_url']],'provider':'fixture'}
        with patch.object(web.time,'monotonic',side_effect=lambda:now[0]), \
             patch.object(web,'image_search',side_effect=search), \
             patch.object(web,'download_public_image') as download:
            with self.assertRaises(web.WebAccessError) as error:web.find_and_download_image('specific image')
        self.assertIsInstance(budgets[0],web.ImageRequestBudget)
        download.assert_not_called();self.assertIsNone(web._IMAGE_BUDGET.get())
        self.assertEqual(error.exception.details['attempted_downloads'],0)

    def test_image_budget_is_not_mistaken_for_a_failed_search_provider(self):
        self.state.cached.return_value=None
        with patch.object(web,'search_duckduckgo',side_effect=web.ImageLookupLimit()), \
             patch.dict(web.os.environ,{'BRAVE_SEARCH_API_KEY':''}):
            with self.assertRaises(web.ImageLookupLimit):web.web_search('metadata image query')
        self.state.block.assert_not_called()

    def test_plain_page_request_keeps_its_normal_timeout(self):
        response = io.BytesIO(b'plain page');response.headers={'Content-Type':'text/plain'}
        response.geturl=lambda:'https://example.com/'
        with patch.object(web,'_opener') as opener:
            opener.return_value.open.return_value=response
            self.assertEqual(web._request_bytes('https://example.com/')[0],b'plain page')
        self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'],web.DEFAULT_TIMEOUT)


def call(number,query,action='image-search'):
    return {'id':'call_'+str(number),'type':'function','function':{
        'name':'shell','arguments':json.dumps({'command':f'python Agent/web_tools.py {action} "{query}"'})}}


class ImageChatCycleTests(unittest.TestCase):
    def test_existing_picture_intent_only_not_generation_or_research(self):
        for text in ('Find a photo of this exact computer', 'Show me pictures of a red panda',
                     'Look up an image of the 2026 device', 'Download that screenshot'):
            with self.subTest(text=text): self.assertTrue(chat.ImageLookupCycle(text).active)
        for text in ('Generate an image of a cat', 'Show me how to create a picture',
                     'Find articles about image classification', 'Search image generation tools',
                     'Search for the latest weather', 'Analyze this photo'):
            with self.subTest(text=text): self.assertFalse(chat.ImageLookupCycle(text).active)

    def test_explicit_image_request_caps_repeated_general_search_then_answers(self):
        p=panel();p.session['messages'][0]['content']='Find a picture of the exact AOOSTAR G-Flip'
        p.tool_runtime.execute.return_value='{"success":true,"results":[{"url":"https://example.com/page"}]}'
        responses=[('', '', [call(1,'exact computer','search')]),
                   ('', '', [call(2,'exact computer','search')]),
                   ('', '', [call(3,'more exact computer','search')]),
                   ('Only source pages were found.', '', [])]
        p.settings['tool_step_limit']=6
        with patch.object(p,'stream_completion',side_effect=responses):p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)
        self.assertEqual(p.session['messages'][-1]['content'],'Only source pages were found.')

    def test_completed_candidate_urls_survive_final_synthesis_timeout(self):
        p=panel();p.session['messages'][0]['content']='Find an image of the specific machine'
        p.tool_runtime.execute.return_value=json.dumps({'images':[IMAGE]})
        with patch.object(p,'stream_completion',side_effect=[('', '', [call(1,'specific machine')]),TimeoutError('fixture timeout')]):
            p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        text=p.session['messages'][-1]['content']
        self.assertIn(IMAGE['image_url'],text)
        self.assertIn('could not finish summarizing',text)
        self.assertIn('TimeoutError',text)
        self.assertIn('exact match has not been verified',text)

    def test_completed_candidates_survive_later_context_overflow_without_another_model_call(self):
        p=panel();p.tool_runtime.execute.return_value=json.dumps({'image_urls':[IMAGE['image_url']]})
        first_api=p.api_messages()
        with patch.object(p,'api_messages',side_effect=[first_api,RuntimeError('fixture context overflow')]), \
             patch.object(p,'stream_completion',return_value=('', '', [call(1,'specific image')])) as stream:
            p.agent_worker('test')
        stream.assert_called_once();p.tool_runtime.execute.assert_called_once()
        self.assertIn(IMAGE['image_url'],p.session['messages'][-1]['content'])

    def test_progress_instruction_is_included_in_context_admission(self):
        p=panel();p.settings['tool_step_limit']=12
        p._last_context_meta={'budget':100}
        p.api_messages=lambda:([],99)
        p.tool_runtime.execute.return_value=json.dumps({'image_urls':[IMAGE['image_url']]})
        with patch.object(p,'stream_completion',side_effect=[('', '', [call(n,f'query {n}')]) for n in range(3)]) as stream:
            p.agent_worker('test')
        self.assertEqual(stream.call_count,1)
        self.assertIn('could not finish summarizing',p.session['messages'][-1]['content'])
        self.assertIn(IMAGE['image_url'],p.session['messages'][-1]['content'])

    def test_initial_overflow_is_not_mistaken_for_completed_image_lookup(self):
        p=panel();p.session['messages'][0]['content']='Find a photo of the exact machine'
        with patch.object(p,'api_messages',side_effect=RuntimeError('current request does not fit')), \
             patch.object(p,'stream_completion') as stream:p.agent_worker('test')
        stream.assert_not_called();p.tool_runtime.execute.assert_not_called()
        self.assertFalse(any(row.get('tool_calls') or row.get('role')=='tool' for row in p.session['messages']))
        self.assertEqual(p.session['messages'][-1]['role'],'assistant')
        self.assertTrue(p.session['messages'][-1]['incomplete'])
        self.assertIn('current request does not fit',p.session['messages'][-1]['content'])
        self.assertTrue(any('current request does not fit' in str(row) for row in p.ev.queue))

    def test_distinct_case_sensitive_download_urls_remain_distinct(self):
        cycle=chat.ImageLookupCycle()
        self.assertIsNone(cycle.before('shell',{'command':'python Agent/web_tools.py download-image https://example.com/Foo.png'}))
        self.assertIsNone(cycle.before('shell',{'command':'python Agent/web_tools.py download-image https://example.com/foo.png'}))
        self.assertEqual(cycle.downloads,2)

    def test_same_failed_query_is_not_executed_twice_but_tools_remain_available(self):
        p=panel();p.tool_runtime.execute.return_value='{"success":false,"images":[]}'
        seen=[]
        responses=[('', '', [call(1,'specific image')]),('', '', [call(2,'  Specific   IMAGE ')]),('No exact match found.', '', [])]
        def respond(messages):
            seen.append((p._reply_without_tools,messages));return responses.pop(0)
        with patch.object(p,'stream_completion',side_effect=respond):p.agent_worker('test')
        p.tool_runtime.execute.assert_called_once()
        self.assertFalse(seen[-1][0]);self.assertIn('meaningful broader/narrower query',seen[-1][1][-1]['content'])
        self.assertEqual(p.session['messages'][-1]['content'],'No exact match found.')

    def test_productive_search_beyond_three_queries_preserves_editing(self):
        p=panel();p.settings['tool_step_limit']=12
        p.tool_runtime.execute.side_effect=[json.dumps({'success':True,'image_urls':[f'https://example.com/{n}.jpg']}) for n in range(5)]+['{"success":true,"output":"edited.jpg"}']
        edit={'id':'edit','type':'function','function':{'name':'shell','arguments':json.dumps({'command':'python Agent/ai_tools.py autoedit "Outputs/found.jpg" "blue shirt"'})}}
        responses=[('', '', [call(n,f'refinement {n}')]) for n in range(1,6)]+[('','',[edit]),('Edited the selected image.','',[])]
        with patch.object(p,'stream_completion',side_effect=responses) as stream:p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,6);self.assertEqual(stream.call_count,7)
        self.assertEqual(p.session['messages'][-1]['content'],'Edited the selected image.')
        self.assertFalse(p._reply_without_tools)

    def test_new_user_turn_gets_a_new_query_budget(self):
        p=panel()
        for n in (1,2):
            if n==2:p.session['messages'].append({'role':'user','content':'Please try again now'})
            with patch.object(p,'stream_completion',side_effect=[('', '', [call(n,'same query')]),('Result.', '', [])]):
                p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,2)

    def test_general_search_is_not_limited_by_image_query_rules(self):
        p=panel()
        with patch.object(p,'stream_completion',side_effect=[('', '', [call(n,'same query','search')]) for n in range(3)]):
            p.agent_worker('test')
        self.assertEqual(p.tool_runtime.execute.call_count,3)

    def test_tool_choice_none_is_sent_to_model_for_final_answer(self):
        p=panel();p._reply_without_tools=True
        response=Mock(status=200)
        response.readline.side_effect=[b'data: {"choices":[{"delta":{"content":"No exact match."},"finish_reason":"stop"}]}\n',b'']
        conn=Mock();conn.getresponse.return_value=response
        with patch.object(chat,'model_id',return_value='fixture'),patch.object(chat.http.client,'HTTPConnection',return_value=conn):
            p._stream_completion_once([])
        payload=json.loads(conn.request.call_args.kwargs['body'])
        self.assertEqual(payload['tool_choice'],'none')
        self.assertFalse(payload['parallel_tool_calls'])


if __name__=='__main__':unittest.main()
