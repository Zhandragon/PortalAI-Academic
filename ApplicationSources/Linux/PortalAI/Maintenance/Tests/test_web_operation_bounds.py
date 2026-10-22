"""Synthetic elapsed-network and useful-partial-evidence regressions."""
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import web_tools as web


PAGE = 'https://example.com/story'
IMAGE = {'image_url': 'https://example.com/event.jpg', 'page_url': PAGE, 'title': 'The event'}


class WebOperationBoundsTests(unittest.TestCase):
    def setUp(self):
        self.state = Mock()
        self.state.cached.return_value = None
        self.state.cooling.return_value = None
        self.state.key.return_value = 'fixture'
        patched = patch.object(web, 'WebState', return_value=self.state)
        patched.start(); self.addCleanup(patched.stop)

    def test_fetch_extracts_lazy_responsive_and_social_images_without_extra_requests(self):
        html = b'''<html><head><meta charset="utf-8"><title>Event report</title>
            <meta property="og:image" content="/event.jpg"></head><body><p>Actual event text.</p>
            <img src="data:image/gif;base64,abc" data-src="/full.jpg" alt="Event photo">
            <picture><source srcset="/small.webp 400w, /large.webp 1200w"></picture>
            <img srcset="data:image/gif;base64,not-an-image-url 1x">
            <img srcset="https://127.0.0.1/private.jpg 400w, /public.jpg 800w">
            <img src="file:///private.jpg"></body></html>'''
        with patch.object(web, '_request_bytes', return_value=(html, PAGE, 'text/html')) as network, \
             patch.object(web.socket, 'getaddrinfo') as dns:
            result = web.fetch_url(PAGE)
        network.assert_called_once(); dns.assert_not_called()
        self.assertEqual(result['title'], 'Event report')
        self.assertIn('Actual event text.', result['text'])
        self.assertEqual(result['image_urls'][0], IMAGE['image_url'])
        self.assertIn('https://example.com/full.jpg', result['image_urls'])
        self.assertIn('https://example.com/large.webp', result['image_urls'])
        self.assertNotIn('https://127.0.0.1/private.jpg', result['image_urls'])
        self.assertNotIn('https://example.com/not-an-image-url', result['image_urls'])
        self.assertTrue(all(not item['download_verified'] for item in result['images']))
        self.assertTrue(result['full_page_fetched'])

    def test_later_metadata_timeout_preserves_earlier_image_and_search_pages(self):
        pages = [{'url': PAGE, 'title': 'First'}, {'url': PAGE + '/next', 'title': 'Second'}]
        with patch.object(web, '_duckduckgo_images', return_value=[]), \
             patch.object(web, 'web_search', return_value={'provider': 'fixture', 'results': pages}), \
             patch.object(web, '_page_image_candidates', side_effect=[[IMAGE], web.ImageLookupLimit()]), \
             patch.object(web, '_wikipedia_lead_images') as wiki:
            result = web.image_search('specific event photograph')
        self.assertEqual(result['image_urls'], [IMAGE['image_url']])
        self.assertEqual(result['search_results'], pages)
        self.assertTrue(result['lookup_limited'])
        wiki.assert_not_called(); self.state.block.assert_not_called()

    def test_article_images_are_exact_advertised_urls_not_guessed_filename_variants(self):
        advertised = 'https://i.dailymail.co.uk/1s/2019/01/04/00/fixture-image-m-1.jpg'
        responsive = 'https://i.dailymail.co.uk/1s/2019/01/04/00/fixture-image-a-4.jpg'
        html = ('<html><meta charset="utf-8"><img data-src="' + advertised +
                '" srcset="' + responsive + ' 1200w"></html>').encode()
        with patch.object(web, '_request_bytes', return_value=(html, PAGE, 'text/html')):
            result = web.fetch_url(PAGE)
        self.assertEqual(set(result['image_urls']), {advertised, responsive})
        self.assertNotIn(advertised.replace('image-m', 'image-a'), result['image_urls'])
        self.assertTrue(all(item['page_url'] == PAGE for item in result['images']))

    def test_discovery_reserves_time_for_download_within_original_total_limit(self):
        now = [0.0]
        pages = [{'url': PAGE}, {'url': PAGE + '/later'}]
        def extract(url):
            if url == PAGE:
                now[0] = 31.0
                return [IMAGE]
            now[0] = 33.0
            web._IMAGE_BUDGET.get().check()
            self.fail('Discovery did not preserve the download allowance')
        def download(url, **kwargs):
            budget = web._IMAGE_BUDGET.get()
            self.assertEqual(budget.remaining(), 12)
            self.assertEqual(budget.request_timeout(12), 12)
            now[0] = 35
            return {'files': ['Outputs/WebImages/fixture.jpg'], 'path': 'Outputs/WebImages/fixture.jpg'}
        with patch.object(web.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(web, '_duckduckgo_images', return_value=[]), \
             patch.object(web, 'web_search', return_value={'provider': 'fixture', 'results': pages}), \
             patch.object(web, '_page_image_candidates', side_effect=extract), \
             patch.object(web, 'download_public_image', side_effect=download) as save:
            result = web.find_and_download_image('specific event photograph')
        save.assert_called_once()
        self.assertEqual(result['files'], ['Outputs/WebImages/fixture.jpg'])
        self.assertIsNone(web._IMAGE_BUDGET.get())

    def test_useful_direct_candidates_do_not_trigger_optional_fallback_enrichment(self):
        images = [{**IMAGE, 'image_url': f'https://example.com/{i}.jpg'} for i in range(4)]
        with patch.object(web, '_duckduckgo_images', return_value=images), \
             patch.object(web, '_page_metadata_images') as metadata, \
             patch.object(web, '_wikipedia_lead_images') as wiki:
            result = web.image_search('specific event')
        self.assertEqual(len(result['images']), 4)
        metadata.assert_not_called(); wiki.assert_not_called()

    def test_blocked_dns_returns_promptly_and_cannot_start_late_http(self):
        entered = threading.Event(); release = threading.Event(); done = threading.Event()
        def resolve(*args, **kwargs):
            entered.set()
            release.wait(2)
            return [(2, 1, 6, '', ('93.184.216.34', 443))]
        original = web._request_bytes_sync
        def tracked(*args, **kwargs):
            try: return original(*args, **kwargs)
            finally: done.set()
        with patch.object(web.socket, 'getaddrinfo', side_effect=resolve), \
             patch.object(web, '_request_bytes_sync', side_effect=tracked), \
             patch.object(web, '_opener') as opener:
            start = time.monotonic()
            try:
                with self.assertRaises(web.WebAccessError) as error:
                    web._request_bytes(PAGE, timeout=.05)
                self.assertTrue(entered.is_set())
                self.assertLess(time.monotonic() - start, .8)
                self.assertEqual(error.exception.details['category'], 'request_timeout')
            finally:
                release.set()
                self.assertTrue(done.wait(2))
            opener.assert_not_called()

    def test_redirects_consume_shared_request_allowance(self):
        budget = web.ImageRequestBudget(requests=1)
        token = web._IMAGE_BUDGET.set(budget)
        try:
            request = web.urllib.request.Request(PAGE)
            with patch.object(web, '_validate_public_url'):
                web.SafeRedirectHandler().redirect_request(request, None, 302, 'Found', {}, PAGE + '/one')
                with self.assertRaises(web.ImageLookupLimit):
                    web.SafeRedirectHandler().redirect_request(request, None, 302, 'Found', {}, PAGE + '/two')
            self.assertEqual(budget.requests, 1)
        finally: web._IMAGE_BUDGET.reset(token)

    def test_research_returns_completed_page_when_later_fetch_hits_total_budget(self):
        now = [0.0]
        pages = [{'url': PAGE}, {'url': PAGE + '/slow'}, {'url': PAGE + '/unused'}]
        def fetch(url, **kwargs):
            if url == PAGE:
                now[0] = 39
                return {'url': PAGE, 'text': 'Completed evidence', 'full_page_fetched': True}
            now[0] = 45
            web._IMAGE_BUDGET.get().check()
        with patch.object(web.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(web, 'web_search', return_value={'provider': 'fixture', 'results': pages}), \
             patch.object(web, 'fetch_url', side_effect=fetch) as fetcher:
            result = web.research('event', 3, 3, 6000)
        self.assertEqual(fetcher.call_count, 2)
        self.assertTrue(result['lookup_limited'])
        self.assertEqual(result['pages'][0]['text'], 'Completed evidence')
        self.assertFalse(result['pages'][1]['full_page_fetched'])
        self.assertEqual(result['results'], pages)
        self.assertIsNone(web._IMAGE_BUDGET.get())


if __name__ == '__main__': unittest.main()
