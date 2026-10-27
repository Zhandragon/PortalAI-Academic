"""Production section navigation, distinct from model-authored trial patches."""
from pathlib import Path
import sys,unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import web_capabilities as web

class ReaderSectionTests(unittest.TestCase):
    def read(self,source,url,final=None,**args):
        session=web.WebSession(ROOT,Mock())
        with patch.object(web,'_request_bytes',return_value=(source.encode(),final or url.split('#')[0],'text/html')):
            value=session.run({'action':'read','url':url,**args})
        return session,value
    def test_id_unicode_legacy_duplicate_and_hidden(self):
        source='<script id="x">hidden</script><p>Intro</p><a name="café"></a><h2 id="x">First</h2><p>'+('A'*500)+'</p><h2 id="x">Second</h2>'
        _,value=self.read(source,'https://example.com/#x',max_chars=150)
        self.assertTrue(value['fragment_found']);self.assertTrue(value['text'].startswith('First'))
        self.assertNotIn('Second',value['text']);self.assertNotIn('hidden',value['text'])
        _,value=self.read(source,'https://example.com/#caf%C3%A9')
        self.assertEqual(value['fragment'],'café');self.assertTrue(value['fragment_found']);self.assertNotIn('Intro',value['text'])
    def test_redirect_missing_fragment_and_explicit_empty_redirect_fragment(self):
        source='<p>Intro</p><h2 id="section">Target</h2>'
        _,value=self.read(source,'https://example.com/old#section','https://example.com/new')
        self.assertTrue(value['fragment_found']);self.assertTrue(value['text'].startswith('Target'))
        _,value=self.read(source,'https://example.com/old#section','https://example.com/new#missing')
        self.assertFalse(value['fragment_found']);self.assertEqual(value['offset'],0)
        _,value=self.read(source,'https://example.com/old#section','https://example.com/new#')
        self.assertEqual(value['fragment'],'');self.assertEqual(value['offset'],0)
    def test_full_cache_offset_precedence_and_original_unicode_find_positions(self):
        source='<p>Straße İSTANBUL</p><h2 id="section">Target phrase</h2>'
        session,value=self.read(source,'https://example.com/#section',offset=0)
        self.assertEqual(value['offset'],0);self.assertIn('Straße',value['text'])
        with patch.object(web,'_request_bytes',side_effect=AssertionError('Must reuse full cached document')):
            found=session.run({'action':'read','document':value['document'],'find':'TARGET PHRASE'})
            street=session.run({'action':'read','document':value['document'],'find':'STRASSE'})
        self.assertTrue(value['text'][found['matches'][0]['offset']:].startswith('Target phrase'))
        self.assertTrue(value['text'][street['matches'][0]['offset']:].startswith('Straße'))
    def test_search_pagination_never_duplicates_expanding_unicode_character(self):
        text=('ß '*31)+'tail'
        first,next_offset=web.find_text(text,'s')
        second,end=web.find_text(text,'s',next_offset)
        self.assertEqual(len(first),30);self.assertEqual(len(second),1);self.assertIsNone(end)
        self.assertEqual([r['offset'] for r in first+second],list(range(0,62,2)))

if __name__=='__main__':unittest.main()
