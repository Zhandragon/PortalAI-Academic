import json
import gzip
import io
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import web_tools as web
from web_state import WebState


class WebTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='Portal web test ');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);(self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.state=WebState(self.root,environ={})
        p=patch.object(web,'WebState',return_value=self.state);p.start();self.addCleanup(p.stop)
        p=patch.dict(web.os.environ,{'BRAVE_SEARCH_API_KEY':''});p.start();self.addCleanup(p.stop)
        p=patch.object(web,'search_bing',side_effect=web.WebAccessError('Independent provider unavailable in this fixture',category='fixture'));p.start();self.addCleanup(p.stop)
        self.result=[{'title':'Documentation','url':'https://www.python.org/doc/','snippet':'Documentation for Python'}]

    def error(self,code=403,headers=None):
        return urllib.error.HTTPError('https://html.duckduckgo.com/',code,'Failed',headers or {},None)

    def test_html_403_falls_back_and_returns_provider_evidence(self):
        with patch.object(web,'search_duckduckgo',side_effect=[self.error(),self.result]) as search:
            result=web.web_search('example')
        self.assertEqual(result['provider'],'duckduckgo-lite')
        self.assertEqual(result['provider_errors'][0]['http_status'],403)
        self.assertTrue(search.call_args_list[1].kwargs['lite'])

    def test_cooldown_persists_across_process_reconstruction_even_for_fresh(self):
        self.state.block('duckduckgo',300,'HTTP 403')
        with patch.object(web,'WebState',return_value=WebState(self.root,environ={})),patch.object(web,'search_duckduckgo',return_value=self.result) as search:
            result=web.web_search('next',fresh=True)
        search.assert_called_once_with('next',6,lite=True)
        self.assertEqual(result['provider_errors'][0]['category'],'cooldown')

    def test_fresh_cache_is_labelled_and_skips_network(self):
        with patch.object(web,'search_duckduckgo',return_value=self.result) as search:
            first=web.web_search('example');second=web.web_search('example')
        self.assertEqual(search.call_count,1);self.assertFalse(first['cached']);self.assertTrue(second['cached'])
        self.assertGreaterEqual(second['cache_age_seconds'],0)

    def test_cache_expiry_and_capacity(self):
        for n in range(70):self.state.save(str(n),6,{'provider':'test','results':self.result})
        with self.state.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM cache').fetchone()[0],64)
            db.execute('UPDATE cache SET at=0');db.commit()
        self.assertIsNone(self.state.cached('69',6))

    def test_rate_limit_retry_after_is_honored(self):
        result=web._web_error(self.error(429,{'Retry-After':'120'}))
        self.assertEqual(result['retry_after_seconds'],120);self.assertEqual(result['category'],'rate_limited')

    def test_lite_parser_keeps_snippet_and_decodes_result_link(self):
        data=b'<a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.python.org%2Fdoc%2F">Docs</a><td class="result-snippet">Python <b>help</b></td>'
        with patch.object(web,'_request_bytes',return_value=(data,'https://lite.duckduckgo.com/','text/html')),patch.object(web,'_validate_public_url'):
            result=web.search_duckduckgo('query',3,lite=True)
        self.assertEqual(result[0]['snippet'],'Python help');self.assertEqual(result[0]['url'],'https://www.python.org/doc/')

    def test_challenge_is_not_mistaken_for_page_content_or_empty_search(self):
        data=b'<html><title>Just a moment...</title><p>Verify browser</p></html>'
        with patch.object(web,'_request_bytes',return_value=(data,'https://example.com','text/html')):
            with self.assertRaises(web.WebAccessError) as error:web.fetch_url('https://example.com')
            self.assertEqual(error.exception.details['category'],'browser_challenge')
            with self.assertRaises(web.WebAccessError):web.search_duckduckgo('query',3)

    def test_fetch_403_and_research_keep_snippets_distinct_from_fetched_pages(self):
        with patch.object(web,'_request_bytes',side_effect=self.error()),patch.object(web,'web_search',return_value={'provider':'test','results':self.result}):
            result=web.research('query',3,1,4000)
        page=result['pages'][0]
        self.assertFalse(page['full_page_fetched']);self.assertNotIn('text',page)
        self.assertEqual(page['source_type'],'search_snippet_only');self.assertEqual(page['fetch_error']['http_status'],403)

    def test_repeated_blocked_page_is_not_requested_again_during_cooldown(self):
        with patch.object(web,'_request_bytes',side_effect=self.error()) as request:
            for _ in range(2):
                with self.assertRaises(web.WebAccessError):web.fetch_url('https://example.com/blocked')
            request.assert_called_once()

    def test_all_blocked_reports_failure_and_stops_repeat_requests(self):
        with patch.object(web,'search_duckduckgo',side_effect=self.error()) as search:
            for _ in range(2):
                with self.assertRaises(web.WebAccessError) as error:web.web_search('unavailable')
            self.assertEqual(search.call_count,2)
        self.assertEqual(error.exception.details['category'],'search_unavailable')

    def test_missing_cache_does_not_disable_search(self):
        with patch.object(self.state,'cached',side_effect=OSError('disk')),patch.object(self.state,'save',side_effect=OSError('disk')),patch.object(web,'search_duckduckgo',return_value=self.result):
            result=web.web_search('example')
        self.assertTrue(result['results']);self.assertTrue(result['warnings'])

    def test_api_key_is_not_forwarded_to_redirect_host(self):
        request=urllib.request.Request('https://api.search.brave.com/res/v1/web/search',headers={'X-Subscription-Token':'test-secret'})
        with patch.object(web,'_validate_public_url'):
            with self.assertRaisesRegex(ValueError,'credential'):
                web.SafeRedirectHandler().redirect_request(request,None,302,'Found',{},'https://example.com/')

    def test_public_url_guard_still_blocks_private_hosts_and_url_credentials(self):
        with self.assertRaises(ValueError):web._validate_public_url('http://localhost/internal')
        with self.assertRaises(ValueError):web._validate_public_url('https://name:secret@example.com/')

    def test_compressed_pages_decode_with_a_hard_expansion_limit(self):
        def response(data):
            stream=io.BytesIO(gzip.compress(data))
            stream.headers={'Content-Type':'text/html','Content-Encoding':'gzip'}
            stream.geturl=lambda:'https://example.com/'
            return stream
        with patch.object(web,'_validate_public_url'),patch.object(web,'_opener') as opener:
            opener.return_value.open.return_value=response(b'<title>Readable</title>')
            page=web.fetch_url('https://example.com/')
            self.assertEqual(page['title'],'Readable')
            opener.return_value.open.return_value=response(b'x'*10000)
            with self.assertRaisesRegex(ValueError,'Decompressed response exceeded'):
                web._request_bytes('https://example.com/',max_bytes=1000)


if __name__=='__main__':unittest.main()
