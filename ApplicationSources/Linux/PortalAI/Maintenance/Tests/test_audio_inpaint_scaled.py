"""No model loads: actual masked flow, source PCM preservation and route contracts."""
from contextlib import contextmanager,ExitStack
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
if os.name=='nt':sys.path.append(str(ROOT/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages'))
import numpy as np
import audio_inpaint_math as math_tools
import audio_inpaint_amd_bridge as bridge
import audio_inpaint_amd_entry as entry


class MaskedAudioMath(unittest.TestCase):
    def test_each_flow_evaluation_receives_observed_context_at_exact_time(self):
        noise=np.array([[[2.],[3.],[4.],[5.]]]);source=np.array([[[10.],[11.],[12.],[13.]]])
        keep=np.array([[[1.],[0.],[0.],[1.]]]);observed=[]
        def flow(t,x):
            expected=(1-t)*noise+t*source
            np.testing.assert_allclose(x[keep==1],expected[keep==1]);observed.append(t)
            return np.full_like(x,7)
        result=math_tools.masked_euler(flow,noise,source,keep,4)
        self.assertEqual(observed,[0,.25,.5,.75])
        np.testing.assert_equal(result[keep==1],source[keep==1])
        np.testing.assert_equal(result[keep==0],(noise+7)[keep==0])
        np.testing.assert_equal(noise,np.array([[[2.],[3.],[4.],[5.]]]))

    def test_source_context_changes_missing_region_through_model_flow(self):
        noise=np.zeros((1,3,1));keep=np.array([[[1.],[0.],[1.]]])
        def run(value):
            source=np.full((1,3,1),value)
            return math_tools.masked_euler(lambda t,x:np.full_like(x,x.mean()),noise,source,keep,8)[0,1,0]
        self.assertGreater(run(4),run(1))

    def test_mask_uses_latent_hop_and_rejects_absent_context(self):
        self.assertEqual(math_tools.mask_span(1,2,44100,1024,345,0),(43,87))
        with self.assertRaisesRegex(ValueError,'observed audio context'):math_tools.mask_span(0,8,44100,1024,345,8)

    def test_blend_is_finite_stereo_and_matches_original_at_boundaries(self):
        source=np.full((12,2),100,dtype=np.int16);generated=np.full((12,2),900,dtype=np.int16)
        result=math_tools.blend_region(source,generated,3)
        np.testing.assert_equal(result[[0,-1]],source[[0,-1]])
        np.testing.assert_equal(result[3:9],generated[3:9])
        generated=generated.astype(float);generated[2,0]=float('nan')
        with self.assertRaisesRegex(ValueError,'non-finite'):math_tools.blend_region(source,generated,2)


class AudioRepairContracts(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def write(self,path,data,rate=44100):
        path.parent.mkdir(parents=True,exist_ok=True)
        with wave.open(str(path),'wb') as file:
            file.setnchannels(data.shape[1]);file.setsampwidth(2);file.setframerate(rate);file.writeframes(data.astype('<i2').tobytes())

    def read(self,path):
        with wave.open(str(path),'rb') as file:return np.frombuffer(file.readframes(file.getnframes()),dtype='<i2').reshape(-1,file.getnchannels())

    def test_pcm_outside_interval_is_byte_identical(self):
        source=self.root/'source.wav';replacement=self.root/'replacement.wav';out=self.root/'out.wav'
        data=(np.arange(44100*3*2).reshape(-1,2)%20000-10000).astype('<i2')
        self.write(source,data);self.write(replacement,np.full((44100*3,2),900))
        job=bridge.request(3,'a bell',start=1,end=2,context=1,crossfade=0)
        bridge.compose_pcm(source,replacement,out,job)
        actual=self.read(out)
        np.testing.assert_equal(actual[:44100],data[:44100]);np.testing.assert_equal(actual[88200:],data[88200:])
        np.testing.assert_equal(actual[44100:88200],np.full((44100,2),900))

    def test_invalid_or_unsupported_sizes_fail_before_work(self):
        for options in ({'start':float('nan'),'end':2},{'start':1,'end':9},
                        {'start':1,'end':2,'context':4},{'start':1,'end':2,'seed':-1},
                        {'start':1,'end':2,'endless':True}):
            with self.subTest(options=options),self.assertRaises((ValueError,TypeError)):
                bridge.request(20,'repair',**options)
        self.assertEqual(bridge.request(20,'repair',start=1,end=2)['mode'],'general')

    def test_music_uses_native_repaint_parameters_without_lm(self):
        args=SimpleNamespace(source=self.root/'window.wav',prompt='piano chord',duration=10.,start=2.,end=4.,seed=12)
        values=entry.music_params(lambda **kwargs:kwargs,args)
        self.assertEqual(values['task_type'],'repaint');self.assertEqual(values['src_audio'],str(args.source))
        self.assertEqual((values['repainting_start'],values['repainting_end']),(2.,4.))
        self.assertFalse(values['thinking']);self.assertFalse(values['enable_normalization']);self.assertEqual(values['inference_steps'],8)

    def test_admission_keeps_twelve_gib_cap_and_never_silently_uses_cpu(self):
        hardware={'system':'Windows','machine':'AMD64','ram_available_bytes':32*bridge.GIB,'gpus':[],
                  'amd_gpu':{'available':True,'compute_ok':True,'free_bytes':8*bridge.GIB,
                             'shared_memory':False,'bf16_compute_ok':True,'backend':'rocm'}}
        for relative in ('Runtime/AMDAudio/packages/open_clip/__init__.py','Services/MMAudio/weights/mmaudio_small_44k.pth'):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
        selected=bridge.plan(root=self.root,hardware=hardware)
        self.assertEqual(selected['backend'],'rocm');self.assertEqual(selected['max_memory_bytes'],12*bridge.GIB)
        hardware['amd_gpu']['compute_ok']=False
        with self.assertRaisesRegex(RuntimeError,'compute probe'):bridge.plan(root=self.root,hardware=hardware)

    def test_lease_restores_and_releases_even_on_model_failure(self):
        import service_manager as services
        with ExitStack() as stack:
            mocked={name:stack.enter_context(patch.object(services,name)) for name in
                    ('acquire_gpu_lease','quiesce_gpu_workers','qwen_gpu_handoff_begin','qwen_gpu_handoff_end','release_gpu_lease')}
            with self.assertRaisesRegex(RuntimeError,'fixture failure'):
                with bridge.lease():raise RuntimeError('fixture failure')
            mocked['qwen_gpu_handoff_end'].assert_called_once_with(mocked['qwen_gpu_handoff_begin'].return_value)
            mocked['release_gpu_lease'].assert_called_once_with(mocked['acquire_gpu_lease'].return_value)

    def pipeline(self,mode='general',revoke=False,stopped=False):
        source=self.root/'source.wav';data=np.full((44100*4,2),700,dtype='<i2');self.write(source,data)
        relative='Outputs/Music/acestep_fixture.flac' if mode=='music' else 'Outputs/SFX/mmaudio_fixture.flac'
        generated=self.root/relative;self.write(generated,np.full((44100*10 if mode=='music' else 44100*3,2),1400))
        original_identity=(generated.stat().st_dev,generated.stat().st_ino)
        state={'epoch':('a','one')};jobplan={'backend':'rocm','engine':'mmaudio-masked-flow'}
        @contextmanager
        def lease(check):check();yield
        def ffmpeg(root,args,work,check):check();shutil.copyfile(Path(args[args.index('-i')+1]),Path(args[-1]));check()
        def info(path):
            with wave.open(str(path),'rb') as file:
                return {'has_audio':True,'duration_seconds':file.getnframes()/file.getframerate(),
                        'audio':{'channels':file.getnchannels()}}
        publish=bridge.publish_no_replace
        def publishing(src,dst):
            publish(src,dst)
            if revoke:state['epoch']=('a','two')
        def worker_result(*args,**kwargs):
            if stopped:state['stopped']=True
            return {'files':[str(generated)],'_owned_file_identity':original_identity}
        def guard(*args):
            if state.get('stopped'):raise RuntimeError('Stopped fixture')
        with ExitStack() as stack:
            stack.enter_context(patch.object(bridge,'_guard',side_effect=guard))
            stack.enter_context(patch.object(bridge,'memory_info',return_value=(32*bridge.GIB,24*bridge.GIB)))
            stack.enter_context(patch.object(bridge,'capture',side_effect=lambda _:state['epoch']))
            stack.enter_context(patch.object(bridge,'private_path',side_effect=lambda root,relative:root/relative))
            stack.enter_context(patch.object(bridge,'media_reference',side_effect=lambda root,path:Path(path)))
            stack.enter_context(patch.object(bridge,'media_temp',return_value=self.root))
            stack.enter_context(patch.object(bridge,'require_space'))
            stack.enter_context(patch.object(bridge,'lease',lease))
            plan=stack.enter_context(patch.object(bridge,'plan',return_value=jobplan))
            worker=stack.enter_context(patch.object(bridge,'generate_window',side_effect=worker_result))
            stack.enter_context(patch.object(bridge,'_ffmpeg',side_effect=ffmpeg))
            stack.enter_context(patch.object(bridge,'publish_no_replace',side_effect=publishing))
            stack.enter_context(patch.object(bridge,'_info',side_effect=lambda root,path,check:info(path)))
            spectral=stack.enter_context(patch('media_edit_bridge.audio_inpaint',return_value={'files':[str(generated)]}))
            if stopped:
                with self.assertRaisesRegex(RuntimeError,'Stopped fixture'):bridge.audio_inpaint(source,'repair',start=1,end=2,mode=mode,root=self.root)
                self.assertFalse(generated.exists());self.assertFalse((self.root/'Outputs/EditedAudio/source_inpainted.wav').exists())
            elif revoke:
                with self.assertRaises(ProfileLocked):bridge.audio_inpaint(source,'repair',start=1,end=2,mode=mode,root=self.root)
                self.assertFalse((self.root/'Outputs/EditedAudio/source_inpainted.wav').exists())
            else:
                result=bridge.audio_inpaint(source,'repair',start=1,end=2,mode=mode,root=self.root)
                actual=self.read(result['files'][0]);np.testing.assert_equal(actual[:44100],data[:44100]);np.testing.assert_equal(actual[88200:],data[88200:])
                if mode=='speech':
                    spectral.assert_called_once();worker.assert_not_called();plan.assert_not_called()
                    self.assertFalse(result['operations']['audio_native']);self.assertIn('no speech/voice/word',result['operations']['note'])
                else:worker.assert_called_once();self.assertTrue(result['operations']['audio_native']);self.assertFalse(generated.exists())

    def test_pipeline_preserves_pcm_and_reports_experimental_method(self):self.pipeline()
    def test_revocation_after_publication_removes_only_new_result(self):self.pipeline(revoke=True)
    def test_explicit_speech_preserves_existing_route_with_honest_label(self):self.pipeline(mode='speech')
    def test_music_pipeline_preserves_pcm_and_cleans_intermediate(self):self.pipeline(mode='music')
    def test_stop_after_model_cleans_intermediate_and_prevents_composition(self):self.pipeline(stopped=True)

    def test_speech_real_fft_and_owned_ffmpeg_hooks(self):
        import media_edit_bridge as legacy
        import dialogue_portable
        from runtime_policy import portable_env
        source=self.root/'speech.wav';out=self.root/'speech-repaired.wav'
        self.write(source,(2000*np.sin(2*np.pi*330*np.arange(44100*3)/44100)).reshape(-1,1))
        @contextmanager
        def exclusive(reason,*,start_guard=None):
            start_guard();yield;start_guard()
        check=Mock();owned=[]
        with ExitStack() as stack:
            stack.enter_context(patch.object(legacy,'_root_dir',return_value=self.root))
            stack.enter_context(patch.object(legacy,'_exclusive_comfy',side_effect=exclusive))
            stack.enter_context(patch.object(legacy,'_comfy_inpaint_image',side_effect=lambda image,*args,**kwargs:image))
            stack.enter_context(patch.object(bridge,'media_temp',return_value=self.root))
            stack.enter_context(patch.object(dialogue_portable,'portable_env',side_effect=lambda root:portable_env(root,before_login=True)))
            value=legacy.audio_inpaint(source,'repair',output=out,start=1,end=2,context=.5,mode='speech',
                start_guard=check,ffmpeg_runner=lambda args:bridge._ffmpeg(ROOT,args,self.root,check),
                probe=lambda path:bridge._info(ROOT,path,check),owned_outputs=owned)
        self.assertTrue(out.is_file());self.assertAlmostEqual(value['duration_seconds'],3.,places=2)
        self.assertGreater(check.call_count,10);self.assertEqual(len(owned),1)
        self.assertEqual(owned[0][0].suffix,'.png')


from profile_paths import ProfileLocked
if __name__=='__main__':unittest.main()
