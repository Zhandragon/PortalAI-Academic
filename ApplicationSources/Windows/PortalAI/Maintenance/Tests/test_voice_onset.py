"""Speech onset, same-stream priming, visualizer timing and cancellation tests."""
from array import array
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
import wave

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter')]
import chat_voice


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);player=self.root/'Tools/ffmpeg/bin/ffplay.exe'
        player.parent.mkdir(parents=True);player.touch()
        self.path=self.root/'speech.wav';self.clock=0.;self.events=[];self.commands=[]
        with wave.open(str(self.path),'wb') as w:
            w.setparams((1,2,24000,0,'NONE','not compressed'));w.writeframes(array('h',[7000]*4800).tobytes())
        self.original=self.path.read_bytes()
        self.activity=Mock()
        self.activity.phase.side_effect=lambda phase,text:self.events.append(('phase',self.clock,phase))
        self.activity.level.side_effect=lambda level,**kw:self.events.append(('level',self.clock,level))
        self.voice=chat_voice.VoiceIO(self.root,lambda:None,activity=self.activity)
        self.proc=Mock();self.proc.returncode=None
        self.proc.poll.side_effect=lambda:self.proc.returncode
        self.proc.kill.side_effect=lambda:setattr(self.proc,'returncode',-1)
        def communicate(timeout):
            if self.clock<1.0:
                self.clock=round(self.clock+.1,3)
                raise subprocess.TimeoutExpired('fixture',timeout)
            self.proc.returncode=0;return None,b''
        self.proc.communicate.side_effect=communicate
        self.job=Mock()

    def play(self,**kwargs):
        def launch(command,**kw):self.commands.append(command);return self.proc
        with patch.object(chat_voice.subprocess,'Popen',side_effect=launch), \
             patch.object(chat_voice.time,'monotonic',side_effect=lambda:self.clock), \
             patch('mission_supervisor.WorkerJob',return_value=self.job), \
             patch('runtime_policy.portable_env',return_value={}), \
             patch('platform_runtime.worker_process_options',return_value={}):
            self.voice.play(self.path,**kwargs)

    def test_qwen_primes_same_stream_and_preserves_source(self):
        self.play()
        cmd=self.commands[0]
        self.assertEqual(cmd[cmd.index('-af')+1],'adelay=500:all=1,apad=pad_dur=0.35')
        self.assertEqual(cmd[-1],str(self.path));self.assertEqual(self.path.read_bytes(),self.original)
        self.assertEqual(len(self.commands),1)

    def test_piper_primes_after_unchanged_pitch_filter(self):
        self.play(pitch_semitones=2)
        cmd=self.commands[0]
        self.assertEqual(cmd[cmd.index('-af')+1],'rubberband=pitch=1.122462048,adelay=500:all=1,apad=pad_dur=0.35')

    def test_orb_and_envelope_wait_for_lead_in_then_end_at_silence(self):
        self.play()
        speaking=[at for kind,at,value in self.events if kind=='phase' and value=='speaking']
        self.assertEqual(speaking,[.5])
        levels=[(at,value) for kind,at,value in self.events if kind=='level']
        self.assertTrue(all(value==0 for at,value in levels if at<.5))
        self.assertTrue(any(value>0 for at,value in levels if .5<=at<.7))
        self.assertTrue(all(value==0 for at,value in levels if at>=.8))
        self.job.close.assert_called_once()

    def test_stop_during_lead_in_kills_only_owned_player_before_speaking(self):
        def check():
            if self.clock>=.2:raise chat_voice.VoiceStopped('Test Stop')
        with self.assertRaises(chat_voice.VoiceStopped):self.play(check=check)
        self.assertFalse(any(kind=='phase' and value=='speaking' for kind,at,value in self.events))
        self.proc.kill.assert_called_once();self.job.close.assert_called_once()
        self.assertEqual(self.events[-1][2],0)

    def test_profile_revocation_during_lead_in_cleans_up(self):
        def check():
            if self.clock>=.2:raise RuntimeError('Profile locked')
        with self.assertRaisesRegex(RuntimeError,'Profile locked'):self.play(check=check)
        self.proc.kill.assert_called_once();self.job.close.assert_called_once()

    def test_failed_player_still_reports_error_and_cleans_up(self):
        def failure(timeout):self.proc.returncode=1;return None,b'audio unavailable'
        self.proc.communicate.side_effect=failure
        with self.assertRaisesRegex(RuntimeError,'audio unavailable'):self.play()
        self.job.close.assert_called_once()


class FilterSampleTests(unittest.TestCase):
    def test_every_qwen_pcm_sample_survives_for_mono_and_stereo(self):
        self.verify_samples(False)

    def test_pitch_filter_output_is_only_padded_not_reprocessed(self):
        self.verify_samples(2.0)
        self.verify_samples(-.5)

    def verify_samples(self,pitch):
        ffmpeg=Path(os.environ.get('PORTALAI_TEST_FFMPEG',str(ROOT/'Tools/ffmpeg/bin/ffmpeg.exe')))
        if not ffmpeg.is_file():self.skipTest('Bundled FFmpeg required for exact PCM test')
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            for channels in (1,2):
                src=base/'source.wav';rate=24000
                samples=array('h',[(i*137)%20000-10000 for i in range(rate*channels)])
                with wave.open(str(src),'wb') as w:
                    w.setparams((channels,2,rate,0,'NONE','not compressed'));w.writeframes(samples.tobytes())
                expected=base/'expected.wav';actual=base/'actual.wav'
                filter='rubberband=pitch='+format(2**(pitch/12),'.9f') if pitch else 'anull'
                for out,filters in ((expected,filter),(actual,filter+',adelay=500:all=1,apad=pad_dur=0.35')):
                    subprocess.run([str(ffmpeg),'-v','error','-nostdin','-y','-i',str(src),'-af',filters,'-c:a','pcm_s16le',str(out)],check=True,timeout=15,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                with wave.open(str(expected),'rb') as a,wave.open(str(actual),'rb') as b:
                    raw=a.readframes(a.getnframes());padded=b.readframes(b.getnframes())
                    lead=rate//2*channels*2
                    self.assertEqual(padded[:lead],bytes(lead))
                    self.assertEqual(padded[lead:lead+len(raw)],raw)
                    self.assertEqual(padded[lead+len(raw):],bytes(round(rate*.35)*channels*2))


if __name__=='__main__':unittest.main()
