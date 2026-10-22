"""Focused rich reads using genuine disposable accounts; no live chat/inference."""
import base64,json,os,sys,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Maintenance/Tests'),str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
import test_native_ui_state as fixture
from native_rich_chat import Controller,observe,opaque,sanitize,media_type
from native_rich_protocol import validate_request,validate_reply,LIMIT,CHUNK,BATCH_CHUNK
from writer_jobs import WriterJobs

class RichTests(unittest.TestCase):
    def setUp(self):
        fixture.NativeStateTests.setUp(self)
        self.app.grab_current=lambda:None;self.panel._check_login=self.export.profile.check
        self.jobs=WriterJobs();self.panel._thread=self.jobs.thread
        self.panel.submit=Mock();self.panel.stop_generation=Mock()
        self.reader=Controller(self.export)
        read=self.reader.read_media
        def checked_read(*a):
            try:return read(*a)
            except Exception as e:self.read_error=repr(e);raise
        self.reader.read_media=checked_read
    def tearDown(self):
        self.jobs.close();self.assertTrue(self.jobs.wait(3)['stopped'])
        fixture.NativeStateTests.tearDown(self)
    def payload(self,op='rich_index',**extra):
        return {'protocol':2 if op=='rich_media_batch' else 1,'request_id':'a'*32,'viewer':'b'*32,'operation':op,
                'binding':{'view':self.export.view,'epoch':self.export.epoch},'conversation':self.panel.session['id'],**extra}
    def call(self,op='rich_index',**extra):
        p=self.payload(op,**extra);r=self.reader.execute(p,time.monotonic()+3)
        if not isinstance(r,dict):
            self.assertTrue(r.done.wait(2))
            if r.error and not getattr(self,'expect_media_refusal',False):
                raise RuntimeError('Fixture read diagnosis: '+getattr(self,'read_error','unknown'))
            r=r.poll()
        validate_reply(r,p);return r['rich']
    def test_actual_records_no_system_or_fabricated_prose_tools(self):
        self.panel.session['messages']+=[{'role':'system','content':'Never export system','reasoning':'no'},
          {'role':'assistant','content':'I could call a tool','reasoning':'Actual recorded thought',
           'tool_calls':[{'id':'call1','function':{'name':'lookup','arguments':'{"query":"fixture","api_key":"hidden"}'}}]},
          {'role':'tool','tool_call_id':'call1','name':'lookup','content':'{"result":"ok","token":"hidden"}'}]
        r=self.call();self.assertEqual([b['kind'] for b in r['blocks']],['thinking','tool'])
        detail=self.call('rich_detail',block=r['blocks'][1]['id']);self.assertIn('fixture',detail['text']);self.assertNotIn('hidden',detail['text'])
        self.assertEqual(r['blocks'][1]['status'],'returned');self.panel.submit.assert_not_called();self.panel.stop_generation.assert_not_called()
    def test_stable_stream_final_ids_and_replaced_turn_invalidates(self):
        self.panel.busy=True;observe(self.panel,'assistant_start',{'index':1});observe(self.panel,'reasoning','Live thought')
        first=self.call()['blocks'][0];self.assertEqual(first['status'],'streaming')
        observe(self.panel,'reasoning',' more');self.assertEqual(first['id'],self.call()['blocks'][0]['id'])
        self.panel.session['messages'].append({'role':'assistant','content':'Result','reasoning':'Live thought more'})
        observe(self.panel,'done',None);self.panel.busy=False
        final=self.call()['blocks'][0];self.assertEqual(first['id'],final['id']);self.assertEqual(final['message'],opaque(self.export.epoch,self.panel.session['id'],1))
        self.panel.session['messages'][1]={'role':'assistant','content':'Edit','reasoning':'Different'}
        with self.assertRaises(PermissionError):self.call('rich_detail',block=first['id'])
    def test_auth_expiry_modal_and_conversation_guards(self):
        p=self.payload()
        with self.assertRaises(TimeoutError):self.reader.execute(p,time.monotonic()-1)
        with self.assertRaises(PermissionError):self.reader.execute({**p,'conversation':'old'},time.monotonic()+1)
        with self.assertRaises(PermissionError):self.reader.execute({**p,'binding':{'view':'old','epoch':'old'}},time.monotonic()+1)
        self.app.grab_current=lambda:object()
        with self.assertRaises(PermissionError):self.call()
        self.app.grab_current=lambda:None;self.backend.logout(self.session)
        with self.assertRaises(PermissionError):self.call()
        replacement=self.backend.login('NativeFixture','Synthetic-native-fixture-2026');self.runtime.replace_session(replacement);self.gate.session=replacement
    def media(self,reference):
        self.panel.session['messages'][0]['attachments']=[{'name':'fixture','path':str(reference)}]
        return self.call()['blocks'][0]['id']
    def test_media_chunk_signature_and_no_external_paths(self):
        folder=self.export.profile.private('Data/Chat/Attachments/'+self.panel.session['id']);folder.mkdir(parents=True)
        path=folder/'fixture.wav';data=b'RIFF'+b'\x00'*4+b'WAVE'+b'\x00'*30000;path.write_bytes(data)
        block=self.media(path);r=self.call('rich_media',block=block,offset=0)
        self.assertEqual(r['mime'],'audio/wav');self.assertEqual(base64.b64decode(r['data']),data[:CHUNK]);self.assertFalse(r['eof'])
        last=self.call('rich_media',block=block,offset=CHUNK);self.assertTrue(last['eof']);self.assertEqual(last['identity'],r['identity'])
        self.assertNotIn(str(folder),json.dumps(r))
        png=folder/'pixel.png';png.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+cqBQAAAAASUVORK5CYII='))
        self.assertEqual(self.call('rich_media',block=self.media(png),offset=0)['mime'],'image/png')
        # A saved reference is still not authority to publish arbitrary files.
        for other in (self.root/'AGENTS.md',self.export.profile.private('Data/secret.txt')):
            other.write_text('private unrelated file');block=self.media(other)
            self.expect_media_refusal=True
            with self.assertRaisesRegex(RuntimeError,'unavailable'):self.call('rich_media',block=block,offset=0)
    def test_too_large_html_links_and_late_revocation(self):
        folder=self.export.profile.private('Data/Chat/Attachments/'+self.panel.session['id']);folder.mkdir(parents=True)
        path=folder/'fixture.png';path.write_bytes(b'<html>not an image</html>');block=self.media(path)
        self.assertEqual(self.call('rich_media',block=block,offset=0)['mime'],'application/octet-stream')
        with path.open('wb') as f:f.truncate(LIMIT+1)
        self.expect_media_refusal=True
        with self.assertRaises(RuntimeError):self.call('rich_media',block=block,offset=0)
        path.write_bytes(b'GIF89a'+b'\x00'*25)
        result=self.reader.execute(self.payload('rich_media',block=block,offset=0),time.monotonic()+3)
        self.assertTrue(result.done.wait(2));self.export.invalidate('closing')
        with self.assertRaises(PermissionError):result.poll()
    def test_path_and_handle_ctime_can_differ_for_unchanged_media(self):
        folder=self.export.profile.private('Data/Chat/Attachments/'+self.panel.session['id']);folder.mkdir(parents=True)
        path=folder/'different-times.wav';data=b'RIFF'+b'\0'*4+b'WAVE'+b'x'*30000;path.write_bytes(data)
        block=self.media(path);ino=path.stat().st_ino;real_fstat=os.fstat
        def handle_stat(fd):
            actual=real_fstat(fd)
            if actual.st_ino!=ino:return actual
            # Windows path stat may expose creation time where fstat exposes
            # change time. These clocks must not be compared across APIs.
            return SimpleNamespace(**{k:getattr(actual,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns')},
                                   st_ctime_ns=actual.st_ctime_ns+1000000000)
        with patch('native_rich_chat.os.fstat',side_effect=handle_stat):
            first=self.call('rich_media',block=block,offset=0)
            last=self.call('rich_media',block=block,offset=CHUNK)
        self.assertEqual(first['identity'],last['identity'])
        self.assertEqual(base64.b64decode(first['data'])+base64.b64decode(last['data']),data)
    def test_media_still_refuses_wrong_handle_or_changed_handle_metadata(self):
        folder=self.export.profile.private('Data/Chat/Attachments/'+self.panel.session['id']);folder.mkdir(parents=True)
        path=folder/'identity.wav';path.write_bytes(b'RIFF'+b'\0'*4+b'WAVE'+b'x'*40)
        block=self.media(path);ino=path.stat().st_ino;real_fstat=os.fstat;self.expect_media_refusal=True
        for field,when,code in [('st_ino',1,'rich_media_replaced'),('st_mtime_ns',1,'rich_media_replaced'),
                                ('st_ctime_ns',2,'rich_media_changed')]:
            with self.subTest(field=field):
                calls=0
                def handle_stat(fd):
                    nonlocal calls
                    actual=real_fstat(fd)
                    if actual.st_ino!=ino:return actual
                    calls+=1;values={k:getattr(actual,k) for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')}
                    if calls>=when:values[field]+=1
                    return SimpleNamespace(**values)
                with patch('native_rich_chat.os.fstat',side_effect=handle_stat):
                    with self.assertRaisesRegex(RuntimeError,'unavailable'):self.call('rich_media',block=block,offset=0)
                self.assertIn(code,self.read_error)
    def test_generated_media_batches_cover_image_video_music_and_speech(self):
        folder=self.export.profile.private('Outputs/NativeRichFixture');folder.mkdir(parents=True)
        formats=[('.png',b'\x89PNG\r\n\x1a\n'+b'\0\0\0\rIHDR'+(128).to_bytes(4,'big')*2,'image/png'),
                 ('.jpg',b'\xff\xd8\xff\xc0\0\x11\x08\0\x80\0\x80','image/jpeg'),
                 ('.gif',b'GIF89a\x80\0\x80\0','image/gif'),
                 ('.webp',b'RIFF'+b'\0'*4+b'WEBPVP8X'+b'\0'*8+b'\x7f\0\0'*2,'image/webp'),
                 ('.wav',b'RIFF'+b'\0'*4+b'WAVE','audio/wav'),('.mp3',b'ID3','audio/mpeg'),
                 ('.ogg',b'OggS','audio/ogg'),('.flac',b'fLaC','audio/flac'),
                 ('.mp4',b'\0\0\0\x18ftyp','video/mp4'),('.webm',b'\x1aE\xdf\xa3','video/webm')]
        assistant={'role':'assistant','tool_calls':[{'id':'media-call','function':{'name':'media_tool','arguments':'{}'}}]}
        tool={'role':'tool','tool_call_id':'media-call','content':'Fixture generated media'}
        self.panel.session['messages'] += [assistant,tool]
        for extension,header,mime in formats:
            with self.subTest(mime=mime):
                data=header+b'x'*(605208-len(header));path=folder/('fixture'+extension);path.write_bytes(data)
                tool['media']=[{'path':path.relative_to(self.root).as_posix()}]
                block=next(b['id'] for b in self.call()['blocks'] if b['kind']=='media')
                offset=0;chunks=[];ident=None
                while offset<len(data):
                    r=self.call('rich_media_batch',block=block,offset=offset);self.assertEqual(r['mime'],mime)
                    self.assertLessEqual(r['next']-offset,BATCH_CHUNK);chunks.append(base64.b64decode(r['data']));offset=r['next']
                    if ident is not None:self.assertEqual(ident,r['identity'])
                    ident=r['identity']
                self.assertEqual(len(chunks),3);self.assertEqual(b''.join(chunks),data);self.assertTrue(r['eof'])
                self.assertLessEqual(self.call('rich_media',block=block,offset=0)['next'],CHUNK)
        with self.assertRaises(ValueError):validate_request({**self.payload('rich_media_batch',block=block,offset=0),'protocol':1})
    def test_truncation_unicode_schema_and_secret_redaction(self):
        self.panel.session['messages'].append({'role':'assistant','content':'','reasoning':'😀'*20000})
        b=self.call()['blocks'][0];r=self.call('rich_detail',block=b['id']);self.assertTrue(r['truncated']);self.assertLessEqual(len(r['text'].encode()),48000)
        for bad in ({**self.payload(),'path':'C:/secret'},{**self.payload(),'protocol':True}):
            with self.assertRaises(ValueError):validate_request(bad)
        for value in ('Authorization: Bearer abc123','password=abc123','{"environment":{"x":"abc123"}}'):
            self.assertNotIn('abc123',sanitize(value))
        self.assertNotIn('abc123',sanitize('{"api_key":"abc123", "large":"'+'x'*60000))
    def test_profile_sealing_waits_for_media_reader(self):
        ready=threading.Event();release=threading.Event()
        self.panel.session['messages'][0]['attachments']=[{'path':'Data/Chat/Attachments/test.wav'}]
        block=self.call()['blocks'][0]['id']
        def slow(*a):ready.set();release.wait(2);raise PermissionError('fixture')
        with patch.object(self.reader,'read_media',side_effect=slow):
            job=self.reader.execute(self.payload('rich_media',block=block,offset=0),time.monotonic()+3);self.assertTrue(ready.wait(1))
            self.jobs.close();self.assertFalse(self.jobs.wait(.01)['stopped']);release.set();self.assertTrue(job.done.wait(2));self.assertTrue(self.jobs.wait(1)['stopped'])

    def test_preview_is_bounded_read_only_and_preserves_original(self):
        folder=self.export.profile.private('Data/Chat/Attachments/'+self.panel.session['id']);folder.mkdir(parents=True)
        path=folder/'photo.png';raw=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+cqBQAAAAASUVORK5CYII=');path.write_bytes(raw)
        block=self.media(path)
        with patch('subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=b'\xff\xd8\xffpreview')) as worker:
            preview=self.call('rich_preview',block=block,offset=0)
        self.assertEqual(preview['mime'],'image/jpeg');self.assertTrue(preview['eof']);self.assertLessEqual(preview['size'],CHUNK)
        self.assertEqual(worker.call_args.kwargs['input'],raw)
        self.assertEqual(base64.b64decode(self.call('rich_media_batch',block=block,offset=0)['data']),raw)
        with self.assertRaises(ValueError):self.call('rich_preview',block=block,offset=1)
        self.panel.submit.assert_not_called()

if __name__=='__main__':unittest.main()
