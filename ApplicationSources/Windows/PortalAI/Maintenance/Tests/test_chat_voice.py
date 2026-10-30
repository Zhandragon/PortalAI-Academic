"""Missing STT bindings, voice turn ownership, and actual Tk event-loop routing."""
import json
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('Agent', 'ControlCenter', 'Tools', 'Maintenance/Tests')]
import stt_bridge
import native_chat as chat
from chat_voice import VoiceIO, VoiceTurn, VoiceStopped, spoken_chunks
import test_chat_timeline as timeline


class RuntimeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='STT binding fixture ')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'Tools').mkdir()
        shutil.copyfile(ROOT/'Tools/stt_runtime.py', self.root/'Tools/stt_runtime.py')
        self.exe = self.root/'Runtime/BootstrapPython/python.exe'
        self.exe.parent.mkdir(parents=True); self.exe.touch()
        self.packages = self.root/'SpeechToText/python_packages'
        self.packages.mkdir(parents=True)
        self.state = self.root/'Agent/.runtime/stt_runtime.json'
        self.state.parent.mkdir(parents=True)
        self.location = patch.object(stt_bridge, '__file__', str(self.root/'Agent/stt_bridge.py'))
        self.location.start(); self.addCleanup(self.location.stop)

    def probe(self, ok=True):
        return patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0 if ok else 1,
                     json.dumps({'python':'3.12.14','faster_whisper':'fixture'}), '' if ok else 'missing package'))

    def test_absent_binding_resolves_existing_packages_then_reuses_cache(self):
        with self.probe() as probe:
            self.assertEqual(stt_bridge._portableai_stt_runtime(), (self.exe, self.packages))
            probe.assert_called_once()
        data = json.loads(self.state.read_text())
        self.assertEqual(data['status'], 'LOCKED_PACKAGE_LAYER')
        self.assertFalse(Path(data['interpreter']).is_absolute())
        with patch('subprocess.run', side_effect=AssertionError('cached binding should be cheap')):
            self.assertEqual(stt_bridge._portableai_stt_runtime(), (self.exe, self.packages))

    def test_corrupt_stale_and_external_bindings_are_rediscovered_locally(self):
        for content in ('{broken', 'null', json.dumps({'interpreter':'missing.exe','package_layer':'gone'}),
                        json.dumps({'interpreter':'C:/outside/python.exe','package_layer':'../outside'})):
            self.state.write_text(content)
            with self.probe():
                self.assertEqual(stt_bridge._portableai_stt_runtime(), (self.exe, self.packages))

    def test_failed_probe_does_not_download_or_pretend_success(self):
        with self.probe(False), patch('urllib.request.urlopen', side_effect=AssertionError('no network')):
            with self.assertRaisesRegex(RuntimeError, 'packages could not be loaded'):
                stt_bridge._portableai_stt_runtime()
        data = json.loads(self.state.read_text())
        self.assertEqual(data['status'], 'UNRESOLVED')
        self.assertIn('missing package', data['attempts'][0]['error'])


class SpeechTests(unittest.TestCase):
    def test_chunks_bound_utf8_without_losing_long_reply(self):
        text = ('Hello world. 你好世界! ' * 800).strip()
        chunks = list(spoken_chunks(text))
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(c.encode('utf-8')) <= 1800 for c in chunks))
        self.assertEqual(''.join(chunks).replace(' ', ''), text.replace(' ', ''))

    def test_markup_is_spoken_as_prose_without_modifying_saved_text(self):
        original = '# Answer\n**Hello** [there](https://example.com)\n```python\ndelete_everything()\n```'
        spoken = ' '.join(spoken_chunks(original))
        self.assertIn('Hello there', spoken)
        self.assertIn('Code is shown in the chat.', spoken)
        self.assertNotIn('delete_everything', spoken)
        self.assertIn('delete_everything', original)

    def test_final_reply_excludes_tool_calls_reasoning_and_old_messages(self):
        turn = VoiceTurn('a', 'question', request_index=1)
        session = {'id':'a','messages':[{'role':'assistant','content':'Old reply'}, {'role':'user','content':'question'},
                   {'role':'assistant','content':'Tool preamble','tool_calls':[{}]}, {'role':'tool','content':'private result'},
                   {'role':'assistant','content':'Final reply','reasoning':'Not spoken'}]}
        turn.finish(session)
        self.assertEqual(turn.reply, 'Final reply'); self.assertTrue(turn.done.is_set())

    def test_cancelled_incomplete_failed_or_switched_turn_never_speaks(self):
        for mode in ('cancelled','incomplete','error','switched','new-user'):
            turn = VoiceTurn('a', 'question', request_index=0)
            rows = [{'role':'user','content':'question'}, {'role':'assistant','content':'Do not speak'}]
            if mode == 'incomplete': rows[-1]['incomplete'] = True
            if mode == 'error': turn.failed = True
            if mode == 'new-user': rows.append({'role':'user','content':'new question'})
            turn.finish({'id':'b' if mode=='switched' else 'a','messages':rows}, mode=='cancelled')
            self.assertEqual(turn.reply, '', mode)
            self.assertTrue(turn.done.is_set())

    def test_cancellation_after_synthesis_prevents_audio_playback(self):
        voice = VoiceIO(ROOT, lambda: None)
        def synth(*a, **kw):
            voice.cancel()
            return {'files':['unused.wav']}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'unused.wav'
            with patch('piper_bridge.synthesize', side_effect=lambda *a, **kw: (voice.cancel() or {'files':[str(path)]})), \
                 patch('piper_bridge.output_path', return_value=path), patch.object(voice, 'play') as play:
                with self.assertRaises(VoiceStopped): voice.speak('Hello')
                play.assert_not_called()


class VoiceUITests(unittest.TestCase):
    setUp = timeline.TimelineTests.setUp

    def prepare(self):
        p = self.p
        p.root = ROOT; p.busy = False
        p.conversation_active = threading.Event(); p.conversation_active.set()
        p._conversation_request = None; p._mic_voice = None
        p.conversation_capture_lock = threading.Lock()
        p.conversation_capture_stream = p.conversation_capture_proc = None
        p.conversation_btn = Mock(); p.mic_btn = Mock()
        p.COL.update(cyan='#00ffff', good='#00ff00', panel='#111111')
        p.prompt = tk.Text(self.app)
        p._resize_prompt = Mock(); p._check_login = Mock()
        p._notice = Mock()
        return p

    def pump(self):
        self.p._pump(); self.app.update()
        self.assertEqual(self.errors, [])

    def test_two_turns_listen_transcribe_reply_speak_then_listen_again(self):
        p = self.prepare(); order = []; calls = [0]
        class Capture:
            def drain_pending(self): order.append('drain')
            def close(self): order.append('closed')
        capture = Capture()
        p._mic_candidates = Mock(return_value=[{'name':'synthetic'}])
        p._open_mic_candidate = Mock(return_value=(capture, 'synthetic'))
        def check():
            if not p.conversation_active.is_set(): raise VoiceStopped()
        voice = p._conversation_io = VoiceIO(ROOT, check)
        def capture_one(*a): order.append('listen'); return Path('synthetic.wav')
        p._capture_conversation_utterance = capture_one
        def transcribe(*a): order.append('transcribe'); return 'Question'
        voice.transcribe = transcribe
        def submit():
            order.append('submit'); p.busy = True
            p.session['messages'] += [{'role':'user','content':'Question'}, {'role':'assistant','content':'Visible spoken answer'}]
            p.ev.put(('assistant_start', {})); p.ev.put(('content', 'Visible spoken answer')); p.ev.put(('done', None))
        p.submit = submit
        def speak(text):
            self.assertEqual(text, 'Visible spoken answer')
            order.append('speak'); calls[0] += 1
            if calls[0] == 2: p.conversation_active.clear()
        voice.speak = speak
        with patch.object(chat, 'WindowsWaveInStream', Capture):
            worker = threading.Thread(target=p._conversation_loop)
            worker.start()
            try:
                deadline = time.monotonic() + 5
                while worker.is_alive() and time.monotonic() < deadline:
                    self.pump(); time.sleep(.01)
            finally:
                voice.cancel(); p.conversation_active.clear(); worker.join(3)
                self.assertFalse(worker.is_alive())
            self.pump()
        self.assertEqual([x for x in order if x != 'drain'], ['listen','transcribe','submit','speak']*2 + ['closed'])
        self.assertIn('Visible spoken answer', p.chat.get('1.0','end'))
        p._notice.assert_not_called()

    def test_manual_mic_puts_text_in_draft_without_sending(self):
        p = self.prepare(); p.conversation_active.clear(); p.submit = Mock()
        voice = p._mic_voice = VoiceIO(ROOT, lambda: None)
        p.ev.put(('mic_text', {'voice':voice, 'text':'Dictated text'})); p.ev.put(('mic_finished', voice))
        self.pump()
        self.assertEqual(p.prompt.get('1.0','end').strip(), 'Dictated text')
        p.submit.assert_not_called(); self.assertIsNone(p._mic_voice)

    def test_failed_submission_releases_waiting_voice_turn(self):
        p = self.prepare()
        for failure in ('login', 'submit'):
            with self.subTest(failure=failure):
                p._check_login = Mock(side_effect=RuntimeError('Expired login') if failure == 'login' else None)
                p.submit = Mock(side_effect=RuntimeError('Admission failed'))
                request = p._conversation_request = VoiceTurn(p.session['id'], 'Question')
                p.ev.put(('conversation_text', request))
                self.pump()
                self.assertTrue(request.done.is_set())
                self.assertTrue(request.failed)
                self.assertEqual(request.reply, '')

    def test_stopped_mic_and_previous_mode_cannot_publish_late_events(self):
        p = self.prepare(); old = VoiceIO(ROOT, lambda: None); old.cancel()
        p._mic_voice = old; p._conversation_io = VoiceIO(ROOT, lambda: None)
        p.ev.put(('mic_text', {'voice':old, 'text':'Late text'}))
        p.ev.put(('conversation_stopped', old))
        self.pump()
        self.assertEqual(p.prompt.get('1.0','end').strip(), '')
        p.conversation_btn.configure.assert_not_called()


if __name__ == '__main__': unittest.main()
