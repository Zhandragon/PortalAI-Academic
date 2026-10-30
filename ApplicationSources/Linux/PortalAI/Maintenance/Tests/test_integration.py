"""Schema, artifact and real HTTP API boundary/recovery regressions."""
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','SDK/python','Maintenance/Tests','Runtime/Knowledge/packages')]
from test_workspace import Fixture
from artifacts import Artifacts
from application_api import APIState,APIError,SCOPES
from application_api_runtime import ApplicationAPI
from writer_jobs import WriterJobs
from structured_generation import schema,parse,mission_schema


class StructuredTests(unittest.TestCase):
    def test_closed_objects_and_no_mutation(self):
        value={'type':'object','properties':{'n':{'type':'integer','minimum':1}},'required':['n']}
        self.assertEqual(parse('{"n":2}',value),{'n':2});self.assertNotIn('additionalProperties',value)
        for bad in ('{"n":0}','{"n":2,"extra":3}','{"n":2,"n":3}','{"n":2.5}','```json\n{"n":2}\n```'):
            with self.subTest(bad=bad),self.assertRaises(Exception):parse(bad,value)
    def test_unsupported_constraints_never_silently_weaken(self):
        for value in ({'$ref':'https://example.org/schema'},{'type':'string','format':'email'},{'type':'number','minimum':0},{'type':['string','null']},{'anyOf':[{'type':'string'}],'properties':{}},{'type':'array'}):
            with self.subTest(value=value),self.assertRaises(ValueError):schema(value)
    def test_nonfinite_and_bounded_input(self):
        for value in ('NaN','Infinity','1e999'):
            with self.assertRaises(ValueError):parse(value,{'type':'number'})
        with self.assertRaises(ValueError):schema({'type':'string','maxLength':999999})
    def test_modes_constrain_actions_and_required_fields(self):
        for mode in ('observe','full','vm'):schema(mission_schema(mode));parse('{"action":"complete"}',mission_schema(mode))
        with self.assertRaises(Exception):parse('{"action":"shell","command":"echo hi"}',mission_schema('observe'))
        parse('{"action":"shell","command":"echo hi"}',mission_schema('full'))
        with self.assertRaises(Exception):parse('{"action":"shell"}',mission_schema('full'))


class ArtifactTests(Fixture):
    def test_compare_and_swap_history_restore_export(self):
        store=Artifacts(self.root);a=store.save('First','html','<h1>First</h1>\n');aid=a['id']
        b=store.save('Next','html','<h1>Second</h1>\n',artifact=aid,expected_revision=a['head'])
        with self.assertRaisesRegex(RuntimeError,'changed'):store.save('Stale','html','stale',artifact=aid,expected_revision=a['head'])
        self.assertIn('+<h1>Second',store.compare(aid,a['head'],b['head']))
        c=store.restore(aid,a['head'],b['head']);self.assertEqual(len(store.history(aid)),3)
        self.assertEqual(store.read(aid)['content'],'<h1>First</h1>\n')
        out=store.export(aid);self.assertEqual(store.export(aid),out)
        (self.root/out['path']).write_text('externally modified')
        with self.assertRaisesRegex(RuntimeError,'modified'):store.export(aid)
        self.assertNotEqual(c['head'],a['head'])
    def test_interrupted_head_publication_preserves_previous_revision(self):
        from workspace_store import Workspace
        store=Artifacts(self.root);a=store.save('A','svg','<svg/>');original=Workspace.save
        def save(obj,path,value):
            if path.startswith('Catalog/'):raise OSError('simulated removal before head commit')
            return original(obj,path,value)
        with patch.object(Workspace,'save',save),self.assertRaises(OSError):store.save('B','svg','<svg>new</svg>',artifact=a['id'],expected_revision=a['head'])
        self.assertEqual(Artifacts(self.root).read(a['id'])['id'],a['head'])
    def test_corruption_paths_and_invalid_charts(self):
        store=Artifacts(self.root);a=store.save('A','svg','<svg/>')
        path=store.path('Versions/'+a['id']+'/'+a['head']+'.json');row=json.loads(path.read_text());row['content']='altered';path.write_text(json.dumps(row))
        with self.assertRaisesRegex(ValueError,'checksum'):store.read(a['id'])
        with self.assertRaises(ValueError):store.read('../escape')
        with self.assertRaises(ValueError):store.save('bad','chart','{"labels":["a"],"series":[{"name":"x","values":[NaN]}]}')


class APITests(Fixture):
    def setUp(self):
        super().setUp();self.jobs=WriterJobs();self.api=ApplicationAPI(SimpleNamespace(root=self.root),self.jobs,lambda:None)
        self.url=self.api.start()['base_url'];self.port=self.api.server.http.server_port;self.state=self.api.state
        self.grant=self.state.issue('test',sorted(SCOPES));self.token=self.grant['token']
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.api.close();self.jobs.close();self.assertTrue(self.jobs.wait(10)['stopped'])
    def request(self,method,path,body=None,key=None,token=None,headers=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.port,timeout=8)
        h={'Authorization':'Bearer '+(token or self.token),'Content-Type':'application/json'}
        if key:h['Idempotency-Key']=key
        h.update(headers or {})
        try:
            conn.request(method,'/v1'+path,json.dumps(body or {}) if method=='POST' else None,h);r=conn.getresponse();return r.status,json.loads(r.read())
        finally:conn.close()
    def test_auth_scope_origin_host_revocation(self):
        self.assertEqual(self.request('GET','/status')[0],200)
        self.assertEqual(self.request('GET','/status',token='invalid')[0],401)
        self.assertEqual(self.request('GET','/status',headers={'Origin':'http://example.org'})[0],403)
        self.assertEqual(self.request('GET','/status',headers={'Host':'example.org'})[0],403)
        limited=self.state.issue('limited',['artifacts:read'])
        self.assertEqual(self.request('POST','/chats',{},'create-123',limited['token'])[0],403)
        self.state.revoke(self.grant['id']);self.assertEqual(self.request('GET','/status')[0],401)
    def test_sdk_mutations_idempotency_and_revision_conflict(self):
        from portalai import Client,APIError as ClientError
        c=Client(self.url,self.token);a=c.create_chat('Test',key='create-chat-1')
        self.assertEqual(a,c.create_chat('Test',key='create-chat-1'))
        with self.assertRaises(ClientError) as error:c.create_chat('Different',key='create-chat-1')
        self.assertEqual(error.exception.code,'IDEMPOTENCY_CONFLICT')
        artifact=c.request('POST','/artifacts',{'title':'Demo','kind':'html','content':'<h1>Hi</h1>'},key='artifact-create-1')
        row=c.request('GET','/artifacts/'+artifact['id']);self.assertEqual(row['id'],artifact['head'])
        status,_=self.request('POST','/artifacts/'+artifact['id']+'/revisions',{'title':'Bad','kind':'html','content':'x','expected_revision':'0'*32},'artifact-stale-1');self.assertEqual(status,409)
        with self.assertRaises(ValueError):c.request('POST','/chats',{})
    def test_uncertain_effect_blocks_same_and_new_key_until_review(self):
        token=self.state.authenticate('Bearer '+self.token);effects=[]
        def uncertain():effects.append(1);raise OSError('lost response after effect')
        with self.assertRaises(OSError):self.state.receipt(token,'uncertain-1','POST','/effect',{},uncertain)
        for key in ('uncertain-1','uncertain-2'):
            with self.assertRaises(APIError):APIState(self.root).receipt(token,key,'POST','/effect',{},uncertain)
        self.assertEqual(len(effects),1);receipt=self.state.pending()[0]
        self.state.resolve(receipt['id'],'confirmed',{'done':True})
        self.assertEqual(self.state.receipt(token,'uncertain-1','POST','/effect',{},uncertain),{'done':True});self.assertEqual(len(effects),1)
    def test_async_cancel_scoped_jobs_and_restart_marking(self):
        begun=threading.Event()
        def slow(kind,body,check,event):
            begun.set()
            while True:check();time.sleep(.02)
        with patch.object(self.api,'work',slow):
            status,data=self.request('POST','/structured',{'question':'test','schema':{'type':'string'}},'job-cancel-1')
            self.assertEqual(status,200);jid=data['data']['job_id'];self.assertTrue(begun.wait(3))
            other=self.state.issue('other',['structured:generate'])
            self.assertEqual(self.request('GET','/jobs/'+jid,token=other['token'])[0],403)
            self.assertEqual(self.request('POST','/jobs/'+jid+'/cancel',{},'cancel-job-1')[0],200)
            deadline=time.monotonic()+5
            while self.api.job(jid)['state'] in ('running','queued') and time.monotonic()<deadline:time.sleep(.03)
            self.assertEqual(self.api.job(jid)['state'],'cancelled')
        self.state.save('Jobs/'+'a'*32+'.json',{'id':'a'*32,'state':'running'})
        self.api.close();reopened=ApplicationAPI(SimpleNamespace(root=self.root),self.jobs,lambda:None)
        self.assertEqual(reopened.job('a'*32)['state'],'needs_review');reopened.close()
    def test_output_chunk_identity_and_traversal(self):
        (self.root/'Outputs').mkdir();(self.root/'Outputs/example.txt').write_text('test output')
        status,row=self.request('GET','/outputs/content?path=example.txt&limit=4');self.assertEqual(status,200);self.assertFalse(row['data']['eof'])
        (self.root/'Outputs/example.txt').write_text('changed')
        self.assertEqual(self.request('GET','/outputs/content?path=example.txt&identity='+row['data']['identity'])[0],409)
        self.assertEqual(self.request('GET','/outputs/content?path=../Agent/hardware_profiles.json')[0],400)
    def test_stop_closes_listener_and_jobs(self):
        from workspace_services import close_all
        self.assertEqual(close_all(self.root),[])
        with self.assertRaises(OSError):self.request('GET','/status')

    @unittest.skipUnless(os.environ.get('PORTALAI_TEST_NODE'),'Explicit bundled Node path needed for SDK acceptance')
    def test_typescript_client_against_real_api(self):
        code="import {Client} from "+json.dumps((ROOT/'SDK/typescript/portalai.ts').as_uri())+";const c=new Client("+json.dumps(self.url)+","+json.dumps(self.token)+");const a=await c.createChat('TypeScript','typescript-create-1');const b=await c.createChat('TypeScript','typescript-create-1');if(a.id!==b.id)throw Error('duplicate');console.log(JSON.stringify({passed:true,id:a.id}));"
        result=subprocess.run([os.environ['PORTALAI_TEST_NODE'],'--experimental-transform-types','--input-type=module','-e',code],capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(result.stdout)['passed'])

    def test_chat_job_commits_one_turn_and_uses_local_transport(self):
        from portalai import Client
        c=Client(self.url,self.token);chat=c.create_chat('Conversation',key='chat-example-1');seen=[]
        def model(root,path,payload=None,check=lambda:None,**kwargs):
            check();seen.append((path,payload))
            return {'default_generation_settings':{'n_ctx':8192}} if path=='/props' else {'choices':[{'finish_reason':'stop','message':{'content':'Synthetic answer'}}]}
        with patch('structured_generation.request_json',model):
            submission=c.message(chat['id'],'Synthetic question',key='message-example-1');row=c.wait(submission['job_id'],timeout=5)
            self.assertEqual(row['state'],'complete',row);self.assertEqual(row['result']['message'],'Synthetic answer')
            self.assertEqual(c.message(chat['id'],'Synthetic question',key='message-example-1'),submission)
        saved=c.request('GET','/chats/'+chat['id']);self.assertEqual(len(saved['messages']),2);self.assertEqual(len(seen),2)


if __name__=='__main__':unittest.main()
