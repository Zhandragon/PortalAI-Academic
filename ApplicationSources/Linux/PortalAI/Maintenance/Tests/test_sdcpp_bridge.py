import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
import sdcpp_bridge as sd
import media_policy as mp
from workload_compatibility import require_workload, CUDA_ONLY, ROCM_MEDIA


class NativeImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.hw = dict(system="Windows", machine="AMD64", ram_available_bytes=12*sd.GIB, gpus=[])

    def test_shared_gpu_has_separate_ram_admission(self):
        probe = "ggml_vulkan: 0 = Radeon 890M (AMD) | uma: 1 | fp16: 1\nVulkan0\tRadeon 890M\nCPU\tx64\n"
        with patch.object(sd, "executable", return_value=self.root/"sd-cli.exe"), patch.object(sd, "run_probe", return_value=probe):
            p = sd.engine_plan(self.root, self.hw)
            self.assertTrue(p["shared_memory"]); self.assertEqual(p["backend"], "vulkan")
            self.hw["ram_available_bytes"] = 9*sd.GIB
            self.assertEqual(sd.engine_plan(self.root, self.hw)["backend"], "cpu")
            with self.assertRaises(RuntimeError): sd.engine_plan(self.root, self.hw, "sdcpp-vulkan")

    def test_broken_vulkan_falls_back_only_in_auto(self):
        with patch.object(sd, "executable", return_value=self.root/"sd-cli.exe"), patch.object(sd, "run_probe", return_value="CPU\tx64"):
            self.assertEqual(sd.engine_plan(self.root, self.hw)["backend"], "cpu")
            with self.assertRaises(RuntimeError): sd.engine_plan(self.root, self.hw, "sdcpp-vulkan")

    def test_unsupported_os_and_low_ram_rejected_before_loading(self):
        with patch.object(sd, "executable") as exe:
            with self.assertRaises(RuntimeError): sd.engine_plan(self.root, {**self.hw, "system": "Darwin"}, "sdcpp-cpu")
            with self.assertRaises(RuntimeError): sd.engine_plan(self.root, {**self.hw, "ram_available_bytes": 6*sd.GIB}, "sdcpp-cpu")
            exe.assert_not_called()

    def test_nvidia_default_keeps_comfy_and_flux(self):
        p = mp.image_plan(self.root, hardware={**self.hw, "gpus": [{"index": 0, "free_bytes": 23*sd.GIB}]}, policy={})
        self.assertEqual((p["engine"], p["profile"]), ("comfyui", "flux"))

    def test_native_cannot_silently_replace_flux_or_loras(self):
        with self.assertRaisesRegex(RuntimeError, "SD1.5 only"):
            mp.image_plan(self.root, profile="flux", engine="sdcpp-cpu", hardware=self.hw, policy={})
        with self.assertRaisesRegex(ValueError, "LoRAs"):
            sd.command({}, self.root, "cat <lora:wan:1>", None, 5, self.root/"x.png")

    def test_command_keeps_prompt_literal_and_paths_relative_to_root(self):
        checkpoint = self.root/mp.SD15; checkpoint.parent.mkdir(parents=True); checkpoint.write_bytes(b'fixture')
        p = dict(executable=str(self.root/"engine.exe"), backend="vulkan", device="vulkan0", width=512, height=512, max_vram_gib=3)
        command = sd.command(p, self.root, 'a "cat"; echo no', "blurry", 52, self.root/"output file.png")
        self.assertIn('a "cat"; echo no', command)
        self.assertIn("te=cpu,vae=cpu,diffusion=vulkan0", command)
        self.assertIn(str(self.root/mp.SD15), command)
        self.assertNotIn("--params-backend", command)

    def test_corrupted_runtime_not_executed(self):
        folder=self.root/"Runtime/StableDiffusion/windows-cpu"; folder.mkdir(parents=True)
        (folder/"sd-cli.exe").write_bytes(b"modified")
        receipt=self.root/"Maintenance/Imports/sdcpp-windows-cpu.json"; receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps(dict(revision=sd.REVISION, verified=True, installed_files=[dict(path="sd-cli.exe", sha256="0"*64)])))
        with self.assertRaisesRegex(RuntimeError, "integrity"): sd.executable(self.root,"cpu")

    def test_output_requires_complete_png_and_correct_dimensions(self):
        def chunk(kind, data): return struct.pack(">I",len(data))+kind+data+struct.pack(">I", zlib.crc32(kind+data)&0xffffffff)
        png = b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR", struct.pack(">IIBBBBB",2,2,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(b"\x00"*14))+chunk(b"IEND",b"")
        p=self.root/"result.png";p.write_bytes(png);sd.validate_png(p,2,2)
        with self.assertRaises(RuntimeError):sd.validate_png(p,3,2)
        p.write_bytes(png[:-5])
        with self.assertRaises(RuntimeError):sd.validate_png(p,2,2)

    def test_cancel_only_marks_the_active_job(self):
        self.assertFalse(sd.cancel(self.root)["requested"])
        p=self.root/"Agent/.runtime/sdcpp-active.json";p.parent.mkdir(parents=True);p.write_text(json.dumps({"token":"a"*32}))
        self.assertTrue(sd.cancel(self.root)["requested"])
        self.assertTrue((p.parent/("sdcpp-"+"a"*32+".stop")).exists())

    def test_cuda_only_jobs_reject_radeon_without_rejecting_cpu_alternatives(self):
        hw = {**self.hw, "gpus": [{"index":0, "backend":"vulkan", "free_bytes":24*sd.GIB}]}
        for command in CUDA_ONLY:
            with self.assertRaisesRegex(RuntimeError, "NVIDIA CUDA"): require_workload(command, hw)
        for command in ROCM_MEDIA - {'music', 'score-video'}:
            with self.assertRaisesRegex(RuntimeError, "compute probe"): require_workload(command, hw)
        for command in ("image", "transcribe", "voice-say", "science", "audio-edit", "video-adjust", "mux", "music", "score-video"):
            require_workload(command, hw)
        require_workload("video", {**self.hw, "gpus": [{"index":0, "backend":"cuda"}]})

    def test_abandoned_partial_cleanup_preserves_completed_outputs(self):
        runtime = self.root/"Agent/.runtime"; runtime.mkdir(parents=True)
        out = self.root/"Outputs/Images"; out.mkdir(parents=True)
        token="f"*32
        (runtime/"sdcpp-active.json").write_text(json.dumps({"token":token}))
        part=out/("sd15_"+token[:12]+".part.png");part.write_bytes(b"partial")
        completed=out/("sd15_"+token[:12]+".png");completed.write_bytes(b"keep")
        sd.cleanup_abandoned(self.root)
        self.assertFalse(part.exists()); self.assertEqual(completed.read_bytes(),b"keep")

    def test_live_ram_floor_terminates_only_owned_worker_without_publishing(self):
        process=Mock(pid=12345);process.poll.return_value=None
        job=Mock();validate=Mock()
        with patch.object(sd.subprocess,'Popen',return_value=process),patch.object(sd,'WorkerJob',return_value=job),\
             patch.object(sd,'require_space'),patch.object(sd,'memory_info',return_value=(16*sd.GIB,2*sd.GIB)):
            with self.assertRaisesRegex(RuntimeError,'free-RAM reserve'):
                sd.run_generation({'backend':'cpu','engine':'test','min_free_ram_bytes':3*sd.GIB},
                    lambda part: ['test-worker',str(part)],validate,root=self.root,kind='video')
        job.close.assert_called_once();process.kill.assert_called_once();process.wait.assert_called_once()
        validate.assert_not_called()
        self.assertFalse((self.root/'Agent/.runtime/sdcpp-active.json').exists())
        self.assertEqual(list((self.root/'Outputs/Videos').iterdir()),[])


if __name__ == "__main__": unittest.main()
