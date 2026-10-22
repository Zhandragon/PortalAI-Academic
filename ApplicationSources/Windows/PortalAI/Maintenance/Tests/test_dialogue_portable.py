"""No GPU/model execution: stage admission, real file publication and recovery."""
from contextlib import ExitStack
import copy
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
import dialogue_portable as module


class DurationTests(unittest.TestCase):
    def test_chunks_keep_full_speech_and_existing_per_graph_cap(self):
        for fps in (4, 16, 25, 30):
            for seconds in (.2, 1.01, 4., 7.99, 8.):
                chunks = module.frame_chunks(seconds, fps)
                self.assertGreaterEqual(sum(chunks), math.ceil(seconds * fps))
                self.assertTrue(all(5 <= item <= 17 and (item-1) % 4 == 0 for item in chunks))
                self.assertLess(sum(chunks)-math.ceil(seconds*fps), 5)
                self.assertLessEqual(len(chunks), 15)

    def test_duration_and_fps_limits_are_explicit_never_truncate(self):
        for seconds in (.1, 120.001, float('nan'), float('inf')):
            with self.assertRaises(ValueError): module.frame_chunks(seconds, 16)
        for fps in (0, 3, 31, 16.5, True):
            with self.assertRaises(ValueError): module.frame_chunks(1., fps)


class PreparationTests(unittest.TestCase):
    def test_options_preserve_voice_motion_and_explicit_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            motion = {'source':str(root/'portrait.png'), 'prompt':'pan left', 'fps':16, 'frames':5,
                      'width':256, 'height':320, 'seed':12}
            options = dict(input='portrait.png', dialogue='My spoken line', motion='pan left', language='Japanese',
                           voice_description='Deep voice', speaker='Ryan', fps=16, width=256, height=320, seed=12)
            with patch('vace_reference.prepare', return_value=motion) as prepare, \
                 patch.object(module, 'capture', return_value=None), \
                 patch.object(module, 'private_path', side_effect=lambda r,p,**k:Path(r)/p):
                request = module.prepare(root, options)
            self.assertEqual(request['motion'], motion)
            self.assertEqual(request['dialogue'], 'My spoken line')
            self.assertEqual(request['language'], 'Japanese')
            self.assertEqual(request['speaker'], 'Ryan')
            self.assertEqual(request['voice_description'], 'Deep voice')
            self.assertEqual(prepare.call_args.kwargs['width'], 256)

    def test_uncensored_flag_is_passed_to_reference_admission_not_dropped(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch('vace_reference.prepare', side_effect=ValueError('no variant')) as prepare:
            with self.assertRaisesRegex(ValueError, 'no variant'):
                module.prepare(Path(directory), {'dialogue':'hello', 'input':'portrait.png', 'motion':'pan', 'uncensored':True})
        self.assertTrue(prepare.call_args.kwargs['uncensored'])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.events = []; self.pieces = []; self.commands = []
        self.request = {'motion':{'source':str(self.root/'portrait.png'), 'prompt':'natural head motion',
                        'width':256, 'height':256, 'frames':5, 'fps':16, 'seed':42},
            'dialogue':'Speak the full sentence.', 'language':'English', 'reference_audio':None,
            'ref_text':None, 'speaker':None, 'voice_description':'Natural voice', 'music_prompt':None,
            'music_lyrics':'', 'music_instrumental':False, 'music_volume':.25, 'duck_music':True,
            'output':str(self.root/'Outputs/Videos/final.mp4'), 'profile_context':None, 'requested_at':time.time()}
        self.duration = 2.0
        self.context = None
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        def own_patch(*args, **kwargs): return self.stack.enter_context(patch(*args, **kwargs))
        own_patch('dialogue_portable.capture', side_effect=lambda root:self.context)
        own_patch('dialogue_portable.private_path', side_effect=lambda root,path,**kwargs:Path(root)/path)
        own_patch('dialogue_portable.media_output', side_effect=lambda root,path:Path(path))
        own_patch('dialogue_portable.require_space')
        self.guard = own_patch('chat_model_switch._guard')
        self.motion_plan = own_patch('radeon_edit.plan', return_value={'backend':'rocm','engine':'wan-vace-1.3b','max_memory_bytes':12*1024**3})
        self.lip_plan = own_patch('musetalk_amd_bridge.plan', return_value={'backend':'rocm'})
        self.tts_plan = own_patch('tts_policy.tts_plan', return_value={'device':'rocm'})
        self.music_plan = own_patch('music_amd_bridge.plan', return_value={'backend':'rocm'})
        self.voice = own_patch('dialogue_portable._voice', side_effect=self.fake_voice)
        self.motion = own_patch('vace_reference.generate', side_effect=self.fake_motion)
        self.lips = own_patch('musetalk_amd_bridge.generate', side_effect=self.fake_lips)
        self.music = own_patch('music_amd_bridge.generate', side_effect=self.fake_music)
        own_patch('dialogue_portable._probe', side_effect=self.fake_probe)
        own_patch('dialogue_portable._run', side_effect=self.fake_run)
        own_patch('dialogue_portable.ffmpeg_path', return_value=self.root/'fake-ffmpeg')

    def make(self, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'fresh fixture data')
        return path

    def fake_voice(self, request, output, root):
        self.events.append('voice'); self.make(output)
        return {'files':[str(output)], 'device':'rocm'}

    def fake_motion(self, request, profile, *, root):
        self.events.append('motion'); self.pieces.append(copy.deepcopy(request))
        output = self.make(self.root/'Outputs/Videos'/f'VACE_reference_{len(self.pieces)}.mp4')
        return {'files':[str(output)]}

    def fake_lips(self, profile, video, audio, *, root):
        self.events.append('lips'); self.assertTrue(Path(video).is_file()); self.assertTrue(Path(audio).is_file())
        return {'files':[str(self.make(self.root/f"Outputs/Videos/MuseTalk/musetalk_fixture_{self.events.count('lips')}.mp4"))]}

    def fake_music(self, profile, prompt, **kwargs):
        self.events.append('music')
        return {'files':[str(self.make(self.root/'Outputs/Music/acestep_fixture.flac'))]}

    def fake_run(self, root, args, work, check, **kwargs):
        check(); self.commands.append(args); self.make(args[-1]); return ''

    def fake_probe(self, root, path, work, check):
        check()
        streams = [{'codec_type':'audio'}]
        if Path(path).suffix == '.mp4':
            streams += [{'codec_type':'video', 'width':256, 'height':256, 'avg_frame_rate':'16/1'}]
        duration = self.duration if Path(path).suffix == '.wav' else ((self.request.get('timing') or {}).get('duration') or self.duration)
        return {'streams':streams}, duration

    def test_sequential_real_motion_chunks_and_stage_readmission(self):
        result = module.generate(self.request, root=self.root)
        self.assertEqual(self.events, ['voice', 'motion', 'motion', 'lips'])
        self.assertEqual([piece['frames'] for piece in self.pieces], [17,17])
        self.assertEqual(self.pieces[0]['source'], self.request['motion']['source'])
        self.assertTrue(self.pieces[1]['source'].endswith('reference_000.png'))
        self.assertTrue(all(piece['prompt']=='natural head motion' for piece in self.pieces))
        self.assertEqual(self.motion_plan.call_count, 3)
        self.assertEqual(self.lip_plan.call_count, 2)
        self.assertEqual(result['target_seconds'], 2.)
        self.assertEqual(result['fps'], 16)
        self.assertFalse(result['physical_hardware_validated'])
        self.assertTrue(Path(result['files'][0]).is_file())
        self.assertFalse(list((self.root/'Outputs/Videos').glob('VACE_reference*')))
        self.assertFalse(list((self.root/'Cache/MediaWorkers/Dialogue').iterdir()))
        self.assertTrue(any('fps=16,scale=256:256:flags=lanczos' in args for args in self.commands))

    def test_twenty_seconds_uses_small_graphs_and_segmented_lips(self):
        from dialogue_timing import options
        self.request['timing'] = options(20, 5)
        result = module.generate(self.request, root=self.root)
        self.assertEqual(result['speech_seconds'], 2.)
        self.assertEqual(result['target_seconds'], 20.)
        self.assertEqual(result['lip_sync_segments'], 3)
        self.assertTrue(all(piece['frames'] <= 17 for piece in self.pieces))
        self.assertEqual(self.lips.call_count, 3)
        self.assertTrue(any('aresample=48000,adelay=240000S:all=1,apad' in args for args in self.commands))

    def test_too_long_dialogue_for_explicit_target_fails_before_motion(self):
        from dialogue_timing import options
        self.request['timing'] = options(1)
        with self.assertRaisesRegex(ValueError, 'not cut or sped up'):
            module.generate(self.request, root=self.root)
        self.motion.assert_not_called(); self.lips.assert_not_called()

    def test_cpu_or_unadmitted_stage_fails_before_voice_without_substitution(self):
        self.motion_plan.side_effect = RuntimeError('no supported compute')
        with self.assertRaisesRegex(RuntimeError, 'no supported compute'):
            module.generate(self.request, root=self.root)
        self.voice.assert_not_called(); self.motion.assert_not_called(); self.lips.assert_not_called()

    def test_request_guard_rejects_stop_before_lease_or_stage_admission(self):
        self.guard.side_effect = RuntimeError('explicit Stop before lease')
        with self.assertRaisesRegex(RuntimeError, 'before lease'):
            module.check_request(self.request, root=self.root)
        with self.assertRaisesRegex(RuntimeError, 'before lease'):
            module.generate(self.request, root=self.root)
        self.motion_plan.assert_not_called(); self.voice.assert_not_called()

    def test_request_guard_rejects_changed_login_before_stage_admission(self):
        self.context = ('different', 'epoch')
        with self.assertRaises(module.ProfileLocked): module.check_request(self.request, root=self.root)
        self.guard.assert_not_called(); self.motion_plan.assert_not_called()

    def test_long_speech_is_not_cut_or_sent_to_motion(self):
        self.duration = 120.1
        with self.assertRaisesRegex(ValueError, 'not truncated'):
            module.generate(self.request, root=self.root)
        self.voice.assert_called_once(); self.motion.assert_not_called(); self.lips.assert_not_called()
        self.assertFalse(Path(self.request['output']).exists())

    def test_motion_failure_never_falls_back_to_still_or_lipsync(self):
        self.motion.side_effect = RuntimeError('motion failed')
        with self.assertRaisesRegex(RuntimeError, 'motion failed'):
            module.generate(self.request, root=self.root)
        self.lips.assert_not_called(); self.assertFalse(Path(self.request['output']).exists())

    def test_revocation_between_stages_cleans_only_own_generated_file(self):
        original = self.make(self.root/'Outputs/Videos/unrelated.mp4')
        def revoke(*args, **kwargs):
            result = self.fake_motion(*args, **kwargs)
            self.context = ('revoked', 'epoch')
            return result
        self.motion.side_effect = revoke
        with self.assertRaises(module.ProfileLocked): module.generate(self.request, root=self.root)
        self.lips.assert_not_called(); self.assertTrue(original.exists())
        self.assertFalse(list((self.root/'Outputs/Videos').glob('VACE_reference*')))

    def test_stop_between_stages_does_not_start_another_model(self):
        def stop(*args, **kwargs):
            result = self.fake_voice(*args, **kwargs)
            self.guard.side_effect = RuntimeError('explicit Stop')
            return result
        self.voice.side_effect = stop
        with self.assertRaisesRegex(RuntimeError, 'explicit Stop'): module.generate(self.request, root=self.root)
        self.motion.assert_not_called(); self.lips.assert_not_called()

    def test_optional_music_runs_after_lips_and_preserves_speech_duration(self):
        self.request['music_prompt'] = 'quiet piano'
        result = module.generate(self.request, root=self.root)
        self.assertEqual(self.events, ['voice','motion','motion','lips','music'])
        self.assertEqual(self.music.call_args.kwargs['duration'], 10.)
        self.assertEqual(result['target_seconds'], 2.)
        self.assertEqual(result['music_generated_seconds'], 10.)

    def test_existing_destination_never_overwritten(self):
        output = self.make(self.request['output']); output.write_bytes(b'original')
        with self.assertRaises(FileExistsError): module.generate(self.request, root=self.root)
        self.assertEqual(output.read_bytes(), b'original')

    def test_revocation_after_atomic_publish_removes_only_our_new_file(self):
        source = self.make(self.root/'source.mp4'); destination = self.root/'result.mp4'
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 3: raise module.ProfileLocked('login ended')
        with self.assertRaises(module.ProfileLocked): module._publish(self.root, source, destination, check)
        self.assertFalse(destination.exists()); self.assertTrue(source.exists())


@unittest.skipUnless(os.environ.get('PORTALAI_TEST_REAL_DIALOGUE_MEDIA') == '1',
                     'Explicit bounded FFmpeg fixture; no real model inference')
class RealMediaTests(unittest.TestCase):
    def test_owned_ffmpeg_concat_timing_fps_and_music_filters(self):
        """Real bundled FFmpeg/jobs; synthetic model outputs, no private account."""
        import runtime_policy
        from platform_runtime import ffmpeg_path, python_path
        if runtime_policy.memory_info()[1] < 3 * 1024**3:
            self.skipTest('Keep at least 3 GiB free for the bounded FFmpeg fixture')
        real_python = python_path(ROOT)
        real_ffmpeg = ffmpeg_path(ROOT)
        real_probe = ffmpeg_path(ROOT, True)
        if not all(path.is_file() for path in (real_python, real_ffmpeg, real_probe)):
            self.skipTest('Bundled platform media binaries are unavailable')
        sys.path.insert(0, str(ROOT/'Tools'))
        from validation_artifacts import ValidationArtifacts
        artifacts = ValidationArtifacts(ROOT, ROOT/'Maintenance/Validation/DialogueMedia_20261010')
        with tempfile.TemporaryDirectory(prefix='fixture_', dir=artifacts.path()) as directory, ExitStack() as stack:
            root = Path(directory)
            (root/'Agent').mkdir(); (root/'work').mkdir()
            shutil.copy2(ROOT/'Agent/sdcpp_worker.py', root/'Agent/sdcpp_worker.py')
            shutil.copy2(ROOT/'Agent/hardware_profiles.json', root/'Agent/hardware_profiles.json')
            if not runtime_policy.storage_budget(root, additional_bytes=512*1024**2, for_outputs=True)['allowed']:
                self.skipTest('Synthetic fixture volume cannot preserve the configured storage floor')
            stack.enter_context(patch.dict(os.environ))
            for name in ('PORTALAI_PROFILE_USER_ID', 'PORTALAI_PROFILE_EPOCH', 'PORTALAI_ACCOUNT_UNLOCK',
                         'PORTALAI_HYDRATION_PORT', 'PORTALAI_HYDRATION_CAPABILITY', 'PORTALAI_HYDRATION_OWNER'):
                os.environ.pop(name, None)
            from profile_paths import UID_ENV, EPOCH_ENV
            os.environ.pop(UID_ENV, None); os.environ.pop(EPOCH_ENV, None)
            stack.enter_context(patch('dialogue_portable.python_path', return_value=real_python))
            stack.enter_context(patch('dialogue_portable.ffmpeg_path', side_effect=lambda root,probe=False:real_probe if probe else real_ffmpeg))
            stack.enter_context(patch('chat_model_switch._guard'))
            stack.enter_context(patch('radeon_edit.plan', return_value={'backend':'synthetic-no-GPU'}))
            stack.enter_context(patch('musetalk_amd_bridge.plan', return_value={'backend':'synthetic-no-GPU'}))
            stack.enter_context(patch('music_amd_bridge.plan', return_value={'backend':'synthetic-no-GPU'}))
            stack.enter_context(patch('tts_policy.tts_plan', return_value={'device':'synthetic-no-GPU'}))
            counter = 0
            def run(args):
                module._run(root, [real_ffmpeg, '-v', 'error', '-nostdin', '-n', *args], root/'work', lambda:None)
            def voice(request, output, root):
                run(['-f','lavfi','-i','sine=frequency=220:sample_rate=24000','-t','2','-c:a','pcm_s16le',output])
                return {'files':[str(output)],'device':'synthetic-no-GPU'}
            def motion(request, profile, *, root):
                nonlocal counter
                counter += 1
                path = root/'Outputs/Videos'/f'VACE_reference_{counter}.mp4'; path.parent.mkdir(parents=True,exist_ok=True)
                run(['-f','lavfi','-i','testsrc2=size=256x256:rate=16','-frames:v',str(request['frames']),
                     '-c:v','libx264','-threads','2','-pix_fmt','yuv420p',path])
                return {'files':[str(path)]}
            def lips(profile, video, audio, *, root):
                _, length = module._probe(root,Path(audio),root/'work',lambda:None)
                self.assertLessEqual(length,8.001)
                path = root/'Outputs/Videos/MuseTalk'/f'musetalk_{counter}_{Path(video).stem}.mp4';path.parent.mkdir(parents=True,exist_ok=True)
                run(['-i',video,'-i',audio,'-map','0:v:0','-map','1:a:0','-vf','fps=25,scale=512:512',
                     '-t',str(length),'-c:v','libx264','-threads','2','-pix_fmt','yuv420p','-c:a','aac',path])
                return {'files':[str(path)]}
            def music(profile, prompt, *, root, **kwargs):
                path = root/'Outputs/Music'/f'acestep_{counter}.flac';path.parent.mkdir(parents=True,exist_ok=True)
                run(['-f','lavfi','-i','sine=frequency=110:sample_rate=48000','-t',str(kwargs['duration']),'-ac','2','-c:a','flac',path])
                return {'files':[str(path)]}
            stack.enter_context(patch('dialogue_portable._voice',side_effect=voice))
            stack.enter_context(patch('vace_reference.generate',side_effect=motion))
            stack.enter_context(patch('musetalk_amd_bridge.generate',side_effect=lips))
            stack.enter_context(patch('music_amd_bridge.generate',side_effect=music))
            for music_prompt, duck, target in ((None,True,2),('quiet piano',True,2),('quiet piano',False,2),(None,True,20)):
                request = {'motion':{'source':str(root/'synthetic-portrait.png'),'prompt':'synthetic motion',
                            'width':256,'height':256,'fps':16,'seed':42}, 'dialogue':'synthetic two seconds',
                    'language':'English','reference_audio':None,'ref_text':None,'speaker':None,'voice_description':None,
                    'music_prompt':music_prompt,'music_lyrics':'','music_instrumental':True,'music_volume':.25,
                    'duck_music':duck,'output':str(root/'Outputs/Videos'/f'final_{counter}.mp4'),
                    'profile_context':None,'requested_at':time.time()}
                if target == 20:
                    from dialogue_timing import options
                    request['timing'] = options(20,5)
                with self.subTest(music=music_prompt,duck=duck,target=target):
                    result = module.generate(request,root=root)
                    self.assertTrue(all(frames<=17 for frames in result['motion_chunks']))
                    self.assertEqual(result['fps'],16)
                    self.assertAlmostEqual(result['target_seconds'],target,places=3)
                    info, duration = module._probe(root,Path(result['files'][0]),root/'work',lambda:None)
                    self.assertLess(abs(duration-target),.1)
                    self.assertEqual({row['codec_type'] for row in info['streams']},{'video','audio'})
                    stream=next(row for row in info['streams'] if row['codec_type']=='video')
                    self.assertEqual((stream['width'],stream['height'],stream['avg_frame_rate']),(256,256,'16/1'))
                    self.assertFalse(list((root/'Cache/MediaWorkers/Dialogue').iterdir()))
                    if target == 20:
                        import wave, array
                        pcm=root/'work'/'timing.wav'
                        run(['-i',result['files'][0],'-vn','-ar','48000','-ac','1','-c:a','pcm_s16le',pcm])
                        with wave.open(str(pcm)) as wav:
                            samples=array.array('h',wav.readframes(wav.getnframes()))
                        def energy(a,b):return sum(x*x for x in samples[int(a*48000):int(b*48000)])/((b-a)*48000)
                        self.assertGreater(energy(5.1,6.9),100000)
                        self.assertLess(energy(.2,4.8),20)
                        self.assertLess(energy(7.2,19.8),20)
                        self.assertEqual(result['lip_sync_segments'],3)


if __name__ == '__main__': unittest.main()
