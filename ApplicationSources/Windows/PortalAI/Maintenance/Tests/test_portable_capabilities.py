"""Storage, account, authorization, interruption and recovery boundaries for r58."""
import base64
import hashlib
import http.server
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import urllib.parse as url
import urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from test_workspace import Fixture,Embedder
from portable_workspace import Organization,Skills,parse_skill,chat_guidance
from knowledge_base import Knowledge
from mcp_client import Connections,Transport
from mcp_oauth import authorize,validate_config,token_result
from chat_voice import SpeechBuffer,VoiceIO,SpeechInterrupted,VoiceStopped
from workflow_builder import typed,update_step


class ProjectSkillTests(Fixture):
    def test_project_assignment_preserves_chats_and_is_persistent(self):
        org=Organization(self.root);sid='a'*32;pid=org.put('Research','Use citations',['b'*32])['id']
        org.assign([sid],pid);self.assertEqual(Organization(self.root).for_chat(sid)['name'],'Research')
        org.remove(pid);self.assertIsNone(org.for_chat(sid));self.assertFalse(org.state()['chats'])
    def test_project_validation(self):
        org=Organization(self.root)
        for kwargs in ({'name':''},{'name':'x','instructions':'a'*4001},{'name':'x','collections':['../escape']}):
            with self.assertRaises(ValueError):org.put(**kwargs)
        with self.assertRaises(ValueError):org.assign(['a'*32],'b'*32)
    def test_skill_import_requires_explicit_enable_and_pages_without_loss(self):
        path=self.root/'SKILL.md';path.write_text('---\nname: reports\ndescription: Write reports\n---\n'+('abc '*1200))
        skills=Skills(self.root);row=skills.import_file(path)
        self.assertFalse(skills.list(enabled_only=True))
        with self.assertRaises(PermissionError):skills.read(row['id'])
        skills.put(row['name'],row['description'],row['body'],skill=row['id'],enabled=True)
        first=skills.read(row['id']);second=skills.read(row['id'],first['next_offset'])
        self.assertEqual(first['instructions']+second['instructions'],row['body'])
        self.assertIsNone(second['next_offset'])
    def test_skill_limits_and_no_executable_import(self):
        skills=Skills(self.root)
        with self.assertRaises(ValueError):skills.put('x','y','字'*20000)
        with self.assertRaises(ValueError):parse_skill('---\nallowed-tools: shell\n---\nDo stuff')
        p=self.root/'run.py';p.write_text('print(1)')
        with self.assertRaises(ValueError):skills.import_file(p)
        with self.assertRaises(ValueError):skills.read('../escape')
    def test_discovery_does_not_load_skill_bodies_into_every_prompt(self):
        skills=Skills(self.root)
        for i in range(10):skills.put('Task '+str(i),'When relevant','UNIQUE BODY '*2000,enabled=True)
        text=chat_guidance(self.root,{'id':'a'*32})
        self.assertNotIn('UNIQUE BODY',text);self.assertLess(len(text),1000)
    def test_disabled_library_adds_no_prompt_cost(self):
        Skills(self.root).put('Draft','Writing','Do this')
        self.assertEqual(chat_guidance(self.root,{'id':'a'*32}),'')
    def test_step_editor_preserves_types_and_unknown_existing_fields(self):
        old={'kind':'prompt','id':'draft','arguments':{'question':'Before','context':{'$ref':'steps.source'},'schema':{'type':'string'}}}
        new=update_step(old,'draft','prompt',{'arguments.question':'After','arguments.context':'@steps.other'})
        self.assertEqual(new['arguments']['schema'],old['arguments']['schema'])
        self.assertEqual(new['arguments']['context'],{'$ref':'steps.other'});self.assertEqual(old['arguments']['question'],'Before')
        self.assertIs(typed('=true'),True);self.assertEqual(typed('={"a":2}'),{'a':2})
    def test_source_quota_and_unchanged_sync_does_not_load_embeddings(self):
        source=self.root/'docs';source.mkdir();(source/'a.txt').write_text('Plants need water')
        kb=Knowledge(self.root,embedder=Embedder());cid=kb.create('Small',source)['id'];kb.sync(cid)
        with patch.object(kb,'embeddings',side_effect=AssertionError('unnecessary model load')):
            self.assertEqual(kb.sync(cid)['changed'],0)
        kb.refresh_policy(cid,300);row=kb.load(cid);row['automatic_source_bytes']=32*1024**2;kb.save('Collections/'+cid+'.json',row)
        (source/'a.txt').write_text('Plants need light')
        with self.assertRaisesRegex(RuntimeError,'allowance'):kb.sync(cid,automatic=True)
        self.assertIn('water',kb.search('plant')['results'][0]['text'])
    def test_auto_refresh_is_off_by_default_and_bounded(self):
        source=self.root/'docs';source.mkdir();(source/'a.txt').write_text('Plant text')
        kb=Knowledge(self.root,embedder=Embedder());cid=kb.create('Small',source)['id']
        with self.assertRaisesRegex(RuntimeError,'disabled'):kb.sync(cid,automatic=True)
        kb.refresh_policy(cid,300);kb.sync(cid,automatic=True)
        self.assertEqual(kb.load(cid)['automatic_source_bytes'],len('Plant text'))
        with self.assertRaises(ValueError):kb.refresh_policy(cid,1)


class VoiceTests(unittest.TestCase):
    def test_stream_buffer_preserves_raw_tail_and_bounds_queue(self):
        s=SpeechBuffer();s.feed('Hello there. How are');raw=s.queue.get_nowait();s.heard+=raw
        self.assertEqual(raw,'Hello there. ');self.assertEqual(s.remaining('Hello there. How are you?'),'How are you?')
        s.feed(' you? '+('Sentence. '*100));self.assertLessEqual(s.queue.qsize(),8);self.assertTrue(s.disabled)
    def test_stream_does_not_read_code_and_mismatched_final_is_not_lost(self):
        s=SpeechBuffer();s.feed('```python\nprint(1)');self.assertTrue(s.disabled);self.assertTrue(s.queue.empty())
        s.heard='I will check. ';self.assertEqual(s.remaining('Here is the result.'),'Here is the result.')
    def test_speech_interrupt_does_not_cancel_microphone_or_future_turn(self):
        voice=VoiceIO(Path('.'),lambda:None);voice.interrupt_speech()
        with self.assertRaises(SpeechInterrupted):voice.check()
        voice.check_capture();voice.reset_speech();voice.check();voice.cancel()
        with self.assertRaises(VoiceStopped):voice.check_capture()
    def test_live_piper_never_uses_handoff_on_low_memory(self):
        from voice_memory import VoiceMemoryError
        voice=VoiceIO(Path('.'),lambda:None)
        with patch('tts_policy.check_piper_memory',side_effect=VoiceMemoryError('speech','piper',10,1)),patch.object(voice,'_stage',side_effect=AssertionError('handoff')):
            with self.assertRaises(VoiceMemoryError):voice.speak_piper_live('Hello')


class MCPContentTests(Fixture):
    def test_resource_access_requires_separate_explicit_grant(self):
        store=Connections(self.root);cid=store.create('Content','http',url='https://example.org/mcp')['id']
        with self.assertRaises(PermissionError):store.content(cid,'resources')
        store.allow_content(cid,True)
        with patch.object(Transport,'initialize'),patch.object(Transport,'catalog',return_value=[{'uri':'doc:one','name':'One'}]),patch.object(Transport,'request',return_value={'contents':[{'text':'Evidence'}]}) as call:
            self.assertEqual(store.content(cid,'resources')[0]['uri'],'doc:one')
            self.assertIn('contents',store.content(cid,'resources','doc:one'))
            with self.assertRaises(ValueError):store.content(cid,'resources','doc:secret')
            self.assertEqual(call.call_count,1)
    def test_expired_signin_never_silently_sends_no_auth(self):
        store=Connections(self.root);cid=store.create('OAuth','http',url='https://example.org/mcp')['id']
        store.configure_oauth(cid,{'issuer':'https://auth.example.org','client_id':'portalai'})
        with self.assertRaisesRegex(RuntimeError,'Sign in'):store.config(cid)
    def test_oauth_config_rejects_remote_http_secrets_and_bad_ports(self):
        for cfg in ({'issuer':'http://remote.example','client_id':'x'}, {'issuer':'https://a.example','client_id':'x','client_secret':'secret'}, {'issuer':'https://a.example','client_id':'x','callback_port':1}):
            with self.assertRaises(ValueError):validate_config(cfg)
        with self.assertRaises(ValueError):token_result({'access_token':'hello\r\nInjected: yes','token_type':'bearer'})


class OAuthLoopbackTests(unittest.TestCase):
    def setUp(self):
        self.calls=[];owner=self
        class Provider(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if 'oauth-protected-resource' in self.path:data={'resource':owner.base+'/mcp','authorization_servers':[owner.base]}
                else:data={'issuer':owner.base,'authorization_endpoint':owner.base+'/authorize','token_endpoint':owner.base+'/token','code_challenge_methods_supported':['S256']}
                self.reply(data)
            def do_POST(self):
                form=url.parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode());owner.calls.append(form)
                self.reply({'access_token':'synthetic-access','refresh_token':'synthetic-refresh','token_type':'Bearer','expires_in':3600})
            def reply(self,data):
                raw=json.dumps(data).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        self.server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Provider);self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
    def test_real_callback_state_pkce_resource_and_token_binding(self):
        seen={};requests=[]
        def visit(target):
            fields=url.parse_qs(url.urlsplit(target).query);seen.update(fields)
            def client():
                for state in ('wrong-state',fields['state'][0]):
                    uri=fields['redirect_uri'][0]+'?'+url.urlencode({'state':state,'code':'synthetic-code'})
                    try:
                        with urllib.request.urlopen(uri,timeout=5) as response:requests.append(response.status)
                    except urllib.error.HTTPError as exc:requests.append(exc.code)
            t=threading.Thread(target=client,daemon=True);t.start()
        token=authorize({'issuer':self.base,'client_id':'fixture'},self.base+'/mcp',lambda:None,visit)
        self.assertEqual(requests,[400,200]);self.assertEqual(token['resource'],self.base+'/mcp')
        fields=self.calls[0];verifier=fields['code_verifier'][0]
        self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode(),seen['code_challenge'][0])
        self.assertEqual(fields['resource'],[self.base+'/mcp']);self.assertNotIn('client_secret',fields)
    def test_cancel_closes_callback_and_never_exchanges_token(self):
        cancel=threading.Event()
        def check():
            if cancel.is_set():raise RuntimeError('Stopped')
        with self.assertRaisesRegex(RuntimeError,'Stopped'):
            authorize({'issuer':self.base,'client_id':'fixture'},self.base+'/mcp',check,lambda target:cancel.set())
        self.assertFalse(self.calls)


class AccessibilityTests(unittest.TestCase):
    def test_accessible_target_must_fit_allowed_observation(self):
        from desktop_accessibility import point
        observation={'rect':[100,100,900,700],'size':[400,300],'native':[800,600]}
        self.assertEqual(point({'enabled':True,'rect':[200,200,100,40]},observation),(75,60))
        for row in ({'enabled':False,'rect':[200,200,100,40]},{'enabled':True,'rect':[0,0,100,40]}):
            with self.assertRaises(ValueError):point(row,observation)


class ComparisonTests(Fixture):
    def test_models_run_sequentially_and_original_profile_is_restored(self):
        from model_comparison import Comparisons
        from types import SimpleNamespace
        calls=[];store=Comparisons(self.root)
        with patch('chat_model_switch.prepare_chat',side_effect=lambda root,level,**kw:calls.append(('prepare',level)) or {}),patch('native_chat.model_id',side_effect=['first','second']),patch('capability_tools.prompt',side_effect=lambda *args:calls.append(('answer',None)) or 'Fixture answer'):
            result=store.run(SimpleNamespace(root=self.root),'Question',['fast','balanced'],threading.Event(),original='deep')
        self.assertEqual(calls,[('prepare','fast'),('answer',None),('prepare','balanced'),('answer',None),('prepare','deep')])
        self.assertTrue(result['restored']);self.assertEqual(store.read(result['id'])['state'],'complete')
    def test_failure_preserves_partial_result_without_automatic_replay(self):
        from model_comparison import Comparisons
        from types import SimpleNamespace
        store=Comparisons(self.root)
        with patch('chat_model_switch.prepare_chat',return_value={}),patch('native_chat.model_id',return_value='fixture'),patch('capability_tools.prompt',side_effect=['First answer',RuntimeError('model failed')]):
            with self.assertRaisesRegex(RuntimeError,'model failed'):store.run(SimpleNamespace(root=self.root),'Question',['fast','balanced'],threading.Event())
        self.assertEqual(len(store.list()[0]['results']),1);self.assertEqual(store.list()[0]['state'],'stopped_or_failed')


class DesktopActionTests(Fixture):
    def test_drag_releases_button_and_consumes_observation_when_focus_changes(self):
        from desktop_control import Desktop
        from contextlib import nullcontext
        from types import SimpleNamespace
        from unittest.mock import Mock
        d=Desktop(self.root,None);row={'rect':[0,0,100,100]}
        d.observation={'token':'one','window':9,'at':time.monotonic(),'rect':row['rect'],'size':(100,100),'native':(100,100)}
        user=SimpleNamespace(GetForegroundWindow=Mock(side_effect=[9,9,8]),WindowFromPoint=lambda p:9,GetAncestor=lambda *a:9,SetCursorPos=Mock())
        with patch.object(d,'dpi',return_value=nullcontext()),patch.object(d,'check',return_value=row),patch.object(d,'focus'),patch.object(d,'api',return_value=(user,None)),patch.object(d,'_send') as send:
            with self.assertRaisesRegex(RuntimeError,'Focus changed'):
                d.call('drag',{'window':9,'observation':'one','x':10,'y':10,'end_x':80,'end_y':80},lambda:None)
        self.assertEqual(send.call_args_list[0].kwargs,{'mouse':(2,0)})
        self.assertEqual(send.call_args_list[-1].kwargs,{'mouse':(4,0)});self.assertIsNone(d.observation)

    def test_changed_accessible_control_never_clicks(self):
        from desktop_control import Desktop
        from contextlib import nullcontext
        d=Desktop(self.root,None);row={'rect':[0,0,100,100]};element={'id':'target','name':'Before','rect':[10,10,20,20],'enabled':True}
        d.observation={'token':'one','window':9,'at':time.monotonic(),'rect':row['rect'],'size':(100,100),'native':(100,100),'elements':{'target':element}}
        with patch.object(d,'dpi',return_value=nullcontext()),patch.object(d,'check',return_value=row),patch('desktop_accessibility.snapshot',return_value=[{**element,'name':'After'}]),patch.object(d,'_send') as send:
            with self.assertRaisesRegex(ValueError,'changed'):
                d.call('click_element',{'window':9,'observation':'one','element':'target'},lambda:None)
        send.assert_not_called();self.assertIsNone(d.observation)


if __name__=='__main__':unittest.main()
