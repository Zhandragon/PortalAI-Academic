"""Synthetic bytes through the real Manager HTTP client, InputAdapter handler,
strict request validator and RAM Transfers. No real account, Tk or messages.
Run with bundled Python: unittest discover -s Maintenance/Tests -p test_native_upload_v2.py
"""
import base64,hashlib,http.client,importlib.util,json,sys,time,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
PROJECTION=ROOT.parent/'Utilities'/'PortalAI-Projection'
def load(name,path):
    relative=Path(path)
    source=(ROOT if relative.parts[0]=='PortalAI' else PROJECTION).joinpath(*relative.parts[1:])
    spec=importlib.util.spec_from_file_location(name,source);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
protocol=load('host_protocol','PortalAI/ControlCenter/native_workflow_protocol.py')
files=load('host_files','PortalAI/ControlCenter/native_workflow_files.py')
remote=load('host_remote','PortalAI/ControlCenter/remote_desktop_input.py')
target=load('host_target','PortalAI-Projection/app/portalai_target.py')

class HostUploadTests(unittest.TestCase):
    def setUp(self):
        self.binding={'view':'v','epoch':'e'};self.account={'state':'ready'};self.viewer='b'*32
        app=SimpleNamespace(after=lambda *a:None,bind=lambda *a,**k:None)
        c=SimpleNamespace(app=app,forms={(self.viewer,'f'):{'page':'chat','fields':{'chat_attachment':{'file':True}}}},
            current=lambda:(self.binding,self.account),describe=lambda *a:{'form':'f'},
            reply=lambda p,**kw:dict(accepted=True,request_id=p['request_id'],operation=p['operation'],**kw))
        def check(p,deadline):
            if deadline<=time.monotonic() or p.get('binding')!=self.binding:raise PermissionError('expired or stale binding')
        c.check=check;self.c=c;self.transfers=files.Transfers(c)
        with patch.object(remote.InputAdapter,'publish_endpoint',lambda _:None):self.adapter=remote.InputAdapter(app,ROOT)
        self.adapter.native_ui=SimpleNamespace(response_current=lambda _:True)
        def execute(job):
            p=protocol.validate_request(job['item']['event']['payload'])
            job['result']=self.transfers.execute(p,job['expires']);job['done'].set();return True
        self.adapter.wait_for_job=execute
        self.manager=target.Manager(ROOT,SimpleNamespace())
        self.endpoint={'port':self.adapter.server.server_port,'token':self.adapter.token,'native_file_upload_protocol':2}
        self.manager.native_chat_endpoint=lambda **kw:({'hwnd':100},self.endpoint)
    def tearDown(self):
        self.adapter.server.shutdown();self.adapter.server.server_close()
        for row in self.transfers.rows.values():row['buffer'].close()
    def request(self,op,**kw):
        p=dict(request_id='a'*32,viewer=self.viewer,operation=op,binding=self.binding.copy(),**kw)
        return self.manager.native_ui(p,time.monotonic()+4)
    def begin(self,size):
        return self.request('file_begin',form='f',field='chat_attachment',name='synthetic.bin',size=size,mime='application/octet-stream')['transfer']
    def test_full_one_mib_and_tail_roundtrip_duplicate_and_integrity(self):
        raw=bytes(range(251))*4178+b'tail';self.assertGreater(len(raw),1048576);transfer=self.begin(len(raw))
        for offset in range(0,len(raw),1048576):
            data=base64.b64encode(raw[offset:offset+1048576]).decode()
            args=dict(protocol=2,transfer=transfer,offset=offset,data=data)
            ack=self.request('file_chunk_v2',**args);self.assertEqual(ack['offset'],min(offset+1048576,len(raw)))
            self.assertEqual(self.request('file_chunk_v2',**args),ack)
        digest=hashlib.sha256(raw).hexdigest();reply=self.request('file_commit',transfer=transfer,sha256=digest)
        self.assertEqual(reply['sha256'],digest);self.assertEqual(self.transfers.rows[transfer]['buffer'].getvalue(),raw)
    def test_legacy_protocol_still_works_and_cannot_take_large_chunks(self):
        transfer=self.begin(24576);data=base64.b64encode(b'x'*24576).decode()
        self.assertEqual(self.request('file_chunk',transfer=transfer,offset=0,data=data)['offset'],24576)
        with self.assertRaises(ValueError):self.request('file_chunk',transfer=transfer,offset=0,data=base64.b64encode(b'x'*1048576).decode())
    def test_v2_requires_host_advertisement_and_explicit_version(self):
        transfer=self.begin(1);self.endpoint.pop('native_file_upload_protocol')
        with self.assertRaisesRegex(RuntimeError,'unavailable'):self.request('file_chunk_v2',protocol=2,transfer=transfer,offset=0,data='eA==')
        self.endpoint['native_file_upload_protocol']=2
        with self.assertRaises(RuntimeError):self.request('file_chunk_v2',protocol=True,transfer=transfer,offset=0,data='eA==')
    def test_bad_offset_digest_and_changed_account_never_commit(self):
        transfer=self.begin(1)
        for args in [dict(protocol=2,transfer=transfer,offset=1,data='eA=='),dict(protocol=2,transfer=transfer,offset=0,data='eHk=')]:
            with self.assertRaises(RuntimeError):self.request('file_chunk_v2',**args)
        self.request('file_chunk_v2',protocol=2,transfer=transfer,offset=0,data='eA==')
        with self.assertRaises(RuntimeError):self.request('file_commit',transfer=transfer,sha256='0'*64)
        self.binding={'view':'other','epoch':'e'}
        with self.assertRaises(RuntimeError):self.request('file_commit',transfer=transfer,sha256=hashlib.sha256(b'x').hexdigest())
        self.assertFalse(self.transfers.rows[transfer]['committed'])
    def test_authenticated_http_large_exception_is_only_for_exact_v2(self):
        for operation,version in [('invoke',2),('file_chunk',2),('file_chunk_v2',True)]:
            conn=http.client.HTTPConnection('127.0.0.1',self.endpoint['port'],timeout=3)
            try:
                body=json.dumps({'event':{'kind':'native_ui','payload':{'operation':operation,'protocol':version,'data':'x'*70000}}})
                conn.request('POST','/input',body,{'Authorization':'Bearer '+self.endpoint['token']})
                reply=conn.getresponse();self.assertEqual(reply.status,400);self.assertIn('Input limit',reply.read().decode())
            finally:conn.close()
    def test_http_authentication_is_required_before_a_large_body(self):
        conn=http.client.HTTPConnection('127.0.0.1',self.endpoint['port'],timeout=3)
        try:
            # Send headers only: rejection must not wait for an unauthenticated
            # body. Sending stray body bytes can cause a Windows TCP reset.
            conn.putrequest('POST','/input');conn.putheader('Content-Length','1400000');conn.endheaders()
            reply=conn.getresponse();self.assertEqual(reply.status,400);self.assertIn('capability refused',reply.read().decode())
        finally:conn.close()
    def test_partial_gui_update_does_not_advertise_or_crash(self):
        with patch.dict(sys.modules,{'native_workflow_protocol':protocol,'native_workflow_files':files}):
            controller=load('upload_controller','PortalAI/ControlCenter/native_workflow.py').Controller
            for schema,transfer,expected in [(2,2,2),(None,2,1),(2,None,1),(None,None,1)]:
                with patch.object(protocol,'UPLOAD_PROTOCOL',schema),patch.object(files.Transfers,'upload_protocol',transfer):
                    c=controller(self.c.app,ROOT,self.adapter);self.assertEqual(c.file_upload_protocol,expected)
    def test_manager_advertises_only_with_matching_gui_capability(self):
        self.manager.inventory=lambda:{}
        self.manager.native_chat_endpoint=lambda *a,**kw:({'hwnd':100},self.endpoint)
        self.endpoint['native_ui_protocol']=1
        with patch.dict(sys.modules,{'profile_shutdown':SimpleNamespace(_marker=lambda _:None)}):
            for version in [None,1,'2',2.0,True,2]:
                self.endpoint['native_file_upload_protocol']=version
                status=self.manager.status()
                self.assertEqual(status.get('native_file_upload_protocol'),2 if type(version) is int and version==2 else None)

if __name__=='__main__':unittest.main()
