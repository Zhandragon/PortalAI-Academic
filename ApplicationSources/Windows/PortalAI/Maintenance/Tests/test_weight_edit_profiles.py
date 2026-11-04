"""Exact profile round trips, original routing and bounded cache ownership."""
import hashlib,json,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Tools/WeightSpace'),str(ROOT/'Agent')]
from quantized_edit import Quantizer,gguf,np,materialize,projection,sha
from edit_profiles import export_profile,prepare_profile,clear_prepared
from weight_edit_profiles import home,catalog,resolve_model,identity,read_manifest

class WeightEditProfilesTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'Maintenance');self.root=Path(self.temp.name)
        folder=self.root/'LLM/models';folder.mkdir(parents=True);self.model=folder/'standard.gguf'
        values=np.random.default_rng(64).normal(0,.1,(32,512)).astype(np.float32)
        packed=Quantizer().blocks(values,gguf.GGMLQuantizationType.Q8_0).reshape(32,-1)
        writer=gguf.GGUFWriter(str(self.model),arch='qwen3');writer.add_tensor('blk.0.ffn_down.weight',packed,raw_dtype=gguf.GGMLQuantizationType.Q8_0)
        writer.add_tensor('output_norm.weight',np.ones(32,dtype=np.float32));writer.write_header_to_file();writer.write_kv_data_to_file();writer.write_tensors_to_file();writer.close()
        u=np.ones(32,dtype=np.float32);u/=np.linalg.norm(u)
        self.recipe={'method':'sparse-projection-subtraction-v1','base_sha256':sha(self.model),'dose':.5,'sites':[projection(self.model,'blk.0.ffn_down.weight',u,columns=8)]}
        self.original=self.model.read_bytes();self.candidate=self.root/'source-candidate.gguf';materialize(self.model,self.recipe,self.candidate)
        self.profile=export_profile(self.root,self.model,self.candidate,self.recipe,label='Synthetic test')
        self.identifier=self.profile['id']
    def tearDown(self):self.temp.cleanup()
    def base(self):return {'id':'test-standard','absolute_path':str(self.model),'variant':'standard'}
    def test_exact_round_trip_and_original_is_preserved(self):
        result=prepare_profile(self.root,self.model,self.identifier)
        self.assertEqual(Path(result['candidate']).read_bytes(),self.candidate.read_bytes())
        self.assertEqual(self.model.read_bytes(),self.original)
        resolved=resolve_model(self.root,self.base(),{'weight_edit_profile':self.identifier})
        self.assertEqual(resolved['candidate_sha256'],sha(self.candidate))
        self.assertEqual(resolve_model(self.root,self.base(),{'weight_edit_profile':'original'}),self.base())
    def test_catalog_is_explicitly_experimental(self):
        row=catalog(self.root)[0];self.assertEqual(row['status'],'experimental');self.assertFalse(row['automatic_retry_eligible']);self.assertFalse(row['prepared'])
    def test_damaged_catalog_card_does_not_break_settings(self):
        card=home(self.root)/'Profiles'/(self.identifier+'.profile.json');card.write_text('[]')
        self.assertEqual(catalog(self.root),[])
    def test_preparation_reuses_verified_unchanged_copy(self):
        prepare_profile(self.root,self.model,self.identifier)
        with mock.patch('edit_profiles.sha',side_effect=AssertionError('Must not rehash an unchanged large model')):
            self.assertTrue(prepare_profile(self.root,self.model,self.identifier)['cached'])
    def test_wrong_variant_uses_its_own_original(self):
        other={**self.base(),'absolute_path':str(self.model.with_name('uncensored.gguf')),'variant':'uncensored'}
        result=resolve_model(self.root,other,{'weight_edit_profile':self.identifier})
        self.assertEqual(result['absolute_path'],other['absolute_path']);self.assertNotIn('candidate_sha256',result)
    def test_unprepared_profile_refuses_loading(self):
        with self.assertRaises(RuntimeError):resolve_model(self.root,self.base(),{'weight_edit_profile':self.identifier})
    def test_tampered_prepared_file_refuses_loading(self):
        result=prepare_profile(self.root,self.model,self.identifier);path=Path(result['candidate'])
        with path.open('ab') as stream:stream.write(b'x')
        with self.assertRaises(RuntimeError):resolve_model(self.root,self.base(),{'weight_edit_profile':self.identifier})
        with self.assertRaises(RuntimeError):clear_prepared(self.root,self.identifier)
    def test_wrong_base_refuses_and_original_stays_unchanged(self):
        with self.model.open('ab') as stream:stream.write(b'x')
        before=self.model.read_bytes()
        with self.assertRaises(ValueError):prepare_profile(self.root,self.model,self.identifier)
        self.assertEqual(self.model.read_bytes(),before)
    def test_loaded_copy_cannot_be_removed(self):
        result=prepare_profile(self.root,self.model,self.identifier)
        with self.assertRaises(RuntimeError):clear_prepared(self.root,self.identifier,in_use=[result['candidate']])
        self.assertTrue(Path(result['candidate']).exists())
    def test_clear_removes_only_known_prepared_copy(self):
        prepare_profile(self.root,self.model,self.identifier);self.assertTrue(clear_prepared(self.root,self.identifier))
        self.assertTrue((home(self.root)/'Profiles'/(self.identifier+'.wsedit')).exists())
        self.assertEqual(self.model.read_bytes(),self.original)
    def test_unknown_cache_file_stops_cleanup(self):
        result=prepare_profile(self.root,self.model,self.identifier);p=Path(result['candidate']).parent/'user-file.txt';p.write_text('keep')
        with self.assertRaises(RuntimeError):clear_prepared(self.root,self.identifier)
        self.assertEqual(p.read_text(),'keep')
    def test_profile_id_escape_refused(self):
        with self.assertRaises(ValueError):prepare_profile(self.root,self.model,'../outside')
        with self.assertRaises(ValueError):clear_prepared(self.root,'../outside')
    def test_receipt_mismatch_refused(self):
        path=self.candidate.with_suffix('.edit.json');data=json.loads(path.read_text());data['candidate_sha256']='0'*64;path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):export_profile(self.root,self.model,self.candidate,self.recipe,label='Bad candidate')
    def test_profile_setting_is_in_model_signature(self):
        from model_preferences import validate,personal
        from effort_policy import chat_policy_signature
        self.assertEqual(personal({})['weight_edit_profile'],'original')
        self.assertEqual(validate({'weight_edit_profile':self.identifier})['weight_edit_profile'],self.identifier)
        self.assertNotEqual(chat_policy_signature({}),chat_policy_signature({'weight_edit_profile':self.identifier}))
        with self.assertRaises(ValueError):validate({'weight_edit_profile':'../bad'})
    def more_profile(self,dose):
        recipe={**self.recipe,'dose':dose};candidate=self.root/('candidate-'+str(dose)+'.gguf')
        materialize(self.model,recipe,candidate)
        return export_profile(self.root,self.model,candidate,recipe,label='Dose '+str(dose))['id']
    def test_two_copy_limit_keeps_loaded_copy_and_compact_profiles(self):
        first=prepare_profile(self.root,self.model,self.identifier)
        second=self.more_profile(1);prepare_profile(self.root,self.model,second)
        third=self.more_profile(2);prepare_profile(self.root,self.model,third,in_use=[first['candidate']])
        self.assertEqual({p.name for p in (home(self.root)/'Prepared').iterdir()},{self.identifier,third})
        self.assertEqual(len(catalog(self.root)),3)
        self.assertEqual(self.model.read_bytes(),self.original)
    def test_interrupted_copy_is_preserved_and_cannot_be_loaded_or_overwritten(self):
        folder=home(self.root)/'Prepared'/self.identifier;folder.mkdir(parents=True)
        partial=folder/'candidate.gguf.partial';partial.write_bytes(b'incomplete')
        with self.assertRaises(RuntimeError):prepare_profile(self.root,self.model,self.identifier)
        with self.assertRaises(RuntimeError):resolve_model(self.root,self.base(),{'weight_edit_profile':self.identifier})
        with self.assertRaises(RuntimeError):clear_prepared(self.root,self.identifier)
        self.assertEqual(partial.read_bytes(),b'incomplete')
    def test_manifest_rejects_inconsistent_delta_size(self):
        source=Path(self.profile['profile_archive']);bad=self.root/'malformed.wsedit'
        with zipfile.ZipFile(source) as z,zipfile.ZipFile(bad,'w') as output:
            for name in z.namelist():output.writestr(name,z.read(name)+(b'extra' if name=='delta.bin' else b''))
        with self.assertRaises(ValueError):read_manifest(bad)
    def test_storage_admission_failure_keeps_cached_profiles(self):
        prepare_profile(self.root,self.model,self.identifier)
        second=self.more_profile(1);prepare_profile(self.root,self.model,second)
        third=self.more_profile(2)
        with mock.patch('edit_profiles.space',side_effect=RuntimeError('80 GiB reserve')):
            with self.assertRaises(RuntimeError):prepare_profile(self.root,self.model,third)
        self.assertEqual({p.name for p in (home(self.root)/'Prepared').iterdir()},{self.identifier,second})
    def test_failed_full_checksum_never_evicts_verified_cache(self):
        prepare_profile(self.root,self.model,self.identifier)
        second=self.more_profile(1);prepare_profile(self.root,self.model,second)
        third=self.more_profile(2)
        with mock.patch('edit_profiles.sha',return_value='0'*64):
            with self.assertRaises(RuntimeError):prepare_profile(self.root,self.model,third)
        self.assertTrue((home(self.root)/'Prepared'/self.identifier/'ready.json').is_file())
        self.assertTrue((home(self.root)/'Prepared'/second/'ready.json').is_file())
    def test_saved_setting_accepts_prepared_profile_and_original(self):
        import settings_page
        values={'selection':'auto','backend':'auto','context_tokens':4096,'weight_edit_profile':self.identifier}
        with mock.patch.object(settings_page,'require_user'),mock.patch.object(settings_page,'inventory',return_value={'models':[]}),mock.patch.object(settings_page,'load_effective_policy',return_value={}),mock.patch.object(settings_page,'save_personal') as save:
            with self.assertRaises(ValueError):settings_page.save_settings(self.root,values,scope='chat')
            save.assert_not_called();prepare_profile(self.root,self.model,self.identifier)
            settings_page.save_settings(self.root,values,scope='chat')
            self.assertEqual(save.call_args.args[1]['weight_edit_profile'],self.identifier)
            values['weight_edit_profile']='original';settings_page.save_settings(self.root,values,scope='chat')
            self.assertEqual(save.call_args.args[1]['weight_edit_profile'],'original')
    def test_profile_changes_the_actual_model_command_and_revert_restores_it(self):
        import runtime_policy as rp
        prepare_profile(self.root,self.model,self.identifier)
        policy=rp.load_policy(ROOT);model={**policy['models'][0],'id':'fixture','path':'LLM/models/standard.gguf','cpu_auto':True,'projector':None}
        policy.update(models=[model],selection='fixture',weight_edit_profile=self.identifier)
        hw={'ram_available_bytes':32*1024**3,'ram_total_bytes':32*1024**3,'gpus':[],'system':'Windows','machine':'AMD64','cpu_count':8}
        backend={'backend':'cpu','gpu':None,'executable':'fixture.exe'}
        edited=rp.select_model(self.root,hw,backend,policy)['selected']
        self.assertEqual(Path(edited['absolute_path']),home(self.root)/'Prepared'/self.identifier/'candidate.gguf')
        self.assertIn('Synthetic test',edited['label'])
        policy['weight_edit_profile']='original'
        self.assertEqual(Path(rp.select_model(self.root,hw,backend,policy)['selected']['absolute_path']),self.model)
    def run_worker(self,action,*,loaded=()):
        import contextlib,io,utility_worker,service_manager,chat_model_switch,research_guard
        work=self.root/('worker-'+action);work.mkdir();request=work/'request.json'
        request.write_text(json.dumps({'action':action,'model':str(self.model),'profile_id':self.identifier}))
        listener={'open':bool(loaded),'listeners':[{'command_line':['fixture','-m',str(p)]} for p in loaded]}
        with mock.patch.object(utility_worker,'ROOT',self.root),mock.patch.object(sys,'argv',['worker',str(request)]),mock.patch.object(service_manager,'acquire_gpu_lease',return_value='fixture-lease'),mock.patch.object(service_manager,'release_gpu_lease') as release,mock.patch.object(service_manager,'_qwen_lifecycle_mutex',return_value=contextlib.nullcontext()),mock.patch.object(chat_model_switch,'_owned_listener',return_value=listener),mock.patch.object(research_guard,'LAB',work),contextlib.redirect_stdout(io.StringIO()):
            try:utility_worker.main()
            finally:release.assert_called_once_with('fixture-lease')
        return json.loads((work/'profile-result.json').read_text())
    def test_utility_worker_prepares_and_clears_exact_profile(self):
        prepared=self.run_worker('prepare-profile');self.assertTrue(prepared['prepared'])
        cleared=self.run_worker('clear-prepared');self.assertTrue(cleared['removed'])
        self.assertEqual(self.model.read_bytes(),self.original)
    def test_utility_worker_preserves_loaded_profile_and_releases_lease(self):
        result=prepare_profile(self.root,self.model,self.identifier)
        with self.assertRaises(RuntimeError):self.run_worker('clear-prepared',loaded=[result['candidate']])
        self.assertTrue(Path(result['candidate']).is_file())

if __name__=='__main__':unittest.main()
