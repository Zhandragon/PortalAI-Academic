import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
import runtime_policy as rp


class RuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        scale = patch.object(rp, "GIB", 1024)
        scale.start()
        self.addCleanup(scale.stop)
        self.temp = tempfile.TemporaryDirectory(prefix="Portal AI test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = rp.load_policy(ROOT)
        self.policy.update(selection="auto", backend="auto", context_tokens=32768, variant_preference="standard")
        for model in self.policy["models"]:
            p = self.root / model["path"]
            p.parent.mkdir(parents=True, exist_ok=True)
            # Scale the memory unit so tests use kilobytes, not real model files.
            sizes = {"qwen1.7-abliterated-q8": 1.71, "qwen27-standard-q4": 17.67, "qwen27-q4": 15.7, "qwen27-q5": 18.2, "qwen4-abliterated-q4": 2.33, "qwen4-q4": 2.33, "qwen1.7-q8": 1.71, "qwen-vl2-q4": 1.03, "qwen-vl2-abliterated-q4": 1.03, "qwen-vl4-q4": 2.33, "qwen-vl4-abliterated-q4": 2.33}
            with p.open("wb") as f:
                f.truncate(int(sizes[model["id"]] * rp.GIB))
            if model.get("projector"):
                with (self.root / model["projector"]).open("wb") as f:
                    f.truncate(int(.87 * rp.GIB))
        self.hw = {"ram_available_bytes": 16*rp.GIB, "ram_total_bytes": 32*rp.GIB,
                   "system": "Windows", "machine": "AMD64", "gpus": [], "cpu_count": 8}

    def select(self, gpu_free=0):
        return rp.select_model(self.root, self.hw, {"gpu": {"free_bytes": gpu_free} if gpu_free else None}, self.policy)["selected"]

    def test_inaccessible_optional_backend_does_not_prevent_cpu_selection(self):
        from unittest.mock import Mock
        denied=Mock();denied.is_file.side_effect=PermissionError('inaccessible')
        cpu=self.root/'cpu.exe';cpu.touch()
        with patch.object(rp,'runtime_candidates',return_value={'cuda':denied,'vulkan':denied,'cpu':cpu}):
            self.assertEqual(rp.choose_backend(self.root,self.hw,probe=False)['backend'],'cpu')
            with self.assertRaisesRegex(RuntimeError,'No working bundled vulkan'):
                rp.choose_backend(self.root,self.hw,requested='vulkan',probe=False)

    def test_3090_and_4090_choose_existing_27b(self):
        self.assertEqual(self.select(23*rp.GIB)["id"], "qwen27-standard-q4")

    def test_cpu_uses_small_model_not_27b(self):
        self.assertEqual(self.select()["id"], "qwen4-q4")
        self.assertEqual(self.select()["gpu_layers"], 0)

    def test_low_ram_auto_shortens_context_and_selects_smaller_model(self):
        self.hw["ram_available_bytes"] = 6*rp.GIB
        selected = self.select()
        self.assertEqual(selected["id"], "qwen1.7-q8")
        self.assertEqual(selected["context_tokens"], 4096)
        self.assertLessEqual(selected["estimated_ram_bytes"], 4*rp.GIB)

    def test_manual_model_keeps_context_and_refuses_if_it_does_not_fit(self):
        self.hw["ram_available_bytes"] = 6*rp.GIB
        self.policy["selection"] = "qwen1.7-q8"
        with self.assertRaisesRegex(RuntimeError, "No installed model fits"):
            self.select()

    def test_auto_does_not_exceed_context_limit_or_lower_memory_reserve(self):
        self.hw["ram_available_bytes"] = 4*rp.GIB
        with self.assertRaisesRegex(RuntimeError, "No installed model fits"):
            self.select()
        self.hw["ram_available_bytes"] = 8*rp.GIB
        self.policy["context_tokens"] = 2048
        self.assertEqual(self.select()["context_tokens"], 2048)

    def test_vram_budget_uses_free_not_total(self):
        self.assertEqual(self.select(5*rp.GIB)["id"], "qwen4-q4")

    def test_manual_partial_offload(self):
        self.policy["selection"] = "qwen27-q4"
        selected = self.select(12*rp.GIB)
        self.assertGreater(selected["gpu_layers"], 0)
        self.assertLess(selected["gpu_layers"], 65)

    def test_impossible_manual_selection_fails(self):
        self.hw["ram_available_bytes"] = 4*rp.GIB
        self.policy["selection"] = "qwen27-q4"
        with self.assertRaisesRegex(RuntimeError, "No installed model fits"):
            self.select()

    def test_relocated_paths_with_spaces(self):
        self.assertTrue(Path(self.select()["absolute_path"]).is_relative_to(self.root))

    def test_escape_and_absolute_config_rejected(self):
        for raw in ["../../outside", "C:\\Users\\x\\model.gguf", "/etc/passwd"]:
            with self.assertRaises(ValueError):
                rp.portable_path(self.root, raw)

    def test_missing_model_falls_back(self):
        for model in self.policy['models']:
            if model['id'].startswith('qwen4-'):(self.root/model['path']).unlink()
        self.assertEqual(self.select()["id"], "qwen1.7-q8")

    def test_original_4b_remains_explicitly_selectable(self):
        self.policy['selection']='qwen4-q4'
        self.assertEqual(self.select()['id'],'qwen4-q4')

    def test_storage_reserves_output_space_and_floor(self):
        usage = rp.shutil._ntuple_diskusage(1000*rp.GIB, 790*rp.GIB, 210*rp.GIB)
        with patch.object(rp.shutil, "disk_usage", return_value=usage):
            self.assertTrue(rp.storage_budget(self.root, self.policy, 10*rp.GIB)["allowed"])
            self.assertFalse(rp.storage_budget(self.root, self.policy, 11*rp.GIB)["allowed"])
            self.assertTrue(rp.storage_budget(self.root, self.policy, 100*rp.GIB, True)["allowed"])
            self.assertFalse(rp.storage_budget(self.root, self.policy, 111*rp.GIB, True)["allowed"])

    def test_wrong_architecture_rejected(self):
        self.hw["machine"] = "aarch64"
        with self.assertRaisesRegex(RuntimeError, "x86-64"):
            rp.choose_backend(self.root, self.hw)

    def test_integrated_gpu_does_not_double_count_system_ram(self):
        self.hw["ram_available_bytes"] = 10*rp.GIB
        backend = {"gpu": {"free_bytes": 24*rp.GIB, "shared_memory": True}}
        selected = rp.select_model(self.root, self.hw, backend, self.policy)["selected"]
        self.assertEqual(selected["id"], "qwen4-q4")

    def test_no_cuda_tool_falls_back_or_reports_unavailable(self):
        self.assertEqual(rp.tool_plan("comfyui", self.hw)["args"], ["--cpu"])
        self.assertEqual(rp.tool_plan("acestep", self.hw)["backend"], "unavailable")


if __name__ == "__main__":
    unittest.main()
