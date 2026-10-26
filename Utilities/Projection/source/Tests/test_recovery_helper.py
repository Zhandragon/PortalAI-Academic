"""Recovery tests use generated keys, fake launches and disposable roots only."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'app'),str(MODULE/'Runtime/packages'),str(MODULE.parent.parent/'PortalAI/Agent')]
import profile_shutdown
import portalai_target
from connection_vault import new_connection,public_pairing
from recovery_transport import RecoveryClient,pairing_request
from recovery_runtime import LaunchController,RecoveryRunner
spec=importlib.util.spec_from_file_location('recovery_receiver',MODULE/'RecoveryHelper/ha/custom_components/portalai_recovery/receiver.py')
receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.now=100.;self.connection=new_connection('https://example.invalid','../../PortalAI','Synthetic recovery')
        self.identity,entry=receiver.pairing(pairing_request(self.connection))
        self.hub=receiver.Receiver({self.identity:entry},clock=lambda:self.now)
        self.client=RecoveryClient(self.connection,MODULE/'Runtime/cacert.pem');self.client.request=self.dispatch
    def tearDown(self):self.client.close()
    def dispatch(self,value):
        if value['action']=='challenge':return self.hub.challenge(value['device_id'])
        if value['action']=='authenticate':return self.hub.authenticate(value)
        return self.hub.poll(self.client.session,value)
    def connect(self):self.client.authenticate();self.client.poll('idle',[])
    def test_projection_pairing_does_not_silently_grant_recovery(self):
        with self.assertRaises(ValueError):receiver.pairing(public_pairing(self.connection))
    def test_public_pairing_has_no_private_key_destination_or_password(self):
        value=pairing_request(self.connection)
        self.assertNotIn('private_key',value);self.assertNotIn('url',value);self.assertNotIn('target',value)
        self.assertEqual(value['capabilities'],['recover_apps'])
    def test_signature_requires_recovery_domain(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        nonce=self.hub.challenge(self.identity)['challenge']
        signed=self.client.key.sign(('PortalAI-Projection-v1:'+self.identity+':'+nonce).encode(),ec.ECDSA(hashes.SHA256()))
        with self.assertRaises(Exception):self.hub.authenticate({'action':'authenticate','device_id':self.identity,'challenge':nonce,'signature':base64.b64encode(signed).decode()})
    def test_authentication_and_poll_replay_are_refused(self):
        captured=[];original=self.dispatch
        self.client.request=lambda value:(captured.append(value.copy()),original(value))[1]
        self.connect()
        with self.assertRaises(PermissionError):self.hub.authenticate(captured[1])
        with self.assertRaises(PermissionError):self.hub.poll(self.client.session,captured[2])
    def test_expired_and_unapproved_helpers_cannot_receive_commands(self):
        with self.assertRaises(PermissionError):self.hub.challenge('f'*32)
        self.connect();self.now+=16
        with self.assertRaises(RuntimeError):self.hub.enqueue(self.identity)
        self.now+=60
        with self.assertRaises(PermissionError):self.client.poll('idle',[])
    def test_only_one_explicit_recovery_is_dispatched_once(self):
        self.connect();key=self.hub.enqueue(self.identity)
        with self.assertRaises(RuntimeError):self.hub.enqueue(self.identity)
        commands=self.client.poll('idle',[])
        self.assertEqual([item['id'] for item in commands],[key])
        self.assertEqual(self.client.poll('recovering',[]),[])
        self.client.poll('launch_requested',[{'id':key,'outcome':'launch_requested'}])
        self.assertEqual(self.hub.devices[self.identity]['reply']['id'],key)
        self.assertIsNone(self.hub.devices[self.identity]['pending'])
    def test_uncertain_delivered_action_is_not_cancelled_or_replayed(self):
        self.connect();key=self.hub.enqueue(self.identity);self.client.poll('idle',[])
        self.hub.cancel_undelivered(self.identity,key)
        with self.assertRaises(RuntimeError):self.hub.enqueue(self.identity)
        self.assertEqual(self.client.poll('idle',[]),[])
    def test_expired_queued_command_is_dropped(self):
        self.connect();self.hub.enqueue(self.identity);self.now+=31
        self.assertEqual(self.client.poll('idle',[]),[])
    def test_reauthentication_drops_old_queue_and_session(self):
        self.connect();old=self.client.session;self.hub.enqueue(self.identity);self.now+=3
        self.client.authenticate();self.assertNotIn(old,self.hub.sessions)
        self.assertEqual(self.client.poll('idle',[]),[])
    def test_revocation_closes_existing_session(self):
        self.connect();self.hub.revoke(self.identity)
        with self.assertRaises(PermissionError):self.client.poll('idle',[])
    def test_remote_shell_kill_restart_and_account_unlock_are_not_capabilities(self):
        self.connect()
        for action in ('shell','restart','force_shutdown','unlock','call_service','reboot'):
            with self.subTest(action=action),self.assertRaises(ValueError):self.hub.enqueue(self.identity,action)
    def test_malformed_full_batch_is_rejected_before_execution(self):
        valid={'id':'a'*32,'action':'recover','ttl':2}
        for commands in ([valid,valid],[{**valid,'payload':{'shell':'x'}}],[{**valid,'ttl':float('nan')}],[{**valid,'action':'kill'}]):
            self.client.request=lambda body:{'commands':commands}
            with self.assertRaises(ValueError):self.client.poll('idle',[])
    def test_forged_reply_does_not_clear_pending_operation(self):
        self.connect();key=self.hub.enqueue(self.identity);self.client.poll('idle',[])
        self.client.poll('idle',[{'id':'f'*32,'outcome':'launch_requested'}])
        self.assertEqual(self.hub.devices[self.identity]['pending']['id'],key)
    def test_malformed_poll_does_not_advance_sequence(self):
        self.connect();seq=self.hub.sessions[self.client.session]['sequence']
        with self.assertRaises(ValueError):self.hub.poll(self.client.session,{'action':'poll','sequence':seq+1,'status':'idle','replies':[{'id':'a'*32,'outcome':'arbitrary secret'}]})
        self.assertEqual(self.hub.sessions[self.client.session]['sequence'],seq)
    def test_real_https_uses_scoped_endpoint_without_ha_credentials(self):
        import datetime,ipaddress,ssl
        from http.server import HTTPServer,BaseHTTPRequestHandler
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder:
            folder=Path(folder);key=ec.generate_private_key(ec.SECP256R1())
            name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Synthetic recovery')]);now=datetime.datetime.now(datetime.timezone.utc)
            cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(1).not_valid_before(now-datetime.timedelta(minutes=1)).not_valid_after(now+datetime.timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True,path_length=None),True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),False).sign(key,hashes.SHA256())
            crt=folder/'ca.pem';private=folder/'key.pem';crt.write_bytes(cert.public_bytes(serialization.Encoding.PEM));private.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
            context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(crt,private);test=self;headers=[]
            class Handler(BaseHTTPRequestHandler):
                def log_message(self,*_):pass
                def do_POST(self):
                    test.assertEqual(self.path,'/api/portalai_recovery/v1');headers.append(dict(self.headers))
                    body=json.loads(self.rfile.read(int(self.headers['Content-Length'])));result=test.dispatch(body)
                    data=json.dumps(result).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            server=HTTPServer(('127.0.0.1',0),Handler);server.socket=context.wrap_socket(server.socket,server_side=True)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            self.client=RecoveryClient({**self.connection,'url':f'https://127.0.0.1:{server.server_port}'},crt)
            try:
                self.connect();request=self.hub.enqueue(self.identity)
                self.assertEqual(self.client.poll('idle',[])[0]['id'],request)
                self.client.poll('launch_requested',[{'id':request,'outcome':'launch_requested'}])
            finally:self.client.close();server.shutdown();server.server_close();thread.join(3)
            self.assertTrue(headers)
            self.assertTrue(all('Authorization' not in row and 'Cookie' not in row for row in headers))
            self.assertIn('X-PortalAI-Recovery-Session',headers[-1])

class Child:
    def __init__(self):self.stdin=io.StringIO();self.code=None;self.terminated=False
    def poll(self):return self.code
    def wait(self,timeout):self.code=0;return 0
    def terminate(self):self.terminated=True;self.code=-1

class LaunchTests(unittest.TestCase):
    def setUp(self):
        base=MODULE/'Tests/Validation';base.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.base=Path(self.temp.name)
        self.module=self.base/'Projection';self.root=self.base/'PortalAI';self.stop=threading.Event()
        for path in (self.module/'Runtime/Python/pythonw.exe',self.module/'Runtime/Python/python312.dll',self.module/'app/projection_worker.py',
                     self.root/'PortalAI.exe',self.root/'ControlCenter/control_center_bootstrap.py',self.root/'Agent/profile_shutdown.py'):
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'synthetic executable fixture, never execute')
        self.connection=new_connection('https://example.invalid','../PortalAI','Synthetic')
        self.manager=Mock();self.manager.owned.return_value={};self.snapshot=Mock(return_value={})
        self.children=[]
        def spawn(*args,**kwargs):child=Child();self.children.append(child);return child
        self.spawn=Mock(side_effect=spawn);self.original_root=getattr(portalai_target,'ROOT',None)
        self.controller=LaunchController(self.connection,self.stop,module=self.module,manager=self.manager,snapshot=self.snapshot,
            popen=self.spawn,clock=lambda:100.,scope=self.module/'state/input/synthetic')
    def tearDown(self):
        self.controller.close()
        if self.original_root is not None:portalai_target.ROOT=self.original_root
        self.temp.cleanup()
    def gui(self):
        return {'executable':str(self.root/'Runtime/BootstrapPython/pythonw.exe'),'argv':['pythonw.exe','-B','-I',str(self.root/'ControlCenter/control_center_bootstrap.py')]}
    def projection(self):
        exe=str(self.module/'Runtime/Python/pythonw.exe')
        return {'executable':exe,'argv':[exe,'-B','-I',str(self.module/'app/projection_worker.py')]}
    def test_both_crashed_launch_worker_and_normal_login_with_private_pipe_only(self):
        with patch.dict('os.environ',{'PORTALAI_ACCOUNT_UNLOCK':'never inherit','PORTALAI_PROFILE_EPOCH':'old'}):
            self.assertEqual(self.controller.recover(130.),'launch_requested')
        self.assertEqual(self.spawn.call_count,2)
        worker,main=self.spawn.call_args_list
        self.assertIn(self.connection['private_key'],json.loads(self.children[0].stdin.getvalue())['private_key'])
        for call in (worker,main):
            self.assertNotIn('PORTALAI_ACCOUNT_UNLOCK',call.kwargs['env']);self.assertNotIn('PORTALAI_PROFILE_EPOCH',call.kwargs['env'])
            self.assertNotIn('PRIVATE KEY',str(call.args));self.assertFalse(call.kwargs.get('shell',False))
        self.assertEqual(main.args[0],[str(self.root/'PortalAI.exe')])
    def test_existing_worker_and_gui_are_not_restarted(self):
        self.snapshot.return_value={1:self.projection(),2:self.gui()}
        self.assertEqual(self.controller.recover(130.),'already_running');self.spawn.assert_not_called()
    def test_projection_can_return_while_leftover_model_requires_explicit_review(self):
        self.manager.owned.return_value={3:{'executable':'synthetic model'}}
        self.assertEqual(self.controller.recover(130.),'projection_restored_review_workers')
        self.assertEqual(self.spawn.call_count,1)
    def test_closing_profile_is_not_reopened(self):
        with patch.object(profile_shutdown,'_marker',return_value={'state':'closing'}):
            self.assertEqual(self.controller.recover(130.),'projection_restored_review_workers')
        self.assertEqual(self.spawn.call_count,1)
    def test_unsealed_profile_without_workers_gets_only_the_normal_login(self):
        with patch.object(profile_shutdown,'_marker',return_value={'state':'open','epoch':'synthetic'}):
            self.assertEqual(self.controller.recover(130.),'launch_requested')
        self.assertEqual(self.spawn.call_args.args[0],[str(self.root/'PortalAI.exe')])
    def test_expired_or_disarmed_request_cannot_launch(self):
        with self.assertRaises(TimeoutError):self.controller.recover(99.)
        self.stop.set()
        with self.assertRaises(TimeoutError):self.controller.recover(130.)
        self.spawn.assert_not_called()
    def test_disarm_during_slow_inventory_prevents_late_launch(self):
        self.snapshot.side_effect=lambda:(self.stop.set(),{})[1]
        with self.assertRaises(TimeoutError):self.controller.recover(130.)
        self.spawn.assert_not_called()
    def test_new_stop_timestamp_prevents_late_launch(self):
        def inventory():
            path=self.root/'Agent/.runtime/qwen_last_stop.json';path.parent.mkdir();path.write_text('{"stopped_at":1}')
            return {}
        self.snapshot.side_effect=inventory
        with self.assertRaises(RuntimeError):self.controller.recover(130.)
        self.spawn.assert_not_called()
    def test_source_change_or_missing_drive_refuses_launch(self):
        (self.module/'app/projection_worker.py').write_text('changed')
        with self.assertRaises(ValueError):self.controller.recover(130.)
        self.spawn.assert_not_called()
    def test_uncertain_companion_identity_is_not_assumed_absent(self):
        self.snapshot.return_value={1:{'executable':str(self.module/'Runtime/Python/pythonw.exe'),'argv':[]}}
        with self.assertRaises(RuntimeError):self.controller.recover(130.)
        self.spawn.assert_not_called()
    def test_repeated_request_does_not_duplicate_tracked_inflight_launch(self):
        self.controller.recover(130.);self.controller.recover(130.)
        self.assertEqual(self.spawn.call_count,2)
    def test_disarm_only_closes_its_own_projection_child(self):
        self.controller.recover(130.);worker,main=self.children
        self.controller.close();self.assertEqual(worker.code,0);self.assertIsNone(main.code)
        self.assertFalse(main.terminated);self.assertEqual(self.controller.connection,{})
    def test_cleanup_failure_retains_exact_handle_for_explicit_retry(self):
        self.controller.recover(130.);worker=self.children[0];original=worker.wait
        worker.wait=Mock(side_effect=OSError('synthetic handle failure'))
        with self.assertRaises(OSError):self.controller.close()
        self.assertIs(self.controller.worker,worker);worker.wait=original;self.controller.close()
        self.assertIsNone(self.controller.worker)
    def test_separate_helper_survives_disposable_app_exits_and_launches_real_fixture_children(self):
        import recovery_runtime
        from contextlib import ExitStack
        script=self.base/'child.py'
        script.write_text('import json,sys,time\nfrom pathlib import Path\nmode=sys.argv[1]\nif mode=="worker":\n json.loads(sys.stdin.readline(32769))\nPath(sys.argv[2]).write_text("started")\nif mode=="worker":\n for line in sys.stdin: pass\nelse: time.sleep(60)\n')
        runtime=MODULE/'Runtime/Python/python.exe';children=[];originals=[]
        def launch(command,**kwargs):
            mode='worker' if len(command)>1 else 'main'
            child=subprocess.Popen([str(runtime),'-B','-I',str(script),mode,str(self.base/(mode+'.ready'))],**kwargs)
            children.append(child);return child
        self.controller.popen=launch
        key_id,entry=receiver.pairing(pairing_request(self.connection));hub=receiver.Receiver({key_id:entry})
        def client_factory(connection,_ca):
            client=RecoveryClient(connection,MODULE/'Runtime/cacert.pem')
            def request(body):
                if body['action']=='challenge':return hub.challenge(body['device_id'])
                if body['action']=='authenticate':return hub.authenticate(body)
                return hub.poll(client.session,body)
            client.request=request;return client
        notify=Mock();runner=RecoveryRunner(self.connection,notify,
            controller_factory=lambda connection,stop:self.controller,client_factory=client_factory)
        self.controller.stop=runner.stop
        try:
            for _ in range(2):originals.append(subprocess.Popen([str(runtime),'-B','-I','-c','import time; time.sleep(60)'],creationflags=subprocess.CREATE_NO_WINDOW))
            with ExitStack() as stack:
                stack.enter_context(patch.object(recovery_runtime,'MODULE',self.module))
                stack.enter_context(patch.object(recovery_runtime,'resolve_target',return_value=self.root))
                runner.start();deadline=time.monotonic()+10
                while key_id not in hub.devices or hub.devices[key_id]['updated'] is None:
                    if time.monotonic()>deadline:self.fail('Synthetic helper did not connect')
                    time.sleep(.02)
                for child in originals:child.terminate();child.wait(timeout=5)
                self.assertTrue(runner.thread.is_alive())
                request=hub.enqueue(key_id)
                while not hub.devices[key_id]['reply']:
                    if time.monotonic()>deadline:self.fail('Synthetic recovery did not complete')
                    time.sleep(.02)
                self.assertEqual(hub.devices[key_id]['reply'],{'id':request,'outcome':'launch_requested'})
                self.assertTrue((self.base/'worker.ready').is_file());self.assertTrue((self.base/'main.ready').is_file())
                runner.disarm();runner.thread.join(15);self.assertFalse(runner.thread.is_alive())
                self.assertIsNotNone(children[0].poll());self.assertIsNone(children[1].poll())
        finally:
            runner.disarm()
            if runner.thread is not None:runner.thread.join(15)
            for child in originals+children:
                if child.poll() is None:child.terminate()
                child.wait(timeout=5)

class RunnerTests(unittest.TestCase):
    def test_disarmed_runner_never_calls_controller(self):
        runner=RecoveryRunner({},Mock());runner.disarm();controller=Mock()
        runner.execute({'id':'a'*32,'deadline':time.monotonic()+10},controller)
        controller.recover.assert_not_called();self.assertEqual(runner.state,'refused_or_uncertain')
    def test_uncertain_exception_is_not_retried_and_does_not_log_private_text(self):
        notify=Mock();runner=RecoveryRunner({},notify);controller=Mock()
        controller.recover.side_effect=OSError('synthetic private payload')
        runner.execute({'id':'a'*32,'deadline':time.monotonic()+10},controller)
        controller.recover.assert_called_once();notify.assert_called_once_with('refused_or_uncertain')
    def test_cleanup_failure_is_reported_without_disarmed_success(self):
        notify=Mock();runner=RecoveryRunner({},notify);runner.controller=Mock()
        runner.controller.close.side_effect=OSError('synthetic cleanup failure');runner.finish()
        self.assertTrue(runner.cleanup_failed);notify.assert_called_once_with('shutdown_failed')

class GuiTests(unittest.TestCase):
    def test_real_tk_arm_disarm_keeps_password_out_of_display_and_waits_for_cleanup(self):
        import tkinter as tk
        import recovery_ui
        from connection_vault import save
        with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder:
            module=Path(folder);(module/'Connections').mkdir()
            connection=new_connection('https://example.invalid','../PortalAI','Synthetic recovery')
            path=module/'Connections/synthetic.enc';save(path,connection,'Synthetic-recovery-password')
            runner=Mock();runner.cleanup_failed=False;runner.thread.is_alive.return_value=True
            app=tk.Tk();app.withdraw()
            try:
                with patch.object(recovery_ui,'MODULE',module),patch.object(recovery_ui,'target_valid',return_value=True),patch.object(recovery_ui,'RecoveryRunner',return_value=runner):
                    window=recovery_ui.Window(app);window.path.set(str(path));window.password.set('Synthetic-recovery-password');window.arm()
                    runner.start.assert_called_once();self.assertEqual(window.password.get(),'')
                    displayed=window.text.get('1.0','end')
                    self.assertNotIn('PRIVATE KEY',displayed);self.assertNotIn('Synthetic-recovery-password',displayed)
                    self.assertIn('portalai_recovery.recover_apps',displayed)
                    window.close();runner.disarm.assert_called_once();window.tick();self.assertTrue(app.winfo_exists())
                    runner.thread.is_alive.return_value=False;runner.cleanup_failed=True
                    window.tick();self.assertTrue(app.winfo_exists())
                    runner.cleanup_failed=False;window.tick()
            finally:
                try:app.destroy()
                except tk.TclError:pass

if __name__=='__main__':unittest.main()
