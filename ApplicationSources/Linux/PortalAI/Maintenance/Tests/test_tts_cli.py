from contextlib import contextmanager
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
import ai_tools


class SpeechCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        policy = self.root/"Agent/hardware_profiles.json"
        policy.parent.mkdir(parents=True)
        policy.write_text(json.dumps({"storage": {"minimum_free_gib": 0,
            "minimum_free_fraction": 0, "output_reserve_gib": 0}}))

    def invoke(self, available_gib, failure=False, engine="piper", gpu=False, admitted="piper"):
        events = []; outputs = []
        @contextmanager
        def handoff(*args):
            events.append("handoff")
            try: yield
            finally: events.append("restore")
        def synth(*args):
            events.append("speech")
            if failure: raise RuntimeError("worker failed")
            return {"success": True, "files": [], "engine": "piper"}
        def custom(*args, **kwargs):
            events.append("qwen"); return {"success": True, "files": []}
        def plan(**kwargs):
            if gpu and engine == "auto": self.assertIn("handoff", events)
            return {"engine": admitted}
        def emit(payload, code=0):
            outputs.append(payload); raise SystemExit(code)
        hardware = {"ram_available_bytes": available_gib*1024**3, "gpus":
            [{"backend": "cuda", "index": 0, "total_bytes": 24*1024**3, "free_bytes": 1024**3}] if gpu else []}
        with patch.object(sys, "argv", ["ai_tools", "voice-say", "hello", "--engine", engine]), \
             patch.object(ai_tools, "root_dir", return_value=self.root), \
             patch("voice_bridge.root_dir", return_value=self.root), \
             patch("runtime_policy.detect_hardware", return_value=hardware), \
             patch("tts_policy.tts_plan", side_effect=plan), \
             patch("piper_bridge.output_path", return_value=self.root/"Outputs/Voices/unused-test.wav"), \
             patch("piper_bridge.synthesize", side_effect=synth), \
             patch.object(ai_tools.VoiceBridge, "custom", side_effect=custom), \
             patch.object(ai_tools, "_set_gpu_state"), patch.object(ai_tools, "_clear_gpu_state"), \
             patch.object(ai_tools, "_exclusive_gpu", side_effect=handoff), \
             patch.object(ai_tools, "emit", side_effect=emit):
            with self.assertRaises(SystemExit) as raised: ai_tools.main()
        return events, outputs[-1], raised.exception.code

    def test_cpu_keeps_chat_when_ram_fits(self):
        events, result, code = self.invoke(8)
        self.assertEqual(events, ["speech"]); self.assertEqual(code, 0)
        self.assertFalse(result["llm_handoff"])

    def test_cpu_releases_chat_only_for_low_ram(self):
        events, result, code = self.invoke(2)
        self.assertEqual(events, ["handoff", "speech", "restore"]); self.assertEqual(code, 0)
        self.assertTrue(result["llm_handoff"])

    def test_failed_cpu_worker_still_restores_chat(self):
        events, result, code = self.invoke(2, failure=True)
        self.assertEqual(events, ["handoff", "speech", "restore"])
        self.assertEqual(code, 1); self.assertFalse(result["success"])

    def test_auto_scales_up_after_reclaiming_ram_and_vram(self):
        events, result, code = self.invoke(2, engine="auto", gpu=True, admitted="qwen")
        self.assertEqual(events, ["handoff", "qwen", "restore"])
        self.assertEqual(code, 0); self.assertEqual(result["engine"], "qwen")

    def test_auto_downscales_if_reclaimed_memory_is_still_insufficient(self):
        events, result, code = self.invoke(8, engine="auto", gpu=True)
        self.assertEqual(events, ["handoff", "speech", "restore"])
        self.assertEqual(code, 0); self.assertEqual(result["engine"], "piper")


if __name__ == "__main__": unittest.main()
