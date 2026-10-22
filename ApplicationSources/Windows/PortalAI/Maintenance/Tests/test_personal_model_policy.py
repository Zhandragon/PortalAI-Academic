"""Real disposable accounts, encrypted restart/relocation, and hardware fixtures."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('Agent', 'ControlCenter', 'Maintenance/Tests')]
import local_accounts as accounts
import model_preferences as preferences
import runtime_policy as runtime
import effort_policy
import model_variants
import settings_page
from profile_runtime import ProfileRuntime
from profile_paths import private_path, capture, ProfileLocked
import test_effort_policy as effort_fixture

PASSWORD = 'Synthetic portable preferences password'


class PersonalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Portal settings fixture ')
        self.root = Path(self.temp.name)/'first'; self.root.mkdir()
        self.env = patch.dict(os.environ, {}, clear=False); self.env.start()
        os.environ.pop('PORTALAI_PROFILE_ID', None); os.environ.pop('PORTALAI_PROFILE_EPOCH', None)
        self.kdf = patch.object(accounts, '_KDF_N', 1024); self.kdf.start()
        (self.root/'Agent').mkdir()
        policy = runtime.load_policy(ROOT)
        policy.update(selection='auto', backend='auto', variant_preference='standard',
                      storage={'minimum_free_gib':1,'minimum_free_fraction':0.0001,'output_reserve_gib':1})
        runtime.atomic_json(self.root/'Agent/hardware_profiles.json', policy)
        self.original = (self.root/'Agent/hardware_profiles.json').read_bytes()
        self.backend = accounts.LocalAccounts(self.root)
        owner = self.backend.bootstrap('Owner', PASSWORD)
        self.backend.create_user(owner, 'Member', PASSWORD, admin_password=PASSWORD)
        self.backend.logout(owner)
        self.controllers = []; self.actor = None

    def tearDown(self):
        for controller in self.controllers:
            if controller._process_lock is not None:
                controller._process_lock.__exit__(None, None, None)
                controller._process_lock = None
        self.backend.logout(); self.kdf.stop(); self.env.stop(); self.temp.cleanup()

    def login(self, name='Member'):
        self.actor = self.backend.login(name, PASSWORD)
        self.controller = ProfileRuntime(self.root, self.backend, quiesce=lambda *_: {'stopped':True})
        self.controllers.append(self.controller)
        self.controller.prepare(self.actor)
        return self.actor

    def close(self):
        return self.controller.close(self.actor, writers_stopped=True)

    def save(self, **changes):
        values = settings_page.policy_values(runtime.load_effective_policy(self.root))
        values.update(changes)
        settings_page.save_settings(self.root, values, session=self.actor, scope='chat')

    def test_member_saves_privately_and_accounts_remain_independent(self):
        self.login(); self.save(variant_preference='uncensored', backend='cpu', context_tokens='4096')
        current = runtime.load_effective_policy(self.root)
        self.assertEqual(current['variant_preference'], 'uncensored')
        settings_page.save_settings(self.root, {'media_variant':'standard','voice_engine':'piper','text_video_engine':'sdcpp-cpu',
            'reference_video_profile':'vace13','music_engine':'musicgen-cpu'}, session=self.actor, scope='media')
        self.assertEqual(runtime.load_effective_policy(self.root)['media']['voice_engine'], 'piper')
        self.assertEqual(runtime.load_effective_policy(self.root)['variant_preference'], 'uncensored')
        with self.assertRaises(PermissionError):
            settings_page.save_storage_settings(self.root, {'minimum_free_gib':1}, session=self.actor)
        self.assertEqual((self.root/'Agent/hardware_profiles.json').read_bytes(), self.original)
        path = private_path(self.root, preferences.RELATIVE)
        first_identity = capture(self.root)
        self.assertTrue(self.close()['sealed']); self.assertFalse(path.exists())
        self.login('Owner')
        self.assertEqual(runtime.load_effective_policy(self.root)['variant_preference'], 'standard')
        self.save(context_tokens='2048'); self.close()
        self.login()
        self.assertNotEqual(capture(self.root), first_identity)
        current = runtime.load_effective_policy(self.root)
        self.assertEqual((current['variant_preference'],current['context_tokens'],current['media']['voice_engine']),
                         ('uncensored',4096,'piper'))
        self.assertEqual(current['media']['media_variant'], 'standard')
        self.assertEqual((current['media']['text_video_engine'],current['media']['reference_video_profile'],
                          current['media']['music_engine']),('sdcpp-cpu','vace13','musicgen-cpu'))
        self.close()

    def test_encrypted_settings_survive_root_relocation(self):
        self.login(); self.save(variant_preference='uncensored', context_tokens='4096')
        settings_page.save_settings(self.root, {'media_variant':'auto'}, session=self.actor, scope='media')
        uid = self.actor.user_id
        self.close(); self.backend.logout()
        moved = self.root.parent/'different machine drive'/ 'PortalAI'
        shutil.copytree(self.root, moved)
        self.root = moved; self.backend = accounts.LocalAccounts(moved)
        self.login()
        policy = runtime.load_effective_policy(moved)
        self.assertEqual(self.actor.user_id, uid)
        self.assertEqual((policy['selection'],policy['backend'],policy['variant_preference']),('auto','auto','uncensored'))
        self.assertEqual(policy['media']['media_variant'], 'auto')
        text = private_path(moved, preferences.RELATIVE).read_text()
        self.assertNotIn(str(moved),text); self.assertNotIn('first',text)
        self.close()

    def test_each_variant_toggle_survives_close_and_reopen_independently(self):
        self.login()
        for chat,media in (('standard','uncensored'),('uncensored','auto'),('uncensored','standard')):
            self.save(variant_preference=chat)
            settings_page.save_settings(self.root, {'media_variant':media}, session=self.actor, scope='media')
            self.assertTrue(self.close()['sealed']);self.login()
            restored=runtime.load_effective_policy(self.root)
            self.assertEqual((restored['variant_preference'],restored['media']['media_variant']),(chat,media))
        self.close()

    def test_locked_forged_and_revoked_sessions_cannot_save_or_read(self):
        with self.assertRaises(ProfileLocked):runtime.load_effective_policy(self.root)
        self.login()
        with self.assertRaises(PermissionError):
            settings_page.save_settings(self.root, {}, session={'role':'admin'}, scope='chat')
        old = self.actor; self.close()
        with self.assertRaises(PermissionError):
            settings_page.save_settings(self.root, {}, session=old, scope='chat')
        with self.assertRaises(ProfileLocked):runtime.load_effective_policy(self.root)

    def test_logout_during_atomic_publication_cannot_leave_new_plaintext(self):
        self.login(); original = preferences.os.replace
        def revoke(source, target):
            original(source, target)
            marker = self.root/'Private/active-session.json'
            state=json.loads(marker.read_text()); state['state']='closing'
            marker.write_text(json.dumps(state))
        with patch.object(preferences.os, 'replace', side_effect=revoke):
            with self.assertRaises(ProfileLocked):self.save(variant_preference='uncensored')
        workspace = self.root/'Private/Users'/self.actor.user_id/'Workspace'
        self.assertEqual(list(workspace.glob('Data/Settings/*.json')), [])
        self.assertEqual(list(workspace.glob('Data/Settings/*.tmp')), [])

    def test_personal_overrides_cannot_change_catalog_or_storage(self):
        self.login()
        for data in ({'storage':{}},{'models':[]},{'variant_preference':'invented'},{'context_tokens':True}):
            with self.assertRaises(ValueError):preferences.save(self.root,data)
        self.close()

    def test_guest_preferences_are_personal_and_persist(self):
        for reopening in (False, True):
            self.actor=self.backend.login_guest()
            self.controller=ProfileRuntime(self.root,self.backend,quiesce=lambda *_:{'stopped':True})
            self.controllers.append(self.controller);self.controller.prepare(self.actor)
            if not reopening:self.save(variant_preference='uncensored',context_tokens='2048')
            self.assertEqual(runtime.load_effective_policy(self.root)['variant_preference'],'uncensored')
            with self.assertRaises(PermissionError):
                settings_page.save_storage_settings(self.root,{},session=self.actor)
            self.close()

    def test_live_saved_images_refresh_in_existing_chat_and_real_child(self):
        import native_chat
        import media_policy
        from types import SimpleNamespace
        self.login()
        checkpoint = self.root/media_policy.SD15
        checkpoint.parent.mkdir(parents=True);checkpoint.write_bytes(b'synthetic checkpoint')
        # Real account/save/prompt/child transport; the child performs admission
        # with synthetic resources only, never inference or production login.
        child = ('import sys,os,json,argparse\nfrom pathlib import Path\n'
                 'sys.path.insert(0,'+repr(str(ROOT/'Agent'))+')\n'
                 'from media_policy import image_plan,GIB\n'
                 'p=argparse.ArgumentParser();p.add_argument("command");p.add_argument("--profile");'
                 'p.add_argument("--override-saved-profile",action="store_true");a,_=p.parse_known_args()\n'
                 'hw={"system":"Windows","gpus":[{"index":0,"backend":"cuda","free_bytes":23*GIB}],"ram_available_bytes":24*GIB}\n'
                 'print(json.dumps(image_plan(Path(__file__).resolve().parents[1],profile=a.profile,hardware=hw,'
                 'respect_saved_profile=os.environ.get("PORTALAI_CHAT_IMAGE_DEFAULTS")=="1" and not a.override_saved_profile)))\n')
        (self.root/'Agent/ai_tools.py').write_text(child,encoding='utf-8')
        with patch.object(native_chat,'bootstrap_python',return_value=ROOT/'Runtime/BootstrapPython/python.exe'):
            tool = native_chat.ToolRuntime(self.root,{'tool_timeout_seconds':30})
        tool.bind_account(self.actor)
        panel = SimpleNamespace(root=self.root,settings={'use_master_instructions':False},
                                store=SimpleNamespace(custom_instructions=lambda:''))
        for saved in ('flux','sd15','flux'):
            settings_page.save_settings(self.root,{'image_profile':saved,'image_engine':'auto','media_variant':'auto'},
                                        session=self.actor,scope='media')
            self.assertIn('image_profile='+saved,native_chat.NativeChat.system_prompt(panel))
            for stale in ('auto','sd15'):
                result = json.loads(tool.execute('generate_image',{'prompt':'synthetic cube','profile':stale}))
                self.assertEqual((result['profile'],result['selection_source']), (saved,'saved'))
        result = json.loads(tool.execute('generate_image',{'prompt':'synthetic cube','profile':'sd15','override_saved_profile':True}))
        self.assertEqual((result['profile'],result['selection_source']), ('sd15','explicit'))
        self.assertTrue(self.close()['sealed'])


class AutomaticVariantTests(unittest.TestCase):
    setUp = effort_fixture.EffortPolicyTests.setUp
    plan = effort_fixture.EffortPolicyTests.plan

    def test_preference_and_hardware_choose_large_small_and_low_ram(self):
        self.policy['variant_preference']='uncensored'
        self.assertEqual(self.plan('balanced')['selection'],'qwen4-abliterated-q4')
        self.backend.update(backend='cpu',gpu=None)
        self.assertEqual(self.plan('balanced')['selection'],'qwen4-abliterated-q4')
        self.hw['ram_available_bytes']=6*runtime.GIB
        self.assertEqual(self.plan('balanced')['selection'],'qwen1.7-abliterated-q8')
        self.assertEqual(self.plan('balanced')['context_tokens'],4096)

    def test_effort_and_explicit_overrides(self):
        self.policy['variant_preference']='uncensored'
        self.assertEqual(self.plan('fast')['selection'],'qwen1.7-abliterated-q8')
        self.assertEqual(self.plan('deep')['selection'],'qwen27-q4')
        self.policy['selection']='qwen4-q4'
        self.assertEqual(self.plan('fast')['selection'],'qwen4-q4')

    def test_missing_preferred_pair_falls_back_with_reason_but_explicit_fails(self):
        self.policy['variant_preference']='uncensored'
        for model in self.policy['models']:
            if model.get('variant')=='abliterated':(self.root/model['path']).unlink()
        plan=self.plan('balanced')
        self.assertEqual(plan['selection'],'qwen4-q4')
        self.assertIn('fallback',plan['model']['variant_reason'])
        self.policy['selection']='qwen4-abliterated-q4'
        with self.assertRaises(RuntimeError):self.plan('balanced')

    def test_cache_signature_includes_profile_and_preference(self):
        original=effort_policy.chat_policy_signature(self.policy)
        for extra in ({'variant_preference':'uncensored'},{'_profile_id':'synthetic-member'}):
            self.assertNotEqual(original,effort_policy.chat_policy_signature({**self.policy,**extra}))


class MediaPreferenceTests(unittest.TestCase):
    def test_chat_and_media_preferences_are_independent_including_old_settings(self):
        for chat in ('standard','uncensored'):
            for media in ('auto','standard','uncensored'):
                policy={'variant_preference':chat,'media':{'media_variant':media}}
                with patch.object(model_variants,'require_flux_alternate',return_value={}):
                    chosen,reason=model_variants.first_pass(ROOT,'flux-klein',policy=policy)
                self.assertEqual(chosen, 'uncensored' if media=='uncensored' else 'official')
                if media=='auto':self.assertIn('Nice chooses',reason)
        old=preferences.merge({'media':{'media_variant':'auto'}}, {'variant_preference':'uncensored'})
        self.assertEqual(model_variants.first_pass(ROOT,'flux-klein',policy=old)[0],'official')
        self.assertEqual(preferences.personal(old)['variant_preference'],'uncensored')
        for media in ('auto','standard','uncensored'):
            changed=preferences.merge(old, {'media':{'media_variant':media}})
            self.assertEqual(changed['variant_preference'],'uncensored')
            changed=preferences.merge(changed, {'variant_preference':'standard'})
            self.assertEqual(changed['media']['media_variant'],media)

    def test_default_standard_explicit_and_hardware_fallback(self):
        import ai_tools
        from types import SimpleNamespace
        policy={'variant_preference':'standard','media':{'media_variant':'uncensored'}}
        with patch.object(model_variants,'require_flux_alternate',side_effect=RuntimeError('needs 20 GiB')):
            variant, reason=model_variants.first_pass(ROOT,'flux-klein',policy=policy)
            self.assertEqual(variant,'official');self.assertIn('20 GiB',reason)
        with patch.object(model_variants,'require_flux_alternate',return_value={}):
            self.assertEqual(model_variants.first_pass(ROOT,'flux-klein',policy=policy)[0],'uncensored')
        with tempfile.TemporaryDirectory() as missing:
            self.assertEqual(model_variants.first_pass(Path(missing),'sd15',policy=policy)[0],'official')
        self.assertEqual(model_variants.first_pass(ROOT,'deterministic',policy=policy)[0],'official')
        with patch.object(model_variants,'first_pass',side_effect=AssertionError('explicit must not fall back')):
            self.assertEqual(ai_tools._default_variant(SimpleNamespace(uncensored=True,official=False),'sd15')[0],'uncensored')
            self.assertEqual(ai_tools._default_variant(SimpleNamespace(uncensored=False,official=True),'flux-klein')[0],'official')


if __name__ == '__main__':unittest.main()
