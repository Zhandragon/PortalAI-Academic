"""Public image fallback, failed-page evidence, and request URL regressions."""
import html
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import web_tools as web
import web_capabilities

IMAGE = 'https://photos.example/object.jpg'
PAGE = 'https://example.org/object'

def anchor(**values):
    return '<a m="' + html.escape(json.dumps(values), quote=True) + '"></a>'

class ImageSearchRecoveryTests(unittest.TestCase):
    def test_bing_parser_keeps_observed_pairs_and_rejects_invalid_candidates(self):
        body = ('<html>' + anchor(murl=IMAGE, purl=PAGE, t='A teapot', desc='Blue ceramic')
                + anchor(murl=IMAGE, purl=PAGE) + anchor(murl='http://127.0.0.1/a', purl=PAGE)
                + anchor(murl=IMAGE+'/other', purl='file:///private') + '<a m="[]"></a></html>').encode()
        with patch.object(web, '_request_bytes', return_value=(body, PAGE, 'text/html')), \
             patch.object(web.socket, 'getaddrinfo', side_effect=AssertionError('No candidate DNS')):
            rows = web._bing_images('ceramic teapot')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['image_url'], rows[0]['page_url']), (IMAGE, PAGE))
        self.assertEqual(rows[0]['alt'], 'Blue ceramic')

    def test_bing_result_limit_and_unicode_query(self):
        body = ('<html>' + ''.join(anchor(murl=IMAGE+str(i), purl=PAGE, t='Café tea pot') for i in range(8)) + '</html>').encode()
        with patch.object(web, '_request_bytes', return_value=(body, PAGE, 'text/html')) as request:
            self.assertEqual(len(web._bing_images('café tea pot', limit=2)), 2)
        query = web.urllib.parse.parse_qs(web.urllib.parse.urlsplit(request.call_args.args[0]).query)
        self.assertEqual(query['q'], ['café tea pot'])

    def test_irrelevant_metadata_uses_one_general_query_simplification(self):
        bad = anchor(murl=IMAGE, purl=PAGE, t='Blue solid background').encode()
        good = anchor(murl=IMAGE+'/cup', purl=PAGE, t='Blue ceramic cup').encode()
        with patch.object(web, '_request_bytes', side_effect=[(bad,PAGE,'text/html'),(good,PAGE,'text/html')]) as request:
            rows = web._bing_images('blue ceramic cup photo')
        self.assertEqual(rows[0]['title'], 'Blue ceramic cup')
        queries = [web.urllib.parse.parse_qs(web.urllib.parse.urlsplit(call.args[0]).query)['q'][0] for call in request.call_args_list]
        self.assertEqual(queries, ['blue ceramic cup photo', 'blue ceramic cup'])

    def test_wrong_subject_does_not_count_as_a_successful_provider(self):
        body = anchor(murl=IMAGE, purl=PAGE, t='Sports news').encode()
        with patch.object(web, '_request_bytes', return_value=(body,PAGE,'text/html')) as request:
            with self.assertRaises(web.WebAccessError):web._bing_images('ceramic teapot')
        request.assert_called_once()

    def test_subject_keywords_do_not_match_fragments_of_other_words(self):
        body = anchor(murl=IMAGE, purl=PAGE, t='Yellow African animals').encode()
        with patch.object(web, '_request_bytes', return_value=(body,PAGE,'text/html')):
            with self.assertRaises(web.WebAccessError):web._bing_images('yellow watering can')

    def test_bing_denial_or_empty_page_is_not_image_success(self):
        for body in (b'<title>Just a moment...</title>', b'<html>No results</html>'):
            with patch.object(web, '_request_bytes', return_value=(body, PAGE, 'text/html')):
                with self.assertRaises(web.WebAccessError):web._bing_images('an object')

    def test_second_public_provider_precedes_costly_page_scraping(self):
        state = Mock(); state.cooling.return_value = None
        with patch.object(web, 'WebState', return_value=state), \
             patch.object(web, '_duckduckgo_images', side_effect=web.WebAccessError('Denied')), \
             patch.object(web, '_bing_images', return_value=[{'image_url':IMAGE, 'page_url':PAGE}]), \
             patch.object(web, '_page_metadata_images') as metadata:
            result = web.image_search('ordinary object', candidate_limit=1)
        self.assertEqual(result['provider'], 'bing-images')
        self.assertFalse(result['images'][0]['download_verified'])
        self.assertTrue(result['provider_errors'])
        metadata.assert_not_called()

    def test_query_specific_miss_does_not_disable_provider_for_other_subjects(self):
        state = Mock(); state.cooling.return_value = None
        with patch.object(web, 'WebState', return_value=state), \
             patch.object(web, '_duckduckgo_images', return_value=[]), \
             patch.object(web, '_bing_images', side_effect=web.WebAccessError('Unrelated', category='no_relevant_results')), \
             patch.object(web, '_page_metadata_images', return_value=('fixture',[],[{'image_url':IMAGE,'page_url':PAGE}])):
            result = web.image_search('ordinary object', candidate_limit=1)
        self.assertEqual(result['image_count'], 1)
        state.block.assert_not_called()

    def test_failed_pages_are_reported_without_mutating_cached_search(self):
        original = {'provider':'fixture', 'results':[{'url':PAGE}, {'url':'https://second.example/page'}]}
        with patch.object(web, 'WebState', return_value=Mock()), \
             patch.object(web, 'web_search', return_value=original), \
             patch.object(web, '_page_image_candidates', side_effect=[web.WebAccessError('Denied'), []]):
            _, pages, images = web._page_metadata_images('ordinary object')
        self.assertEqual(images, [])
        self.assertEqual(pages[0]['image_lookup']['status'], 'failed')
        self.assertEqual(pages[1]['image_lookup']['status'], 'no_images')
        self.assertNotIn('image_lookup', original['results'][0])

    def test_no_image_guidance_does_not_claim_an_image_url_exists(self):
        session = web_capabilities.WebSession(ROOT, Mock())
        with patch.object(web, 'image_search', return_value={'images':[], 'search_results':[{'url':PAGE}]}):
            result = session.run({'action':'image_search', 'query':'an object'})
        self.assertIn('No image candidates', result['next_step'])
        self.assertIn('already inspected', result['next_step'])

    def test_request_encodes_path_and_query_without_double_encoding(self):
        response = io.BytesIO(b'bytes'); response.headers = {'Content-Type':'text/plain'}
        response.geturl = lambda: PAGE
        with patch.object(web, '_validate_public_url'), patch.object(web, '_opener') as opener:
            opener.return_value.open.return_value = response
            web._request_bytes('https://example.org/café photo%20one?q=red ball')
        request = opener.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://example.org/caf%C3%A9%20photo%20one?q=red%20ball')

    def test_invalid_destination_is_rejected_before_url_normalization(self):
        with patch.object(web, '_opener') as opener:
            with self.assertRaises(ValueError):web._request_bytes('http://127.0.0.1/a b')
        opener.assert_not_called()

if __name__ == '__main__':unittest.main()
