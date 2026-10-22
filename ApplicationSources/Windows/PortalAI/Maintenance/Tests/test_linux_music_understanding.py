"""Linux specialists: explicit admission, isolated workers, no partial-result claims."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import music_understanding_runtime as runtime
import music_understanding_enhanced as bridge


class LinuxMusicTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hw = {'system':'Linux','machine':'x86_64','ram_available_bytes':8*runtime.GIB,'gpus':[]}

    def test_small_cpu_specialists_do_not_require_large_moss_admission(self):
        for kind in ('clap','separate-vocals'):
            plan = runtime.plan(self.root,kind,'cpu',hardware=self.hw)
            self.assertEqual(plan['backend'],'cpu')
            self.assertEqual(plan['max_memory_bytes'],4*runtime.GIB)
        with self.assertRaisesRegex(RuntimeError,'44 GiB'):
            runtime.plan(self.root,'moss','cpu',hardware=self.hw)

    def test_explicit_gpu_never_silently_falls_back_to_cpu(self):
        for backend in ('cuda','rocm'):
            with self.assertRaisesRegex(RuntimeError,'compute probe'):
                runtime.plan(self.root,'clap',backend,hardware=self.hw)
        self.assertEqual(runtime.plan(self.root,'clap','auto',hardware=self.hw)['backend'],'cpu')

    def test_gpu_memory_and_shared_ram_admission(self):
        self.hw['media_gpu'] = {'backend':'rocm','available':True,'compute_ok':True,
                                'free_bytes':24*runtime.GIB,'shared_memory':False}
        self.hw['ram_available_bytes']=32*runtime.GIB
        self.assertEqual(runtime.plan(self.root,'moss','rocm',hardware=self.hw)['backend'],'rocm')
        self.hw['media_gpu']['shared_memory']=True
        with self.assertRaisesRegex(RuntimeError,'44 GiB'):
            runtime.plan(self.root,'moss','rocm',hardware=self.hw)
        self.hw['media_gpu']['free_bytes']=runtime.GIB
        with self.assertRaisesRegex(RuntimeError,'GPU memory'):
            runtime.plan(self.root,'clap','rocm',hardware=self.hw)
        self.assertEqual(runtime.plan(self.root,'clap','auto',hardware=self.hw)['backend'],'cpu')

    def test_linux_clap_runs_when_moss_is_missing(self):
        model=self.root/'MusicUnderstanding/models/CLAP-larger-music';model.mkdir(parents=True)
        (model/'config.json').write_text('{}')
        instance=bridge.EnhancedMusicUnderstandingBridge();instance.root=self.root
        instance.legacy=MagicMock();instance.legacy.understand.return_value={'tempo':120}
        with (patch.object(instance,'_specialist_available',side_effect=lambda kind:(kind=='clap','MOSS unavailable')),
             patch.object(bridge,'_run_json',return_value={'genre':[{'label':'fixture','similarity':.1}],'device':'cpu'}) as execute):
            result=instance.understand('fixture.wav')
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[0][2],'clap')
        self.assertEqual(result['semantic_backend'],'CLAP')
        self.assertTrue(result['partial'])

    def test_demucs_only_result_does_not_claim_semantic_or_lyrics_answer(self):
        instance=bridge.EnhancedMusicUnderstandingBridge();instance.root=self.root
        instance.legacy=MagicMock();instance.legacy.understand.return_value={'tempo':120}
        with (patch.object(instance,'_specialist_available',side_effect=lambda kind:(kind=='separate-vocals','unavailable')),
             patch.object(bridge,'_run_json',return_value={'vocals_path':str(self.root/'vocals.wav')}) as execute):
            result=instance.understand('fixture.wav',question='Please transcribe lyrics',semantic=False)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(result['semantic_backend'],'Demucs vocal isolation')
        self.assertFalse(result['semantic_available'])
        self.assertNotIn('moss_music',result)

    def test_owned_worker_uses_bundled_loader_isolation_and_admitted_memory(self):
        profile={'backend':'cpu','shared_memory':False,'max_memory_bytes':4*runtime.GIB}
        with (patch.object(runtime,'plan',return_value=profile) as admission,
             patch.object(runtime,'python_path',return_value=self.root/'Runtime/LinuxPython/run-python'),
             patch.object(runtime,'portable_env',return_value={}),
             patch('linux_owned_run.run',return_value=SimpleNamespace(returncode=0)) as execute):
            runtime.run(self.root,['clap','--audio','fixture.wav','--device','cpu'],60)
        admission.assert_called_once_with(self.root,'clap','cpu')
        command=execute.call_args.args[0]
        self.assertEqual(command[:3],[str(self.root/'Runtime/LinuxPython/run-python'),'-B','-I'])
        self.assertIn('--portalai-backend',command)
        self.assertEqual(execute.call_args.kwargs['memory_bytes'],4*runtime.GIB)
        self.assertEqual(execute.call_args.kwargs['env']['HF_HUB_OFFLINE'],'1')

    def test_failed_admission_cannot_start_worker(self):
        with (patch.object(runtime,'plan',side_effect=RuntimeError('not enough RAM')),
             patch('linux_owned_run.run') as execute):
            with self.assertRaisesRegex(RuntimeError,'RAM'): runtime.run(self.root,['moss'],60)
        execute.assert_not_called()

    def test_changed_captured_login_blocks_late_launch_and_result(self):
        profile={'backend':'cpu','shared_memory':False,'max_memory_bytes':4*runtime.GIB}
        for sequence, calls in (([('a','old'),('a','new')],0),
                                ([('a','old'),('a','old'),('a','new')],1)):
            with (patch.object(runtime,'plan',return_value=profile),
                  patch.object(runtime,'portable_env',return_value={}),
                  patch('profile_paths.capture',side_effect=sequence),
                  patch('linux_owned_run.run') as execute):
                with self.assertRaises(PermissionError): runtime.run(self.root,['clap'],60)
            self.assertEqual(execute.call_count,calls)

    def test_worker_cannot_emit_after_profile_revocation(self):
        driver=self.driver();driver.RUNTIME_BACKEND='cpu';driver.PROFILE_CONTEXT=('a','old')
        with patch.object(driver,'capture',return_value=('a','new')),patch('builtins.print') as output:
            with self.assertRaises(PermissionError): driver.emit({'genre':['late result']})
        output.assert_not_called()

    def driver(self):
        spec=importlib.util.spec_from_file_location('portalai_music_driver_test',ROOT/'MusicUnderstanding/runtime_driver.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        module.ROOT=self.root
        return module

    def publish_vocals_case(self, revoke_at=None):
        from profile_paths import UID_ENV, EPOCH_ENV, private_path, ProfileLocked
        driver=self.driver(); context=('a'*32,'b'*32)
        driver.RUNTIME_BACKEND='cpu'; driver.RUNTIME_DEVICE='cpu'; driver.PROFILE_CONTEXT=context
        marker=self.root/'Private/active-session.json';marker.parent.mkdir(parents=True)
        marker.write_text(json.dumps({'user_id':context[0],'epoch':context[1],'state':'open'}))
        def revoke():
            marker.write_text(json.dumps({'user_id':context[0],'epoch':context[1],'state':'closing'}))
        class Vocals:
            shape=(3,2)
            def __len__(self):return 3
        audio=Vocals(); soundfile=MagicMock()
        soundfile.info.return_value=SimpleNamespace(frames=3,samplerate=44100,channels=2)
        def write(path,*args,**kwargs):
            path.write_bytes(b'synthetic-wave')
            if revoke_at=='write':revoke()
            if revoke_at=='cancel':raise KeyboardInterrupt()
        soundfile.write.side_effect=write
        replace=os.replace
        def publish(source,target):
            replace(source,target)
            if revoke_at=='rename':revoke()
        with (patch.dict(os.environ,{UID_ENV:context[0],EPOCH_ENV:context[1]}),
              patch.dict(sys.modules,{'soundfile':soundfile}),
              patch.object(driver.os,'replace',side_effect=publish),patch('builtins.print') as output):
            outdir=private_path(self.root,'MusicUnderstanding/cache/demucs')/'fixture'
            if revoke_at=='before':revoke()
            if revoke_at:
                with self.assertRaises(KeyboardInterrupt if revoke_at=='cancel' else ProfileLocked):
                    driver._publish_vocals(audio,44100,outdir,context)
                output.assert_not_called()
                self.assertFalse((outdir/'vocals.wav').exists())
                self.assertEqual(list(outdir.glob('*.part.wav')),[])
                if revoke_at=='before':soundfile.write.assert_not_called()
            else:
                driver._publish_vocals(audio,44100,outdir,context)
                self.assertEqual((outdir/'vocals.wav').read_bytes(),b'synthetic-wave')
                self.assertEqual(json.loads(output.call_args.args[0])['vocals_path'],str(outdir/'vocals.wav'))
        self.assertFalse((self.root/'MusicUnderstanding/cache/demucs').exists())

    def test_demucs_publication_is_private_and_checked(self):self.publish_vocals_case()
    def test_demucs_revocation_after_inference_prevents_output(self):self.publish_vocals_case('before')
    def test_demucs_revocation_during_write_removes_own_partial(self):self.publish_vocals_case('write')
    def test_demucs_revocation_during_rename_removes_own_final(self):self.publish_vocals_case('rename')
    def test_demucs_cancel_during_write_removes_own_partial(self):self.publish_vocals_case('cancel')

    def test_long_audio_refused_before_decoder_and_no_windows_ffmpeg_fallback(self):
        driver=self.driver()
        # Only the NumPy symbol is required for the early duration rejection.
        with (patch.dict(sys.modules,{'numpy':MagicMock()}),
             patch('platform_runtime.ffmpeg_path',side_effect=lambda root,probe=False:root/('ffprobe' if probe else 'ffmpeg')),
             patch('platform_runtime.linux_elf_command',side_effect=lambda root,command:(command,None)),
             patch('subprocess.run',return_value=SimpleNamespace(stdout=b'{"format":{"duration":"301"}}')) as execute):
            with self.assertRaisesRegex(ValueError,'300 seconds'): driver._linux_audio('fixture.wav',48000)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[0][0],str(self.root/'ffprobe'))

    def test_decode_checks_output_bounds_and_complete_shape(self):
        driver=self.driver()
        fake_numpy=MagicMock()
        replies=[SimpleNamespace(stdout=b'{"format":{"duration":"1"}}'),
                 SimpleNamespace(returncode=0,stdout=b'123',stderr=b'')]
        with (patch.dict(sys.modules,{'numpy':fake_numpy}),
             patch('platform_runtime.ffmpeg_path',side_effect=lambda root,probe=False:root/('ffprobe' if probe else 'ffmpeg')),
             patch('platform_runtime.linux_elf_command',side_effect=lambda root,command:(command,None)),
             patch('subprocess.run',side_effect=replies)):
            with self.assertRaisesRegex(RuntimeError,'invalid or oversized'): driver._linux_audio('fixture.wav',48000)
        fake_numpy.frombuffer.assert_not_called()


if __name__=='__main__': unittest.main()
