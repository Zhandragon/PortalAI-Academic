"""Real Tk rendering, PCM state, and muted capture using disposable audio."""
import queue,struct,tempfile,threading,tkinter as tk,unittest,wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
from voice_activity import VoiceActivity,pcm_level
from voice_visualizer import VoiceVisualizer,blend
from test_account_presentation_tk import LIGHT,DARK
from tk_fixture_cleanup import finish_tk_fixture
import native_chat as chat


class ActivityTests(unittest.TestCase):
    def test_pcm_silence_loudness_and_odd_sample(self):
        self.assertEqual(pcm_level(b'\0'*3200),0)
        self.assertEqual(pcm_level(b'\0'),0)
        self.assertGreater(pcm_level(struct.pack('<h',9000)*1600),.99)

    def test_fade_and_microphone_mute_preserve_speaker_activity(self):
        a=VoiceActivity()
        with patch('voice_activity.time.monotonic',return_value=10):a.level(1)
        with patch('voice_activity.time.monotonic',return_value=10.35):self.assertAlmostEqual(a.snapshot()['level'],.5)
        with patch('voice_activity.time.monotonic',return_value=10.6):self.assertEqual(a.snapshot()['level'],0)
        a.toggle_mute();a.level(1);self.assertEqual(a.snapshot()['level'],0)
        a.phase('speaking');a.level(1,source='speaker');self.assertGreater(a.snapshot()['level'],.99)

    def test_muting_discards_partial_utterance_and_does_not_stop_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            a=VoiceActivity();p=chat.NativeChat.__new__(chat.NativeChat)
            p.settings={'conversation_silence_seconds':.3,'conversation_min_speech_seconds':.2}
            p.ev=queue.Queue();p.busy=False;p.conversation_turn=0
            p.conversation_active=threading.Event();p.conversation_active.set()
            p._conversation_io=SimpleNamespace(check=lambda:None,activity=a)
            p.store=SimpleNamespace(recordings=Path(folder))
            class Capture:
                sample_rate=16000;channels=1
                count=0
                def read_chunk(self,**kw):
                    self.count+=1
                    if self.count==3:a.toggle_mute()
                    if self.count==5:a.toggle_mute()
                    if self.count>12:raise AssertionError('Capture did not finish')
                    value=7000 if self.count<5 else 3000 if self.count<8 else 0
                    return struct.pack('<h',value)*1600
            with patch.object(chat,'WindowsWaveInStream',Capture):out=p._capture_conversation_utterance(Capture(),'synthetic')
            self.assertIsNotNone(out)
            with wave.open(str(out),'rb') as f:data=f.readframes(f.getnframes())
            self.assertNotIn(struct.pack('<h',7000)*10,data)
            self.assertIn(struct.pack('<h',3000)*10,data)


class VisualizerTkTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.withdraw();self.errors=[]
        self.app.report_callback_exception=lambda *a:self.errors.append(str(a))
        self.addCleanup(finish_tk_fixture,self.app)

    def test_real_widget_turquoise_gold_mute_and_timer_lifecycle(self):
        for palette in (LIGHT,DARK):
            palette={**palette,'gold':palette['gold_mid'],'cyan':palette['accent']}
            v=VoiceVisualizer(self.app,palette);a=VoiceActivity();v.show(a)
            self.app.update();self.assertIsNotNone(v._after)
            a.phase('speaking');a.level(1,source='speaker')
            for _ in range(20):v._paint()
            colors=[v.canvas.itemcget(i,'fill') for i in v.canvas.find_withtag('voice') if v.canvas.type(i)=='line']
            self.assertIn(palette['cyan'].lower(),colors)
            self.assertIsNotNone(v.logo)
            self.assertEqual(len(v.logo.frames),24)
            self.assertLess(v.logo.pixel_bytes,100*1024)
            self.assertEqual(v.canvas.itemcget(v.canvas.find_withtag('logo-frame')[0],'image'),str(v.logo.base))
            a.level(0)
            for _ in range(40):v._paint()
            colors=[v.canvas.itemcget(i,'fill') for i in v.canvas.find_withtag('voice') if v.canvas.type(i)=='line']
            self.assertIn(palette['gold'].lower(),colors)
            v.toggle_mute();self.assertTrue(a.muted);self.assertEqual(v.mute.cget('text'),'Unmute microphone')
            v.hide();self.assertIsNone(v._after);self.assertFalse(v._visible)
            v.show(a);v.destroy();self.app.update();self.assertEqual(self.errors,[])

    def test_palette_blend_boundaries(self):
        self.assertEqual(blend('#A88446','#58B7C7',0),'#a88446')
        self.assertEqual(blend('#A88446','#58B7C7',1),'#58b7c7')

    def test_orb_is_static_until_nice_speaks_even_with_microphone_audio(self):
        palette={**LIGHT,'gold':LIGHT['gold_mid'],'cyan':LIGHT['accent']}
        v=VoiceVisualizer(self.app,palette);a=VoiceActivity();v.show(a)
        def geometry():return [(v.canvas.coords(i),v.canvas.itemcget(i,'image')) for i in v.canvas.find_withtag('orb')]
        for phase in ('listening','thinking','transcribing','restoring'):
            a.phase(phase);a.level(1)
            with patch('voice_visualizer.time.monotonic',return_value=10):v._paint();first=geometry()
            with patch('voice_visualizer.time.monotonic',return_value=11):v._paint();second=geometry()
            self.assertEqual(first,second,phase)
        a.phase('speaking');a.level(1,source='speaker')
        with patch('voice_visualizer.time.monotonic',return_value=12):v._paint();first=geometry()
        with patch('voice_visualizer.time.monotonic',return_value=13):v._paint();second=geometry()
        self.assertNotEqual(first,second)
        v.destroy()


if __name__=='__main__':unittest.main()
