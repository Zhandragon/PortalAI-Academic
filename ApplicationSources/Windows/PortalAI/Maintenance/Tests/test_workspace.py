"""Meaningful recovery, protocol, document and workflow boundary regressions."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from knowledge_base import Knowledge
from knowledge_extract import extract
from workflows import Workflows
from mcp_client import Connections,Transport


class Embedder:
    fingerprint='synthetic-unit-embedding'
    def encode(self,texts,check=lambda:None):
        check();return [[1. if 'plant' in t.lower() else 0.,1. if 'engine' in t.lower() else 0.,.1] for t in texts]


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        (self.root/'Agent').mkdir();(self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':1,'minimum_free_fraction':.0001,'output_reserve_gib':0}}))


class KnowledgeTests(Fixture):
    def setUp(self):
        super().setUp();self.source=self.root/'documents';self.source.mkdir();(self.source/'botany.txt').write_text('Plants use sunlight to produce sugar. Plant leaves are green.')
        self.kb=Knowledge(self.root,embedder=Embedder());self.cid=self.kb.create('Reference',self.source)['id']
    def test_persistent_incremental_sync_citations_and_changes(self):
        self.assertEqual(self.kb.sync(self.cid)['changed'],1)
        citation=self.kb.search('plant')['results'][0]['citation']
        self.assertIn('sunlight',self.kb.read(citation)['text'])
        reopened=Knowledge(self.root,embedder=Embedder());self.assertEqual(reopened.sync(self.cid)['changed'],0)
        (self.source/'botany.txt').write_text('Plants need mineral nutrients.')
        self.assertEqual(reopened.sync(self.cid)['changed'],1)
        with self.assertRaises(ValueError):reopened.read(citation)
        new=reopened.search('plant')['results'][0];self.assertNotEqual(new['citation'],citation)
        self.assertIn('mineral',reopened.read(new['citation'])['text'])
    def test_missing_source_preserves_existing_index(self):
        self.kb.sync(self.cid);self.source.rename(self.root/'unmounted')
        with self.assertRaises(FileNotFoundError):self.kb.sync(self.cid)
        self.assertIn('sunlight',self.kb.search('plant')['results'][0]['text'])
    def test_failed_or_cancelled_sync_preserves_prior_transaction(self):
        self.kb.sync(self.cid);(self.source/'botany.txt').write_text('New plant text')
        with patch('knowledge_base.extract',side_effect=RuntimeError('cancelled')):
            with self.assertRaises(RuntimeError):self.kb.sync(self.cid)
        self.assertIn('sunlight',self.kb.search('plant')['results'][0]['text'])
    def test_deleted_source_removed_only_after_complete_inventory(self):
        self.kb.sync(self.cid);(self.source/'botany.txt').unlink();self.assertEqual(self.kb.sync(self.cid)['removed_from_index'],1)
        self.assertFalse(self.kb.search('plant')['results'])
    def test_corrupted_cached_original_refused(self):
        self.kb.sync(self.cid);(self.source/'botany.txt').write_text('New plant text');self.kb.sync(self.cid)
        original='Plants use sunlight to produce sugar. Plant leaves are green.'
        blob=self.kb.path('Sources/'+self.cid+'/'+hashlib.sha256(original.encode()).hexdigest()+'.txt');blob.write_text('corrupt')
        (self.source/'botany.txt').write_text(original)
        with self.assertRaisesRegex(ValueError,'checksum'):self.kb.sync(self.cid)
    def test_source_listing_and_citation_path_boundaries(self):
        self.assertEqual(self.kb.list()[0]['id'],self.cid)
        with self.assertRaises(ValueError):self.kb.load('../elsewhere')
        with self.assertRaises(ValueError):self.kb.read('kb:../../secret')
    def test_office_text_and_locations(self):
        doc=self.root/'example.docx'
        with zipfile.ZipFile(doc,'w') as z:z.writestr('word/document.xml','<doc><t>Portable research notes</t></doc>')
        self.assertIn('research',extract(self.root,doc)[0][1])
        slide=self.root/'example.pptx'
        with zipfile.ZipFile(slide,'w') as z:z.writestr('ppt/slides/slide2.xml','<slide><t>Second slide</t></slide>')
        self.assertEqual(extract(self.root,slide)[0],('slide 1','Second slide'))
    def test_html_ignores_script_text(self):
        p=self.root/'web.html';p.write_text('<p>Useful fact</p><script>secret();</script>')
        self.assertIn('Useful fact',extract(self.root,p)[0][1]);self.assertNotIn('secret',extract(self.root,p)[0][1])


class WorkflowTests(Fixture):
    def template(self,steps,inputs=()):return self.store.put({'version':1,'name':'Synthetic flow','inputs':list(inputs),'steps':steps})['id']
    def setUp(self):super().setUp();self.calls=[];self.store=Workflows(self.root,execute=lambda kind,step,args,op:self.calls.append(op) or {'ok':True})
    def test_conditions_typed_inputs_output_and_approval_survive_restart(self):
        tid=self.template([{'id':'choose','kind':'condition','left':{'$ref':'inputs.flag'},'right':True,'then':'approve','else':'end'},
                           {'id':'approve','kind':'approval'},{'id':'result','kind':'output','value':{'$ref':'inputs.flag'}}],['flag'])
        row=self.store.start(tid,{'flag':True});rid=row['id'];self.assertEqual(self.store.advance(rid)['state'],'approval')
        self.store=Workflows(self.root);self.store.approve(rid);row=self.store.advance(rid)
        self.assertEqual(row['state'],'complete');self.assertIs(row['results']['result'],True)
    def test_false_branch_does_not_execute_later_steps(self):
        tid=self.template([{'id':'choose','kind':'condition','left':False,'operator':'truthy','then':'effect','else':'end'},{'id':'effect','kind':'mcp'}])
        row=self.store.advance(self.store.start(tid,{})['id']);self.assertEqual(row['state'],'complete');self.assertFalse(self.calls)
    def test_template_edits_do_not_change_saved_run(self):
        tid=self.template([{'id':'result','kind':'output','value':1}]);row=self.store.start(tid,{})
        updated=self.store.template(tid);updated['steps'][0]['value']=2;self.store.put(updated,tid)
        self.assertEqual(self.store.advance(row['id'])['results']['result'],1)
    def test_uncertain_effect_never_replayed_on_restart(self):
        def fail(*args):self.calls.append('effect');raise OSError('crash after effect')
        self.store.executor=fail;tid=self.template([{'id':'effect','kind':'mcp'}]);rid=self.store.start(tid,{})['id']
        with self.assertRaises(OSError):self.store.advance(rid)
        with self.assertRaises(RuntimeError):Workflows(self.root,execute=fail).advance(rid)
        self.assertEqual(self.calls,['effect']);self.store.review(rid,'confirmed',{'saved':True})
        self.assertEqual(self.store.advance(rid)['state'],'complete')
    def test_retries_bounded_to_three_explicit_attempts(self):
        self.store.executor=lambda *args:(_ for _ in ()).throw(RuntimeError('model failed'))
        tid=self.template([{'id':'draft','kind':'prompt'}]);rid=self.store.start(tid,{})['id']
        for _ in range(3):
            with self.assertRaisesRegex(RuntimeError,'model failed'):self.store.advance(rid)
        with self.assertRaisesRegex(RuntimeError,'three attempts'):self.store.advance(rid)
    def test_cycles_arbitrary_tools_and_invalid_inputs_rejected(self):
        with self.assertRaises(ValueError):self.template([{'id':'loop','kind':'condition','then':'loop','else':'end'}])
        with self.assertRaises(ValueError):self.template([{'id':'bad','kind':'tool','tool':'shell'}])
        tid=self.template([{'id':'result','kind':'output'}],['required'])
        with self.assertRaises(ValueError):self.store.start(tid,{})
    def test_completed_run_is_idempotent(self):
        tid=self.template([{'id':'effect','kind':'mcp'}]);rid=self.store.start(tid,{})['id'];self.store.advance(rid);self.store.advance(rid)
        self.assertEqual(len(self.calls),1)


class FakeTransport:
    rows=[{'name':'write','inputSchema':{'type':'object','properties':{'text':{'type':'string'}},'required':['text']}}]
    calls=0;fail=False
    def __init__(self,*args):pass
    def initialize(self):pass
    def tools(self):return self.rows
    def close(self):pass
    def request(self,*args):
        type(self).calls+=1
        if self.fail:raise OSError('response lost after write')
        return {'content':[{'type':'text','text':'done'}]}


class MCPTests(Fixture):
    def setUp(self):
        super().setUp();self.connections=Connections(self.root);self.cid=self.connections.create('Fixture','stdio',command=['{python}'])['id']
        FakeTransport.calls=0;FakeTransport.fail=False
        self.transport=patch('mcp_client.Transport',FakeTransport);self.transport.start();self.addCleanup(self.transport.stop)
        self.connections.grant(self.cid,FakeTransport.rows)
    def test_complete_operation_is_not_dispatched_twice(self):
        self.connections.call(self.cid,'write',{'text':'x'},'operation1');self.connections.call(self.cid,'write',{'text':'x'},'operation1')
        self.assertEqual(FakeTransport.calls,1)
    def test_lost_response_blocks_identical_action_until_review(self):
        FakeTransport.fail=True
        with self.assertRaises(OSError):self.connections.call(self.cid,'write',{'text':'x'},'op')
        with self.assertRaisesRegex(RuntimeError,'uncertain'):self.connections.call(self.cid,'write',{'text':'x'},'different-op')
        rid=self.connections.receipts()[0]['id'];self.connections.resolve(rid,'confirmed')
        result=self.connections.call(self.cid,'write',{'text':'x'},'op');self.assertTrue(result['reviewed']);self.assertEqual(FakeTransport.calls,1)
    def test_explicit_retry_grant_and_schema_validation(self):
        with self.assertRaises(Exception):self.connections.call(self.cid,'write',{'text':42})
        self.assertEqual(FakeTransport.calls,0);FakeTransport.fail=True
        with self.assertRaises(OSError):self.connections.call(self.cid,'write',{'text':'x'})
        self.connections.resolve(self.connections.receipts()[0]['id'],'allow_retry');FakeTransport.fail=False
        self.connections.call(self.cid,'write',{'text':'x'});self.assertEqual(FakeTransport.calls,2)
    def test_disable_and_schema_changes_refuse_dispatch(self):
        with patch.object(FakeTransport,'rows',[{'name':'write','inputSchema':{'type':'object'}}]):
            with self.assertRaisesRegex(PermissionError,'schema changed'):self.connections.call(self.cid,'write',{'text':'x'})
        self.connections.grant(self.cid,[],enabled=False)
        with self.assertRaises(PermissionError):self.connections.call(self.cid,'write',{'text':'x'})
        self.assertEqual(FakeTransport.calls,0)
    def test_external_schema_references_and_remote_plaintext_refused(self):
        self.connections.grant(self.cid,[{'name':'bad','inputSchema':{'$ref':'https://example.org/schema'}}])
        with self.assertRaisesRegex(ValueError,'External schema'):self.connections.call(self.cid,'bad',{})
        with self.assertRaises(ValueError):self.connections.create('Unsafe','http',url='http://example.org/mcp')
    def test_credential_values_omitted_from_catalogue(self):
        cid=self.connections.create('Private','http',url='https://example.org/mcp',headers={'Authorization':'fixture-secret'})['id']
        self.assertNotIn('fixture-secret',json.dumps(self.connections.list()))
    def test_new_tool_format_retry_classification_is_conservative(self):
        from tool_protocol import read_only_tool_attempt
        for name,action in [('knowledge','search'),('knowledge','read'),('mcp','tools'),('workflow','status')]:
            self.assertTrue(read_only_tool_attempt(name,{'action':action},self.root))
        for name,action in [('mcp','call'),('workflow','start'),('workflow','continue'),('computer','click'),('computer','screenshot')]:
            self.assertFalse(read_only_tool_attempt(name,{'action':action},self.root))
    def test_http_sse_session_initialization_and_tool_call(self):
        import http.server,threading
        seen=[]
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def log_message(self,*args):pass
            def do_POST(self):
                body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));seen.append((body,self.headers.get('Mcp-Session-Id')))
                method=body.get('method')
                if 'id' not in body:self.send_response(202);self.send_header('Content-Length','0');self.end_headers();return
                result=({'protocolVersion':'2025-11-25','capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}} if method=='initialize' else {'tools':FakeTransport.rows} if method=='tools/list' else {'content':[{'type':'text','text':'hello'}]})
                payload=('data: '+json.dumps({'jsonrpc':'2.0','id':body['id'],'result':result})+'\n\n').encode()
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Mcp-Session-Id','fixture-session');self.send_header('Transfer-Encoding','chunked');self.end_headers()
                self.wfile.write(('%x\r\n'%len(payload)).encode()+payload+b'\r\n0\r\n\r\n');self.wfile.flush()
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        t=Transport(self.root,{'transport':'http','url':'http://127.0.0.1:'+str(server.server_port)+'/mcp'},lambda:None)
        self.addCleanup(t.close);t.initialize();self.assertEqual(t.tools()[0]['name'],'write');self.assertIn('content',t.request('tools/call',{'name':'write','arguments':{'text':'hello'}}))
        self.assertEqual(seen[0][1],None);self.assertEqual(seen[1][1],'fixture-session')


if __name__=='__main__':unittest.main()
