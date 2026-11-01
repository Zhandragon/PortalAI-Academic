"""r59 portable bundle, authorization, storage and reasoning regressions."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from test_workspace import Fixture
from skill_packs import SkillPacks,wheel_files
from mcp_oauth import validate_config,client_for_redirect,metadata,refresh


class BundleTests(Fixture):
    def bundle(self,files=None,**changes):
        files=files or {'SKILL.md':b'---\nname: Fixture\ndescription: Test a report\n---\nRead the supporting guide.',
                         'scripts/report.py':b'import sys;print("report",*sys.argv[1:])','guides/help.txt':b'Check the source before writing.'}
        manifest={'version':1,'instructions':'SKILL.md','files':{n:hashlib.sha256(b).hexdigest() for n,b in files.items()},'scripts':{'report':'scripts/report.py'}}
        manifest.update(changes);target=self.root/'bundle.zip'
        with zipfile.ZipFile(target,'w') as z:
            z.writestr('skill.json',json.dumps(manifest))
            for name,raw in files.items():z.writestr(name,raw)
        return target
    def test_import_is_disabled_and_edits_preserve_bundle_but_disable_revokes_code(self):
        store=SkillPacks(self.root);row=store.import_pack(self.bundle());sid=row['id']
        self.assertFalse(row['enabled']);self.assertFalse(row['code_enabled'])
        with self.assertRaises(PermissionError):store.assets(sid)
        store.put(row['name'],row['description'],row['body'],skill=sid,enabled=True);store.allow_code(sid,True)
        self.assertIn('Check the source',store.file(sid,'guides/help.txt')['content'])
        row=store.put(row['name'],row['description'],'Edited guide',skill=sid,enabled=False)
        self.assertTrue(row['pack']);self.assertFalse(row['code_enabled'])
    def test_tamper_traversal_case_alias_and_reserved_paths_are_refused(self):
        store=SkillPacks(self.root)
        for name in ('../outside','Dependencies/x.py','a/../b','con.txt','A.txt'):
            files={'SKILL.md':b'Guide','a.txt':b'x',name:b'y'}
            with self.subTest(name=name),self.assertRaises(ValueError):store.import_pack(self.bundle(files,scripts={}))
        target=self.root/'corrupt.zip'
        with zipfile.ZipFile(target,'w') as z:
            z.writestr('SKILL.md','Changed guide')
            z.writestr('skill.json',json.dumps({'version':1,'files':{'SKILL.md':'0'*64}}))
        with self.assertRaisesRegex(ValueError,'checksum'):store.import_pack(target)
    def test_pending_execution_prevents_replay_and_requires_review(self):
        from workspace_store import digest
        store=SkillPacks(self.root);row=store.import_pack(self.bundle());sid=row['id']
        store.put(row['name'],row['description'],row['body'],skill=sid,enabled=True)
        runtime=SimpleNamespace(_account_role=lambda:'admin')
        with self.assertRaises(PermissionError):store.run(sid,'report',[],runtime)
        store.allow_code(sid,True);rid=store.new_id();action={'skill':sid,'script':'report','arguments':[]}
        store.save('Calls/'+rid+'.json',{**action,'id':rid,'state':'pending','signature':digest(action)})
        with self.assertRaisesRegex(RuntimeError,'uncertain'):store.run(sid,'report',[],runtime)
        store.review_call(rid,True)
        self.assertEqual(json.loads(store.path('Calls/'+rid+'.json').read_text())['state'],'reviewed')
    def test_tampered_file_never_launches(self):
        store=SkillPacks(self.root);row=store.import_pack(self.bundle());sid=row['id']
        store.put(row['name'],row['description'],row['body'],skill=sid,enabled=True);store.allow_code(sid,True)
        store.path('Packs/'+sid+'/scripts/report.py').write_text('print("changed")')
        with patch('subprocess.Popen') as launch,self.assertRaisesRegex(ValueError,'changed'):
            store.run(sid,'report',[],SimpleNamespace(_account_role=lambda:'admin'))
        launch.assert_not_called()
    def test_real_owned_script_uses_isolated_bundled_wheel(self):
        portable=Path(os.environ.get('PORTALAI_TEST_PYTHON',sys.executable))
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('fixture_dep/__init__.py','VALUE="isolated dependency"')
            z.writestr('fixture_dep-1.0.dist-info/WHEEL','Wheel-Version: 1.0\nTag: py3-none-any\n')
        files={'SKILL.md':b'Use the report script.','scripts/report.py':b'import fixture_dep;print(fixture_dep.VALUE)','vendor/dep.whl':raw.getvalue()}
        store=SkillPacks(self.root);row=store.import_pack(self.bundle(files,wheels=['vendor/dep.whl']));sid=row['id']
        store.put(row['name'],row['description'],row['body'],skill=sid,enabled=True);store.allow_code(sid,True)
        with patch('platform_runtime.python_path',return_value=portable):
            result=store.run(sid,'report',[],SimpleNamespace(_account_role=lambda:'admin'))
        self.assertEqual(result['exit_code'],0);self.assertIn('isolated dependency',result['output'])
        self.assertNotIn('fixture_dep',sys.modules)
    def test_dependency_executable_pth_is_refused(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:
            z.writestr('x-1.dist-info/WHEEL','Tag: py3-none-any\n');z.writestr('hook.pth','import os')
        with self.assertRaisesRegex(ValueError,'hooks'):wheel_files(raw.getvalue())


class OAuthExtensionTests(unittest.TestCase):
    def test_dynamic_registration_has_exact_callback_and_no_secret(self):
        cfg=validate_config({'client_mode':'dynamic'});redirect='http://127.0.0.1:12345/portalai-oauth/callback'
        with patch('mcp_oauth.request_json',return_value={'client_id':'new-client','redirect_uris':[redirect]}) as request:
            self.assertEqual(client_for_redirect(cfg,{'registration_endpoint':'https://provider.example/register'},redirect,lambda:None),'new-client')
        self.assertEqual(request.call_args.kwargs['json_fields']['redirect_uris'],[redirect])
        self.assertEqual(request.call_args.kwargs['json_fields']['token_endpoint_auth_method'],'none')
        with patch('mcp_oauth.request_json',return_value={'client_id':'x','client_secret':'secret'}),self.assertRaises(ValueError):
            client_for_redirect(cfg,{'registration_endpoint':'https://provider.example/register'},redirect,lambda:None)
    def test_metadata_requires_provider_support_and_exact_redirect(self):
        cfg=validate_config({'client_mode':'metadata','client_id':'https://client.example/portal.json'})
        with self.assertRaisesRegex(ValueError,'advertise'):client_for_redirect(cfg,{},'http://127.0.0.1:12345/callback',lambda:None)
        with patch('mcp_oauth.request_json',return_value={'client_id':cfg['client_id'],'redirect_uris':['http://127.0.0.1:54321/callback']}),self.assertRaisesRegex(ValueError,'exact'):
            client_for_redirect(cfg,{'client_id_metadata_document_supported':True},'http://127.0.0.1:12345/callback',lambda:None)
    def test_challenge_discovery_still_binds_resource_and_pkce(self):
        resource='https://server.example/mcp';issuer='https://provider.example'
        def request(target,check):
            if 'oauth-protected-resource' in target:raise RuntimeError('HTTP 404')
            if target=='https://server.example/custom-metadata':return {'resource':resource,'authorization_servers':[issuer]}
            return {'issuer':issuer,'authorization_endpoint':issuer+'/auth','token_endpoint':issuer+'/token','code_challenge_methods_supported':['S256']}
        with patch('mcp_oauth.protected_metadata_url',return_value='https://server.example/custom-metadata'),patch('mcp_oauth.request_json',side_effect=request):
            self.assertEqual(metadata(validate_config({'client_mode':'dynamic'}),resource,lambda:None)['issuer'],issuer)
    def test_refresh_uses_registered_client_from_saved_token(self):
        token={'client_id':'issued','refresh_token':'refresh','token_endpoint':'https://p.example/token','resource':'https://r.example/mcp'}
        with patch('mcp_oauth.request_json',return_value={'access_token':'new','token_type':'Bearer'}) as request:
            refresh({'client_id':''},token,lambda:None)
        self.assertEqual(request.call_args.args[2]['client_id'],'issued')


class StorageReadTests(Fixture):
    def test_eighty_gib_floor_blocks_growth_below_headroom(self):
        from runtime_policy import storage_budget,GIB
        (self.root/'Agent/storage_reserve.json').write_text('{"minimum_free_gib":80}')
        with patch('shutil.disk_usage',return_value=SimpleNamespace(total=1000*GIB,free=81*GIB)):
            self.assertTrue(storage_budget(self.root,additional_bytes=GIB)['allowed'])
            self.assertFalse(storage_budget(self.root,additional_bytes=GIB+1)['allowed'])
    def test_transient_windows_open_conflict_retries_read_only(self):
        from workspace_store import read_json
        path=self.root/'record.json';path.write_text('{"state":"complete"}');original=Path.open;count=[]
        def opening(p,*args,**kwargs):
            count.append(1)
            if len(count)<3:raise PermissionError('replacement in progress')
            return original(p,*args,**kwargs)
        with patch('workspace_store.os.name','nt'),patch.object(Path,'open',opening),patch('workspace_store.time.sleep'):
            self.assertEqual(read_json(path),{'state':'complete'})
        self.assertEqual(len(count),3)


class TaskNotebookTests(unittest.TestCase):
    def chat(self,messages):
        import threading
        from unittest.mock import Mock
        return SimpleNamespace(session={'messages':messages},cancel_event=threading.Event(),_check_login=lambda:None,store=SimpleNamespace(save_session=Mock()))
    def test_verified_plan_requires_original_successful_evidence(self):
        from task_notebook import execute
        chat=self.chat([{'role':'user','content':'Fix and test'},{'role':'tool','name':'shell','content':'{"exit_code":0,"output":"3 tests passed"}','execution':{'dispatched':True,'outcome':'returned'}}])
        step={'id':'verify','goal':'Run relevant tests','check':'Tests pass','status':'verified','evidence':[1]}
        result=json.loads(execute(chat,{'action':'update','steps':[step]}));self.assertTrue(result['all_verified'])
        for change in ({'evidence':[]},{'evidence':[0]}):
            with self.assertRaises(ValueError):execute(chat,{'action':'update','steps':[{**step,**change}]})
        chat.session['messages'][1]['content']='{"exit_code":1}'
        with self.assertRaisesRegex(ValueError,'failure'):execute(chat,{'action':'update','steps':[step]})
    def test_plan_is_scoped_to_current_request_and_preserved(self):
        from task_notebook import execute,guidance
        chat=self.chat([{'role':'user','content':'Research'}]);execute(chat,{'action':'update','steps':[{'id':'source','goal':'Find source','check':'Read primary evidence','status':'active'}]})
        self.assertIn('Find source',guidance(chat.session));chat.session['messages'].append({'role':'user','content':'Different task'})
        self.assertEqual(guidance(chat.session),'');self.assertIn('0',chat.session['task_notebooks'])
    def test_relevant_skill_beats_alphabetical_order_without_loading_body(self):
        from portable_workspace import rank_skills
        rows=[{'name':'A writing','description':'Write fiction'},{'name':'Z databases','description':'Inspect SQLite tables and indexes'}]
        self.assertEqual(rank_skills(rows,'Inspect the SQLite indexes')[0]['name'],'Z databases')


class CanvasWorkflowTests(Fixture):
    def test_drawn_forward_link_changes_routing_and_preserves_approval(self):
        from workflow_canvas import connect
        from workflows import Workflows
        flow={'version':1,'name':'Canvas','steps':[{'id':'first','kind':'output','value':'one'},{'id':'skip','kind':'output','value':'two'},{'id':'approve','kind':'approval'}]}
        connect(flow,'first','approve');flow['layout']={'first':[23,40]}
        store=Workflows(self.root);tid=store.put(flow)['id'];rid=store.start(tid,{})['id'];row=store.advance(rid)
        self.assertEqual(row['state'],'approval');self.assertNotIn('skip',row['results'])
        with self.assertRaisesRegex(ValueError,'forward'):connect(flow,'approve','first')
        self.assertNotIn('next',flow['steps'][-1])
    def test_invalid_positions_and_condition_ports_are_rejected(self):
        from workflows import validate
        from workflow_canvas import connect
        flow={'version':1,'name':'Test','steps':[{'id':'first','kind':'output','value':1}],'layout':{'first':[float('nan'),0]}}
        with self.assertRaises(ValueError):validate(flow)
        flow.pop('layout')
        with self.assertRaises(ValueError):connect(flow,'first','end','else')


class MonitorTests(Fixture):
    def test_background_monitor_defers_busy_work_and_stop_fences_updates(self):
        import threading
        from knowledge_monitor import KnowledgeMonitor
        from knowledge_base import Knowledge
        from unittest.mock import Mock
        source=self.root/'docs';source.mkdir();(source/'a.txt').write_text('Plants')
        kb=Knowledge(self.root);cid=kb.create('Docs',source)['id'];kb.refresh_policy(cid,300)
        chat=SimpleNamespace(root=self.root,tool_runtime=object(),busy=False,conversation_active=threading.Event())
        with patch('knowledge_monitor.guard',return_value=lambda:None):monitor=KnowledgeMonitor(chat)
        self.addCleanup(lambda:[s.close() for s in monitor.signals.values()])
        with patch('runtime_policy.memory_info',return_value=(8*1024**3,4*1024**3)),patch.object(Knowledge,'sync',return_value={'changed':1}) as sync:
            monitor.tick(0);sync.assert_not_called();chat.busy=True;monitor.tick(400);sync.assert_not_called()
            chat.busy=False;monitor.tick(400);sync.assert_called_once_with(cid,automatic=True)
            monitor.close()
            with self.assertRaisesRegex(RuntimeError,'stopped'):monitor.tick(800)
    @unittest.skipUnless(os.name=='nt','Windows directory signals')
    def test_real_windows_folder_notification_detects_change(self):
        from knowledge_monitor import FolderSignal
        import time
        signal=FolderSignal(self.root);self.addCleanup(signal.close);self.assertIsNotNone(signal.handle)
        (self.root/'event.txt').write_text('changed')
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            if signal.changed():break
            time.sleep(.01)
        else:self.fail('No directory change signal')


class AgentAPITests(Fixture):
    def test_token_tools_require_explicit_agent_scope(self):
        from application_api import APIState
        state=APIState(self.root)
        with self.assertRaisesRegex(ValueError,'scope'):state.issue('Bad',['chats:write'],tools=['read_file'])
        with self.assertRaises(ValueError):state.issue('Bad',['agent:execute'],tools=['unreviewed_tool'])
        grant=state.issue('Reader',['agent:execute'],tools=['read_file']);row=state.authenticate('Bearer '+grant['token'])
        self.assertEqual(row['tools'],['read_file'])
    def test_real_harness_records_granted_file_read_and_blocks_ungranted_schema(self):
        import threading
        from application_api import APIState
        from headless_chat import run
        from native_chat import NativeChat,_scoped_tools
        state=APIState(self.root);grant=state.issue('Read',['agent:execute'],tools=['read_file']);cid=state.new_id()
        state.save('Chats/'+cid+'.json',{'id':cid,'title':'API fixture','messages':[]})
        file=self.root/'fixture.txt';file.write_text('Evidence from the actual file')
        def call(name,args,cid):return {'id':cid,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
        answers=[('', '',[call('tool_help',{'tools':['read_file']},'help1')],False),
                 ('','',[call('read_file',{'path':str(file)},'read1')],False),('The file contains the expected evidence.','',[],False)]
        api=SimpleNamespace(root=self.root,state=state,runtime=SimpleNamespace())
        with patch('native_chat.bootstrap_python',return_value=sys.executable),patch('chat_effort_ui.ChatEffortControls.prepare_request',return_value=True),patch.object(NativeChat,'_runtime_context_limit',return_value=8192),patch.object(NativeChat,'_completion_with_tool_repair',side_effect=answers):
            result=run(api,{'chat':cid,'message':'Read fixture.txt','tools':['read_file'],'token':grant['id']},lambda:None,threading.Event())
        saved=json.loads(state.path('Chats/'+cid+'.json').read_text());tools=[r for r in saved['messages'] if r.get('role')=='tool']
        self.assertEqual(result['state'],'complete',result);self.assertIn('Evidence from the actual file',tools[-1]['content'])
        self.assertNotIn('pending_agent_job',saved)
        p=SimpleNamespace(_api_allowed_tools={'read_file','chat_history'},settings={},session={})
        self.assertEqual({r['function']['name'] for r in _scoped_tools(p)},{'read_file','chat_history'})
    def test_interrupted_turn_is_never_replayed(self):
        import threading
        from application_api import APIState
        from headless_chat import run
        state=APIState(self.root);grant=state.issue('No tools',['agent:execute']);cid=state.new_id()
        state.save('Chats/'+cid+'.json',{'id':cid,'messages':[],'pending_agent_job':True})
        with patch('native_chat.NativeChat.agent_worker') as worker,self.assertRaisesRegex(RuntimeError,'unfinished'):
            run(SimpleNamespace(root=self.root,state=state,runtime=object()),{'chat':cid,'message':'Continue','tools':[],'token':grant['id']},lambda:None,threading.Event())
        worker.assert_not_called()


if __name__=='__main__':unittest.main()
