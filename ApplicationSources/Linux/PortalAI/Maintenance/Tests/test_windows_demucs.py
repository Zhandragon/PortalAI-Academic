"""Offline Windows model/decode/epoch boundaries; synthetic data only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import windows_demucs as runtime


class WindowsDemucsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='PortalAI synthetic Demucs ')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def model(self):
        p=self.root/runtime.MODEL;p.parent.mkdir(parents=True);p.write_bytes(b'pinned synthetic model')
        self.enterContext(patch.object(runtime,'MODEL_BYTES',p.stat().st_size))
        self.enterContext(patch.object(runtime,'MODEL_SHA256',hashlib.sha256(p.read_bytes()).hexdigest()))
        return p

    def test_missing_model_fails_before_inference_import_or_network(self):
        with self.assertRaises(FileNotFoundError):runtime.infer(self.root,'ignored','cpu',lambda:None)

    def test_wrong_size_is_not_an_installed_model(self):
        p=self.model();p.write_bytes(b'x')
        with self.assertRaisesRegex(RuntimeError,'incomplete'):runtime.model_path(self.root)

    def test_same_size_corruption_is_refused(self):
        p=self.model();p.write_bytes(b'X'*p.stat().st_size)
        with self.assertRaisesRegex(RuntimeError,'integrity'):runtime.model_path(self.root)

    def test_exact_pin_verifies_without_downloader(self):
        p=self.model()
        with patch('urllib.request.urlopen',side_effect=AssertionError('no network')):
            self.assertEqual(runtime.model_path(self.root),p)

    def test_revoked_profile_after_hash_blocks_model_import(self):
        self.model();guard=MagicMock(side_effect=[None,PermissionError('epoch revoked')])
        with self.assertRaises(PermissionError):runtime.infer(self.root,'ignored','cpu',guard)
        self.assertEqual(guard.call_count,2)

    def test_cpu_selection_never_probes_gpu(self):
        torch=MagicMock();torch.cuda.is_available.side_effect=AssertionError('GPU probe')
        self.assertEqual(runtime.select_device('cpu',torch),'cpu')

    def test_explicit_cuda_never_silently_becomes_cpu(self):
        torch=MagicMock();torch.cuda.is_available.return_value=False
        with self.assertRaisesRegex(RuntimeError,'unavailable'):runtime.select_device('cuda',torch)
        self.assertEqual(runtime.select_device('auto',torch),'cpu')

    def test_unknown_device_is_refused(self):
        with self.assertRaises(ValueError):runtime.select_device('host-fallback',MagicMock())

    def test_real_mono_decode_resamples_complete_stereo(self):
        import numpy as np,soundfile as sf
        source=self.root/'synthetic.wav';sf.write(source,np.sin(np.arange(2205)*.1),22050,subtype='FLOAT')
        audio=runtime.decode_audio(self.root,source,44100,2)
        self.assertEqual(audio.shape,(4410,2));self.assertTrue(np.isfinite(audio).all())
        np.testing.assert_array_equal(audio[:,0],audio[:,1])

    def test_overlong_audio_is_refused_before_allocation(self):
        with patch('soundfile.info',return_value=SimpleNamespace(frames=301*44100,samplerate=44100,channels=2)),patch('soundfile.read') as read:
            with self.assertRaisesRegex(ValueError,'300'):runtime.decode_audio(self.root,'fixture',44100,2)
        read.assert_not_called()

    def test_empty_audio_is_refused_before_allocation(self):
        with patch('soundfile.info',return_value=SimpleNamespace(frames=0,samplerate=44100,channels=2)),patch('soundfile.read') as read:
            with self.assertRaises(ValueError):runtime.decode_audio(self.root,'fixture',44100,2)
        read.assert_not_called()

    def test_nonfinite_decoded_audio_is_refused(self):
        import numpy as np,soundfile as sf
        source=self.root/'nan.wav';sf.write(source,np.full((30,2),np.nan),44100,subtype='FLOAT')
        with self.assertRaisesRegex(RuntimeError,'non-finite'):runtime.decode_audio(self.root,source,44100,2)

    def test_decode_mutation_is_refused(self):
        import numpy as np
        with patch('soundfile.info',return_value=SimpleNamespace(frames=10,samplerate=44100,channels=2)),patch('soundfile.read',return_value=(np.zeros((9,2)),44100)):
            with self.assertRaisesRegex(RuntimeError,'changed'):runtime.decode_audio(self.root,'fixture',44100,2)

    def test_ffmpeg_bad_duration_never_starts_decoder(self):
        with patch('soundfile.info',side_effect=RuntimeError()),patch('platform_runtime.ffmpeg_path',return_value=self.root/'ffprobe.exe'),patch('subprocess.run',return_value=SimpleNamespace(stdout=b'{"format":{"duration":"nan"}}')) as run:
            with self.assertRaises(ValueError):runtime.decode_audio(self.root,'fixture',44100,2)
        self.assertEqual(run.call_count,1)

    def test_ffmpeg_partial_frame_is_refused(self):
        with patch('soundfile.info',side_effect=RuntimeError()),patch('platform_runtime.ffmpeg_path',return_value=self.root/'ffmpeg.exe'),patch('subprocess.run',side_effect=[SimpleNamespace(stdout=b'{"format":{"duration":"1"}}'),SimpleNamespace(stdout=b'123')]):
            with self.assertRaisesRegex(RuntimeError,'invalid'):runtime.decode_audio(self.root,'fixture',44100,2)

    def test_windows_branch_keeps_linux_route(self):
        spec=importlib.util.spec_from_file_location('demucs_boundary_driver',ROOT/'MusicUnderstanding/runtime_driver.py');driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
        with patch.object(driver.os,'name','posix'),patch.object(driver,'_separate_vocals_linux',return_value='linux') as call:
            self.assertEqual(driver.separate_vocals('fixture','cpu'),'linux')
        call.assert_called_once_with('fixture')


if __name__=='__main__':unittest.main()
