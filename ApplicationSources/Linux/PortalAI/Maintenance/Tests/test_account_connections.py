"""Synthetic accounts and service clients only; no owner records or live sends."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch,MagicMock

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent')]
import account_connections as connections
import account_setup as setup
import account_services as services
import mission_accounts
import local_accounts
from profile_runtime import ProfileRuntime
from profile_paths import private_path,UID_ENV,EPOCH_ENV
from runtime_policy import atomic_json,portable_env

PASSWORD='synthetic administrator passphrase'
TOKEN='gho_'+'s'*36
PROFILES={'github-test':{'backend':'github','enabled':True,'permissions':sorted(services.OPERATIONS & {x for x in services.OPERATIONS if x.startswith('github_')}),'login':'FixtureBot','account_id':42}}
SECRETS={'github-test':{'token':TOKEN}}


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        env=patch.dict(os.environ,{},clear=False);env.start();self.addCleanup(env.stop)
        for key in (UID_ENV,EPOCH_ENV,connections.ENV):os.environ.pop(key,None)
        work=patch.object(local_accounts,'_KDF_N',1024);work.start();self.addCleanup(work.stop)
        # Crypto dependencies remain the actual bundled, audited runtime.
        original=mission_accounts.activate
        crypto=patch.object(mission_accounts,'activate',lambda root=None:original(ROOT));crypto.start();self.addCleanup(crypto.stop)
        self.store=local_accounts.LocalAccounts(self.root);self.session=self.store.bootstrap('Owner',PASSWORD)
        self.runtime=ProfileRuntime(self.root,self.store,quiesce=lambda *_:{'stopped':True})
        self.runtime.prepare(self.session);self.addCleanup(self.cleanup_runtime)
        atomic_json(self.root/'Agent/hardware_profiles.json',{'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}})
        self.spec={'version':1,'id':'a'*32,'target_username':'Owner','objective':'Synthetic ordinary user objective',
                   'max_steps':12,'interval_seconds':3600,'max_runs':0,'autonomous_recovery':True,'sources':[{'kind':'synthetic'}]}

    def cleanup_runtime(self):
        if self.runtime.session is not None and self.runtime.session.active:self.runtime.close(self.runtime.session,writers_stopped=True)
        elif self.runtime._process_lock is not None:self.runtime._process_lock.__exit__(None,None,None)
        self.store.logout()

    def create(self):
        with patch('account_import.collect',return_value=(copy.deepcopy(PROFILES),copy.deepcopy(SECRETS))):
            return setup.apply(self.root,self.session,self.spec)

    def test_encrypted_import_normal_records_and_repeat_without_duplicates(self):
        result=self.create();again=self.create();self.assertEqual(result,again)
        raw=private_path(self.root,connections.RELATIVE).read_bytes();self.assertNotIn(TOKEN.encode(),raw)
        self.assertEqual(connections.read(self.root)['secrets'],SECRETS)
        mission=setup.Missions(self.root).load(result['mission_id']);schedule=setup.Schedules(self.root).load(result['schedule_id'])
        self.assertEqual(mission['objective'],self.spec['objective']);self.assertEqual(mission['steps'],0)
        self.assertEqual(schedule['source_mission'],mission['id']);self.assertFalse(schedule['enabled']);self.assertTrue(schedule['autonomous_recovery'])
        self.assertEqual(len(setup.Schedules(self.root).list()),1)
        self.assertNotIn(TOKEN,json.dumps(result));self.assertFalse(private_path(self.root,'Data/Missions/supervisor.json').exists())

    def test_lost_schedule_receipt_recovers_created_schedule(self):
        original=setup.Schedules.create
        def lost(instance,*args,**kwargs):original(instance,*args,**kwargs);raise OSError('synthetic lost receipt')
        with patch.object(setup.Schedules,'create',lost),self.assertRaises(OSError):self.create()
        result=self.create();self.assertEqual(len(setup.Schedules(self.root).list()),1)
        self.assertEqual(setup.Schedules(self.root).list()[0]['id'],result['schedule_id'])

    def test_changed_request_refuses_and_connections_not_overwritten(self):
        self.create();before=private_path(self.root,connections.RELATIVE).read_bytes()
        self.spec['objective']='different'
        with self.assertRaises(ValueError):self.create()
        self.assertEqual(before,private_path(self.root,connections.RELATIVE).read_bytes())

    def test_wrong_target_and_guest_or_forged_session_rejected(self):
        self.spec['target_username']='Other'
        with self.assertRaises(PermissionError):self.create()
        from types import SimpleNamespace
        fake=SimpleNamespace(active=True,role='admin',user_id=self.session.user_id,profile_key=self.session.profile_key,username='Owner')
        with self.assertRaises(PermissionError):connections.write(self.root,fake,connections.read(self.root))
        with self.assertRaises(PermissionError):setup.apply(self.root,fake,self.spec)

    def test_no_secret_in_profile_discovery_and_scope_denied(self):
        self.create();api=mission_accounts.Accounts(self.root)
        result=api.call({'mode':'full'},'', 'profiles')
        self.assertNotIn(TOKEN,json.dumps(result));self.assertIn('github_get',result['profiles'][0]['operations'])
        for mode in ('vm','observe'):
            with self.assertRaises(PermissionError):api.call({'mode':mode},'github-test','github_identity')

    def test_authentication_tamper_and_wrong_key_fail_closed(self):
        self.create();path=private_path(self.root,connections.RELATIVE);raw=path.read_bytes()
        with self.assertRaises(PermissionError):connections.read(self.root,key=b'X'*32)
        data=json.loads(raw);data['ciphertext']=base64.b64encode(b'changed').decode();atomic_json(path,data)
        with self.assertRaises(PermissionError):connections.read(self.root)
        path.write_bytes(raw)

    def test_lock_clears_worker_key_and_relogin_restores_ciphertext(self):
        self.create();old=mission_accounts.Accounts(self.root)
        self.assertNotIn(connections.ENV,portable_env(self.root,include_account_unlock=True))
        self.assertNotIn(connections.ENV,portable_env(self.root))
        self.assertNotIn(connections.ENV,os.environ)
        self.runtime.pause_hydration();self.assertNotIn(connections.ENV,os.environ)
        with self.assertRaises(PermissionError):old.profiles()
        self.runtime.close(self.session,writers_stopped=True)
        with self.assertRaises(PermissionError):old.profiles()
        self.session=self.store.login('Owner',PASSWORD);self.runtime.prepare(self.session)
        self.assertEqual(connections.read(self.root)['secrets'],SECRETS)
        with self.assertRaises(PermissionError):old.profiles()

    def test_effect_lost_reply_is_not_replayed(self):
        self.create();api=mission_accounts.Accounts(self.root);mission={'mode':'full','id':'b'*32,'steps':1}
        with patch.object(services,'call',side_effect=TimeoutError('synthetic secret '+TOKEN)) as call:
            for _ in range(2):
                with self.assertRaises(RuntimeError) as error:api.call(mission,'github-test','github_create_repo',{'name':'test'})
                self.assertNotIn(TOKEN,str(error.exception))
            self.assertEqual(call.call_count,1)

    def test_successful_effect_returns_original_receipt(self):
        self.create();api=mission_accounts.Accounts(self.root);mission={'mode':'full','id':'b'*32,'steps':1}
        with patch.object(services,'call',return_value={'id':42}) as call:
            a=api.call(mission,'github-test','github_create_repo',{'name':'test'})
            b=api.call(mission,'github-test','github_create_repo',{'name':'test'})
            self.assertEqual(a,b);call.assert_called_once()

    def test_github_bound_identity_host_and_owned_repo_checks(self):
        self.create();api=mission_accounts.Accounts(self.root);cfg=PROFILES['github-test']
        with patch.object(services,'request',return_value={'login':'Other','id':1}):
            with self.assertRaises(PermissionError):services.call(api,cfg,'github-test','github_identity',{},None)
        with patch.object(services,'request',return_value={'login':'FixtureBot','id':42}) as request:
            for path in ('https://evil.invalid','//evil.invalid','/repos/Other/secret','/repos/FixtureBot/../secret'):
                with self.assertRaises((ValueError,PermissionError)):services.call(api,cfg,'github-test','github_get',{'path':path},None)
            services.call(api,cfg,'github-test','github_create_repo',{'name':'sample'},None)
            self.assertTrue(request.call_args.args[-1]['private'])

    def test_tokens_never_sent_to_redirect_or_model_and_verification_preserved(self):
        with self.assertRaises(RuntimeError):services.NoRedirect().redirect_request(None,None,302,'Moved',{},'https://evil.invalid')
        value=connections.redact({'token':TOKEN,'verification_code':'moltbook_verify_abcd'},SECRETS)
        self.assertEqual(value['token'],'[redacted]');self.assertEqual(value['verification_code'],'moltbook_verify_abcd')

    def test_cross_connection_secret_publication_is_rejected_before_network(self):
        self.create();api=mission_accounts.Accounts(self.root)
        with patch.object(services.urllib.request,'build_opener') as network:
            with self.assertRaises(PermissionError):services.request(api,'github-test','github','POST','/user/repos',{'description':TOKEN})
            network.assert_not_called()

    def test_import_errors_do_not_expose_source_secrets(self):
        with patch('account_import.collect',side_effect=ValueError(TOKEN)),self.assertRaises(RuntimeError) as error:self.create_unmocked()
        self.assertNotIn(TOKEN,str(error.exception))
        self.assertFalse(private_path(self.root,connections.RELATIVE).exists())

    def create_unmocked(self):return setup.apply(self.root,self.session,self.spec)

    @unittest.skipUnless(os.name=='nt','Windows source migration')
    def test_dpapi_roundtrip_and_source_preservation(self):
        from account_import import dpapi_text
        path=self.root/'synthetic.dpapi'
        import ctypes
        from ctypes import wintypes
        class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
        raw='synthetic-credential-only'.encode('utf-16-le');buf=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
        incoming=Blob(len(raw),buf);out=Blob();crypt=ctypes.WinDLL('crypt32');kernel=ctypes.WinDLL('kernel32')
        crypt.CryptProtectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
        kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
        self.assertTrue(crypt.CryptProtectData(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(out)))
        try:path.write_text(ctypes.string_at(out.data,out.size).hex())
        finally:kernel.LocalFree(out.data)
        before=path.read_bytes()
        self.assertEqual(dpapi_text(path),'synthetic-credential-only');self.assertEqual(before,path.read_bytes())

    def test_password_change_preserves_connection_key_and_other_account_cannot_read(self):
        self.create();data=private_path(self.root,connections.RELATIVE).read_bytes()
        self.store.create_user(self.session,'Member','synthetic member passphrase',admin_password=PASSWORD)
        replacement=self.store.change_password(self.session,PASSWORD,'synthetic changed passphrase')
        self.runtime.replace_session(replacement);self.session=replacement
        self.assertEqual(connections.read(self.root)['secrets'],SECRETS)
        self.runtime.close(self.session,writers_stopped=True)
        member=self.store.login('Member','synthetic member passphrase');self.runtime.prepare(member);self.session=member
        private_path(self.root,connections.RELATIVE).parent.mkdir(parents=True,exist_ok=True)
        private_path(self.root,connections.RELATIVE).write_bytes(data)
        with self.assertRaises(PermissionError):connections.read(self.root)

    def test_real_guest_cannot_import_connections(self):
        self.runtime.close(self.session,writers_stopped=True)
        self.session=self.store.login_guest();self.runtime.prepare(self.session)
        with self.assertRaises(PermissionError):self.create()
        self.assertNotIn(connections.ENV,os.environ)

    def test_standard_account_cannot_bypass_missions_administrator_boundary(self):
        self.store.create_user(self.session,'Member','synthetic member passphrase',admin_password=PASSWORD)
        self.runtime.close(self.session,writers_stopped=True)
        self.session=self.store.login('Member','synthetic member passphrase');self.runtime.prepare(self.session)
        self.spec['target_username']='Member'
        with self.assertRaisesRegex(PermissionError,'administrator'):self.create()
        self.assertEqual(setup.Schedules(self.root).list(),[])
        self.assertFalse(private_path(self.root,connections.RELATIVE).exists())

    def test_known_verification_failure_is_not_a_success_receipt(self):
        self.create();api=mission_accounts.Accounts(self.root)
        cfg={'backend':'moltbook'}
        with patch.object(services,'request',return_value={'success':False,'error':'Incorrect answer'}) as request:
            result=services.call(api,cfg,'github-test','moltbook_verify',{'verification_code':'moltbook_verify_fixture','answer':'15.00'},None)
        self.assertFalse(result['result']['success'])

    def test_network_pins_tls_host_and_strips_remote_secret_echo(self):
        self.create();api=mission_accounts.Accounts(self.root)
        response=MagicMock();response.__enter__.return_value=response;response.read.return_value=json.dumps({'echo':TOKEN}).encode()
        opener=MagicMock();opener.open.return_value=response
        with patch.object(services.urllib.request,'build_opener',return_value=opener):
            value=services.request(api,'github-test','github','GET','/user')
        req=opener.open.call_args.args[0]
        self.assertEqual(req.full_url,'https://api.github.com/user');self.assertEqual(req.get_header('Authorization'),'Bearer '+TOKEN)
        self.assertEqual(value['echo'],'[redacted]')

    def test_rate_limit_persists_cooldown_and_does_not_repeat_request(self):
        self.create();api=mission_accounts.Accounts(self.root)
        opener=MagicMock();opener.open.side_effect=services.urllib.error.HTTPError('https://api.github.com/user',429,'rate limit',{'Retry-After':'90'},None)
        with patch.object(services.urllib.request,'build_opener',return_value=opener):
            for _ in range(2):
                with self.assertRaises(RuntimeError):services.request(api,'github-test','github','GET','/user')
        self.assertEqual(opener.open.call_count,1)

    def test_autonomous_recovery_classifies_only_known_read_only_connections(self):
        from mission_recovery import read_only
        for op in ('profiles','github_get','github_identity','email_read','wallet_balance','moltbook_home'):
            self.assertTrue(read_only({'action':'account','operation':op}))
        for op in ('github_put_file','github_create_pr','email_send','wallet_send','moltbook_comment','moltbook_verify','unknown'):
            self.assertFalse(read_only({'action':'account','operation':op}))

    def test_account_worker_receives_key_only_through_pipe_and_opens_encrypted_connection(self):
        self.create();env=portable_env(self.root,include_account_unlock=True)
        self.assertNotIn(self.session.profile_key.hex(),json.dumps(env))
        self.assertNotIn(base64.b64encode(connections.current_key(self.root,connections.capture(self.root))).decode(),json.dumps(env))
        script="import sys,json,os;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import account_connections as c;c.receive_worker_input(Path(sys.argv[3]));assert c.ENV not in os.environ;import mission_accounts as m;original=m.activate;m.activate=lambda root:original(Path(sys.argv[2]));print(json.dumps(m.Accounts(Path(sys.argv[3])).call({'mode':'full'},'','profiles')))"
        process=connections.start_account_process([sys.executable,'-B','-I','-c',script,str(ROOT/'Agent'),str(ROOT),str(self.root)],self.root,
            env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output,error=process.communicate(timeout=20)
        self.assertEqual(process.returncode,0,error);self.assertNotIn(TOKEN.encode(),output)
        self.assertEqual(json.loads(output)['profiles'][0]['name'],'github-test')

    def test_supervisor_can_forward_key_to_worker_without_environment_secret(self):
        self.create()
        worker="import sys,json,os;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import account_connections as c;c.receive_worker_input(Path(sys.argv[2]));print(json.dumps({'unlocked':c.unlocked(Path(sys.argv[2])),'environment_key':c.ENV in os.environ}))"
        supervisor="import sys,subprocess;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import account_connections as c;r=Path(sys.argv[2]);c.receive_worker_input(r);p=c.start_account_process([sys.executable,'-B','-I','-c',sys.argv[3],sys.argv[1],str(r)],r,stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));out,err=p.communicate(timeout=10);sys.stdout.buffer.write(out);sys.exit(p.returncode)"
        process=connections.start_account_process([sys.executable,'-B','-I','-c',supervisor,str(ROOT/'Agent'),str(self.root),worker],self.root,
            env=portable_env(self.root),stdout=subprocess.PIPE,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        output,error=process.communicate(timeout=20)
        self.assertEqual(process.returncode,0,error);self.assertEqual(json.loads(output),{'unlocked':True,'environment_key':False})

    def test_failed_pipe_terminates_its_child_without_disclosing_packet(self):
        self.create();process=MagicMock();process.stdin.write.side_effect=BrokenPipeError('synthetic')
        with patch.object(connections.subprocess,'Popen',return_value=process),self.assertRaisesRegex(RuntimeError,'startup pipe failed'):
            connections.start_account_process(['synthetic-worker'],self.root)
        process.terminate.assert_called_once();process.wait.assert_called_once()


if __name__=='__main__':unittest.main()
