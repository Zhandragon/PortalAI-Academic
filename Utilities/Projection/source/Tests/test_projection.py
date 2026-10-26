import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
import base64
import importlib.util
import json
import pathlib
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'Runtime/packages')]
if sys.platform.startswith('linux'):sys.path.insert(0,str(ROOT/'Runtime/LinuxPackages'))
import connection_vault as vault
from projection_client import Client
spec=importlib.util.spec_from_file_location('receiver',ROOT/'HomeAssistant/custom_components/portalai_projection/receiver.py')
receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)
from windows_desktop import png_rgb


class Tests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'Tests/Validation';folder.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.folder=pathlib.Path(self.temp.name)
        self.connection=vault.new_connection('https://example.invalid','../PortalAI','Synthetic')
        identity,entry=receiver.pairing(vault.public_pairing(self.connection))
        self.receiver=receiver.Receiver({identity:entry});self.identity=identity
        self.client=Client(self.connection,ROOT/'Runtime/cacert.pem')
    def tearDown(self):self.client.close();self.temp.cleanup()
    def dispatch(self,body):
        if body['action']=='challenge':return self.receiver.challenge(body['device_id'])
        if body['action']=='authenticate':return self.receiver.authenticate(body)
        return self.receiver.poll(self.client.session,body)
    def connect(self):
        self.client.request=self.dispatch;self.client.authenticate();self.client.poll({'windows':[]},{},[])
    def test_encrypted_settings_and_password_change(self):
        path=self.folder/'connection.enc';vault.save(path,self.connection,'Synthetic-password-A')
        raw=path.read_bytes();self.assertNotIn(b'example.invalid',raw);self.assertNotIn(b'PRIVATE KEY',raw)
        self.assertEqual(vault.unlock(path,'Synthetic-password-A'),self.connection)
        with self.assertRaises(Exception):vault.unlock(path,'incorrect-password')
        vault.save(path,self.connection,'Synthetic-password-B')
        with self.assertRaises(Exception):vault.unlock(path,'Synthetic-password-A')
        self.assertEqual(vault.unlock(path,'Synthetic-password-B')['device_id'],self.identity)
    def test_ciphertext_tamper_rejected(self):
        path=self.folder/'connection.enc';vault.save(path,self.connection,'Synthetic-password-A')
        raw=bytearray(path.read_bytes());raw[-1]^=1;path.write_bytes(raw)
        with self.assertRaises(Exception):vault.unlock(path,'Synthetic-password-A')
    def test_never_store_ha_credentials(self):
        for key in ('password','access_token','refresh_token','cookie'):
            with self.assertRaises(ValueError):vault.save(self.folder/'bad.enc',{**self.connection,key:'secret'},'Synthetic-password-A')
        public=vault.public_pairing(self.connection)
        self.assertEqual(set(public),{'device_id','name','public_key','fingerprint'})
    def test_url_rejects_credentials_http_and_paths(self):
        for address in ('http://example.com','https://user:pass@example.com','https://example.com/api','https://example.com/?token=abc','https://example.com/#secret'):
            with self.assertRaises(ValueError):vault.url(address)
    def test_unapproved_device_rejected(self):
        with self.assertRaises(PermissionError):self.receiver.challenge('f'*32)
    def test_wrong_signing_key_rejected(self):
        other=vault.new_connection(self.connection['url'],'../PortalAI','Other');other['device_id']=self.identity
        wrong=Client(other,ROOT/'Runtime/cacert.pem');wrong.request=self.dispatch
        with self.assertRaises(Exception):wrong.authenticate()
    def test_challenge_and_poll_replay_rejected(self):
        captured=[]
        def request(body):captured.append(body);return self.dispatch(body)
        self.client.request=request;self.client.authenticate()
        with self.assertRaises(PermissionError):self.receiver.authenticate(captured[1])
        self.client.poll({'windows':[]},{},[])
        with self.assertRaises(PermissionError):self.receiver.poll(self.client.session,captured[-1])
    def test_revocation_closes_projection_session(self):
        self.connect();self.receiver.revoke(self.identity)
        with self.assertRaises(PermissionError):self.client.poll(None,{},[])
    def test_no_ha_actions_exposed(self):
        self.connect()
        for action in ('call_service','fire_event','shell','auth','states','webhook','download'):
            with self.assertRaises(ValueError):self.receiver.enqueue(self.identity,action,{})
    def test_expired_commands_are_not_delivered(self):
        self.connect();key=self.receiver.enqueue(self.identity,'input',{'event':{'kind':'text','text':'do not replay'}})
        self.receiver.devices[self.identity]['queue'][0]['expires']=time.monotonic()-1
        self.assertEqual(self.client.poll(None,{},[]),[])
        self.assertNotIn(key,self.receiver.devices[self.identity]['replies'])
    def test_commands_dispatched_once_and_acks_scoped(self):
        self.connect();key=self.receiver.enqueue(self.identity,'start',{'request_id':'a'*32})
        commands=self.client.poll(None,{},[]);self.assertEqual(commands[0]['id'],key)
        self.assertEqual(self.client.poll(None,{},[{'id':key,'result':{'accepted':True}},{'id':'f'*32,'result':{}}]),[])
        state=self.receiver.devices[self.identity]
        self.assertTrue(state['replies'][key]['result']['accepted']);self.assertNotIn('f'*32,state['replies'])
    def test_stalled_capture_does_not_disable_force_control(self):
        self.connect();state=self.receiver.devices[self.identity];state['frame_at']=time.monotonic()-100
        self.client.poll(None,{'operation':{'state':'idle'}},[])
        self.assertTrue(self.receiver.enqueue(self.identity,'force_shutdown',{'confirm':'UNSAFE SHUTDOWN'}))
    def test_one_viewer_and_valid_png_header(self):
        self.connect();self.receiver.lease(self.identity,'first')
        with self.assertRaises(PermissionError):self.receiver.lease(self.identity,'second')
        png=base64.b64encode(png_rgb(b'\0'*(80*40*4),80,40)).decode()
        valid={'png':png,'width':80,'height':40,'window':'a'*32,'windows':[]}
        self.assertEqual(receiver.frame(valid)['width'],80)
        with self.assertRaises(ValueError):receiver.frame({**valid,'width':81})
    def test_real_https_transport_has_no_ha_authorization(self):
        import datetime
        from http.server import HTTPServer,BaseHTTPRequestHandler
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import ipaddress
        key=ec.generate_private_key(ec.SECP256R1());name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic receiver')]);now=datetime.datetime.now(datetime.timezone.utc)
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256())
        crt=self.folder/'ca.pem';private=self.folder/'key.pem';crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM));private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(crt,private);test=self;headers=[];peers=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*_):pass
            def do_POST(self):
                headers.append(dict(self.headers));peers.append(self.client_address);test.assertEqual(self.path,'/api/portalai_projection/v1')
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                result=test.dispatch(body);data=json.dumps(result).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=HTTPServer(('127.0.0.1',0),Handler);server.socket=context.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.client=Client({**self.connection,'url':f'https://127.0.0.1:{server.server_port}'},crt)
        try:self.client.authenticate();self.client.poll({'windows':[]},{},[])
        finally:self.client.close();server.shutdown();server.server_close();thread.join(3)
        self.assertEqual(len(headers),3)
        self.assertEqual(len(set(peers)),1)
        self.assertTrue(all('Authorization' not in h and 'Cookie' not in h for h in headers))

    def test_corrupt_profile_marker_keeps_management_status_available(self):
        import portalai_target
        portalai_target.configure(default_target())
        manager=portalai_target.Manager(default_target(),object());manager.inventory=lambda fresh=False:{}
        with patch('profile_shutdown._marker',side_effect=RuntimeError('Corrupt marker')):
            status=manager.status()
        self.assertIn('unavailable',status['profile_state']);self.assertEqual(status['operation']['state'],'idle')

    def test_optional_input_scope_is_consumed_before_child_launches(self):
        import os
        sys.path.insert(0,str(default_target()/'ControlCenter'))
        import remote_desktop_input
        module=self.folder/'Projection';(module/'app').mkdir(parents=True);(module/'app/projection_worker.py').write_text('# fixture')
        scope=module/'state/input/synthetic-owner'
        scope.mkdir(parents=True)
        with patch.dict(os.environ,{'PORTALAI_PROJECTION_HOME':str(module),'PORTALAI_PROJECTION_INPUT':str(scope)}),patch.object(remote_desktop_input,'InputAdapter') as adapter:
            remote_desktop_input.install(object(),self.folder)
            self.assertEqual(adapter.call_args.args[1],scope)
            self.assertNotIn('PORTALAI_PROJECTION_HOME',os.environ);self.assertNotIn('PORTALAI_PROJECTION_INPUT',os.environ)


if __name__=='__main__':unittest.main()
