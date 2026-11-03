"""Photo retrieval regressions; invented profiles/pixels, never owner identity."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter')]
import web_tools as web
import web_capabilities as caps
import web_research as research
from web_image_quality import candidate_quality,assess_image
from image_lookup_policy import ImageLookupCycle
from chat_evidence import web_evidence

PAGE='https://scholar.google.com/citations?user=MAIN&hl=en'
PHOTO='https://scholar.googleusercontent.com/citations?view_op=medium_photo&user=MAIN&citpid=2'
RELATED='https://scholar.googleusercontent.com/citations?view_op=view_photo&user=OTHER'
HTML=('<html><title>Example researcher</title><meta property="og:image" content="/logo.png">'
      '<img src="/citations/images/avatar_scholar_128.png">'
      '<img src="'+RELATED+'" alt="Colleague"><img id="gsc_prf_pup-img" src="'+PHOTO+'">'
      '<a href="https://example.org/profile">Personal profile</a>'
      '<table><tr><th>Paper</th><th>Year</th></tr><tr><td>Example</td><td>2026</td></tr></table></html>')

class ProfileImages(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        (self.root/'Agent').mkdir();(self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.profile=Mock();self.profile.private.side_effect=lambda path:self.root/path
        self.session=caps.WebSession(self.root,self.profile);self.addCleanup(self.session.close)
    def read(self,html=HTML,url=PAGE):
        with patch.object(caps,'_request_bytes',return_value=(html.encode(),url,'text/html')):
            return self.session.run({'action':'read','url':url,'max_chars':100})
    def test_main_profile_precedes_social_logo_other_people_and_default(self):
        items=web._html_image_candidates(HTML,PAGE,12)
        self.assertEqual(items[0]['image_url'],PHOTO);self.assertEqual(items[0]['image_role'],'profile_image')
        self.assertEqual(next(x for x in items if x['image_url']==RELATED)['image_role'],'related_profile_image')
        self.assertTrue(items[-1]['likely_placeholder']);self.assertFalse(items[0]['exact_match_verified'])
    def test_read_returns_images_without_raw_html(self):
        result=self.read();self.assertEqual(result['image_urls'][0],PHOTO)
        self.assertNotIn('_html',result);self.assertNotIn('<table>',json.dumps(result));self.assertTrue(result['html_cached'])
    def test_read_then_cached_discover_never_refetches(self):
        page=self.read()
        with patch.object(research,'_request_bytes',side_effect=AssertionError('refetch')):
            result=self.session.run({'action':'discover','document':page['document'],'kind':'image'})
        self.assertEqual(result['resources'][0]['url'],PHOTO)
        self.assertEqual(result['resources'][0]['image_role'],'profile_image')
    def test_read_then_cached_tables_preserves_structure(self):
        page=self.read()
        result=self.session.run({'action':'data','document':page['document'],'format':'html','table':0})
        self.assertIn('2026',json.dumps(result));self.assertIn('Example',json.dumps(result))
    def test_cache_is_bounded_and_eviction_explicit(self):
        with patch.object(caps,'HTML_CACHE_CHARS',800):
            raw={'url':'https://example.org/data.json','text':'{"value":42}','content_type':'application/json'}
            key=self.session._save_document(raw);raw['document']=key
            first=self.read('<p>'+('A'*280)+'</p>')
            for _ in range(4):self.read('<p>'+('B'*280)+'</p>')
            self.assertLessEqual(sum(len(d.get('_html','')) for d in self.session.documents.values()),800)
            with self.assertRaisesRegex(ValueError,'bounded cache'):
                self.session.run({'action':'discover','document':first['document']})
            self.assertIn('AAA',self.session.run({'action':'read','document':first['document']})['text'])
            self.assertNotIn('html_cached',raw)
            self.assertIn('42',json.dumps(self.session.run({'action':'data','document':key})))
    def test_large_html_not_cached_but_candidates_returned(self):
        with patch.object(caps,'HTML_CACHE_CHARS',100):result=self.read()
        self.assertFalse(result['html_cached']);self.assertEqual(result['image_urls'][0],PHOTO)
    def test_jsonld_person_and_lazy_srcset_keep_evidence(self):
        markup='<meta property="og:image" content="/logo.png"><script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'Person','name':'Example','image':{'contentUrl':'/portrait.jpg'}}]})+'</script><img class="profile-photo" data-srcset="/small.jpg 1x, /large.jpg 2x">'
        images=web._html_image_candidates(markup,'https://example.org/person')
        self.assertEqual(images[0]['image_url'],'https://example.org/portrait.jpg')
        self.assertEqual(images[0]['alt'],'Example');self.assertTrue(any(x['image_url'].endswith('large.jpg') for x in images))
    def test_malformed_and_private_images_are_ignored(self):
        items=web._html_image_candidates('<img src="http://[bad/"><img src="http://127.0.0.1/x.png"><img src="/ok.jpg">','https://example.org/')
        self.assertEqual([i['image_url'] for i in items],['https://example.org/ok.jpg'])
    def test_scholar_host_lookalike_cannot_claim_same_profile(self):
        self.assertEqual(candidate_quality(PHOTO,'https://scholar.google.com.evil.example/citations?user=MAIN')['image_role'],'candidate')
    def test_github_url_alone_is_not_assumed_to_be_placeholder(self):
        self.assertFalse(candidate_quality('https://avatars.githubusercontent.com/u/123')['likely_placeholder'])
    def test_photo_download_rejects_default_before_publication(self):
        url='https://scholar.google.com/citations/images/avatar_scholar_128.png'
        with patch.object(research,'_request_bytes',return_value=(b'\xff\xd8\xfffixture',url,'image/jpeg')):
            with self.assertRaisesRegex(ValueError,'default avatar'):
                self.session.run({'action':'download','url':url,'purpose':'person_photo'})
        self.assertFalse((self.root/'Outputs').exists())
    def test_unrelated_download_does_not_start_image_cycle(self):
        cycle=ImageLookupCycle('Download the paper and summarize it')
        self.assertIsNone(cycle.before('web',{'action':'download','arguments':{'url':'https://example.org/paper.pdf'}}))
        self.assertFalse(cycle.active);self.assertEqual(cycle.downloads,0)
    def test_extensionless_jpeg_download_uses_signature(self):
        with patch.object(research,'_request_bytes',return_value=(b'\xff\xd8\xfffixture',PHOTO,'image/jpeg')):
            result=self.session.run({'action':'download','url':PHOTO})
        self.assertEqual(Path(result['path']).suffix,'.jpg');self.assertTrue(result['download_verified'])
        self.assertFalse(result['exact_match_verified']);self.assertFalse(result['content_analyzed'])
    def test_image_mime_with_html_body_is_not_saved_as_photo(self):
        with patch.object(research,'_request_bytes',return_value=(b'<html>not an image</html>',PHOTO,'image/jpeg')):
            with self.assertRaises(ValueError):self.session.run({'action':'download','url':PHOTO})
        self.assertFalse((self.root/'Outputs').exists())
    def test_revoked_download_cannot_publish(self):
        self.profile.check.side_effect=[None,None,RuntimeError('revoked')]
        with patch.object(research,'_request_bytes',return_value=(b'\xff\xd8\xfffixture',PHOTO,'image/jpeg')):
            with self.assertRaisesRegex(RuntimeError,'revoked'):self.session.run({'action':'download','url':PHOTO})
        self.assertFalse((self.root/'Outputs').exists())
    def test_compacted_context_keeps_photo_url_and_role(self):
        page=self.read();page['text']='long '*10000
        result=json.loads(web_evidence({'name':'web','content':json.dumps({'ok':True,'result':page})},7,1100))
        self.assertEqual(result['images'][0]['image_url'],PHOTO)
        self.assertEqual(result['images'][0]['image_role'],'profile_image');self.assertEqual(result['url'],PAGE)
        self.assertFalse(result['images'][0]['exact_match_verified']);self.assertLess(len(result['text_excerpt']),400)
        self.assertTrue(result['text_truncated'])
    def test_modern_search_is_bounded_and_worker_evidence_collected(self):
        cycle=ImageLookupCycle('Find a photo of Example Researcher')
        call={'action':'read','arguments':{'url':PAGE}}
        self.assertIsNone(cycle.before('web',call));page=self.read()
        cycle.record('web',call,{'ok':True,'result':page})
        self.assertIn(PHOTO,cycle.links)
        follow={'action':'discover','arguments':{'document':page['document'],'kind':'image'}}
        self.assertIsNone(cycle.before('web',follow));self.assertEqual(cycle.downloads,2)
        for i in range(cycle.MAX_SEARCHES):
            call={'action':'search','arguments':{'query':'Example '+str(i)}}
            if cycle.before('web',call) is None:cycle.record('web',call,{'ok':True,'result':{'results':[{'url':'https://example.org/'+str(i)}]}})
        self.assertTrue(cycle.finalize)
        self.assertIsNotNone(cycle.before('web',{'action':'search','arguments':{'query':'one more'}}))
        self.assertIsNone(cycle.before('read_file',{'path':'other-request.txt'}))
    def test_paged_read_is_distinct_but_still_bounded(self):
        cycle=ImageLookupCycle('Find a photo')
        for n in range(cycle.MAX_INSPECTIONS):
            call={'action':'read','arguments':{'url':PAGE,'offset':n*100}}
            self.assertIsNone(cycle.before('web',call));cycle.record('web',call,{'ok':True,'result':{'url':PAGE}})
        self.assertIsNotNone(cycle.before('web',{'action':'read','arguments':{'url':PAGE,'offset':9000}}))

if __name__=='__main__':unittest.main()
