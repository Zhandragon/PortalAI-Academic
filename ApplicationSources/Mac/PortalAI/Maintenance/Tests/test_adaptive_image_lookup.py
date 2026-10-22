"""Synthetic progress/time limits, including mixed lookup-and-edit requests."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'ControlCenter')]
from image_lookup_policy import ImageLookupCycle


def args(query, action='image-search'):
    return {'command': f'python Agent/web_tools.py {action} "{query}"'}


class AdaptiveImageLookupTests(unittest.TestCase):
    def run_lookup(self, cycle, query, data, action='image-search'):
        request = args(query, action)
        self.assertIsNone(cycle.before('shell', request))
        cycle.record('shell', request, json.dumps(data))

    def test_six_productive_refinements_are_allowed(self):
        cycle = ImageLookupCycle('Find a specific photograph')
        for index in range(6):
            self.run_lookup(cycle, f'meaningful query {index}',
                            {'image_urls': [f'https://example.com/{index}.png'], 'lookup_limited': True})
            self.assertFalse(cycle.finalize)
        self.assertEqual(cycle.searches, 6)
        self.assertEqual(len(cycle.links), 6)

    def test_refinement_room_then_stalled_searches_close_only_web_lookup(self):
        cycle = ImageLookupCycle()
        self.run_lookup(cycle, 'first', {'image_urls': ['https://example.com/first.png']})
        self.run_lookup(cycle, 'second', {'image_urls': ['https://example.com/first.png']})
        self.assertFalse(cycle.finalize)
        self.run_lookup(cycle, 'third', {'success': False, 'details': {'image_urls': []}})
        self.assertFalse(cycle.finalize)
        self.run_lookup(cycle, 'fourth spelling/event strategy', {'images': []})
        self.assertTrue(cycle.finalize)
        self.assertEqual(cycle.no_progress, 3)
        self.assertIsNone(cycle.before('shell', {'command': 'python Agent/ai_tools.py autoedit source.png "edit"'}))
        self.assertIsNone(cycle.before('science', {'operation': 'calc'}))
        self.assertIsNone(cycle.before('read_file', {'path': 'Outputs/result.txt'}))
        blocked = json.loads(cycle.before('shell', args('fifth')))
        self.assertTrue(blocked['searches_closed'])
        self.assertFalse(blocked['lookup_closed'])
        self.assertTrue(blocked['known_candidate_retrieval_available'])
        self.assertEqual(blocked['_portableai']['scope'], 'image_lookup_only')
        self.assertIn('Other requested actions', cycle.guidance())

    def test_new_source_pages_reset_stalled_count_without_claiming_image(self):
        cycle = ImageLookupCycle('Find an image of a machine')
        self.run_lookup(cycle, 'first', {'results': []}, 'search')
        self.run_lookup(cycle, 'second', {'results': [{'url': 'https://example.com/credible-page'}]}, 'search')
        self.assertEqual(cycle.no_progress, 0)
        self.assertFalse(cycle.finalize)
        self.assertEqual(cycle.links, [])
        self.assertIn('Source pages (not verified image URLs)', cycle.fallback())

    def test_elapsed_clock_starts_at_first_lookup_not_unrelated_work(self):
        now = [0.0]
        with patch('image_lookup_policy.time.monotonic', side_effect=lambda: now[0]):
            cycle = ImageLookupCycle('Find a picture then edit it')
            now[0] = 500
            self.assertIsNone(cycle.before('science', {'operation': 'calc'}))
            self.assertIsNone(cycle.started_at)
            self.run_lookup(cycle, 'first', {'image_urls': ['https://example.com/a.png']})
            self.assertEqual(cycle.started_at, 500)
            now[0] = 679.9
            self.assertIsNone(cycle.before('shell', args('second')))
            # Finishing an admitted request retains its new evidence after 180s.
            now[0] = 681
            cycle.record('shell', args('second'), '{"image_urls":["https://example.com/b.png"]}')
            self.assertTrue(cycle.finalize)
            self.assertIn('https://example.com/b.png', cycle.links)
            self.assertIsNotNone(cycle.before('shell', args('third')))

    def test_duplicates_are_blocked_without_disabling_first_refinement(self):
        cycle = ImageLookupCycle()
        self.run_lookup(cycle, 'original query', {'success': False})
        duplicate = args(' Original   QUERY ', 'search')
        first = json.loads(cycle.before('shell', duplicate))
        self.assertFalse(first['lookup_closed'])
        self.assertIn('Change the query meaningfully', first['error'])
        cycle.record('shell', duplicate, json.dumps(first))
        self.assertEqual(cycle.no_progress, 1)
        self.run_lookup(cycle, 'changed query', {'image_urls': ['https://example.com/new.png']})
        self.assertFalse(cycle.finalize)
        self.assertIsNotNone(cycle.before('shell', duplicate))
        self.assertTrue(cycle.finalize)
        self.assertEqual(cycle.searches, 2)

    def test_eight_productive_searches_are_the_safety_ceiling(self):
        cycle = ImageLookupCycle()
        for index in range(8):
            self.run_lookup(cycle, str(index), {'image_urls': [f'https://example.com/{index}.png']})
        self.assertIsNotNone(cycle.before('shell', args('ninth')))
        self.assertEqual(cycle.searches, 8)
        self.assertTrue(cycle.finalize)

    def test_six_distinct_fetch_downloads_are_the_safety_ceiling(self):
        cycle = ImageLookupCycle('Find an image of the machine')
        for index in range(6):
            action = 'fetch' if index % 2 else 'download-image'
            self.run_lookup(cycle, f'https://example.com/{index}.png', {'success': False}, action)
        self.assertIsNotNone(cycle.before('shell', args('https://example.com/seventh.png', 'fetch')))
        self.assertEqual(cycle.downloads, 6)
        self.assertTrue(cycle.finalize)

    def test_mixed_find_then_edit_or_generate_keeps_lookup_intent(self):
        for request in ('Find an image of a cat then edit the image to wear a hat',
                        'Generate a logo, then find a photograph of an actual shop',
                        'Find photos of the building and create a new image using their colors'):
            with self.subTest(request=request):
                self.assertTrue(ImageLookupCycle(request).active)
        for request in ('Show me how to create a picture', 'Search image generation tools',
                        'Find articles about image classification', 'Generate an image of a cat'):
            with self.subTest(request=request):
                self.assertFalse(ImageLookupCycle(request).active)

    def test_general_nonimage_research_remains_unrestricted(self):
        cycle = ImageLookupCycle('Research the weather')
        for index in range(20):
            self.run_lookup(cycle, 'weather', {'results': []}, 'search')
        self.assertFalse(cycle.active)
        self.assertFalse(cycle.finalize)
        self.assertEqual(cycle.searches, 0)

    def test_saved_download_nested_result_preserves_real_path_and_url(self):
        cycle = ImageLookupCycle()
        self.run_lookup(cycle, 'specific machine', {'chosen': {'image_url': 'https://example.com/a.png',
                        'page_url': 'https://example.com/page'}, 'download': {'download_verified': True,
                        'source_url': 'https://example.com/a.png', 'path': 'Outputs/WebImages/actual.png'}})
        self.assertEqual(cycle.links, ['https://example.com/a.png'])
        self.assertIn('Outputs/WebImages/actual.png', cycle.fallback())
        self.assertIn('exact match has not been verified', cycle.fallback())

    def test_case_sensitive_urls_and_argument_options_are_preserved(self):
        cycle = ImageLookupCycle()
        for url in ('https://example.com/A.png', 'https://example.com/a.png'):
            self.assertIsNone(cycle.before('shell', args(url, 'download-image')))
        request = {'command': 'python Agent\\web_tools.py image-search --page-limit 3 " A specific PHOTO "'}
        self.assertEqual(cycle.request('shell', request), ('image-search', 'a specific photo'))

    def test_stalled_searches_still_allow_known_candidate_download_then_edit(self):
        cycle = ImageLookupCycle('Find a photo and edit it')
        url = 'https://example.com/source.png'
        self.run_lookup(cycle, 'first', {'images': [{'image_url': url, 'page_url': 'https://example.com/page'}]})
        self.run_lookup(cycle, 'second', {'images': []})
        self.run_lookup(cycle, 'third', {'images': []})
        self.run_lookup(cycle, 'fourth', {'images': []})
        self.assertTrue(cycle.finalize)
        self.assertIsNotNone(cycle.before('shell', args('https://example.com/unreturned.png', 'download-image')))
        self.run_lookup(cycle, url, {'download_verified': True, 'source_url': url,
                        'path': 'Outputs/WebImages/download.png'}, 'download-image')
        self.assertEqual(cycle.saved_files, ['Outputs/WebImages/download.png'])
        self.assertIsNone(cycle.before('shell', {'command': 'python Agent/ai_tools.py autoedit "Outputs/WebImages/download.png" "make it blue"'}))

    def test_returned_page_may_supply_new_image_after_search_closure(self):
        cycle = ImageLookupCycle('Find an image')
        page, image = 'https://example.com/page', 'https://example.com/photo.png'
        self.run_lookup(cycle, 'first', {'results': [{'url': page}]}, 'search')
        self.run_lookup(cycle, 'second', {'results': []}, 'search')
        self.run_lookup(cycle, 'third', {'results': []}, 'search')
        self.run_lookup(cycle, 'fourth', {'results': []}, 'search')
        self.run_lookup(cycle, page, {'url': page, 'image_url': image}, 'fetch')
        self.run_lookup(cycle, image, {'download_verified': True, 'source_url': image,
                        'path': 'Outputs/WebImages/photo.png'}, 'download-image')
        self.assertIn(image, cycle.links)
        self.assertTrue(cycle.finalize)
        self.assertIn('Previously returned candidate image/source URLs', cycle.guidance())

    def test_duplicate_and_query_ceiling_closures_allow_known_evidence_only(self):
        for closure in ('duplicate', 'ceiling'):
            with self.subTest(closure=closure):
                cycle = ImageLookupCycle()
                for index in range(8 if closure == 'ceiling' else 1):
                    self.run_lookup(cycle, f'query {index}', {'image_urls': [f'https://example.com/{index}.png']})
                if closure == 'duplicate':
                    cycle.before('shell', args('query 0'))
                    cycle.before('shell', args('query 0'))
                self.assertTrue(cycle.finalize)
                self.assertIsNotNone(cycle.before('shell', args('https://example.com/unknown', 'fetch')))
                self.assertIsNone(cycle.before('shell', args('https://example.com/0.png', 'download-image')))

    def test_elapsed_or_six_inspections_close_even_known_candidates(self):
        now = [0.0]
        with patch('image_lookup_policy.time.monotonic', side_effect=lambda: now[0]):
            cycle = ImageLookupCycle()
            candidates = [f'https://example.com/{index}.png' for index in range(7)]
            self.run_lookup(cycle, 'first', {'image_urls': candidates})
            self.run_lookup(cycle, 'second', {'image_urls': candidates})
            self.run_lookup(cycle, 'third', {'image_urls': candidates})
            for url in candidates[:6]:
                self.run_lookup(cycle, url, {'success': False}, 'download-image')
            blocked = json.loads(cycle.before('shell', args(candidates[6], 'download-image')))
            self.assertTrue(blocked['lookup_closed'])
            self.assertFalse(blocked['known_candidate_retrieval_available'])
            self.assertIn('No further web image lookup attempts remain', cycle.guidance())
            timed = ImageLookupCycle()
            self.run_lookup(timed, 'first', {'image_urls': candidates})
            now[0] = 180
            blocked = json.loads(timed.before('shell', args(candidates[0], 'download-image')))
            self.assertTrue(blocked['lookup_closed'])
            self.assertFalse(blocked['known_candidate_retrieval_available'])

    def test_portable_python_flags_and_result_schemas(self):
        request = {'command': '"Runtime/BootstrapPython/python.exe" -B -I -X utf8 Agent/web_tools.py image-search --page-limit=2 "exact machine"'}
        cycle = ImageLookupCycle()
        self.assertEqual(cycle.request('shell', request), ('image-search', 'exact machine'))
        self.assertIsNone(cycle.before('shell', request))
        cycle.record('shell', request, json.dumps({'success': False, 'details': {
            'images': [{'image_url': 'https://example.com/image.png', 'page_url': 'https://example.com/article'}],
            'search_results': [{'url': 'https://example.com/search-evidence'}]}}))
        self.assertEqual(cycle.links, ['https://example.com/image.png'])
        self.assertEqual(set(cycle.source_links), {'https://example.com/article', 'https://example.com/search-evidence'})
        self.assertEqual(cycle.no_progress, 0)

    def test_two_empty_queries_allow_spelling_and_event_refinement(self):
        cycle = ImageLookupCycle('Find an image from when Alexandra Ocasio-Cortez was dancing and edit it')
        self.run_lookup(cycle, 'Alexandra Ocasio-Cortez dancing photo', {'images': []})
        self.run_lookup(cycle, 'Alexandra Ocasio-Cortez dance image', {'images': []})
        self.assertFalse(cycle.finalize)
        self.run_lookup(cycle, 'Ocasio-Cortez Boston University dance video 2010',
                        {'results': [{'url': 'https://example.com/event-report'}]}, 'search')
        self.assertFalse(cycle.finalize)
        self.assertEqual(cycle.no_progress, 0)
        self.assertIn('possibly misspelled name', cycle.guidance())
        self.assertIsNone(cycle.before('shell', {'command': 'python Agent/ai_tools.py autoedit found.jpg "edit"'}))

    def test_structured_fetch_result_retains_page_image_candidates(self):
        cycle = ImageLookupCycle('Find an image')
        request = args('https://example.com/page', 'fetch')
        self.assertIsNone(cycle.before('shell', request))
        cycle.record('shell', request, {'url': 'https://example.com/page', 'images': [
            {'image_url': 'https://example.com/from-metadata.jpg', 'page_url': 'https://example.com/page', 'download_verified': False}]})
        self.assertEqual(cycle.links, ['https://example.com/from-metadata.jpg'])
        self.assertEqual(cycle.source_links, ['https://example.com/page'])


if __name__ == '__main__':
    unittest.main()
