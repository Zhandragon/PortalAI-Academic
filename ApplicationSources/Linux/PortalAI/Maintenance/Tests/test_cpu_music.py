"""CPU music admission, task preservation, cancellation and publication fences."""
import ast
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import music_cpu as cpu
import music_selection as selection
import sdcpp_bridge as native
from profile_paths import UID_ENV, EPOCH_ENV, ProfileLocked


class CPUMusicTests(unittest.TestCase):
    def setUp(self):
        self.hw = {'system':'Windows', 'machine':'AMD64', 'ram_available_bytes':16*cpu.GIB, 'gpus':[]}
        self.request = dict(prompt='quiet piano', lyrics='', duration=15, instrumental=True, policy={})
        self.profile = {'engine':'musicgen-cpu', 'backend':'cpu', 'profile':'musicgen-small'}

    def test_limits_never_drop_lyrics_or_shorten_requested_audio(self):
        for duration in (1, 15.25, 30):cpu.validate_request('piano', '', duration, True)
        for lyrics, duration, instrumental in (('lyrics', 15, True), ('', 15, False), ('', 31, True),
                                                ('', 0, True), ('', math.nan, True)):
            with self.assertRaises(ValueError):cpu.validate_request('piano', lyrics, duration, instrumental)

    def test_cpu_memory_and_os_admission_precede_asset_load(self):
        with patch.object(cpu, 'assets') as assets:
            with self.assertRaisesRegex(RuntimeError, '10 GiB'):cpu.plan(ROOT, {**self.hw, 'ram_available_bytes':9*cpu.GIB})
            with self.assertRaisesRegex(RuntimeError, 'x64'):cpu.plan(ROOT, {**self.hw, 'machine':'arm64'})
            assets.assert_not_called()

    def test_explicit_cpu_never_probes_gpu(self):
        with patch.object(cpu, 'plan', return_value=self.profile), patch.object(selection, 'music_scaled') as gpu:
            result = selection.admit('musicgen-cpu', hardware=self.hw, **self.request)
        self.assertEqual(result, self.profile);gpu.assert_not_called()

    def test_automatic_cpu_only_after_gpu_admission_fails_before_inference(self):
        with patch('music_amd_bridge.plan', side_effect=RuntimeError('No GPU')), patch.object(cpu, 'plan', return_value=self.profile):
            result = selection.admit('auto', hardware=self.hw, **self.request)
        self.assertEqual(result['engine'], 'musicgen-cpu')
        self.assertIn('before inference', result['selection_note'])

    def test_explicit_gpu_and_vocal_requests_do_not_fall_back(self):
        with patch('music_amd_bridge.plan', side_effect=RuntimeError('No GPU')), patch.object(cpu, 'plan') as fallback:
            with self.assertRaisesRegex(RuntimeError, 'No GPU'):
                selection.admit('acestep-scaled', hardware=self.hw, **self.request)
            with self.assertRaisesRegex(ValueError, 'instrumentals only'):
                selection.admit('auto', hardware=self.hw, **{**self.request, 'instrumental':False, 'lyrics':'sing this'})
            fallback.assert_not_called()

    def test_automatic_preserves_fitting_nvidia_and_linux_gpu_routes(self):
        hw = {**self.hw, 'gpus':[{'backend':'cuda', 'index':0, 'free_bytes':12*cpu.GIB}]}
        self.assertEqual(selection.admit('auto', hardware=hw, **self.request)['engine'], 'acestep-service')
        with patch('music_amd_bridge.plan', return_value={'backend':'cuda'}), patch.object(cpu, 'plan') as fallback:
            result = selection.admit('auto', hardware={**hw, 'system':'Linux'}, **self.request)
            self.assertEqual(result['engine'], 'acestep-scaled');fallback.assert_not_called()

    def test_profile_revocation_is_not_a_cpu_fallback(self):
        with patch('music_amd_bridge.plan', side_effect=ProfileLocked('ended')), patch.object(cpu, 'plan') as fallback:
            with self.assertRaises(ProfileLocked):selection.admit('auto', hardware=self.hw, **self.request)
            fallback.assert_not_called()

    def test_guard_keeps_original_time_and_login(self):
        with patch.object(selection, 'capture', return_value=('user','epoch')), patch.object(selection.time, 'time', return_value=123):
            guard = selection.request_guard(ROOT)
            with patch('chat_model_switch._guard') as stop:
                guard();stop.assert_called_once_with(ROOT.resolve(), 123)
        with patch.object(selection, 'capture', return_value=('user','new-epoch')):
            with self.assertRaises(ProfileLocked):guard()

    def test_revocation_after_native_publish_removes_only_its_new_output(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=False):
            os.environ.pop(UID_ENV, None);os.environ.pop(EPOCH_ENV, None)
            root=Path(temp);(root/'Agent').mkdir()
            process=Mock(pid=12345, returncode=0);process.poll.return_value=0
            job=Mock();parts=[]
            def command(part):
                part.write_bytes(b'synthetic audio');parts.append(part)
                return ['fixture']
            def check():
                if parts and parts[0].with_name(parts[0].name.replace('.part.', '.')).exists():
                    raise RuntimeError('Stopped after publication')
            with patch.object(native.subprocess, 'Popen', return_value=process), patch.object(native, 'WorkerJob', return_value=job), patch.object(native, 'require_space'):
                with self.assertRaisesRegex(RuntimeError, 'Stopped after publication'):
                    native.run_generation(self.profile, command, lambda p:None, root=root, kind='music', check_request=check)
            self.assertEqual(list((root/'Outputs/Music').iterdir()), [])
            job.close.assert_called_once()


if __name__ == '__main__':unittest.main()
