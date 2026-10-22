"""Explicit timelines and exact recovery pages under context pressure."""
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import os
import shutil
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import dialogue_timing as timing
import chat_evidence as evidence
import ai_tools


class TimelineTests(unittest.TestCase):
    def test_twenty_seconds_with_natural_dialogue_and_three_actions(self):
        beats = [{'seconds':5, 'prompt':'approach'}, {'seconds':8, 'prompt':'speak'}, {'seconds':7, 'prompt':'run'}]
        plan = timing.options(20, 5, json.dumps(beats))
        self.assertEqual(timing.target(6, plan), 20)
        for cap in (17, 81):
            pieces = timing.motion_chunks(20, 16, cap, 'global', plan['motion_plan'])
            self.assertEqual(sum(p['keep_frames'] for p in pieces), 320)
            self.assertTrue(all(5 <= p['frames'] <= cap and p['frames'] % 4 == 1 for p in pieces))
            self.assertEqual(list(dict.fromkeys(p['prompt'] for p in pieces)), ['approach','speak','run'])
            for prompt, seconds in [('approach',5),('speak',8),('run',7)]:
                self.assertEqual(sum(p['keep_frames'] for p in pieces if p['prompt']==prompt), seconds*16)

    def test_dialogue_must_fit_without_cutting_or_stretching(self):
        with self.assertRaisesRegex(ValueError, 'not cut or sped up'):
            timing.target(7, timing.options(10, 4))
        self.assertEqual(timing.target(7, timing.options(None, 4)),11)

    def test_bad_timing_rejected(self):
        for value in [-1, 0, 121, float('nan'), float('inf'), True]:
            with self.assertRaises(ValueError): timing.options(value)
        for beats in [[], [{}], [{'seconds':2,'prompt':'x'}], {'seconds':20,'prompt':'x'}]:
            with self.assertRaises(ValueError): timing.options(20, 0, beats)

    def test_lips_remain_within_existing_model_limits_including_tiny_tail(self):
        for fps in (4,16,30):
            for seconds in (.2, 8, 8.001, 16.01, 20, 119.99, 120):
                pieces = list(timing.lip_chunks(seconds, fps))
                self.assertTrue(all(.2 <= length <= 8 for _,length in pieces), pieces)
                self.assertAlmostEqual(sum(p[1] for p in pieces),seconds)
                self.assertAlmostEqual(pieces[-1][0]+pieces[-1][1],seconds)

    def test_catalog_example_round_trips_to_timing(self):
        from media_tool_api import capabilities
        data = capabilities('dialogue-video')[0]
        argv = data['example']['arguments']
        self.assertEqual(timing.options(float(argv[3]),float(argv[5]),argv[7])['duration'],20)

    def test_native_motion_rejects_short_model_output(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        bridge = Mock();bridge.run.return_value={'files':['short.mp4']}
        with patch.object(ai_tools,'workflow_key',return_value='video'), patch.object(ai_tools,'_workflow_models',return_value=[]), \
             patch.object(ai_tools,'_set_gpu_state'), patch.object(ai_tools,'resolve_root',side_effect=Path), \
             patch.object(ai_tools,'_media_duration_seconds',return_value=1):
            with self.assertRaisesRegex(RuntimeError,'too short'):
                ai_tools._generate_dialogue_motion(bridge,Path('source.png'),'default',1,16,
                    timing.motion_chunks(20,16,81,'action'),SimpleNamespace(width=256,height=256),
                    {'outputs':{'videos':'outputs'}},lambda:None)
        self.assertEqual(bridge.run.call_count,1)

    def test_native_stop_prevents_next_lip_model(self):
        from unittest.mock import Mock
        check=Mock(side_effect=RuntimeError('stopped'))
        with patch.object(ai_tools,'MuseTalkBridge') as bridge:
            with self.assertRaisesRegex(RuntimeError,'stopped'):
                ai_tools._sync_dialogue_segments('video','voice',20,16,check)
        bridge.assert_not_called()


class ExactPageTests(unittest.TestCase):
    def test_compacted_history_pages_reconstruct_original_exactly(self):
        original = 'Help start\n' + ('escaped " \\ 😃 --duration 20\n' * 180) + 'last flag'
        session={'messages':[{'role':'tool','content':original}]}
        offset=0; collected=''
        while True:
            raw=evidence.execute(session,{'action':'read','message_id':0,'offset':offset,'limit':8000})
            page=json.loads(evidence.project({'name':'chat_history','content':raw},1,600))
            self.assertLessEqual(len(json.dumps(page,ensure_ascii=False)),600)
            self.assertEqual(page['text'],original[offset:offset+len(page['text'])])
            collected+=page['text']
            if page['complete']:break
            self.assertGreater(page['next_offset'],offset)
            offset=page['next_offset']
        self.assertEqual(collected,original)

    def test_short_complete_help_is_not_truncated_without_pressure(self):
        raw=evidence.execute({'messages':[{'content':'a'*1631}]},{'action':'read','message_id':0})
        self.assertEqual(evidence.project({'name':'chat_history','content':raw},1,4000),raw)

    def test_file_pages_have_same_exact_cursor_behavior(self):
        import native_chat
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'help.txt';p.write_text('0123456789'*200,encoding='utf-8')
            runtime=Mock();runtime.safe_path.return_value=p
            raw=native_chat.ToolRuntime.read_file(runtime,str(p),900,100)
            row=json.loads(evidence.project({'name':'read_file','content':raw},1,600))
            self.assertEqual(row['text'],p.read_text()[100:row['next_offset']])
            self.assertFalse(row['complete'])
            end=json.loads(native_chat.ToolRuntime.read_file(runtime,str(p),900,1900))
            self.assertTrue(end['complete']);self.assertIsNone(end['next_offset'])

@unittest.skipUnless(os.environ.get('PORTALAI_TEST_REAL_DIALOGUE_MEDIA') == '1', 'Explicit synthetic FFmpeg fixture')
class NativeAssemblyTests(unittest.TestCase):
    def test_twenty_second_native_segments_and_audio_alignment(self):
        from contextlib import ExitStack
        from types import SimpleNamespace
        from unittest.mock import Mock
        from platform_runtime import ffmpeg_path
        ffmpeg, probe = ffmpeg_path(ROOT), ffmpeg_path(ROOT, True)
        if not ffmpeg.is_file() or not probe.is_file():self.skipTest('Bundled FFmpeg unavailable')
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            work=Path(directory)
            for name, value in [('_find_ffmpeg', str(ffmpeg)),('_find_ffprobe',str(probe))]:
                stack.enter_context(patch.object(ai_tools,name,return_value=value))
            stack.enter_context(patch.object(ai_tools,'media_reference',side_effect=lambda root,p:Path(p)))
            stack.enter_context(patch.object(ai_tools,'media_output',side_effect=lambda root,p:Path(p)))
            stack.enter_context(patch.object(ai_tools,'_runtime_media_path',side_effect=lambda prefix,suffix:work/(prefix+uuid.uuid4().hex+suffix)))
            stack.enter_context(patch.object(ai_tools,'resolve_root',side_effect=lambda p:work))
            stack.enter_context(patch.object(ai_tools,'workflow_key',return_value='video'))
            stack.enter_context(patch.object(ai_tools,'_workflow_models',return_value=[]))
            stack.enter_context(patch.object(ai_tools,'_set_gpu_state'))
            bridge=Mock(); specs=[]
            def configure(*args):specs.append(args)
            bridge.configure_video.side_effect=configure
            def generate(*args):
                out=work/f'graph_{len(specs)}.mp4'
                ai_tools._run_ffmpeg(['-f','lavfi','-i','testsrc2=size=256x256:rate=16',
                    '-frames:v',str(specs[-1][-2]),'-c:v','libx264','-threads','2','-pix_fmt','yuv420p',str(out)])
                return {'files':[str(out)]}
            bridge.run.side_effect=generate
            pieces=timing.motion_chunks(20,16,81,'action')
            motion=ai_tools._generate_dialogue_motion(bridge,work/'source.png','official',1,16,pieces,
                SimpleNamespace(width=256,height=256),{'outputs':{'videos':'outputs'}},lambda:None)
            self.assertEqual(len(specs),4)
            self.assertTrue(all(args[-2]<=81 for args in specs))
            self.assertTrue(all(Path(call.args[0]).is_file() for call in bridge.upload_image.call_args_list[1:]))
            voice=work/'voice.wav'
            ai_tools._run_ffmpeg(['-f','lavfi','-i','sine=frequency=220:sample_rate=24000','-t','2','-c:a','pcm_s16le',str(voice)])
            video,audio,duration=ai_tools._prepare_generated_dialogue_video(motion,voice,timing.options(20,5))
            lip_lengths=[]
            def lips(video,audio,**kwargs):
                lip_lengths.append(ai_tools._media_duration_seconds(audio))
                output=work/f'lip_{len(lip_lengths)}.mp4';shutil.copy2(video,output)
                return {'files':[str(output)]}
            model=Mock();model.sync.side_effect=lips
            with patch.object(ai_tools,'MuseTalkBridge',return_value=model):
                result=ai_tools._sync_dialogue_segments(video,audio,duration,16,lambda:None)
            self.assertEqual(len(lip_lengths),3);self.assertTrue(all(.2<=v<=8 for v in lip_lengths))
            final=ai_tools._finalize_dialogue_track(result['files'][0],audio,work/'final.mp4',duration)
            self.assertAlmostEqual(ai_tools._media_duration_seconds(final),20.,places=1)
            import array, wave
            with wave.open(str(audio)) as wav:
                samples=array.array('h',wav.readframes(wav.getnframes()))
            self.assertEqual(len(samples),20*48000)
            self.assertEqual(max(map(abs,samples[:5*48000])),0)
            self.assertGreater(max(map(abs,samples[5*48000:7*48000])),1000)
            self.assertEqual(max(map(abs,samples[7*48000+100:])),0)


if __name__ == '__main__': unittest.main()
