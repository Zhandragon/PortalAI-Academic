"""Real parsing/publication contracts; no external network or production profiles."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import web_tools as web
from web_state import WebState
from profile_paths import ProfileLocked, UID_ENV, EPOCH_ENV

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1cAAAAASUVORK5CYII=')
PUBLIC='https://independent.example/photo.png'


class WebImageTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name);(self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        env=patch.dict(os.environ,{},clear=False);env.start();self.addCleanup(env.stop)
        os.environ.pop(UID_ENV,None);os.environ.pop(EPOCH_ENV,None)
        self.state=WebState(self.root)
        for target,value in [('ROOT',self.root),('WebState',lambda:self.state),('_validate_public_url',lambda url:None),('owned_preview',lambda *a:False)]:
            p=patch.object(web,target,value);p.start();self.addCleanup(p.stop)

    def enable_profile(self):
        self.marker=self.root/'Private/active-session.json';self.marker.parent.mkdir()
        self.active={'state':'open','user_id':'a'*32,'epoch':'b'*32}
        self.marker.write_text(json.dumps(self.active))
        os.environ[UID_ENV]='a'*32;os.environ[EPOCH_ENV]='b'*32
        self.state=WebState(self.root)

    def revoke(self):
        self.marker.write_text(json.dumps({**self.active,'state':'closed'}))

    def test_opener_installs_verified_portable_https_context(self):
        opener=web._opener()
        handler=next(h for h in opener.handlers if isinstance(h,web.urllib.request.HTTPSHandler))
        self.assertEqual(handler._context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(handler._context.check_hostname)
        self.assertGreaterEqual(handler._context.cert_store_stats()['x509_ca'],121)

    def test_json_bot_challenge_is_not_empty_image_success(self):
        body=json.dumps({'response_type':'botnet_challenge','challenge':{'opaque':'fixture'}}).encode()
        with patch.object(web,'_request_bytes',return_value=(body,PUBLIC,'application/json')):
            with self.assertRaises(web.WebAccessError) as error:web._json_request(PUBLIC)
        self.assertEqual(error.exception.details['category'],'browser_challenge')

    def test_image_provider_errors_are_distinct_from_no_results(self):
        with patch.object(web,'_request_bytes',return_value=(b'{"error":{"code":"maxlag","info":"Busy"}}',PUBLIC,'application/json')):
            with self.assertRaises(web.WebAccessError):web._json_request(PUBLIC)

    def test_general_image_results_take_priority_and_keep_arbitrary_domain(self):
        item={'image_url':PUBLIC,'page_url':'https://independent.example/story','title':'Fixture'}
        with patch.object(web,'_duckduckgo_images',return_value=[item]) as general,patch.object(web,'_wikipedia_lead_images') as wiki:
            result=web.image_search('unrestricted literal subject',candidate_limit=1)
        general.assert_called_once_with('unrestricted literal subject',limit=1);wiki.assert_not_called()
        self.assertEqual(result['image_urls'],[PUBLIC])
        self.assertEqual(result['images'][0]['page_url'],item['page_url'])
        self.assertFalse(result['images'][0]['download_verified'])

    def test_general_page_images_precede_wikimedia_and_keep_page_evidence_separate(self):
        pages=[{'url':'https://independent.example/story','snippet':'This is page text'}]
        with patch.object(web,'_duckduckgo_images',return_value=[]),patch.object(web,'_page_metadata_images',return_value=('ddg',pages,[{'image_url':PUBLIC,'page_url':pages[0]['url']}])) as metadata,patch.object(web,'_wikipedia_lead_images') as wiki:
            result=web.image_search('literal query',candidate_limit=1)
        metadata.assert_called_once();wiki.assert_not_called()
        self.assertEqual(result['image_urls'],[PUBLIC]);self.assertEqual(result['search_results'],pages)

    def test_empty_images_do_not_turn_page_text_into_an_image(self):
        with patch.object(web,'_duckduckgo_images',return_value=[]),patch.object(web,'_page_metadata_images',return_value=('ddg',[{'url':PUBLIC,'snippet':'Only text'}],[])),patch.object(web,'_wikipedia_lead_images',return_value=[]),patch.object(web,'_wikimedia_commons_images',return_value=[]):
            result=web.image_search('query')
        self.assertEqual(result['images'],[]);self.assertEqual(result['image_count'],0)
        output=io.StringIO()
        with patch.object(web,'image_search',return_value=result),patch.object(sys,'argv',['web_tools.py','image-search','query']),contextlib.redirect_stdout(output):
            with self.assertRaises(SystemExit) as exit:web.main()
        self.assertEqual(exit.exception.code,1);self.assertFalse(json.loads(output.getvalue())['success'])

    def test_real_metadata_parser_returns_image_url_not_article_url(self):
        body=b'<html><title>Article</title><meta property="og:image" content="/media/photo.png"><p>Text</p></html>'
        with patch.object(web,'_request_bytes',return_value=(body,'https://independent.example/article','text/html')):
            candidates=web._page_image_candidates('https://independent.example/article')
        self.assertEqual(candidates[0]['image_url'],'https://independent.example/media/photo.png')

    def test_image_fetch_returns_url_instead_of_decoding_pixels_as_text(self):
        for mime in ('image/png','application/octet-stream'):
            with self.subTest(mime=mime),patch.object(web,'_request_bytes',return_value=(PNG,PUBLIC,mime)):
                result=web.fetch_url(PUBLIC)
                candidates=web._page_image_candidates(PUBLIC)
            self.assertEqual(result['image_url'],PUBLIC);self.assertEqual(result['text'],'')
            self.assertEqual(candidates[0]['image_url'],PUBLIC)

    def test_credential_cannot_follow_same_host_https_downgrade(self):
        request=web.urllib.request.Request('https://api.search.brave.com/search',headers={'X-Subscription-Token':'fixture-secret'})
        with self.assertRaisesRegex(ValueError,'HTTPS origin'):
            web.SafeRedirectHandler().redirect_request(request,None,302,'Found',{},'http://api.search.brave.com/search')

    def test_ddg_token_challenge_has_explicit_category(self):
        with patch.object(web,'_request_bytes',return_value=(b'<title>Just a moment...</title>',PUBLIC,'text/html')):
            with self.assertRaises(web.WebAccessError) as error:web._duckduckgo_vqd('query')
        self.assertEqual(error.exception.details['category'],'browser_challenge')

    def test_html_is_rejected_despite_image_suffix_or_mime(self):
        for mime in ('text/html','image/jpeg'):
            with self.subTest(mime=mime),patch.object(web,'_request_bytes',return_value=(b'<html>Error page</html>',PUBLIC,mime)):
                with self.assertRaisesRegex(ValueError,'not a recognized image'):web.download_public_image(PUBLIC)
        self.assertFalse((self.root/'Outputs').exists())

    def test_download_uses_bytes_format_and_gui_files_contract(self):
        with patch.object(web,'_request_bytes',return_value=(PNG,'https://independent.example/file.jpg','application/octet-stream')):
            result=web.download_public_image(PUBLIC,query='Fixture')
        path=Path(result['path']);self.assertEqual(path.suffix,'.png');self.assertEqual(path.read_bytes(),PNG)
        self.assertEqual(result['files'],[str(path)]);self.assertEqual(result['validation'],'image_signature')
        self.assertIs(result['download_verified'],True)
        self.assertIs(result['exact_match_verified'],False)
        self.assertIn('already validated and saved',result['note'])
        self.assertIn('does not verify the pictured subject',result['note'])
        self.assertIn('ask what to change',result['note'])
        self.assertIn('no ai_tools.py image-info command',result['note'])
        self.assertFalse(list(path.parent.glob('*.part')))

    def test_revocation_during_network_prevents_output_and_new_cache(self):
        self.enable_profile()
        def network(*a,**k):self.revoke();return PNG,PUBLIC,'image/png'
        with patch.object(web,'_request_bytes',side_effect=network):
            with self.assertRaises(ProfileLocked):web.download_public_image(PUBLIC)
        self.assertFalse(list(self.root.glob('Private/Users/**/*')))

    def test_failed_disk_flush_removes_own_partial(self):
        with patch.object(web,'_request_bytes',return_value=(PNG,PUBLIC,'image/png')),patch.object(web.os,'fsync',side_effect=OSError('fixture disk failure')):
            with self.assertRaises(OSError):web.download_public_image(PUBLIC)
        self.assertFalse(list(self.root.glob('Outputs/**/*.*')))

    def test_revocation_after_publish_removes_only_own_image(self):
        self.enable_profile();original=Path.rename
        def rename(source,target):
            result=original(source,target);self.revoke();return result
        with patch.object(web,'_request_bytes',return_value=(PNG,PUBLIC,'image/png')),patch.object(Path,'rename',rename):
            with self.assertRaises(ProfileLocked):web.download_public_image(PUBLIC)
        self.assertFalse(list(self.root.glob('Private/Users/**/*.png')))
        self.assertFalse(list(self.root.glob('Private/Users/**/*.part')))

    def test_revocation_cleanup_preserves_foreign_replacement(self):
        self.enable_profile();original=Path.rename;sentinels=[]
        def rename(source,target):
            result=original(source,target);target=Path(target);self.revoke()
            # Create the replacement before dropping the old inode, avoiding
            # filesystem inode reuse in this deterministic identity regression.
            replacement=target.with_suffix('.sentinel');replacement.write_bytes(b'foreign')
            replacement.replace(target);sentinels.append(target);return result
        with patch.object(web,'_request_bytes',return_value=(PNG,PUBLIC,'image/png')),patch.object(Path,'rename',rename):
            with self.assertRaises(ProfileLocked):web.download_public_image(PUBLIC)
        self.assertEqual(sentinels[0].read_bytes(),b'foreign')

    def test_search_and_image_search_propagate_login_end_not_cache_warning(self):
        self.enable_profile()
        def response(*a,**k):self.revoke();return [{'image_url':PUBLIC,'url':PUBLIC}]
        with patch.object(web,'search_duckduckgo',side_effect=response):
            with self.assertRaises(ProfileLocked):web.web_search('query')
        self.marker.write_text(json.dumps(self.active))
        with patch.object(web,'_duckduckgo_images',side_effect=response):
            with self.assertRaises(ProfileLocked):web.image_search('query')


if __name__=='__main__':unittest.main()
