"""Synthetic account/HTTP fixtures only; no owner data or live model jobs."""
import io,json,os,socket,sys,tempfile,threading,unittest,urllib.error,urllib.request,uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import instance_runtime as instances
import web_capabilities as web
import agent_collaboration as agents
from profile_context import CapturedProfile

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'app';self.root.mkdir()
    def tearDown(self):self.temp.cleanup()

class Ports(Fixture):
    def test_simultaneous_instances_have_distinct_complete_port_sets(self):
        other=self.base/'drive2';other.mkdir();host=self.base/'host';host.mkdir()
        with patch.object(instances,'host_directory',return_value=host):
            with instances.InstanceSession(self.root),instances.InstanceSession(other):
                a=instances.endpoints(self.root);b=instances.endpoints(other)
                self.assertFalse(set(a.values())&set(b.values()))
                self.assertEqual(set(a),set(instances.DEFAULTS))
    def test_manual_occupied_port_does_not_touch_listener(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));listener.listen();number=listener.getsockname()[1]
            instances.save_settings(self.root,{'ports':{'qwen':number}})
            with self.assertRaises(RuntimeError):instances.InstanceSession(self.root,self.base/'host').start()
            with socket.create_connection(('127.0.0.1',number),timeout=1):pass
    def test_double_controller_refused_and_stale_reservation_reclaimed(self):
        host=self.base/'host';host.mkdir()
        with patch.object(instances,'host_directory',return_value=host):
            with instances.InstanceSession(self.root):
                with self.assertRaises(RuntimeError):instances.InstanceSession(self.root).start()
            with instances.InstanceSession(self.root) as new:self.assertEqual(len(new.record['ports']),len(instances.DEFAULTS))
    def test_bad_manual_settings_preserve_existing(self):
        instances.save_settings(self.root,{'ports':{'qwen':24001}})
        for ports in ({'qwen':-1},{'qwen':True},{'qwen':24001,'comfyui':24001},{'unknown':24001}):
            with self.assertRaises(ValueError):instances.save_settings(self.root,{'ports':ports})
        self.assertEqual(instances.settings(self.root)['ports']['qwen'],24001)
    def test_copied_endpoint_map_is_not_used(self):
        p=self.root/'Agent/.runtime/instance-endpoints.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'key':'wrong-root','ports':{'qwen':31000}}))
        self.assertEqual(instances.port('qwen',self.root),8080)

class HTTPFixture(Fixture):
    def setUp(self):
        super().setUp();self.requests=[];seen=self.requests
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                seen.append((self.path,self.headers.get('Authorization')))
                if self.path=='/redirect':self.send_response(302);self.send_header('Location','http://127.0.0.1:1/forbidden');body=b''
                elif self.path=='/large':self.send_response(200);body=b'X'*(web.LIMIT+1)
                else:self.send_response(200);body=b'<html><title>Fixture</title><h1>One</h1><p>alpha</p><h2>Two</h2><p>omega</p><input aria-label="Name"><button onclick="document.querySelector(\'h1\').textContent=\'Clicked\'">Go</button><a href="/next">Next</a></html>'
                self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(body)));self.end_headers()
                try:self.wfile.write(body)
                except (BrokenPipeError,ConnectionResetError):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));seen.append(('POST',body.decode()))
                self.send_response(201);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(body)
        self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.http.server_port)
    def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();super().tearDown()
    def validator(self,url):
        parsed=urllib.parse.urlparse(url)
        if parsed.hostname!='127.0.0.1' or parsed.port!=self.http.server_port:raise ValueError('Outside synthetic HTTP fixture')
        return parsed
    def test_api_mutation_once_and_redirect_not_followed(self):
        with patch.object(web,'_validate_public_url',side_effect=self.validator):
            result=web.api_request({'url':self.url,'method':'POST','json':{'proof':'once'}})
            self.assertEqual(result['status'],201)
            result=web.api_request({'url':self.url+'/redirect'})
            self.assertEqual(result['status'],302);self.assertFalse(result['redirect_followed'])
        self.assertEqual(len(self.requests),2)
    def test_credentials_require_tls_and_invalid_headers_never_send(self):
        with patch.object(web,'_validate_public_url',side_effect=self.validator):
            for headers in ({'Authorization':'secret'},{'Host':'wrong'},{'X-Test':'x\r\nBad: header'}):
                with self.assertRaises(ValueError):web.api_request({'url':self.url,'headers':headers})
        self.assertEqual(self.requests,[])
    def test_response_and_request_size_limits(self):
        with patch.object(web,'_validate_public_url',side_effect=self.validator):
            with self.assertRaises(ValueError):web.api_request({'url':self.url+'/large'})
            with self.assertRaises(ValueError):web.api_request({'url':self.url,'method':'POST','body':'x'*(1024*1024+1)})
    def test_real_browser_state_inspection_and_close(self):
        class Profile:
            def check(inner):pass
            def private(inner,name):return self.root/name
        session=web.WebSession(ROOT,Profile())
        try:
            with patch.object(web,'_validate_public_url',side_effect=self.validator):
                opened=session.run({'action':'open','url':self.url});key=opened['page']
                self.assertEqual(opened['title'],'Fixture')
                view=session.run({'action':'inspect','page':key});self.assertIn('alpha',view['text']);self.assertEqual(view['links'][0]['text'],'Next')
                session.run({'action':'fill','page':key,'role':'textbox','name':'Name','value':'synthetic'})
                session.run({'action':'click','page':key,'role':'button','name':'Go'})
                view=session.run({'action':'inspect','page':key,'selector':'h1'});self.assertEqual(view['text'],'Clicked')
                shot=session.run({'action':'screenshot','page':key});self.assertTrue(Path(shot['screenshot']).is_file())
                with self.assertRaises(ValueError):session.run({'action':'open','url':'http://127.0.0.1:1/'})
        finally:session.close()
        self.assertIsNone(session.browser)

class Reader(Fixture):
    def test_full_document_is_retrievable_without_repeating_fetch(self):
        session=web.WebSession(self.root,CapturedProfile(self.root));source='<h1>Start</h1><p>'+('abc '*10000)+'</p><h2>End</h2><a href="/there">Link</a>'
        with patch.object(web,'_request_bytes',return_value=(source.encode(),'https://example.com/','text/html')) as fetch:
            first=session.run({'action':'read','url':'https://example.com/','max_chars':100})
            key=first['document'];parts=[first['text']];current=first
            while current['next_offset'] is not None:
                current=session.run({'action':'read','document':key,'offset':current['next_offset'],'max_chars':50000});parts.append(current['text'])
            self.assertEqual(fetch.call_count,1);self.assertIn('End',''.join(parts));self.assertEqual(len(''.join(parts)),first['total_chars'])
            result=session.run({'action':'read','document':key,'find':'End'});self.assertTrue(result['matches'])
            self.assertEqual(first['links'][0]['url'],'https://example.com/there')
    def test_guest_write_denial_before_start(self):
        session=web.WebSession(self.root,CapturedProfile(self.root),'guest')
        for args in ({'action':'click'},{'action':'request','method':'POST'}):
            with self.assertRaises(PermissionError):session.run(args)
        self.assertIsNone(session.browser)
    def test_private_and_invalid_urls_fail_closed(self):
        for url in ('file:///C:/secret','http://127.0.0.1/','http://user:secret@example.com','http://169.254.169.254/'):
            with self.assertRaises(ValueError):web._validate_public_url(url)
    def test_profile_expiry_stops_reads(self):
        profile=CapturedProfile(self.root)
        with patch.object(profile,'check',side_effect=PermissionError('ended')):
            with self.assertRaises(PermissionError):web.WebSession(self.root,profile).run({'action':'help'})

class Collaboration(Fixture):
    def setUp(self):
        super().setUp();self.other=self.base/'second-drive';self.other.mkdir();self.host=self.base/'host';self.host.mkdir()
        self.hostpatch=patch.object(instances,'host_directory',return_value=self.host);self.hostpatch.start()
        self.a=instances.InstanceSession(self.root).start();self.b=instances.InstanceSession(self.other).start()
        agents.configure(self.root,True);agents.configure(self.other,True)
        self.one=agents.Broker(self.root,CapturedProfile(self.root),'admin').start()
        self.two=agents.Broker(self.other,CapturedProfile(self.other),'admin').start()
    def tearDown(self):
        self.one.close();self.two.close();self.a.close();self.b.close();self.hostpatch.stop();super().tearDown()
    def test_bidirectional_pairing_and_message_deduplication(self):
        self.one.pair('other',self.two.code());self.two.pair('first',self.one.code())
        args={'action':'send','agent':'chat','text':'finding','message_id':uuid.uuid4().hex}
        first=self.one.request(self.one.peers['other'],args);second=self.one.request(self.one.peers['other'],args)
        self.assertFalse(first['duplicate']);self.assertTrue(second['duplicate']);self.assertEqual(len(agents.Mailbox(self.other).inbox()['messages']),1)
        self.two.request(self.two.peers['first'],{**args,'text':'reply'})
        self.assertEqual(agents.Mailbox(self.root).inbox()['messages'][0]['text'],'reply')
    def test_unpaired_requests_denied(self):
        row={'port':self.two.server.server_port,'token':'x'*43}
        with self.assertRaises(urllib.error.HTTPError):self.one.request(row,{'action':'hello'})
    def test_incoming_delegation_requires_receiver_opt_in_and_mode(self):
        self.one.pair('other',self.two.code())
        args={'action':'delegate','request_id':uuid.uuid4().hex,'objective':'Read source','mode':'full'}
        with patch.object(agents,'create_agent') as create:
            with self.assertRaises(urllib.error.HTTPError):self.one.request(self.one.peers['other'],args)
            agents.configure(self.other,True,True,'observe')
            with self.assertRaises(urllib.error.HTTPError):self.one.request(self.one.peers['other'],args)
            create.assert_not_called()
    def test_delegation_receipt_prevents_duplicate_spawn(self):
        self.one.pair('other',self.two.code());agents.configure(self.other,True,True,'observe')
        args={'action':'delegate','request_id':uuid.uuid4().hex,'objective':'Read source','mode':'observe'}
        with patch.object(agents,'create_agent',return_value={'agent':'a'*32}) as create:
            self.one.request(self.one.peers['other'],args);self.one.request(self.one.peers['other'],args);self.assertEqual(create.call_count,1)
    def test_ended_login_or_stop_denies_messages(self):
        self.one.pair('other',self.two.code())
        with patch.object(self.two.profile,'check',side_effect=PermissionError('ended')):
            with self.assertRaises(urllib.error.HTTPError):self.one.request(self.one.peers['other'],{'action':'send','text':'late'})
        self.two.close()
        with self.assertRaises(Exception):self.one.request(self.one.peers['other'],{'action':'hello'})
        self.assertEqual(agents.Mailbox(self.other).inbox()['messages'],[])
    def test_mode_denials_and_offline_vm(self):
        from mission_modes import authorize_action
        for action in ('message','inbox'):
            authorize_action('observe',action)
            with self.assertRaises(PermissionError):authorize_action('vm',action)
        with self.assertRaises(PermissionError):agents.create_agent(self.root,{'objective':'x','mode':'full'},'user')

    def test_mission_web_requires_full_admin_and_closes_on_stop(self):
        from mission_runner import Missions
        store=Missions(self.root);mission=store.create('inspect public page',mode='observe')
        args={'action':'web','mission':mission['id'],'operation':'help','parameters':{}}
        with self.assertRaises(PermissionError):self.one.relay(args)
        mission['mode']='full';store.save(mission)
        with patch('web_tool_api.WebClient') as worker:
            worker.return_value.call.return_value='{"ok":true,"result":{"fixture":true}}'
            self.assertTrue(self.one.relay(args)['ok'])
            self.assertTrue(self.one.relay(args)['ok']);self.assertEqual(worker.call_count,1)
            self.one.close();worker.return_value.close.assert_called_once()
        self.two.role='user'
        with patch('mission_runner.Missions.load',return_value=mission),patch('mission_runner.Missions.stopped',return_value=False):
            with self.assertRaises(PermissionError):self.two.relay(args)

if __name__=='__main__':unittest.main()
