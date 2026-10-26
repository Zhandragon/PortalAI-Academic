"""Exact returned receiver contract, synthetic identity/state, no production key."""
import base64
import copy
import datetime
import ipaddress
import json
import logging
from pathlib import Path
import ssl
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import uuid

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'app'),str(MODULE/'Runtime/packages'),str(MODULE/'Tests'),
             str(MODULE/'Runtime/NativeState/websockets-15.0.1-py3-none-any.whl')]
from connection_vault import new_connection,public_pairing
from native_transport import NativeTransport,wire_snapshot,socket_factory
from native_receiver_schema import PROTOCOL,MAX_BYTES,MEDIA,decode,encode
from native_receiver_reference.core import NativeHub


def ready():
    return {'version':2,'view':uuid.uuid4().hex,'epoch':uuid.uuid4().hex,'revision':17,
        'account':{'state':'ready','displayName':'Synthetic'},
        'runtime':{'state':'sleeping','cpu':None,'gpu':None,'memory':40,'model':'Synthetic model'},
        'models':[{'id':'qwen1.7-q8','name':'Synthetic Qwen 1.7B','kind':'Chat','installed':True,'selected':True,'state':'unknown'}],
        'packages':[{'id':'model_qwen1.7-q8','name':'Synthetic component','purpose':'Fixture','state':'available'}],
        'chat':{'conversations':[],'current':None,'messages':[],'busy':False,'contextUsed':None,'contextLimit':None,'replyCap':None,
            'window':{'conversationsComplete':False,'messagesComplete':True}},
        'settings':{'selection':'qwen1.7-q8','variant':'standard','backend':'auto','context':8192,'reply':2048,'effort':'Balanced',
            'media':{k:'auto' for k in MEDIA}}}


class Source:
    def __init__(self):self.value=ready();self.binding=None;self.endpoint=None;self.binds=0;self.reads=0;self.failed=False
    def bind(self,*,fresh):
        assert fresh
        self.binds+=1;self.value.update(view=uuid.uuid4().hex,epoch=uuid.uuid4().hex)
        self.binding={k:self.value[k] for k in ('view','epoch')}
    def snapshot(self):
        self.reads+=1
        if self.failed:raise RuntimeError('stale GUI')
        if self.value['account']['state']=='ready':value=copy.deepcopy(self.value)
        else:value={k:copy.deepcopy(self.value[k]) for k in ('version','view','epoch','revision','account')}
        return {'snapshot':value}


class HubSocket:
    def __init__(self,hub,identity):
        self.hub=hub;self.identity=identity;self.connection=None;self.nonce='a'*64;self.sent=[];self.after_bound=None
        self.replies=[{'protocol':PROTOCOL,'kind':'hello','maxFrameBytes':MAX_BYTES,'leaseSeconds':10}]
    def send(self,text):
        value=decode(text);self.sent.append(value);kind=value['kind']
        if kind=='hello':
            assert value['device_id']==self.identity
            if not self.hub.permitted(self.identity):raise PermissionError('grant')
            reply={'kind':'challenge','challenge':self.nonce}
        elif kind=='authenticate':
            self.hub.authenticate(self.identity,self.nonce,value['signature'])
            self.connection=self.hub.attach(self.identity)
            reply={'kind':'authenticated','capabilities':['native.state.read'],'leaseSeconds':10}
        elif kind=='bind':
            self.hub.bind(self.identity,self.connection,value['binding']);reply={'kind':'bound','binding':value['binding']}
            if self.after_bound:self.after_bound()
        elif kind=='snapshot':
            self.hub.publish(self.identity,self.connection,value['snapshot']);reply={'kind':'accepted','revision':value['snapshot']['revision']}
        elif kind=='invalidate':
            self.hub.invalidate(self.identity,self.connection);reply={'kind':'invalidated'}
        else:raise AssertionError('Effect/unsupported kind: '+kind)
        self.replies.append({'protocol':PROTOCOL,**reply})
    def recv(self,timeout):return encode(self.replies.pop(0)).decode()
    def close(self):
        if self.connection:self.hub.detach(self.identity,self.connection)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.connection=new_connection('https://example.invalid','../PortalAI','Synthetic')
        public=public_pairing(self.connection);self.identity=self.connection['device_id']
        self.hub=NativeHub({self.identity:public},{self.identity:public['fingerprint']})
        self.ws=HubSocket(self.hub,self.identity)
        self.client=NativeTransport(self.connection,Mock(),threading.Event())
        self.source=Source();self.client.local=self.source;self.client.ws=self.ws
        self.client.demand.update({'version':1,'screen':False,'native':True,'lease_seconds':5},time.monotonic())
    def tearDown(self):self.client.close()
    def test_signature_is_verified_by_actual_receiver_core(self):
        self.client.authenticate();self.assertIsNotNone(self.ws.connection)
        self.assertEqual([p['kind'] for p in self.ws.sent],['hello','authenticate'])
        self.assertEqual(self.source.reads,0)
    def test_projection_pairing_alone_does_not_grant_native_read(self):
        self.hub.grants.clear()
        with self.assertRaises(PermissionError):self.client.authenticate()
        self.assertEqual(self.source.binds,0);self.assertEqual(self.source.reads,0)
    def test_fresh_GUI_reads_coalesce_to_acknowledged_contiguous_wire_revisions(self):
        self.client.authenticate();self.assertTrue(self.client.step())
        self.source.value['revision']=321;self.assertTrue(self.client.step())
        values=[p['snapshot'] for p in self.ws.sent if p['kind']=='snapshot']
        self.assertEqual([v['revision'] for v in values],[0,1]);self.assertGreaterEqual(self.source.reads,4)
        self.assertEqual(self.source.value['revision'],321)
        self.assertEqual(self.hub.read(self.identity)['last_revision'],1)
    def test_wire_adaptation_is_inert_unique_and_matches_saved_model(self):
        original=copy.deepcopy(self.source.value);wire=wire_snapshot(original,0)
        self.assertEqual(wire['models'][0]['id'],wire['settings']['selection'])
        self.assertNotEqual(wire['models'][0]['id'],wire['packages'][0]['id'])
        self.assertEqual(wire['models'][0]['state'],'unavailable');self.assertTrue(wire['models'][0]['installed'])
        self.assertEqual(original,self.source.value)
    def test_lock_invalidates_and_new_account_requires_fresh_GUI_binding(self):
        self.client.authenticate();self.client.step();old=dict(self.client.binding)
        self.source.value['account']={'state':'closing','displayName':''}
        self.assertFalse(self.client.step())
        with self.assertRaises(PermissionError):self.hub.read(self.identity)
        self.source.value['account']={'state':'ready','displayName':'Synthetic'}
        self.client.step();self.assertNotEqual(self.client.binding,old)
        self.assertEqual(self.source.binds,2)
    def test_stale_GUI_does_not_replay_last_private_frame(self):
        self.client.authenticate();self.client.step();self.source.failed=True
        self.assertFalse(self.client.step())
        self.assertEqual(sum(p['kind']=='snapshot' for p in self.ws.sent),1)
        with self.assertRaises(PermissionError):self.hub.read(self.identity)
    def test_logout_during_network_bind_prevents_private_publish(self):
        self.client.authenticate()
        self.ws.after_bound=lambda:self.source.value.update(account={'state':'locked','displayName':''})
        self.assertFalse(self.client.step())
        self.assertFalse(any(p['kind']=='snapshot' for p in self.ws.sent))
    def test_wrong_acknowledgement_cannot_advance_wire_revision(self):
        self.client.authenticate();receive=self.client.receive
        self.client.receive=lambda kind,names: {'revision':999} if kind=='accepted' else receive(kind,names)
        with self.assertRaises(ValueError):self.client.step()
        self.assertEqual(self.client.revision,0)
    def test_malformed_challenge_never_signs_or_reads_GUI(self):
        self.ws.nonce='b'*65
        with self.assertRaises(ValueError):self.client.authenticate()
        self.assertEqual([p['kind'] for p in self.ws.sent],['hello']);self.assertEqual(self.source.reads,0)
    def test_receiver_scope_extension_or_wrong_lease_is_refused(self):
        for update in ({'capabilities':['native.state.read','chat.submit']},{'leaseSeconds':True},{'leaseSeconds':11}):
            self.setUp();receive=self.client.receive
            def changed(kind,names):
                value=receive(kind,names)
                if kind=='authenticated':value.update(update)
                return value
            self.client.receive=changed
            with self.subTest(update=update),self.assertRaises((ValueError,PermissionError)):self.client.authenticate()
            self.assertEqual(self.source.reads,0);self.client.close()
    def test_stop_does_not_publish_a_prepared_snapshot(self):
        self.client.authenticate();self.client.stop.set();self.assertFalse(self.client.step())
        self.assertFalse(any(p['kind']=='snapshot' for p in self.ws.sent))
    def test_url_uses_only_the_saved_projection_origin_and_fixed_native_path(self):
        self.assertEqual(self.client.address,'wss://example.invalid/api/portalai_native/v2')
        for address in ('http://example.invalid','https://token@example.invalid','https://example.invalid/other'):
            with self.assertRaises(ValueError):NativeTransport({**self.connection,'url':address},Mock(),threading.Event())
    def test_dependency_and_socket_policy_keeps_TLS_and_bounds(self):
        from websockets.sync import client
        with patch.object(client,'connect') as connect:
            socket_factory(self.client.address,self.client.context)
            options=connect.call_args.kwargs
            self.assertIs(options['ssl'],self.client.context);self.assertTrue(options['ssl'].check_hostname)
            self.assertEqual(options['ssl'].verify_mode,ssl.CERT_REQUIRED)
            for key in ('proxy','origin','additional_headers','compression'):self.assertIsNone(options[key])
            self.assertEqual(options['max_size'],180000);self.assertEqual(options['max_queue'],2)
            connect.return_value.socket.settimeout.assert_called_once_with(4)
    def test_strict_receiver_rejects_unknown_fields_and_oversized_messages(self):
        value=ready();value['unexpected']='private'
        with self.assertRaises(ValueError):wire_snapshot(value,0)
        for raw in ('{"key":1,"key":2}','{"key":NaN}','x'*180001):
            with self.assertRaises(ValueError):decode(raw)


class RealTLSTests(unittest.TestCase):
    def test_real_verified_TLS_websocket_and_receiver_signature_then_state(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        from websockets.sync.server import serve
        connection=new_connection('https://example.invalid','../PortalAI','Synthetic')
        public=public_pairing(connection);identity=connection['device_id']
        hub=NativeHub({identity:public},{identity:public['fingerprint']})
        errors=[];finished=threading.Event();requests=[]
        logger=logging.Logger('native-tls-fixture');logger.addHandler(logging.NullHandler())
        def handler(socket):
            try:
                requests.append(dict(socket.request.headers))
                machine=HubSocket(hub,identity)
                socket.send(machine.recv(2))
                for text in socket:
                    machine.send(text);socket.send(machine.recv(2))
            except Exception as exc:errors.append(type(exc).__name__)
            finally:finished.set()
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
            name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'localhost')])
            now=datetime.datetime.now(datetime.timezone.utc)
            cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256())
            (folder/'cert.pem').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            (folder/'key.pem').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);server_context.load_cert_chain(folder/'cert.pem',folder/'key.pem')
            client_context=ssl.create_default_context(cafile=str(folder/'cert.pem'))
            with serve(handler,'127.0.0.1',0,ssl=server_context,compression=None,max_size=MAX_BYTES,logger=logger) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                transport=NativeTransport(connection,Mock(),threading.Event());transport.local=Source()
                try:
                    # Production trust must reject this fixture's self-signed
                    # certificate; the separate fixture context trusts it only
                    # for the explicit loopback positive test below.
                    with self.assertRaises(ssl.SSLCertVerificationError):
                        socket_factory('wss://127.0.0.1:'+str(server.socket.getsockname()[1])+'/api/portalai_native/v2',transport.context)
                    transport.ws=socket_factory('wss://127.0.0.1:'+str(server.socket.getsockname()[1])+'/api/portalai_native/v2',client_context)
                    transport.authenticate()
                    transport.demand.update({'version':1,'screen':False,'native':True,'lease_seconds':5},time.monotonic())
                    self.assertTrue(transport.step());self.assertTrue(transport.step())
                    self.assertEqual(hub.read(identity)['last_revision'],1)
                    transport.invalidate()
                    with self.assertRaises(PermissionError):hub.read(identity)
                finally:transport.close()
                self.assertTrue(finished.wait(3))
        self.assertFalse(errors)
        self.assertTrue(requests)
        for name in ('origin','authorization','cookie','sec-websocket-extensions'):self.assertNotIn(name,requests[0])


if __name__=='__main__':unittest.main()
