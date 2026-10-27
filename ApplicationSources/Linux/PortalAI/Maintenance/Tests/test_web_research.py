import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import web_tools as web
import web_research as research
from web_capabilities import WebSession
from web_search_fallback import BingSearchParser
from web_state import WebState

class ResearchTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        (self.root/'Agent').mkdir();(self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.profile=Mock();self.profile.private.side_effect=lambda rel:self.root/rel
        self.session=WebSession(self.root,self.profile)
        self.addCleanup(self.session.close)
    def document(self,text,mime='text/html',url='https://example.com/page'):
        value={'url':url,'text':text,'content_type':mime,'headings':[],'links':[]};key=self.session._save_document(value);value['document']=key;return key
    def test_bing_organic_nested_markup_decoded_target_and_no_ads(self):
        target='https://docs.python.org/3/library/stdtypes.html';encoded='a1'+base64.urlsafe_b64encode(target.encode()).decode().rstrip('=')
        source='<li class="b_ad"><h2><a href="https://ad.example/">Ad</a></h2></li><li class="b_algo"><style>bad</style><h2><a href="https://www.bing.com/ck/a?u='+encoded+'">Python <b>docs</b></a></h2><p>A &amp; B</p><ul><li>extra</li></ul></li>'
        parser=BingSearchParser(web._candidate_url);parser.feed(source);parser.finish()
        self.assertEqual(parser.results,[{'title':'Python docs','url':target,'snippet':'A & B'}])
    def test_bing_rejects_private_targets_and_duplicates(self):
        source=''.join('<li class="b_algo"><h2><a href="'+url+'">x</a></h2></li>' for url in ('http://127.0.0.1/a','file:///a','https://u:p@example.com','https://example.com/a','https://example.com/a'))
        parser=BingSearchParser(web._candidate_url);parser.feed(source);parser.finish();self.assertEqual(len(parser.results),1)
    def test_bing_challenge_is_not_an_empty_success(self):
        with patch.object(web,'_request_bytes',return_value=(b'<title>Captcha</title>','https://www.bing.com/','text/html')):
            with self.assertRaises(web.WebAccessError):web.search_bing('query',6)
    def test_independent_provider_after_blocked_duckduckgo(self):
        state=WebState(self.root,environ={});rows=[{'title':'Docs','url':'https://docs.python.org/','snippet':'Official'}]
        with patch.object(web,'WebState',return_value=state),patch.dict(web.os.environ,{'BRAVE_SEARCH_API_KEY':''}),patch.object(web,'search_duckduckgo',side_effect=web.WebAccessError('challenge',category='browser_challenge')),patch.object(web,'search_bing',return_value=rows) as bing:
            first=web.web_search('documentation');second=web.web_search('documentation')
        self.assertEqual(first['provider'],'bing');self.assertTrue(second['cached']);bing.assert_called_once();self.assertEqual(first['provider_errors'][0]['category'],'browser_challenge')
    def test_site_search_filters_host_and_path(self):
        rows=[{'url':x} for x in ('https://docs.python.org/3/library/a','https://docs.python.org/3/libraryx/a','https://docs.python.org.evil.test/3/library/a','https://other.org/3/library/a')]
        with patch.object(research,'web_search',return_value={'results':rows,'provider':'fixture'}) as search:
            result=self.session.run({'action':'site_search','site':'https://docs.python.org/3/library','query':'strings'})
        self.assertEqual(len(result['results']),1);self.assertIn('site:docs.python.org/3/library',search.call_args.args[0])
    def test_site_search_rejects_private_scope(self):
        with patch.object(research,'web_search') as search:
            with self.assertRaises(ValueError):self.session.run({'action':'site_search','site':'localhost','query':'x'})
        search.assert_not_called()
    def test_site_query_encodes_observed_field_and_keeps_existing_filter(self):
        with patch.object(self.session,'_read',return_value={'text':'Results'}) as read:
            value=self.session.run({'action':'site_query','url':'https://example.com/find?type=paper&q=old','parameter':'q','query':'A & B'})
        self.assertEqual(read.call_args.args[0]['url'],'https://example.com/find?type=paper&q=A+%26+B')
        self.assertEqual(value['text'],'Results')
        with self.assertRaises(ValueError):self.session.run({'action':'site_query','url':'http://localhost/find','parameter':'q','query':'x'})
    def test_jsonl_and_binary_spreadsheet_are_not_misparsed(self):
        key=self.document('{"x":1}\n\n{"x":2}\n','application/x-ndjson')
        self.assertEqual(self.session.run({'action':'data','document':key})['items'],[{'x':1},{'x':2}])
        with patch.object(research,'_request_bytes',return_value=(b'PK\x03\x04bytes','https://example.com/sheet.xlsx','application/octet-stream')):
            with self.assertRaises(ValueError):self.session.run({'action':'data','url':'https://example.com/sheet.xlsx'})
    def test_discovery_identifies_media_files_transcripts_forms_tables(self):
        source='<title>Study</title><video src="clip.mp4"><track src="captions.vtt"></video><audio><source src="sound.ogg"></audio><a href="data.csv">Data</a><a href="paper.pdf">Paper</a><form action="/find"><input type="search" name="q"></form><table><tr><th>A</th></tr><tr><td>1</td></tr></table><script type="application/ld+json">{"@type":"VideoObject","contentUrl":"https://example.com/video.webm"}</script>'
        key=self.document(source);result=self.session.run({'action':'discover','document':key})
        self.assertTrue({'video','audio','transcript','data','pdf'}.issubset({x['kind'] for x in result['resources']}))
        self.assertFalse(any(x['content_fetched'] for x in result['resources']));self.assertEqual(result['search_forms'][0]['fields'][0]['name'],'q');self.assertEqual(result['tables_found'],1)
    def test_discovery_ignores_private_script_and_form_secrets(self):
        key=self.document('<script><a href="https://secret.example/">hidden</a></script><a href="http://127.0.0.1/">bad</a><form><input type="hidden" name="token" value="secret"><input name="q" value="secret"></form>')
        result=self.session.run({'action':'discover','document':key});self.assertEqual(result['resources'],[]);self.assertNotIn('secret',json.dumps(result))
    def test_feed_enclosures_and_data_attributes_are_preserved(self):
        key=self.document('<rss><channel><item><link>https://example.com/episode</link><enclosure url="https://example.com/clip.mp3" type="audio/mpeg" /></item></channel></rss>','application/rss+xml')
        links=self.session.run({'action':'discover','document':key})['resources']
        self.assertTrue(any(r['kind']=='audio' for r in links))
        self.assertTrue(any(r['url']=='https://example.com/episode' for r in links))
        data=self.session.run({'action':'data','document':key,'tag':'item'})
        self.assertTrue(any(r['attributes'].get('url','').endswith('.mp3') for r in data['items'][0]['children']))
    def test_binary_read_does_not_claim_to_have_analyzed_media(self):
        import web_capabilities
        with patch.object(web_capabilities,'_request_bytes',return_value=(b'RIFFbytes','https://example.com/audio.wav','audio/wav')):
            result=self.session.run({'action':'read','url':'https://example.com/audio.wav'})
        self.assertFalse(result['content_analyzed']);self.assertNotIn('text',result);self.assertEqual(result['kind'],'audio')
    def test_pdf_binary_bytes_still_reach_pdf_text_extraction(self):
        import web_capabilities
        reader=Mock();reader.pages=[Mock()];reader.pages[0].extract_text.return_value='Extracted paper text'
        with patch.object(web_capabilities,'_request_bytes',return_value=(b'%PDF-1.7\x00stream','https://example.com/paper.pdf','application/pdf')),patch.object(web_capabilities,'prepare'),patch.dict(sys.modules,{'pypdf':Mock(PdfReader=Mock(return_value=reader))}):
            result=self.session.run({'action':'read','url':'https://example.com/paper.pdf'})
        self.assertEqual(result['text'],'Extracted paper text');self.assertEqual(result['source'],'PDF text extraction')
    def test_json_pointer_and_pagination_do_not_skip_requested_rows(self):
        key=self.document(json.dumps({'a/b':list(range(120))}),'application/json')
        result=self.session.run({'action':'data','document':key,'pointer':'/a~1b','limit':100})
        self.assertEqual(result['items'],list(range(100)));self.assertEqual(result['next_offset'],100)
    def test_invalid_json_pointer_is_rejected(self):
        key=self.document('[1,2]','application/json')
        for pointer in ('/-1','/01','/~2'):
            with self.assertRaises(ValueError):self.session.run({'action':'data','document':key,'pointer':pointer})
    def test_large_data_preview_never_returns_an_unusable_next_offset(self):
        key=self.document(json.dumps(list(range(11000))),'application/json')
        result=self.session.run({'action':'data','document':key,'offset':10000,'limit':100})
        self.assertIsNone(result['next_offset']);self.assertTrue(result['more_available'])
        self.assertEqual(result['items'][0],10000)
    def test_csv_quoted_cells_and_tsv(self):
        key=self.document('name,value\n"A,B",2\n','text/csv');result=self.session.run({'action':'data','document':key})
        self.assertEqual(result['items'][1],['A,B','2'])
        key=self.document('a\tb\n1\t2','text/tab-separated-values');self.assertEqual(self.session.run({'action':'data','document':key})['format'],'tsv')
    def test_html_tables_and_xml_feed(self):
        key=self.document('<table><tr><th>x</th><th>y</th></tr><tr><td>1</td><td>2</td></tr></table>')
        self.assertEqual(self.session.run({'action':'data','document':key})['items'][1],['1','2'])
        key=self.document('<rss><channel><item><title>Entry</title></item></channel></rss>','application/rss+xml')
        result=self.session.run({'action':'data','document':key,'tag':'item'});self.assertEqual(result['items'][0]['text'],'Entry')
    def test_xml_entities_and_invalid_limits_rejected(self):
        key=self.document('<!DOCTYPE x [<!ENTITY s "bad">]><x>&s;</x>','application/xml')
        with self.assertRaises(ValueError):self.session.run({'action':'data','document':key})
        with self.assertRaises(ValueError):self.session.run({'action':'discover','document':key,'limit':True})
    def test_fetch_keeps_real_document_and_does_not_refetch_cached_data(self):
        with patch.object(research,'_request_bytes',return_value=(b'{"rows":[1,2]}','https://example.com/data','application/json')) as fetch:
            result=self.session.run({'action':'data','url':'https://example.com/data','pointer':'/rows'})
            again=self.session.run({'action':'data','document':result['document'],'pointer':'/rows'})
        fetch.assert_called_once();self.assertEqual(again['items'],[1,2])
    def test_database_query_is_encoded_and_metadata_is_distinguished(self):
        payload={'message':{'total-results':1,'items':[{'title':['Paper'],'URL':'https://doi.org/10.1/x','DOI':'10.1/x'}]}}
        with patch.object(research,'_request_bytes',return_value=(json.dumps(payload).encode(),'https://api.crossref.org/works','application/json')) as fetch:
            result=self.session.run({'action':'catalog_search','provider':'crossref','query':'A & B'})
        self.assertIn('A+%26+B',fetch.call_args.args[0]);self.assertEqual(result['results'][0]['title'],'Paper');self.assertIn('not been fetched',result['source'])
    def test_media_info_is_metadata_only(self):
        with patch.object(research,'_request_bytes',return_value=(b'{"title":"Clip","html":"<script>bad</script>"}','https://www.youtube.com/oembed','application/json')):
            result=self.session.run({'action':'media_info','url':'https://www.youtube.com/watch?v=example'})
        self.assertFalse(result['content_analyzed']);self.assertNotIn('html',result['metadata'])
    def test_expired_profile_does_not_start_network(self):
        self.profile.check.side_effect=PermissionError('ended')
        with patch.object(research,'_request_bytes') as fetch:
            with self.assertRaises(PermissionError):self.session.run({'action':'data','url':'https://example.com/data'})
        fetch.assert_not_called()
    def test_download_is_bounded_inert_private_and_hashed(self):
        with patch.object(research,'_request_bytes',return_value=(b'a,b\n1,2','https://example.com/data.csv','text/csv')) as fetch,patch.object(research,'require_space'):
            result=self.session.run({'action':'download','url':'https://example.com/data.csv','max_bytes':1000})
        self.assertEqual(fetch.call_args.kwargs['max_bytes'],1000);self.assertTrue(Path(result['path']).is_relative_to(self.root/'Outputs/WebResearch'));self.assertFalse(result['executed']);self.assertFalse(result['content_analyzed']);self.assertEqual(len(result['sha256']),64)
    def test_guest_download_denied_and_executable_extension_not_preserved(self):
        self.session.role='guest'
        with patch.object(research,'_request_bytes') as fetch:
            with self.assertRaises(PermissionError):self.session.run({'action':'download','url':'https://example.com/x'})
        fetch.assert_not_called();self.session.role='admin'
        with patch.object(research,'_request_bytes',return_value=(b'MZ','https://example.com/program.exe','application/octet-stream')),patch.object(research,'require_space'):
            result=self.session.run({'action':'download','url':'https://example.com/program.exe'})
        self.assertTrue(result['path'].endswith('.data'))
    def test_revoked_download_removes_its_new_file(self):
        def check():
            if list((self.root/'Outputs/WebResearch').glob('*.csv')):raise PermissionError('ended')
        self.profile.check.side_effect=check
        with patch.object(research,'_request_bytes',return_value=(b'x','https://example.com/data.csv','text/csv')),patch.object(research,'require_space'):
            with self.assertRaises(PermissionError):self.session.run({'action':'download','url':'https://example.com/data.csv'})
        self.assertEqual(list((self.root/'Outputs/WebResearch').iterdir()),[])

if __name__=='__main__':unittest.main()
