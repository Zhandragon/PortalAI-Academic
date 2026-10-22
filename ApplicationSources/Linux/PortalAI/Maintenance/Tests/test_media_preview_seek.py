"""Bounded loopback playback ranges; only synthetic account/files are used."""
from functools import partial
from http.server import ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from urllib.parse import quote

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import media_server
import media_paths
import profile_paths
from media_player import player_document


class MediaRangeTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='portal-range-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.uid='a'*32;self.epoch='b'*32
        registry=self.root/'Private/Accounts';registry.mkdir(parents=True)
        (registry/'initialized.json').write_text('{}')
        self.active=self.root/'Private/active-session.json'
        self.active.write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'open'}))
        env=patch.dict(os.environ,{profile_paths.UID_ENV:self.uid,profile_paths.EPOCH_ENV:self.epoch});env.start();self.addCleanup(env.stop)
        self.outputs=profile_paths.workspace_root(self.root,self.uid)/'Outputs';self.outputs.mkdir(parents=True)
        self.data=bytes(range(256))*32;(self.outputs/'fixture.mp4').write_bytes(self.data)
        self.token=media_paths.preview_credentials(self.root)
        handler=partial(media_server.PortableAIOutputHandler,directory=str(self.outputs),portable_root=self.root,
                        profile_context=(self.uid,self.epoch),capability=self.token)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler);self.server.daemon_threads=True
        thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True);thread.start()
        def close():self.server.shutdown();self.server.server_close();thread.join(timeout=3)
        self.addCleanup(close)
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.url=self.base+'/fixture.mp4?portal_token='+self.token

    def request(self,url=None,method='GET',**headers):
        try:r=urlopen(Request(url or self.url,method=method,headers=headers),timeout=3)
        except HTTPError as error:r=error
        with r:return r.status,r.headers,r.read()

    def test_full_head_and_browser_seek_ranges(self):
        status,headers,data=self.request();self.assertEqual((status,data),(200,self.data))
        self.assertEqual(headers['Accept-Ranges'],'bytes');self.assertEqual(headers['Content-Type'],'video/mp4')
        self.assertEqual(headers['Content-Length'],str(len(self.data)));self.assertEqual(headers['Cache-Control'],'no-store')
        for header,start,end in [('bytes=0-1',0,1),('bytes=2048-',2048,8191),('bytes=-128',8064,8191),('bytes=8100-9999',8100,8191),('bytes=-9000',0,8191)]:
            with self.subTest(header=header):
                status,headers,data=self.request(Range=header)
                self.assertEqual((status,data),(206,self.data[start:end+1]))
                self.assertEqual(headers['Content-Range'],f'bytes {start}-{end}/8192')
                self.assertEqual(headers['Content-Length'],str(end-start+1))
        status,headers,data=self.request(method='HEAD',Range='bytes=0-1')
        self.assertEqual((status,data),(200,b''));self.assertEqual(headers['Content-Length'],'8192')
        self.assertIsNone(headers['Content-Range'])

    def test_unsatisfiable_and_empty_ranges_have_correct_416(self):
        for header in ('bytes=8192-','bytes=3-2','bytes=-0','bytes=-','bytes=nope','bytes='+'9'*50+'-'):
            status,headers,data=self.request(Range=header)
            self.assertEqual((status,data),(416,b''));self.assertEqual(headers['Content-Range'],'bytes */8192')
            self.assertEqual(headers['Content-Length'],'0')
        (self.outputs/'empty.wav').touch()
        status,headers,data=self.request(self.base+'/empty.wav?portal_token='+self.token,Range='bytes=0-')
        self.assertEqual((status,data),(416,b''));self.assertEqual(headers['Content-Range'],'bytes */0')

    def test_multipart_unknown_units_and_stale_if_range_receive_whole_file(self):
        _,headers,_=self.request();etag=headers['ETag'];modified=headers['Last-Modified']
        for kwargs in ({'Range':'items=0-1'},{'Range':'bytes=0-1,4-5'},{'Range':'bytes=0-1','If-Range':'"stale"'}):
            status,_,data=self.request(**kwargs);self.assertEqual((status,data),(200,self.data))
        for validator in (etag,modified):
            status,headers,data=self.request(**{'Range':'bytes=0-1','If-Range':validator})
            self.assertEqual((status,data),(206,self.data[:2]))

    def test_ranges_and_player_require_token_and_revoke_on_logout(self):
        for suffix in ('','?portal_player=1'):
            self.assertEqual(self.request(self.base+'/fixture.mp4'+suffix,Range='bytes=0-1')[0],403)
        self.active.write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'sealing'}))
        for suffix in ('','&portal_player=1'):
            self.assertEqual(self.request(self.url+suffix,Range='bytes=0-1')[0],403)
            self.assertEqual(self.request(self.url+suffix,method='HEAD')[0],403)

    def test_player_keeps_raw_source_capability_and_escapes_filename(self):
        name='SOURCE & fixture.mp4';(self.outputs/name).write_bytes(self.data)
        url=self.base+'/'+quote(name)+'?portal_token='+self.token+'&portal_player=1'
        status,headers,data=self.request(url);html=data.decode()
        self.assertEqual(status,200);self.assertIn('text/html',headers['Content-Type'])
        self.assertIn('SOURCE &amp; fixture.mp4',html);self.assertIn('src="/'+quote(name)+'?portal_token='+self.token+'"',html)
        self.assertIn("seek.addEventListener('input'",html);self.assertIn('media.currentTime=target',html)
        self.assertIn("default-src 'none'",headers['Content-Security-Policy']);self.assertNotIn('https://',html)
        status,head,body=self.request(url,method='HEAD');self.assertEqual((status,body),(200,b''))
        self.assertGreater(int(head['Content-Length']),1000)

    def test_active_transfer_stops_on_revocation_between_chunks(self):
        handler=object.__new__(media_server.PortableAIOutputHandler)
        handler._response_range=(0,200000);target=io.BytesIO()
        with patch.object(handler,'_authorized',side_effect=[True,True,False]):
            handler.copyfile(io.BytesIO(b'x'*200000),target)
        self.assertEqual(len(target.getvalue()),65536)


class PlayerDocumentTests(unittest.TestCase):
    def test_untrusted_title_cannot_inject_markup_and_source_stays_local(self):
        html,csp=player_document('/fixture.mp4?portal_token=token','<script>SOURCE</script>','video')
        self.assertIn(b'&lt;script&gt;SOURCE&lt;/script&gt;',html);self.assertNotIn(b'<script>SOURCE',html)
        self.assertIn("media-src 'self'",csp)
        for url in ('https://external.example/movie.mp4','//external.example/movie.mp4'):
            with self.assertRaises(ValueError):player_document(url,'fixture','video')

    def test_preview_metadata_preserves_raw_url_and_adds_player_url(self):
        import ai_tools
        with patch.object(ai_tools,'_resolve_output_file',return_value=(Path('fixture.mp4'),Path('fixture.mp4'),None)), \
             patch.object(ai_tools,'_ensure_media_server',return_value=('http://127.0.0.1:8765',{})), \
             patch.object(ai_tools,'preview_url',side_effect=lambda root,url:url+'?portal_token=synthetic'):
            result=ai_tools._preview_for_path('fixture.mp4')
        self.assertEqual(result['url'],'http://127.0.0.1:8765/fixture.mp4?portal_token=synthetic')
        self.assertEqual(result['player_url'],result['url']+'&portal_player=1')
        self.assertIn(result['player_url'],result['markdown'])


if __name__=='__main__':unittest.main()
