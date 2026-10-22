"""HA 0.5.9 attachment protocol against installed host modules; synthetic inputs."""
import importlib.util,threading,time,types,unittest,sys
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
PROJECTION=ROOT.parent/'Utilities/PortalAI-Projection'
path=ROOT/'ControlCenter/native_chat_command.py'
spec=importlib.util.spec_from_file_location('chat_attachment_reference',path)
chat=importlib.util.module_from_spec(spec);spec.loader.exec_module(chat)

class AttachmentChatTests(unittest.TestCase):
    def setUp(self):
        self.panel=types.SimpleNamespace(session={'id':'chat'},busy=False,
            pending_attachments=[{'name':'fixture.jpg'}],cancel_event=threading.Event(),
            _check_login=lambda:None,submit=Mock(return_value=True))
        self.ex=types.SimpleNamespace(chat=self.panel,thread_id=threading.get_ident(),
            allowed=lambda **kw:True,mode='ready',view='a'*32,epoch='b'*32,
            app=types.SimpleNamespace(grab_current=lambda:None),lock=threading.RLock(),
            session=types.SimpleNamespace(user_id='user'),profile=types.SimpleNamespace(identity='profile'))
        self.controller=chat.Controller(self.ex)
        self.payload={'operation':'send','text':'Test attachment','request_id':'c'*32,'viewer':'d'*32,
            'binding':{'view':self.ex.view,'epoch':self.ex.epoch},'conversation':'chat'}
    def execute(self,p=None):return self.controller.execute(p or self.payload,time.monotonic()+5)
    def test_legacy_text_request_does_not_consume_pending_attachments(self):
        with self.assertRaisesRegex(RuntimeError,'pending_attachments'):self.execute()
        self.panel.submit.assert_not_called()
    def test_opt_in_uses_existing_submit_and_admission_exactly_once(self):
        p={**self.payload,'include_pending_attachments':True}
        receipt=self.execute(p);self.assertIsInstance(receipt,chat.Receipt)
        self.assertIs(self.execute(p),receipt);self.panel.submit.assert_called_once_with(remote_text=p['text'],remote_admission=receipt)
        receipt.ready.set();self.assertTrue(receipt.poll()['accepted'])
    def test_incomplete_attachment_copy_is_still_refused(self):
        self.panel._attachment_picker_pending=object()
        with self.assertRaisesRegex(RuntimeError,'pending_attachments'):self.execute({**self.payload,'include_pending_attachments':True})
        self.panel.submit.assert_not_called()
    def test_opt_in_cannot_bypass_account_conversation_or_modal_guards(self):
        for change in ('account','conversation','modal'):
            self.setUp()
            if change=='account':self.ex.mode='locked'
            elif change=='conversation':self.panel.session={'id':'other'}
            else:self.ex.app.grab_current=lambda:object()
            with self.assertRaises(PermissionError):self.execute({**self.payload,'include_pending_attachments':True})
            self.panel.submit.assert_not_called()
    def test_opt_in_is_strict_and_send_only(self):
        for value in (False,1,'true',None):
            with self.assertRaises(ValueError):chat.validate({**self.payload,'include_pending_attachments':value})
        p={k:v for k,v in self.payload.items() if k!='text'};p.update(operation='stop',include_pending_attachments=True)
        with self.assertRaises(ValueError):chat.validate(p)
    def test_lock_before_admission_never_acknowledges_send(self):
        receipt=self.execute({**self.payload,'include_pending_attachments':True});receipt.ready.set();self.ex.mode='locked'
        with self.assertRaises(RuntimeError):receipt.poll()
        self.assertTrue(receipt.cancel_event.is_set());self.assertIsNone(receipt.result)

class CapabilityTests(unittest.TestCase):
    def setUp(self):
        root=ROOT
        def load(name,path):
            spec=importlib.util.spec_from_file_location(name,(PROJECTION if path.startswith('PortalAI-Projection/') else ROOT).joinpath(*Path(path).parts[1:]))
            module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
        self.target=load('chat_target_reference','PortalAI-Projection/app/portalai_target.py')
        self.remote=load('chat_remote_reference','PortalAI/ControlCenter/remote_desktop_input.py')
        self.manager=self.target.Manager(root,types.SimpleNamespace())
        self.endpoint={'native_chat_protocol':1}
        self.manager.native_chat_endpoint=lambda *a,**kw:({'hwnd':100},self.endpoint)
    def test_manager_status_forwards_only_exact_capability(self):
        self.manager.inventory=lambda:{}
        with patch.dict(sys.modules,{'profile_shutdown':types.SimpleNamespace(_marker=lambda _:None)}):
            for version in (None,False,True,'1',2,1):
                self.endpoint['native_chat_attachment_protocol']=version
                self.assertEqual(self.manager.status().get('native_chat_attachment_protocol'),1 if type(version) is int and version==1 else None)
    def test_old_or_malformed_gui_capability_refused_before_http(self):
        payload={'viewer':'a'*32,'operation':'send','include_pending_attachments':True}
        with patch('http.client.HTTPConnection') as http:
            for version in (None,False,True,'1',2):
                self.endpoint['native_chat_attachment_protocol']=version
                with self.assertRaisesRegex(RuntimeError,'attachment_update_required'):
                    self.manager.native_chat(payload,time.monotonic()+5)
            http.assert_not_called()
    def test_gui_metadata_requires_updated_controller(self):
        saved=[]
        adapter=types.SimpleNamespace(app=object(),window_id=lambda _:100,path=Mock(),
            server=types.SimpleNamespace(server_port=12345),token='synthetic-test-only')
        policy=types.SimpleNamespace(atomic_json=lambda p,m:saved.append(m))
        linux=types.SimpleNamespace(identity=lambda _: {'start_ticks':1})
        with patch.dict(sys.modules,{'runtime_policy':policy,'linux_process':linux}):
            for version in (None,False,True,'1',2,1):
                adapter.native_chat=types.SimpleNamespace(attachment_protocol=version)
                self.remote.InputAdapter.publish_endpoint(adapter)
                self.assertEqual(saved[-1].get('native_chat_attachment_protocol'),1 if type(version) is int and version==1 else None)

if __name__=='__main__':unittest.main()
