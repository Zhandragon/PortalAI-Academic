"""Native model selection, admission and literal command/route regressions."""
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch
import tempfile
import subprocess
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent')]
import native_flux as flux
import workload_compatibility as workloads
import model_preferences
import media_policy


class NativeFluxTests(unittest.TestCase):
    def profile(self, variant='uncensored', shared=False, ram=24):
        backend={'backend':'vulkan' if shared else 'cpu','device':'Vulkan0' if shared else 'cpu',
                 'engine':'sdcpp-vulkan' if shared else 'sdcpp-cpu','executable':'engine.exe',
                 'shared_memory':shared,'max_vram_gib':3}
        def asset(root,relative):
            return SimpleNamespace(is_file=lambda:True,stat=lambda:SimpleNamespace(st_size=flux.SIZES[relative]))
        with patch.object(flux,'engine_plan',return_value=backend),patch.object(flux,'portable_path',side_effect=asset):
            return flux.plan(ROOT,variant=variant,engine=backend['engine'],hardware={'ram_available_bytes':ram*flux.GIB})

    def test_variants_share_dit_with_matching_encoder(self):
        for variant,encoder in (('uncensored',flux.ALTERNATE),('official',flux.ENCODER)):
            profile=self.profile(variant)
            argv=flux.command(profile,ROOT,'a literal `test` $(text)',None,52,'output.png')
            self.assertEqual(argv[argv.index('--llm')+1],str(ROOT/encoder))
            self.assertEqual(argv[argv.index('--diffusion-model')+1],str(ROOT/flux.DIT))
            self.assertEqual(argv[argv.index('-p')+1],'a literal `test` $(text)')
            profile['encoder_path']='mismatched'
            with self.assertRaisesRegex(ValueError,'admitted variant'):flux.command(profile,ROOT,'x',None,52,'out.png')

    def test_cpu_and_shared_memory_limits_are_not_vram_interchangeable(self):
        with self.assertRaisesRegex(RuntimeError,'12 GiB'):self.profile(ram=11)
        with self.assertRaisesRegex(RuntimeError,'16 GiB'):self.profile(shared=True,ram=15)
        self.assertEqual(self.profile(shared=True)['max_memory_bytes'],10*flux.GIB)

    def test_automatic_backend_can_keep_the_same_weights_on_cpu(self):
        cpu={'engine':'sdcpp-cpu','backend':'cpu','device':'cpu','executable':'engine.exe'}
        gpu={**cpu,'engine':'sdcpp-vulkan','backend':'vulkan','shared_memory':True}
        def asset(root,relative):
            return SimpleNamespace(is_file=lambda:True,stat=lambda:SimpleNamespace(st_size=flux.SIZES[relative]))
        with patch.object(flux,'engine_plan',side_effect=[gpu,cpu]) as choose,patch.object(flux,'portable_path',side_effect=asset):
            result=flux.plan(ROOT,variant='uncensored',hardware={'ram_available_bytes':14*flux.GIB})
        self.assertEqual(result['engine'],'sdcpp-cpu')
        self.assertEqual(result['encoder_path'],flux.ALTERNATE)
        self.assertIn('auto selected CPU',result['reason'])
        self.assertEqual(choose.call_args.args[2],'sdcpp-cpu')

    def test_validation_rejects_silent_semantic_substitution(self):
        profile=self.profile()
        for kwargs in ({'negative':'blurry'},{'prompt':'<lora:wrong:1>'},{'prompt':'x\0y'},{'steps':0},{'seed':-1}):
            values=dict(prompt='teapot',negative=None,seed=52,output='out.png');values.update(kwargs)
            with self.assertRaises(ValueError):flux.command(profile,ROOT,**values)
        for kwargs in ({'width':1024},{'width':129},{'engine':'comfyui'}):
            with self.assertRaises(ValueError):flux.plan(ROOT,**kwargs)

    def test_native_routes_work_without_rocm_but_semantic_masks_do_not(self):
        hw={'system':'Windows','machine':'AMD64','gpus':[],'amd_gpu':{'compute_ok':False}}
        for cmd in ('edit','inpaint','autoedit','video-inpaint'):
            args=SimpleNamespace(cmd=cmd,edit_profile='auto',engine='auto')
            self.assertTrue(flux.selected(args,hw));workloads.require_workload(cmd,hw,native=True)
        with self.assertRaises(RuntimeError):workloads.require_workload('mask',hw)
        with self.assertRaises(ValueError):workloads.require_workload('music',hw,native=True)
        args=SimpleNamespace(cmd='edit',edit_profile='flux',engine='sdcpp-cpu')
        with self.assertRaises(ValueError):flux.selected(args,hw)

    def test_saved_profile_and_engine_reach_the_native_planner(self):
        policy={'media':{'image_profile':'klein4','image_engine':'sdcpp-cpu','media_variant':'uncensored'},'variant_preference':'standard'}
        model_preferences.validate(policy)
        with patch.object(flux,'plan',return_value={}) as plan:
            media_policy.image_plan(ROOT,hardware={'system':'Linux'},policy=policy)
        self.assertEqual(plan.call_args.kwargs['engine'],'sdcpp-cpu')
        self.assertEqual(plan.call_args.kwargs['variant'],'uncensored')

    def test_masked_edit_preserves_pixels_with_real_ffmpeg_composition(self):
        sys.path.append(str(ROOT/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages'))
        from PIL import Image
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'source.png';mask=folder/'mask.png';output=folder/'out.png'
            Image.new('RGB',(256,128),'red').save(source)
            m=Image.new('L',(256,128),0);m.paste(255,(128,0,256,128));m.save(mask)
            def runner(profile,build,validate,**kwargs):
                commands=build(output)
                subprocess.run(commands[0],check=True,capture_output=True,timeout=20)
                native=commands[1];generated=Path(native[native.index('-o')+1])
                Image.new('RGB',(profile['width'],profile['height']),'blue').save(generated)
                subprocess.run(commands[2],check=True,capture_output=True,timeout=20)
                validate(output);return {'files':[str(output)]}
            with patch.object(flux,'media_reference',side_effect=lambda root,path:Path(path)), \
                 patch.object(flux,'media_temp',return_value=folder), \
                 patch.object(flux,'run_generation',side_effect=runner):
                flux.edit(self.profile(),source,'change the selected area to blue',mask=mask)
            with Image.open(output) as out:
                self.assertEqual(out.getpixel((0,0)),(255,0,0))
                self.assertEqual(out.getpixel((127,127)),(255,0,0))
                self.assertEqual(out.getpixel((128,0)),(0,0,255))


if __name__=='__main__':unittest.main()
