from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import native_video as video


class NativeVideoTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.hw={'system':'Windows','machine':'AMD64','ram_available_bytes':16*video.GIB,'gpus':[]}
        self.engine={'backend':'vulkan','engine':'sdcpp-vulkan','executable':'engine.exe','device':'vulkan0',
                     'shared_memory':False,'max_vram_gib':4}

    def test_wan_profile_admits_dedicated_but_accounts_for_shared_memory(self):
        with patch.object(video,'engine_plan',return_value=self.engine),patch.object(video,'SIZES',{}):
            plan=video.video_plan(self.root,hardware=self.hw)
            self.assertEqual(plan['profile'],'wan13-t2v')
            self.engine['shared_memory']=True
            with self.assertRaisesRegex(RuntimeError,'18 GiB'):video.video_plan(self.root,hardware=self.hw)

    def test_invalid_frame_and_pixel_budgets_rejected_before_loading(self):
        with patch.object(video,'engine_plan') as engine:
            for kwargs in ({'frames':18},{'frames':37},{'frames':33,'width':512,'height':512},
                           {'width':255},{'fps':0},{'engine':'comfyui'}):
                with self.assertRaises(ValueError):video.video_plan(self.root,hardware=self.hw,**kwargs)
        engine.assert_not_called()

    def test_missing_weights_fail_without_downloading(self):
        with patch.object(video,'engine_plan',return_value=self.engine):
            with self.assertRaisesRegex(RuntimeError,'missing/incomplete'):video.video_plan(self.root,hardware=self.hw)

    def test_command_uses_video_mode_and_separate_quantized_text_encoder(self):
        plan={**self.engine,'width':256,'height':256,'frames':5,'fps':8}
        args=video.command(plan,self.root,'A "quoted" teapot; literal',None,52,self.root/'video.avi',2)
        self.assertEqual(args[args.index('-M')+1],'vid_gen')
        self.assertIn(str(self.root/video.T5),args)
        self.assertIn('te=cpu,vae=cpu,diffusion=vulkan0',args)
        self.assertIn('A "quoted" teapot; literal',args)
        with self.assertRaisesRegex(ValueError,'LoRAs'):video.command(plan,self.root,'<lora:wrong:1>',None,52,self.root/'video.avi',2)


if __name__=='__main__':unittest.main()
