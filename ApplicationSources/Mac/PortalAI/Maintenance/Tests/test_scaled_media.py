"""Hardware admission, architecture rewiring and platform isolation regressions."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'Agent'))
import radeon_edit as edit
import musetalk_amd_bridge as muse
import sfx_amd_bridge as sfx
import sdcpp_bridge as sd
import linux_ml

class ScaledMediaTests(unittest.TestCase):
    def hw(self,shared=False,ram=24,gpu=10,system='Windows'):
        device={'available':True,'compute_ok':True,'bf16_compute_ok':True,'shared_memory':shared,'free_bytes':gpu*sd.GIB,'backend':'rocm'}
        return {'system':system,'machine':'x86_64','gpus':[],'ram_available_bytes':ram*sd.GIB,'amd_gpu':device,'media_gpu':device}

    def test_small_vace_has_no_14b_adapter_references(self):
        wf=json.loads((ROOT/'Workflows/API/Wan2.1_VACE_14B_V2V_API.json').read_text())
        edit.small_vace(wf)
        self.assertNotIn('3',wf)
        self.assertEqual(wf['1']['inputs']['unet_name'],'wan2.1_vace_1.3B_fp16.safetensors')
        for node in wf.values():
            for value in node['inputs'].values():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],str):self.assertIn(value[0],wf)
        self.assertEqual(wf['13']['class_type'],'VAEDecodeTiled')

    def test_shared_ram_is_admitted_separately(self):
        self.assertEqual(edit.plan('video-edit',hardware=self.hw())['max_chunk_frames'],17)
        with self.assertRaisesRegex(RuntimeError,'24 GiB'):edit.plan('video-edit',hardware=self.hw(shared=True,ram=23))
        with self.assertRaisesRegex(RuntimeError,'GPU memory'):edit.plan('video-edit',hardware=self.hw(gpu=7))
        with self.assertRaisesRegex(RuntimeError,'20 GiB'):muse.plan(hardware=self.hw(shared=True,ram=19))

    def test_linux_small_profiles_require_the_linux_probe(self):
        hw=self.hw(system='Linux');hw['media_gpu']={'compute_ok':False}
        for call in (lambda:edit.plan(hardware=hw),lambda:muse.plan(hardware=hw),lambda:sfx.plan(hardware=hw)):
            with self.assertRaisesRegex(RuntimeError,'compute probe'):call()
        self.assertEqual(linux_ml.media_compute(ROOT,self.hw(system='Linux'),True)['backend'],'rocm')

    def test_linux_native_engine_probes_its_own_binary(self):
        with patch.object(sd,'executable',return_value=Path('/portable/sd-cli')) as exe,patch.object(sd,'run_probe',return_value='CPU\tx64'):
            profile=sd.engine_plan(ROOT,self.hw(system='Linux'),'sdcpp-cpu')
        self.assertEqual(profile['backend'],'cpu');exe.assert_called_once_with(ROOT,'cpu')

    def test_windows_cuda_routing_is_unchanged(self):
        hw=self.hw();hw['gpus']=[{'index':0,'backend':'cuda'}]
        self.assertFalse(edit.uses_radeon(hw))

    def test_cpu_diagnostics_are_named_and_memory_bounded(self):
        # Admission unit test, not an audit of installed runtime permissions.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for relative in ('Video/MuseTalk/models/dwpose/dw-ll_ucoco_384.onnx',
                             'Runtime/AMDMusic/api-packages/diffusers/__init__.py',
                             'Runtime/AMDAudio/packages/open_clip/__init__.py',
                             'Services/MMAudio/weights/mmaudio_small_44k.pth'):
                path=root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
            for profile in (edit.plan(root=root,hardware=self.hw(),cpu_validation=True),
                            muse.plan(root=root,hardware=self.hw(),cpu_validation=True),
                            sfx.plan(root=root,hardware=self.hw(),cpu_validation=True)):
                self.assertIn('validation',profile['backend']);self.assertLessEqual(profile['max_memory_bytes'],14*sd.GIB)
                self.assertEqual(profile['min_free_ram_bytes'],4*sd.GIB)

    def test_invalid_edit_never_launches(self):
        with patch.object(edit,'run_generation') as launch:
            for kwargs in ({'steps':0},{'steps':51},{'seed':-1}):
                with self.assertRaises(ValueError):edit.edit({},ROOT/'AGENTS.md','test',**kwargs)
            launch.assert_not_called()

    def test_comfy_input_previews_are_not_generated_outputs(self):
        from comfy_bridge import ComfyBridge
        data={'8':{'videos':[{'filename':'original.mp4','type':'input'}]},
              '9':{'videos':[{'filename':'preview.mp4','type':'temp'}]},
              '15':{'videos':[{'filename':'edited.mp4','type':'output'}]}}
        self.assertEqual([r['filename'] for r in ComfyBridge._collect_file_items(data)],['edited.mp4'])

if __name__=='__main__':unittest.main()
