import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"Agent"))
import amd_runtime as amd
import runtime_policy as rp
from media_policy import image_plan,SD15


class AMDTests(unittest.TestCase):
    def test_uninstalled_runtime_never_probes_host_torch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(amd.subprocess,"run") as run:
            self.assertFalse(amd.probe(Path(temp))["available"])
            run.assert_not_called()

    def test_loaded_nvidia_module_cannot_be_mixed(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            receipt=root/"Maintenance/Imports/amd-runtime-lock.json";receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({"status":"installed-unvalidated-on-Radeon"}))
            torch=root/"Runtime/AMDPython/packages/torch/__init__.py";torch.parent.mkdir(parents=True);torch.touch()
            with patch.dict(sys.modules,{"torch":SimpleNamespace(__file__=str(root/"other/torch/__init__.py"))}):
                with self.assertRaisesRegex(RuntimeError,"mix"):amd.activate(root)

    def test_probe_failure_is_unavailable_not_a_synthetic_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            p=root/"Runtime/AMDPython/packages/torch/__init__.py";p.parent.mkdir(parents=True);p.touch()
            with patch.object(amd.subprocess,"run",side_effect=OSError("driver missing")):
                self.assertIn("driver missing",amd.probe(root)["reason"])

    def test_comfy_selects_verified_rocm_and_accounts_for_shared_ram(self):
        hw={"system":"Windows","gpus":[],"ram_available_bytes":14*rp.GIB,
            "amd_gpu":{"available":True,"compute_ok":True,"free_bytes":4*rp.GIB,"shared_memory":True}}
        plan=rp.tool_plan("comfyui",hw)
        self.assertEqual(plan["backend"],"rocm")
        self.assertIn("--disable-triton-backend",plan["args"])
        self.assertNotIn("--cpu",plan["args"])
        hw["ram_available_bytes"]=8*rp.GIB
        with self.assertRaisesRegex(RuntimeError,"shared memory"):rp.tool_plan("comfyui",hw)

    def test_second_or_vulkan_gpu_is_not_counted_as_cuda(self):
        for gpu in ({"backend":"vulkan","total_bytes":24*rp.GIB,"index":0},
                    {"backend":"cuda","total_bytes":24*rp.GIB,"index":1}):
            self.assertEqual(rp.tool_plan("comfyui",{"gpus":[gpu]})["backend"],"cpu")

    def test_explicit_comfy_image_reports_rocm_and_retains_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);checkpoint=root/SD15;checkpoint.parent.mkdir(parents=True);checkpoint.touch()
            hw={"system":"Windows","machine":"AMD64","gpus":[],"ram_available_bytes":14*rp.GIB,
                "amd_gpu":{"available":True,"compute_ok":True,"free_bytes":4*rp.GIB,"shared_memory":True}}
            result=image_plan(root,engine="comfyui",hardware=hw,policy={})
            self.assertEqual((result["profile"],result["backend"]),("sd15","rocm"))
            with self.assertRaises(ValueError):image_plan(root,engine="comfyui",width=1024,hardware=hw,policy={})
            with self.assertRaises(RuntimeError):image_plan(root,engine="comfyui",profile="flux",hardware=hw,policy={})


if __name__=="__main__":unittest.main()
