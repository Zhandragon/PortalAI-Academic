import json
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
import media_policy as mp
import stt_bridge
import stt_worker
from comfy_bridge import ComfyBridge


class MediaPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Portal media test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hw = {"gpus": [], "ram_available_bytes": 12*mp.GIB}
        checkpoint = self.root/mp.SD15
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"test")
        base = self.root/mp.BASE_STT
        base.mkdir(parents=True)
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            (base/name).write_bytes(b"test")

    def gpu(self, free=23):
        self.hw["gpus"] = [{"index": 0, "backend": "cuda", "total_bytes": 24*mp.GIB, "free_bytes": free*mp.GIB}]

    def image(self, **kwargs):
        return mp.image_plan(self.root, hardware=self.hw, policy={}, **kwargs)

    def speech(self, **kwargs):
        return mp.speech_plan(self.root, hardware=self.hw, policy={}, **kwargs)

    def test_cpu_uses_small_local_models(self):
        self.assertEqual(self.image()["profile"], "sd15")
        self.assertEqual(self.image()["width"], 512)
        speech = self.speech()
        self.assertEqual((speech["device"], speech["model"]), ("cpu", "base"))
        self.assertTrue(Path(speech["model_path"]).is_relative_to(self.root))

    def test_24g_gpu_keeps_large_models(self):
        self.gpu()
        self.assertEqual(self.image()["profile"], "flux")
        self.assertEqual(self.speech()["model"], "large-v3-turbo")

    def test_current_free_memory_is_used(self):
        self.gpu(5)
        self.assertEqual(self.image()["profile"], "sd15")
        with self.assertRaises(RuntimeError): self.image(profile="flux")
        self.gpu(.5)
        with self.assertRaises(RuntimeError): self.image()
        self.assertEqual(self.speech()["device"], "cpu")

    def test_other_gpu_cannot_inflate_device_zero_budget(self):
        self.gpu(4)
        self.hw["gpus"].append({"index": 1, "free_bytes": 48*mp.GIB, "backend": "cuda"})
        self.assertEqual(self.image()["profile"], "sd15")

    def test_shared_vulkan_memory_does_not_imply_cuda_media(self):
        self.hw["gpus"] = [{"index": 0, "backend": "vulkan", "free_bytes": 32*mp.GIB}]
        self.assertEqual(self.image()["backend"], "cpu")

    def test_low_memory_refuses_before_loading(self):
        self.hw["ram_available_bytes"] = 2*mp.GIB
        with self.assertRaises(RuntimeError): self.image()
        with self.assertRaises(RuntimeError): self.speech()

    def test_explicit_dimensions_are_validated_not_silently_changed(self):
        for width, height in [(4096, 512), (511, 512), (0, 512), (512, -1)]:
            with self.assertRaises(ValueError): self.image(width=width, height=height)
        self.assertEqual(self.image(width=256, height=384)["height"], 384)

    def test_incomplete_speech_model_fails_offline(self):
        (self.root/mp.BASE_STT/"tokenizer.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "incomplete"): self.speech()

    def test_setting_and_explicit_profile(self):
        self.gpu()
        plan = mp.image_plan(self.root, hardware=self.hw, policy={"media": {"image_profile": "sd15"}})
        self.assertEqual(plan["profile"], "sd15")
        self.assertEqual(self.image(profile="flux")["profile"], "flux")

    def test_chat_named_profile_is_pinned_across_stale_model_arguments(self):
        self.gpu()
        for saved in ('sd15', 'flux'):
            for requested in (None, 'auto', 'sd15', 'flux'):
                with self.subTest(saved=saved, requested=requested):
                    plan = mp.image_plan(self.root, profile=requested, hardware=self.hw,
                                         policy={'media': {'image_profile': saved}}, respect_saved_profile=True)
                    self.assertEqual(plan['profile'], saved)
                    self.assertEqual(plan['selection_source'], 'saved')
                    self.assertEqual(plan['tool_requested_profile'], requested)
        self.gpu(5)
        for requested in (None, 'auto', 'sd15'):
            with self.assertRaisesRegex(RuntimeError, 'FLUX profile needs'):
                mp.image_plan(self.root, profile=requested, hardware=self.hw,
                              policy={'media': {'image_profile':'flux'}}, respect_saved_profile=True)

    def test_direct_override_and_automatic_still_use_fresh_hardware(self):
        self.gpu()
        plan = mp.image_plan(self.root, profile='sd15', hardware=self.hw,
                             policy={'media': {'image_profile':'flux'}}, respect_saved_profile=False)
        self.assertEqual((plan['profile'],plan['selection_source']), ('sd15','explicit'))
        for free, expected in ((23,'flux'),(5,'sd15'),(23,'flux')):
            self.gpu(free)
            plan = mp.image_plan(self.root, hardware=self.hw, policy={'media':{'image_profile':'auto'}},
                                 respect_saved_profile=True)
            self.assertEqual((plan['profile'],plan['selection_source']), (expected,'automatic'))

    def test_saved_klein_uses_its_native_admission_not_stale_flux(self):
        with patch('native_flux.plan', return_value={'profile':'klein4','engine':'sdcpp-cpu'}) as native:
            plan = mp.image_plan(self.root, profile='flux', hardware=self.hw,
                                 policy={'media':{'image_profile':'klein4'}}, respect_saved_profile=True)
        self.assertEqual(plan['profile'], 'klein4')
        native.assert_called_once()
        self.assertEqual(native.call_args.kwargs['engine'], 'auto')

    def test_saved_large_transcription_uses_its_own_cuda_floor_without_model_downgrade(self):
        policy = {'media':{'speech_model':'large-v3-turbo'}}
        for free, device in ((5,'cuda'),(2,'cpu'),(3,'cuda'),(.5,'cpu')):
            self.gpu(free)
            plan = mp.speech_plan(self.root, hardware=self.hw, policy=policy)
            self.assertEqual((plan['model'],plan['device']), ('large-v3-turbo',device))
        self.gpu(2)
        with self.assertRaisesRegex(RuntimeError, '3 GiB'):
            mp.speech_plan(self.root, device='cuda', hardware=self.hw, policy=policy)
        self.assertEqual(self.speech(model='base', device='cuda')['model'], 'base')

    def test_small_workflow_applies_dimensions_seed_and_negative(self):
        wf = json.loads((ROOT/"Workflows/API/SD15_T2I_Portable.json").read_text())
        ComfyBridge().configure_t2i(wf, "a cube", "blur", 256, 384, 123)
        self.assertEqual(wf["4"]["inputs"]["height"], 384)
        self.assertEqual(wf["5"]["inputs"]["seed"], 123)
        self.assertEqual(wf["3"]["inputs"]["text"], "blur")

    def test_stt_honors_pinned_runtime_and_removes_host_python_paths(self):
        python = self.root/"Runtime/BootstrapPython/python.exe"
        python.parent.mkdir(parents=True); python.touch()
        packages = self.root/"SpeechToText/python_packages_312"
        packages.mkdir(parents=True)
        state = self.root/"Agent/.runtime/stt_runtime.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"interpreter": "Runtime/BootstrapPython/python.exe",
                                     "package_layer": "SpeechToText/python_packages_312"}))
        with patch.object(stt_bridge, "root_dir", return_value=self.root), \
             patch.object(stt_bridge, "__file__", str(self.root/"Agent/stt_bridge.py")), \
             patch.dict(os.environ, {"PYTHONHOME": "C:/unrelated", "PYTHONPATH": "C:/unrelated"}):
            bridge = stt_bridge.SttBridge()
            self.assertEqual(bridge.python, python)
            self.assertEqual(bridge.packages, packages)
            env = bridge._env()
            self.assertNotIn("PYTHONHOME", env)
            self.assertEqual(env["PYTHONPATH"], str(bridge.packages))
            self.assertEqual(env["HF_HUB_OFFLINE"], "1")

    def test_whisper_model_cannot_download_during_inference(self):
        loader = Mock()
        stt_worker._model("base", "cpu", self.root, loader)
        self.assertTrue(loader.call_args.kwargs["local_files_only"])

    def test_multilingual_transcript_survives_legacy_windows_pipe(self):
        data = io.BytesIO()
        stream = io.TextIOWrapper(data, encoding="cp1252")
        with patch.object(sys, "stdout", stream), self.assertRaises(SystemExit):
            stt_worker.emit({"text": "你好世界 — العربية"})
        stream.flush()
        payload = data.getvalue().decode("ascii").split("=", 1)[1]
        self.assertEqual(json.loads(payload)["text"], "你好世界 — العربية")

    def test_tool_result_survives_legacy_windows_pipe(self):
        from _common import emit
        data = io.BytesIO(); stream = io.TextIOWrapper(data, encoding="cp1252")
        with patch.object(sys, "stdout", stream), self.assertRaises(SystemExit):
            emit({"text": "你好世界 — العربية", "file": "Outputs/你好.txt"})
        stream.flush(); payload = json.loads(data.getvalue().decode("ascii"))
        self.assertEqual(payload["text"], "你好世界 — العربية")
        self.assertEqual(payload["file"], "Outputs/你好.txt")

    def test_storage_rejection_prevents_comfy_submission(self):
        with patch("comfy_bridge.require_space", side_effect=RuntimeError("reserve")), patch("comfy_bridge.http_json") as post:
            with self.assertRaisesRegex(RuntimeError, "reserve"): ComfyBridge().queue({})
            post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
