import json
import sys
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests','SDK/python')]
from test_workspace import Fixture
import test_integration as integration


class AgentRouteTests(Fixture):
    def setUp(self):
        super().setUp()
        from writer_jobs import WriterJobs
        from application_api_runtime import ApplicationAPI
        from application_api import SCOPES
        from types import SimpleNamespace
        self.jobs=WriterJobs();self.api=ApplicationAPI(SimpleNamespace(root=self.root),self.jobs,lambda:None)
        self.url=self.api.start()['base_url'];self.port=self.api.server.http.server_port;self.state=self.api.state
        self.grant=self.state.issue('test',sorted(SCOPES));self.token=self.grant['token'];self.addCleanup(self.cleanup)
    cleanup=integration.APITests.cleanup
    request=integration.APITests.request

    def chat(self):
        status,row=self.request('POST','/chats',{'title':'Agent route fixture'},'agent-create-chat')
        self.assertEqual(status,200);return row['data']['id']

    def wait(self,jid):
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            row=self.api.job(jid)
            if row['state'] not in ('queued','running'):return row
            time.sleep(.02)
        self.fail('Job did not complete')

    def test_http_grant_subset_idempotency_and_pending_turn_refusal(self):
        cid=self.chat();token=self.state.issue('reader',['agent:execute','chats:read'],tools=['read_file'])['token']
        status,row=self.request('POST','/chats/'+cid+'/agent',{'message':'Read','tools':['write_file']},'agent-denied-1',token)
        self.assertEqual(status,403,row)
        calls=[]
        def work(kind,body,check,event):check();calls.append((kind,body['tools']));return {'state':'complete','message':'done'}
        with patch.object(self.api,'work',side_effect=work):
            status,row=self.request('POST','/chats/'+cid+'/agent',{'message':'Read','tools':['read_file']},'agent-submitted-1',token)
            self.assertEqual(status,200,row);self.assertEqual(self.wait(row['data']['job_id'])['state'],'complete')
            self.assertEqual(self.request('POST','/chats/'+cid+'/agent',{'message':'Read','tools':['read_file']},'agent-submitted-1',token)[1],row)
        self.assertEqual(calls,[('agent',['read_file'])])
        saved=json.loads(self.state.path('Chats/'+cid+'.json').read_text());saved['pending_agent_job']=True;self.state.save('Chats/'+cid+'.json',saved)
        self.assertEqual(self.request('POST','/chats/'+cid+'/agent',{'message':'Continue'},'agent-uncertain-1',token)[0],409)

    def test_revocation_during_actual_harness_turn_blocks_tool_execution(self):
        from native_chat import NativeChat,ToolRuntime
        cid=self.chat();grant=self.state.issue('writer',['agent:execute'],tools=['write_file']);target=self.root/'must-not-be-written.txt'
        count=0
        def model(*args,**kwargs):
            nonlocal count
            count+=1
            name='tool_help' if count==1 else 'write_file'
            arguments={'tools':['write_file']} if count==1 else {'path':str(target),'content':'must not run'}
            if count==2:self.state.revoke(grant['id'])
            return ('','',[{'id':'call'+str(count),'type':'function','function':{'name':name,'arguments':json.dumps(arguments)}}],False)
        with patch('native_chat.bootstrap_python',return_value=sys.executable),patch('chat_effort_ui.ChatEffortControls.prepare_request',return_value=True),patch.object(NativeChat,'_runtime_context_limit',return_value=8192),patch.object(NativeChat,'_completion_with_tool_repair',side_effect=model),patch.object(ToolRuntime,'execute',wraps=ToolRuntime.execute) as execute:
            status,row=self.request('POST','/chats/'+cid+'/agent',{'message':'Write the fixture'},'agent-revoked-1',grant['token']);self.assertEqual(status,200,row)
            result=self.wait(row['data']['job_id']);self.assertEqual(result['state'],'failed',result);execute.assert_not_called()
        self.assertFalse(target.exists());saved=json.loads(self.state.path('Chats/'+cid+'.json').read_text());self.assertTrue(saved['pending_agent_job'])


class VoiceAdmissionTests(unittest.TestCase):
    def test_import_preparation_never_starts_on_small_or_cpu_only_hardware(self):
        from voice_prewarm import PreparedVoice
        hardware={'ram_total_bytes':16*1024**3,'ram_available_bytes':10*1024**3,'gpus':[]}
        with patch('runtime_policy.detect_hardware',return_value=hardware),patch('subprocess.Popen') as launch:
            self.assertIsNone(PreparedVoice.start(ROOT,lambda:None));launch.assert_not_called()
        hardware['gpus']=[{'backend':'cuda','index':0}];hardware['ram_available_bytes']=7*1024**3
        with patch('runtime_policy.detect_hardware',return_value=hardware),patch('subprocess.Popen') as launch:
            self.assertIsNone(PreparedVoice.start(ROOT,lambda:None));launch.assert_not_called()


if __name__=='__main__':unittest.main()
