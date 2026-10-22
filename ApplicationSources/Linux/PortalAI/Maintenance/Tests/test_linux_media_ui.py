from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'ControlCenter')]
import media_devices as media
import native_chat as chat


class LinuxMediaUITests(unittest.TestCase):
    def test_capture_formats_only_advertised_inputs(self):
        media.capture_formats.cache_clear()
        result = subprocess.CompletedProcess([], 0, ' DE alsa ALSA\n D  pulse Pulse input\n E  oss output\n', '')
        with patch.object(media, 'ffmpeg_path', return_value=ROOT / 'PortalAI.exe'), patch.object(media.subprocess, 'run', return_value=result):
            self.assertEqual(media.capture_formats(str(ROOT)), ('pulse', 'alsa'))
        media.capture_formats.cache_clear()

    def test_linux_auto_preserves_backend_fallback(self):
        with patch.object(media, 'capture_formats', return_value=('pulse', 'alsa')):
            choices = media.microphone_candidates(ROOT, 'auto')
            self.assertEqual([x['backend'] for x in choices], ['pulse', 'alsa'])
            self.assertEqual(media.microphone_candidates(ROOT, 'alsa:hw:2,0')[0]['device_id'], 'hw:2,0')
            with self.assertRaisesRegex(RuntimeError, 'Linux microphone selection'):
                media.microphone_candidates(ROOT, 'winmm:1')

    def test_microphone_values_are_arguments_not_shell(self):
        device = 'source ; touch /tmp/wrong'
        cmd = media.capture_command(ROOT, {'backend': 'pulse', 'device_id': device})
        self.assertEqual(cmd[cmd.index('-i') + 1], device)
        self.assertIn('-nostdin', cmd)
        with self.assertRaises(ValueError):
            media.capture_command(ROOT, {'backend': 'lavfi'})

    def test_player_uses_bundled_loader_and_parent_guard(self):
        command = media.linux_player_command(ROOT, ROOT / 'Outputs/example.wav', audio_only=True)
        self.assertEqual(Path(command[0]).name, 'ld-linux-x86-64.so.2')
        self.assertIn('-nodisp', command)
        guarded = media.owned_linux_command(ROOT, command)
        self.assertEqual(Path(guarded[0]).name, 'run-python')
        self.assertIn(str(os.getpid()), guarded)
        self.assertIn(str(ROOT / 'ControlCenter/linux_media_exec.py'), guarded)

    def test_linux_play_dispatches_to_owned_player(self):
        panel = chat.NativeChat.__new__(chat.NativeChat)
        panel._play_linux_media = Mock()
        panel._notice = Mock()
        with patch.object(chat, 'os', SimpleNamespace(name='posix')):
            panel._play_audio_here(ROOT / 'Outputs/audio.wav')
        panel._play_linux_media.assert_called_once_with(ROOT / 'Outputs/audio.wav', audio_only=True)
        panel._notice.assert_not_called()

    def test_linux_mic_selection_and_manual_writer_are_connected(self):
        panel = chat.NativeChat.__new__(chat.NativeChat)
        panel.root = ROOT
        panel.settings = {'microphone_device': 'auto'}
        panel.conversation_active = threading.Event()
        panel.busy = False
        panel.store = SimpleNamespace(recordings=ROOT / 'Outputs')
        panel.mic_stop_event = threading.Event()
        panel.mic_btn = Mock()
        panel.model_lbl = Mock()
        panel.COL = {'bad': 'red'}
        panel._notice = Mock()
        from writer_jobs import WriterJobs
        panel._writer_jobs = WriterJobs()
        panel._manual_wave_writer = Mock()
        candidate = {'backend': 'pulse', 'device_id': 'default', 'name': 'pulse:default'}
        stream = Mock()
        panel._open_mic_candidate = Mock(return_value=(stream, candidate['name']))
        with patch.object(chat, 'os', SimpleNamespace(name='posix')), \
             patch.object(media, 'microphone_candidates', return_value=[candidate]), \
             patch.object(panel._writer_jobs, 'thread', wraps=panel._writer_jobs.thread) as thread:
            panel.start_mic()
        panel._writer_jobs.close()
        self.assertTrue(panel.wait_for_writers(2)['stopped'])
        self.assertIs(panel.mic_stream, stream)
        self.assertIsNone(panel.mic_proc)
        self.assertEqual(thread.call_args.kwargs['target'], panel._manual_wave_writer)
        panel._manual_wave_writer.assert_called_once_with(stream, panel.mic_path)
        panel._notice.assert_not_called()

    def test_directshow_manual_capture_writes_a_file(self):
        panel = chat.NativeChat.__new__(chat.NativeChat)
        panel.conversation_active = threading.Event()
        panel.busy = False
        panel.store = SimpleNamespace(recordings=ROOT / 'Outputs')
        panel._mic_candidates = Mock(return_value=[{'backend': 'dshow', 'name': 'Microphone'}])
        panel._start_ffmpeg_mic = Mock(return_value=Mock())
        panel._open_mic_candidate = Mock(side_effect=AssertionError('raw PCM pipe is not a WAV recording'))
        panel.mic_btn = Mock()
        panel.model_lbl = Mock()
        panel.COL = {'bad': 'red'}
        panel.start_mic()
        self.assertEqual(panel._start_ffmpeg_mic.call_args.args[0], 'Microphone')
        self.assertEqual(panel._start_ffmpeg_mic.call_args.args[1].suffix, '.wav')

    def test_external_open_reports_missing_desktop_handler(self):
        # Desktop-handler behavior belongs to an isolated unprofiled fixture;
        # the installed account registry may correctly be locked during tests.
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'PORTALAI_PROFILE_ID':'', 'PORTALAI_PROFILE_EPOCH':''}):
            root = Path(folder)
            target = root/'synthetic.txt'; target.write_text('fixture')
            with patch.object(media, 'os', SimpleNamespace(name='posix')), patch.object(media.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'xdg-open'):
                    media.open_external(root, target)


if __name__ == '__main__':
    unittest.main()
