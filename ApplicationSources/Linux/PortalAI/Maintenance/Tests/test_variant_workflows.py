"""The shipped official and alternate graphs must select distinct, compatible assets."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]
MODELS=ROOT/'Generative/ComfyUI_windows_portable/ComfyUI/models'


class VariantWorkflowTests(unittest.TestCase):
    @staticmethod
    def workflow(name):
        return json.loads((ROOT/'Workflows/API'/name).read_text(encoding='utf-8'))

    @staticmethod
    def inputs(graph, kind, key):
        return [n['inputs'][key] for n in graph.values() if n.get('class_type')==kind]

    def test_flux_official_encoder_is_preserved_and_alternate_encoder_is_connected(self):
        cfg=json.loads((ROOT/'Agent/config.json').read_text())['comfy']['workflows']
        for tool in ('image','edit','inpaint'):
            with self.subTest(tool=tool):
                official=self.workflow(cfg[tool+'_official']);alternate=self.workflow(cfg[tool+'_uncensored'])
                self.assertEqual(self.inputs(official,'CLIPLoader','clip_name'),['qwen_3_8b_fp8mixed.safetensors'])
                self.assertEqual(self.inputs(alternate,'CLIPLoader','clip_name'),['flux2-klein-9b-abliterated-qwen3-8b-fp16.safetensors'])
                self.assertEqual(self.inputs(alternate,'CLIPLoader','type'),['flux2'])
                self.assertEqual(self.inputs(alternate,'UNETLoader','unet_name'),['flux-2-klein-base-9b-uncensored.safetensors'])
                for path in self.inputs(alternate,'CLIPLoader','clip_name'):
                    self.assertEqual((MODELS/'text_encoders'/path).stat().st_size,16381516808)

    def test_wan_alternate_keeps_matching_high_low_pair_and_original_base(self):
        official=self.workflow('Wan2.2_14B_I2V_Official.json');alternate=self.workflow('Wan2.2_14B_I2V_Uncensored.json')
        self.assertEqual(set(self.inputs(official,'UNETLoader','unet_name')),set(self.inputs(alternate,'UNETLoader','unet_name')))
        self.assertEqual(set(self.inputs(alternate,'LoraLoaderModelOnly','lora_name')),
                         {'Wan2.2_LightX2V_high_n54vv.safetensors','Wan2.2_LightX2V_low_n54vv.safetensors'})
        self.assertEqual(set(self.inputs(official,'LoraLoaderModelOnly','lora_name')),
                         {'wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors',
                          'wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors'})

    def test_ui_alternate_download_metadata_points_to_verified_publishers(self):
        for filename in ('Flux2_Klein_9B_Image_Edit_Uncensored.json','Wan2.2_14B_I2V_Uncensored.json'):
            text=(ROOT/'Workflows'/filename).read_text(encoding='utf-8')
            self.assertNotIn('Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files/loras/Wan2.2_LightX2V_',text)
            self.assertNotIn('black-forest-labs/FLUX.2-klein-base-9b-fp8/resolve/main/flux-2-klein-base-9b-uncensored',text)


if __name__=='__main__':unittest.main()
