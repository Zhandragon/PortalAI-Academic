"""Read-only exporter: real disposable authentication/profile, no production data."""
import copy
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
from native_ui_state import Exporter
from native_ui_protocol import PROTOCOL, MAX_FRAME, MEDIA, encode, decode, validate_envelope, validate_snapshot
from local_accounts import LocalAccounts
from profile_runtime import ProfileRuntime


class App:
    _portalai_main_ready=True
    _portalai_account_dialogs=()
    def after(self,*_): return 'fixture-timer'
    def after_cancel(self,*_): pass
    def bind(self,*_,**__): pass


class NativeStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='PortalAI-native-unit-')
        self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{},clear=False);self.env.start()
        os.environ.pop('PORTALAI_PROFILE_ID',None);os.environ.pop('PORTALAI_PROFILE_EPOCH',None)
        self.backend=LocalAccounts(self.root)
        self.session=self.backend.bootstrap('NativeFixture','Synthetic-native-fixture-2026')
        self.runtime=ProfileRuntime(self.root,self.backend,quiesce=lambda *_:{'stopped':True})
        self.runtime.prepare(self.session)
        self.gate=SimpleNamespace(session=self.session,locked=False)
        self.app=App()
        self.panel=SimpleNamespace(_closing=False,busy=False,session={'id':uuid.uuid4().hex,'title':'Fixture chat',
                'messages':[{'role':'user','content':'Synthetic text <not HTML>'}]},
            _last_context_meta={},_model_context_limit=None,_cached_model_name='Fixture model',
            _cached_model_state='sleeping',settings={'max_output_tokens':2048},effort=SimpleNamespace(profile='balanced'))
        self.settings=SimpleNamespace(saved_values={'selection':'auto','variant_preference':'standard','backend':'auto',
            'context_tokens':'8192',**{k:'auto' for k in MEDIA}})
        self.folder=self.root/'endpoint';self.folder.mkdir()
        self.export=Exporter(self.app,self.root,self.gate,self.panel,self.settings,self.folder,0)

    def tearDown(self):
        self.export.close()
        self.runtime.close(self.gate.session,writers_stopped=True)
        self.env.stop()
        self.temp.cleanup()

    def read(self):
        generation=uuid.uuid4().hex
        b=self.export.request('/native/v2/bind',{'protocol':PROTOCOL,'generation':generation})
        result=self.export.request('/native/v2/snapshot',{'protocol':PROTOCOL,'generation':generation,**b['binding']})
        validate_envelope(result)
        return result

    def http(self,path,body,token=None):
        conn=http.client.HTTPConnection('127.0.0.1',self.export.server.server_port,timeout=3)
        try:
            conn.request('POST',path,body if isinstance(body,bytes) else encode(body),
                         {'Authorization':'Bearer '+(token if token is not None else self.export.token)})
            response=conn.getresponse();return response.status,response.read(MAX_FRAME+1)
        finally:conn.close()

    def test_actual_authenticated_profile_read_and_no_domain_side_effect(self):
        before=copy.deepcopy(self.panel.session)
        self.panel.store=SimpleNamespace(list_sessions=lambda: self.fail('export hydrated/read catalog'))
        result=self.read();s=result['snapshot']
        self.assertEqual(s['account'],{'state':'ready','displayName':'NativeFixture'})
        self.assertEqual(s['chat']['messages'][0]['text'],'Synthetic text <not HTML>')
        self.assertIsNone(s['runtime']['gpu']);self.assertIsNone(s['chat']['contextLimit'])
        self.assertEqual(self.panel.session,before)
        self.assertNotIn(self.session.user_id,encode(result).decode())
        self.assertNotIn(str(self.root),encode(result).decode())
        self.assertNotIn(self.session._token,encode(result).decode())

    def test_named_model_ids_with_decimal_are_valid_and_metadata_is_allowlisted(self):
        self.settings.saved_values['selection']='qwen1.7-q8'
        self.export.observe({'telemetry':{'cpu':None,'gpu':13,'ram':40,'process_counters':{'secret':'exclude'}},
            'settings_models':[{'id':'qwen1.7-q8','label':'Qwen 1.7B','installed':True,'path':'C:/private/secret'}],
            'installed':{'model_qwen1.7-q8':('INSTALLED','C:/private/runtime')}})
        self.export.tick();s=self.read()['snapshot']
        self.assertTrue(s['models'][0]['selected']);self.assertEqual(s['models'][0]['state'],'unknown')
        self.assertNotIn('private',encode(s).decode());self.assertEqual(s['runtime']['gpu'],13)
        self.assertEqual(s['packages'][0]['id'],'model_qwen1.7-q8')

    def test_loading_or_empty_chat_is_representable(self):
        self.panel._session_load_request={'pending':True};self.export.tick();s=self.read()['snapshot']
        self.assertIsNone(s['chat']['current']);self.assertEqual(s['chat']['messages'],[])
        self.assertFalse(s['chat']['busy'])

    def test_endpoint_is_separate_capability_and_export_is_not_written_to_disk(self):
        endpoint=json.loads(self.export.path.read_text())
        self.assertEqual(endpoint['scope'],'native.state.read')
        self.assertNotIn('NativeFixture',self.export.path.read_text())
        self.assertEqual(self.export.server.server_address[0],'127.0.0.1')
        self.assertEqual(len(list(self.folder.iterdir())),1)
        status,_=self.http('/native/v2/bind',{'protocol':PROTOCOL,'generation':'one'},token='projection-token')
        self.assertEqual(status,409)

    def test_network_has_only_exact_read_routes_and_bounded_json(self):
        for path,body in [('/input',{}),('/native/v2/submit',{}),('/native/v2/bind',{'protocol':PROTOCOL,'generation':'g','command':'chat.submit'}),
                          ('/native/v2/bind',b'{"generation":"a","generation":"b"}'),('/native/v2/bind',b'x'*2049)]:
            with self.subTest(path=path,body=str(body)[:40]):self.assertEqual(self.http(path,body)[0],409)
        status,raw=self.http('/native/v2/bind',{'protocol':PROTOCOL,'generation':'g'})
        self.assertEqual(status,200);self.assertEqual(decode(raw)['capabilities'],['native.state.read'])

    def test_lock_revokes_old_binding_and_prepared_response(self):
        old=self.read();self.gate.locked=True;self.export.invalidate('closing')
        self.assertFalse(self.export.response_current(old))
        with self.assertRaises(PermissionError):
            self.export.request('/native/v2/snapshot',{'protocol':PROTOCOL,'generation':'g',
                'view':old['snapshot']['view'],'epoch':old['snapshot']['epoch']})
        locked=self.read()['snapshot']
        self.assertEqual(set(locked),{'version','view','epoch','revision','account'})
        self.assertEqual(locked['account']['displayName'],'')

    def test_stalled_GUI_expires_view_without_waiting_for_Tk(self):
        old=self.read();self.export.published_at-=3
        start=time.perf_counter();self.assertFalse(self.export.response_current(old))
        self.assertLess(time.perf_counter()-start,.1)
        self.assertEqual(self.read()['snapshot']['account']['state'],'locked')
        self.export.tick();new=self.read()['snapshot']
        self.assertEqual(new['account']['state'],'ready');self.assertNotEqual(new['epoch'],old['snapshot']['epoch'])

    def test_account_modal_suppresses_private_state(self):
        self.app._portalai_account_dialogs=[SimpleNamespace(closed=False)]
        s=self.read()['snapshot'];self.assertEqual(s['account']['state'],'locked');self.assertNotIn('chat',s)

    def test_real_session_expiry_clears_cached_private_state(self):
        old=self.read();previous=self.session._expires
        try:
            self.session._expires=self.backend.clock()-1
            self.assertFalse(self.export.response_current(old))
            s=self.read()['snapshot']
            self.assertEqual(s['account'],{'state':'locked','displayName':''})
            self.assertNotIn('chat',s)
        finally:self.session._expires=previous

    def test_real_session_replacement_requires_fresh_binding(self):
        old=self.read();new=self.backend.login('NativeFixture','Synthetic-native-fixture-2026')
        self.runtime.replace_session(new);self.gate.session=new
        self.assertFalse(self.export.response_current(old))
        self.export.reauthorize();self.export.tick()
        self.assertNotEqual(self.read()['snapshot']['epoch'],old['snapshot']['epoch'])

    def test_network_rebind_rotates_GUI_authority_without_renewing_cache_age(self):
        old=self.read();at=self.export.published_at
        result=self.export.request('/native/v2/rebind',{'protocol':PROTOCOL,'generation':'fresh'})
        self.assertNotEqual(result['binding']['view'],old['snapshot']['view'])
        self.assertEqual(self.export.published_at,at)
        self.assertFalse(self.export.response_current(old))
        fresh=self.export.request('/native/v2/snapshot',{'protocol':PROTOCOL,'generation':'fresh',**result['binding']})
        self.assertEqual(fresh['snapshot']['account']['state'],'ready')
        self.export.published_at-=3
        locked=self.export.request('/native/v2/rebind',{'protocol':PROTOCOL,'generation':'expired'})
        s=self.export.request('/native/v2/snapshot',{'protocol':PROTOCOL,'generation':'expired',**locked['binding']})['snapshot']
        self.assertEqual(s['account']['state'],'locked');self.assertNotIn('chat',s)

    def test_role_string_and_lookalike_session_do_not_authenticate(self):
        old=self.gate.session
        try:
            for fake in ('admin',SimpleNamespace(role='admin',user_id=old.user_id)):
                self.gate.session=fake
                with self.assertRaises(PermissionError):self.export.reauthorize()
        finally:self.gate.session=old

    def test_cache_read_is_a_copy_and_unchanged_refresh_keeps_revision(self):
        old=self.read();revision=old['snapshot']['revision'];old['snapshot']['chat']['messages'][0]['text']='mutated'
        self.export.tick();new=self.read()['snapshot'];self.assertEqual(new['revision'],revision)
        self.assertNotEqual(new['chat']['messages'][0]['text'],'mutated')

    def test_utf8_frame_budget_keeps_saved_transcript_and_marks_excerpt(self):
        self.panel.session['messages']=[{'role':'assistant','content':'界😀'*10000} for _ in range(110)]
        self.export.tick();result=self.read()
        self.assertLessEqual(len(encode(result)),MAX_FRAME)
        self.assertEqual(result['snapshot']['account']['state'],'ready')
        self.assertFalse(result['snapshot']['chat']['window']['messagesComplete'])
        self.assertTrue(all(r['truncated'] for r in result['snapshot']['chat']['messages']))
        self.assertEqual(len(self.panel.session['messages']),110)
        self.assertEqual(self.panel.session['messages'][0]['content'],'界😀'*10000)


class ProtocolTests(unittest.TestCase):
    def test_native_opt_in_is_consumed_before_children_even_without_projection(self):
        import remote_desktop_input
        with patch.dict(os.environ,{'PORTALAI_NATIVE_STATE':'2','PORTALAI_PROJECTION_HOME':'','PORTALAI_PROJECTION_INPUT':''}):
            self.assertIsNone(remote_desktop_input.install(object(),ROOT))
            self.assertNotIn('PORTALAI_NATIVE_STATE',os.environ)

    def test_projection_opt_in_retains_separate_native_scope(self):
        import remote_desktop_input
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);(base/'app').mkdir();(base/'app/projection_worker.py').write_text('# fixture')
            scope=base/'state/input/fixture';scope.mkdir(parents=True)
            app=App()  # Public workflows now register bounded Tk timers and Destroy.
            with patch.dict(os.environ,{'PORTALAI_NATIVE_STATE':'2','PORTALAI_PROJECTION_HOME':str(base),'PORTALAI_PROJECTION_INPUT':str(scope)}),patch.object(remote_desktop_input,'InputAdapter') as adapter:
                self.assertIs(remote_desktop_input.install(app,ROOT),adapter.return_value)
                self.assertEqual(app._portalai_native_state_folder,scope)
                self.assertIs(app._portalai_projection_adapter,adapter.return_value)
                self.assertFalse(any(k in os.environ for k in ('PORTALAI_NATIVE_STATE','PORTALAI_PROJECTION_HOME','PORTALAI_PROJECTION_INPUT')))

    def test_duplicate_json_keys_nonfinite_and_bool_revision_rejected(self):
        for value in (b'{"a":1,"a":2}',b'{"x":NaN}',b'{"x":Infinity}'):
            with self.assertRaises(ValueError):decode(value)
        s={'version':2,'view':'v','epoch':'e','revision':True,'account':{'state':'locked','displayName':''}}
        with self.assertRaises(ValueError):validate_snapshot(s)

    def test_locked_state_has_exact_fields_and_no_name(self):
        s={'version':2,'view':'v','epoch':'e','revision':0,'account':{'state':'closing','displayName':''}}
        self.assertIs(validate_snapshot(s),s)
        for patch_value in ({'chat':{}},{'account':{'state':'locked','displayName':'private'}}):
            with self.assertRaises(ValueError):validate_snapshot({**s,**patch_value})

    def test_protocol_media_catalog_matches_domain(self):
        from model_preferences import MEDIA_CHOICES
        self.assertEqual(MEDIA,MEDIA_CHOICES)


if __name__=='__main__':unittest.main()
