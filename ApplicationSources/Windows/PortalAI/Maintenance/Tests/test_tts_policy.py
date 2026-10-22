import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
import tts_policy as tp
import piper_bridge as pb
from voice_bridge import VoiceBridge


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Portal voice test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in (tp.PIPER_MODEL, tp.PIPER_MODEL+".json", "Voice/Piper/packages/piper/__init__.py", "Voice/Piper/packages/onnxruntime/__init__.py"):
            p = self.root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b"fixture")
        self.hw = {"system": "Windows", "machine": "AMD64", "gpus": [], "ram_available_bytes": 8*tp.GIB}

    def plan(self, **kwargs): return tp.tts_plan(self.root, hardware=self.hw, policy={}, **kwargs)

    def test_cpu_and_radeon_use_cpu_voice(self):
        self.assertEqual(self.plan()["engine"], "piper")
        self.hw["gpus"] = [{"backend": "vulkan", "index": 0, "free_bytes": 24*tp.GIB}]
        self.assertEqual(self.plan()["device"], "cpu")

    def test_auto_uses_free_cuda_and_explicit_piper_is_respected(self):
        self.hw["gpus"] = [{"backend": "cuda", "index": 0, "free_bytes": 9*tp.GIB}]
        self.assertEqual(self.plan()["engine"], "qwen")
        self.assertEqual(self.plan(engine="piper")["engine"], "piper")
        self.hw["gpus"][0]["free_bytes"] = 2*tp.GIB
        self.assertEqual(self.plan()["engine"], "piper")

    def test_second_gpu_does_not_inflate_device_zero_budget(self):
        self.hw["gpus"] = [{"backend": "cuda", "index": 1, "free_bytes": 24*tp.GIB}]
        self.assertEqual(self.plan()["engine"], "piper")

    def test_rocm_requires_compute_and_shared_ram_after_handoff(self):
        self.hw["amd_gpu"] = {"available": True, "compute_ok": True, "free_bytes": 10*tp.GIB,
                              "total_bytes": 16*tp.GIB, "shared_memory": True}
        tp.qwen_preflight(self.hw)
        self.assertTrue(tp.tts_needs_handoff("auto", self.hw))
        self.assertEqual(self.plan()["engine"], "piper")  # Only 8 GiB system RAM free.
        self.hw["ram_available_bytes"] = 14*tp.GIB
        self.assertEqual(self.plan()["device"], "rocm")
        self.hw["amd_gpu"]["compute_ok"] = False
        with self.assertRaises(RuntimeError): self.plan(engine="qwen")
        with self.assertRaises(RuntimeError): tp.qwen_preflight(self.hw)

    def test_dedicated_rocm_and_explicit_cpu(self):
        self.hw["amd_gpu"] = {"available": True, "compute_ok": True, "free_bytes": 10*tp.GIB,
                              "total_bytes": 16*tp.GIB, "shared_memory": False}
        self.assertEqual(self.plan()["device"], "rocm")
        self.assertEqual(self.plan(engine="piper")["device"], "cpu")
        with patch("amd_runtime.probe", side_effect=AssertionError("NVIDIA must not probe AMD")):
            tp.with_amd_probe({**self.hw, "gpus": [{"backend": "cuda", "index": 0}]})

    def test_explicit_piper_does_not_load_a_gpu_probe(self):
        with patch.object(tp, "detect_hardware", return_value=self.hw), patch("amd_runtime.probe", side_effect=AssertionError("CPU voice must not probe Torch")):
            self.assertEqual(tp.tts_plan(self.root,"piper",policy={})["device"],"cpu")

    def test_manual_qwen_and_low_ram_refuse(self):
        with self.assertRaisesRegex(RuntimeError, "CUDA"): self.plan(engine="qwen")
        self.hw["ram_available_bytes"] = 2*tp.GIB
        with self.assertRaisesRegex(RuntimeError, "available RAM"): self.plan()

    def test_qwen_preflight_rejects_non_cuda_before_handoff(self):
        with self.assertRaisesRegex(RuntimeError, "NVIDIA"): tp.qwen_preflight(self.hw)
        self.hw["gpus"] = [{"backend": "vulkan", "index": 0, "total_bytes": 24*tp.GIB}]
        with self.assertRaisesRegex(RuntimeError, "NVIDIA"): tp.qwen_preflight(self.hw)
        self.hw["gpus"][0]["backend"] = "cuda"
        self.hw["gpus"][0]["free_bytes"] = 0
        tp.qwen_preflight(self.hw)  # It is legitimate to free chat VRAM after this preflight.

    def test_auto_reclaims_chat_before_downscaling_capable_gpu(self):
        self.hw["gpus"] = [{"backend": "cuda", "index": 0, "total_bytes": 24*tp.GIB, "free_bytes": tp.GIB}]
        self.assertTrue(tp.tts_needs_handoff("auto", self.hw))
        self.assertFalse(tp.tts_needs_handoff("piper", self.hw))
        self.hw["ram_available_bytes"] = 2*tp.GIB
        self.assertTrue(tp.tts_needs_handoff("piper", self.hw))
        self.hw["gpus"][0]["backend"] = "vulkan"
        self.hw["ram_available_bytes"] = 8*tp.GIB
        self.assertFalse(tp.tts_needs_handoff("auto", self.hw))

    def test_unsupported_language_is_not_silently_substituted(self):
        with self.assertRaisesRegex(RuntimeError, "English only"): self.plan(language="German")

    def test_missing_asset_and_wrong_platform_are_reported(self):
        (self.root/tp.PIPER_MODEL).unlink()
        with self.assertRaisesRegex(RuntimeError, "incomplete"): self.plan()
        self.hw["system"] = "Darwin"
        with self.assertRaisesRegex(RuntimeError, "Windows/Linux x64"): self.plan()

    def test_text_limits_preserve_input(self):
        self.assertEqual(tp.validate_text("  Hello\nworld.  "), "  Hello\nworld.  ")
        for text in (" ", "a\0b", "界"*1400):
            with self.assertRaises(ValueError): tp.validate_text(text)

    def test_qwen_uses_bundled_base_instead_of_moved_venv_launcher(self):
        base = self.root/"Runtime/BootstrapPython/python.exe"; base.parent.mkdir(parents=True); base.touch()
        packages = self.root/"Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts"; packages.mkdir(parents=True)
        with patch("voice_bridge.root_dir", return_value=self.root):
            bridge = VoiceBridge()
        self.assertEqual(bridge._python(), base)

    def test_output_cannot_escape_or_overwrite(self):
        for name in ("../elsewhere.wav", "Outputs/../elsewhere.wav", "Outputs/x.mp3"):
            with self.assertRaises(ValueError): pb.output_path(self.root, name)
        p = self.root/"Outputs/existing.wav"; p.parent.mkdir(); p.write_bytes(b"keep")
        with self.assertRaises(FileExistsError): pb.output_path(self.root, str(p))
        self.assertEqual(p.read_bytes(), b"keep")

    def test_disk_rejection_precedes_worker_creation(self):
        with patch.object(pb, "tts_plan"), patch.object(pb, "require_space", side_effect=RuntimeError("SSD reserve")), patch.object(pb.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "SSD reserve"): pb.synthesize("hello", root=self.root)
            launch.assert_not_called()

    def test_stop_prevents_worker_start(self):
        stop = self.root/"STOP"; stop.touch()
        with patch.object(pb, "tts_plan"), patch.object(pb, "require_space"), patch.object(pb.subprocess, "Popen") as launch:
            with self.assertRaisesRegex(RuntimeError, "stopped"): pb.synthesize("hello", root=self.root, stop=stop)
            launch.assert_not_called()

    def test_cleanup_only_removes_owned_partial_output(self):
        runtime = self.root/"Agent/.runtime"; runtime.mkdir(parents=True)
        output = self.root/"Outputs"; output.mkdir()
        token = "a"*32
        part = output/("voice."+token+".part.wav"); part.write_bytes(b"partial")
        request = runtime/("piper_"+token+".json")
        request.write_text(json.dumps({"staging_output": part.relative_to(self.root).as_posix()}))
        pb.cleanup_abandoned(self.root); self.assertFalse(part.exists())
        keep = self.root/("outside."+token+".part.wav"); keep.write_bytes(b"keep")
        request.write_text(json.dumps({"staging_output": str(keep)}))
        pb.cleanup_abandoned(self.root); self.assertEqual(keep.read_bytes(), b"keep")


if __name__ == "__main__": unittest.main()
