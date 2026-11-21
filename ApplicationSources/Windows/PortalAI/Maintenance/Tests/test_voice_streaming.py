"""Streaming reserve, cancellation, portability and CPU preloading regressions."""
from array import array
import importlib.util
import io
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
from voice_pcm_player import PlaybackBuffer, PCMPlayer
from chat_voice import VoiceStopped


class BufferTests(unittest.TestCase):
    def test_fast_producer_keeps_two_chunks_before_playback(self):
        buffer = PlaybackBuffer()
        a, b = b'a'*46080, b'b'*46080
        self.assertFalse(buffer.add(a, 20))
        self.assertTrue(buffer.add(b, 20.6))
        self.assertEqual(b''.join(buffer.drain()), a+b)
        self.assertEqual(buffer.drain(), [])

    def test_slow_producer_buffers_until_eof_without_dropping_samples(self):
        buffer = PlaybackBuffer()
        chunks = [bytes([n])*46080 for n in range(20)]
        for n, raw in enumerate(chunks):
            self.assertFalse(buffer.add(raw, 20+1.9*n))
        self.assertEqual(b''.join(buffer.drain()), b''.join(chunks))

    def test_startup_import_time_does_not_count_as_generation_speed(self):
        buffer = PlaybackBuffer()
        self.assertFalse(buffer.add(b'a'*46080, 120))
        self.assertTrue(buffer.add(b'b'*46080, 120.6))

    def test_delayed_second_chunk_can_recover_with_later_fast_chunks(self):
        buffer = PlaybackBuffer()
        self.assertFalse(buffer.add(b'a'*46080, 0))
        self.assertFalse(buffer.add(b'b'*46080, 1.9))
        self.assertFalse(buffer.add(b'c'*46080, 2.1))
        self.assertTrue(buffer.add(b'd'*46080, 2.3))

    def test_complete_short_reply_still_plays(self):
        buffer = PlaybackBuffer()
        self.assertFalse(buffer.add(b'a'*6000, 1))
        self.assertEqual(buffer.drain(), [b'a'*6000])


class PlayerTests(unittest.TestCase):
    def player(self):
        player = PCMPlayer.__new__(PCMPlayer)
        player.voice = SimpleNamespace(check=lambda: None, activity=None)
        player.job = Mock()
        player.proc = Mock()
        player.proc.poll.return_value = None
        player.error = None
        player.started = None
        player.closed = False
        player.samples = 0
        player.envelope = []
        player.envelope_pending = b''
        player.queue = queue.Queue()
        return player

    def test_writer_drains_slow_producer_exactly_once_after_completion(self):
        player = self.player()
        chunks = [bytes([i])*46080 for i in range(8)]
        for i, raw in enumerate(chunks):
            player.queue.put((raw, i*1.9))
        player.queue.put(None)
        player.write()
        self.assertIsNone(player.error)
        self.assertEqual(b''.join(c.args[0] for c in player.proc.stdin.write.call_args_list), b''.join(chunks))
        player.proc.stdin.close.assert_called_once()

    def test_cancellation_during_buffering_is_immediate(self):
        player = self.player()
        player.voice.check = Mock(side_effect=VoiceStopped('Stopped'))
        with self.assertRaises(VoiceStopped):
            player.put((b'a'*46080, 1))
        self.assertTrue(player.queue.empty())
        player.proc.stdin.write.assert_not_called()

    def test_read_sharing_violation_retries_before_publishing_any_samples(self):
        player = self.player()
        raw = array('h', [7000]*2400).tobytes()
        payload = io.BytesIO()
        with wave.open(payload, 'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'))
            wav.writeframes(raw)
        real_open = wave.open
        attempts = 0
        def open_chunk(*args):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError('scanner')
            return real_open(io.BytesIO(payload.getvalue()), 'rb')
        with patch('voice_pcm_player.wave.open', side_effect=open_chunk), patch('voice_pcm_player.time.sleep'):
            player.push('speech.wav')
        self.assertEqual(attempts, 2)
        self.assertEqual(player.samples, len(raw))
        self.assertEqual(player.queue.get_nowait()[0], raw)
        self.assertTrue(player.queue.empty())

    def test_stop_during_file_retry_never_publishes(self):
        player = self.player()
        player.voice.check = Mock(side_effect=[None, VoiceStopped('Stopped')])
        with patch('voice_pcm_player.wave.open', side_effect=PermissionError), patch('voice_pcm_player.time.sleep'):
            with self.assertRaises(VoiceStopped):
                player.push('speech.wav')
        self.assertEqual(player.samples, 0)
        self.assertTrue(player.queue.empty())


class PortabilityTests(unittest.TestCase):
    def test_relocated_player_uses_that_roots_bundled_ffplay(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI relocated voice ') as folder:
            voice = SimpleNamespace(root=Path(folder), check=lambda: None, activity=None)
            proc = Mock()
            proc.poll.return_value = 0
            with patch('voice_pcm_player.subprocess.Popen', return_value=proc) as launch, \
                 patch('voice_pcm_player.threading.Thread'), patch('mission_supervisor.WorkerJob'), \
                 patch('runtime_policy.portable_env', return_value={}) as env:
                with PCMPlayer(voice, -.5):
                    pass
            self.assertEqual(launch.call_args.args[0][0], str(Path(folder)/'Tools/ffmpeg/bin/ffplay.exe'))
            env.assert_called_once_with(voice.root)

    def test_cpu_or_rocm_retains_original_predictor_and_restores_method(self):
        import qwen_voice_acceleration
        for cuda, hip in ((False, None), (True, 'rocm')):
            original = Mock(return_value='original')
            predictor = SimpleNamespace(generate=original)
            model = SimpleNamespace(model=SimpleNamespace(talker=SimpleNamespace(code_predictor=predictor)))
            torch = SimpleNamespace(version=SimpleNamespace(hip=hip))
            kwargs = dict(inputs_embeds=SimpleNamespace(is_cuda=cuda), max_new_tokens=15, do_sample=True,
                          top_p=1., top_k=50, temperature=.9, output_hidden_states=True, return_dict_in_generate=True)
            with patch.dict(sys.modules, {'torch': torch}):
                with qwen_voice_acceleration.accelerate(model):
                    self.assertEqual(predictor.generate(**kwargs), 'original')
            self.assertIs(predictor.generate, original)
            original.assert_called_once_with(**kwargs)

    def test_invalid_configuration_never_uses_specialized_decoder(self):
        import qwen_voice_acceleration
        original = Mock(return_value='original')
        predictor = SimpleNamespace(generate=original)
        model = SimpleNamespace(model=SimpleNamespace(talker=SimpleNamespace(code_predictor=predictor)))
        with patch.dict(sys.modules, {'torch': SimpleNamespace()}):
            with qwen_voice_acceleration.accelerate(model):
                self.assertEqual(predictor.generate(unsupported=True), 'original')
        self.assertIs(predictor.generate, original)


class PreparationTests(unittest.TestCase):
    def test_large_memory_host_prepares_cpu_model_with_bounded_job(self):
        from voice_prewarm import PreparedVoice
        gib = 1024**3
        hw = {'ram_total_bytes':32*gib, 'ram_available_bytes':16*gib,
              'gpus':[{'backend':'cuda','index':0}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc, job = Mock(), Mock()
            proc.poll.return_value = None
            with patch('runtime_policy.detect_hardware', return_value=hw), patch('runtime_policy.require_space'), \
                 patch('runtime_policy.portable_env', return_value={}), patch('media_paths.media_runtime', return_value=root), \
                 patch('platform_runtime.python_path', return_value=root/'Runtime/BootstrapPython/python.exe'), \
                 patch('platform_runtime.worker_process_options', return_value={}), \
                 patch('voice_prewarm.subprocess.Popen', return_value=proc) as launch, \
                 patch('mission_supervisor.WorkerJob', return_value=job), patch('voice_prewarm.threading.Thread'):
                ticket = PreparedVoice.start(root, lambda: None)
                self.assertEqual(launch.call_args.kwargs['env']['PORTALAI_VOICE_PRELOAD'], '1')
                job.limit_memory.assert_called_once_with(8*gib)
                ticket.close()
                job.close.assert_called_once()

    def test_moderate_memory_host_only_prepares_imports(self):
        from voice_prewarm import PreparedVoice
        gib = 1024**3
        hw = {'ram_total_bytes':16*gib, 'ram_available_bytes':9*gib,
              'gpus':[{'backend':'cuda','index':0}]}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc, job = Mock(), Mock()
            proc.poll.return_value = None
            with patch('runtime_policy.detect_hardware', return_value=hw), patch('runtime_policy.require_space'), \
                 patch('runtime_policy.portable_env', return_value={}), patch('media_paths.media_runtime', return_value=root), \
                 patch('platform_runtime.python_path', return_value=root/'Runtime/BootstrapPython/python.exe'), \
                 patch('platform_runtime.worker_process_options', return_value={}), \
                 patch('voice_prewarm.subprocess.Popen', return_value=proc) as launch, \
                 patch('mission_supervisor.WorkerJob', return_value=job), patch('voice_prewarm.threading.Thread'):
                ticket = PreparedVoice.start(root, lambda: None)
                self.assertNotIn('PORTALAI_VOICE_PRELOAD', launch.call_args.kwargs['env'])
                job.limit_memory.assert_called_once_with(2*gib)
                ticket.close()


if __name__ == '__main__':
    unittest.main()
