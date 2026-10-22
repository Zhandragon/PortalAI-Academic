"""Explicit selection, catalog truthfulness, and alternate model admission."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import ai_tools
import model_variants as variants
import native_video as video
import runtime_policy as runtime
import media_edit_bridge as media_edit
import chat_model_switch as chat_switch
from account_tool_policy import registered_media_argv
from chat_effort_ui import model_label


class ModelVariantTests(unittest.TestCase):
    def test_chat_labels_identify_actual_variants_without_guessing(self):
        self.assertEqual(model_label('qwen27-standard-q4'),'27B Standard')
        self.assertEqual(model_label('LLM/models/Qwen3.8-27B-Q4_K_M.gguf'),'27B Standard')
        self.assertEqual(model_label('qwen27-q5'),'27B Abliterated')
        self.assertEqual(model_label('LLM/models/Qwen3.8-27B-Abliterated-Q4_K_M.gguf'),'27B Abliterated')
        self.assertEqual(model_label('custom-27b'),'27B')

    def test_large_encoder_uses_its_own_free_memory_admission(self):
        gib=1024**3
        hw={'system':'Windows','ram_available_bytes':19*gib,
            'gpus':[{'index':0,'backend':'cuda','free_bytes':24*gib}]}
        with self.assertRaisesRegex(RuntimeError,'20 GiB'):
            variants.require_flux_alternate(ROOT,hw)
        hw['ram_available_bytes']=24*gib
        hw['gpus']=[{'index':0,'backend':'cuda','free_bytes':12*gib},
                    {'index':1,'backend':'cuda','free_bytes':24*gib}]
        with self.assertRaisesRegex(RuntimeError,'20 GiB'):
            variants.require_flux_alternate(ROOT,hw)
        hw['system']='Linux'
        with self.assertRaisesRegex(RuntimeError,'Windows/CUDA'):
            variants.require_flux_alternate(ROOT,hw)

    def test_cached_model_does_not_override_current_variant_preference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); runtime_dir=root/'Agent/.runtime'; runtime_dir.mkdir(parents=True)
            saved={'level':'fast','preview_only':False,'model':{'id':'alternate'},
                   'command':[],'completion_options':{},'backend':{}}
            (runtime_dir/'hardware_launch_plan.json').write_text(json.dumps(saved))
            standard={'model_preference':{'explicit':None,'automatic':['standard']}}
            self.assertIsNone(chat_switch._saved_admitted_plan(root,'fast',standard))
            explicit={'model_preference':{'explicit':'alternate','automatic':['standard']}}
            self.assertEqual(chat_switch._saved_admitted_plan(root,'fast',explicit),saved)
            explicit['model_preference']['explicit']='another-alternate'
            self.assertIsNone(chat_switch._saved_admitted_plan(root,'fast',explicit))

    def test_frame_inpaint_uses_requested_workflow_and_native_scaled_alternate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            generated = root/'generated.png'; generated.write_bytes(b'synthetic output')
            bridge = Mock(); bridge.run.return_value = {'files':[str(generated)]}
            with patch('radeon_edit.uses_radeon', return_value=False), \
                 patch('comfy_bridge.ComfyBridge', return_value=bridge), \
                 patch.object(media_edit, 'private_path', return_value=root):
                media_edit._comfy_inpaint_image(root/'in.png',root/'mask.png','teapot',variant='uncensored')
                bridge.workflow.assert_called_with('inpaint_uncensored')
                media_edit._comfy_inpaint_image(root/'in.png',root/'mask.png','teapot')
                bridge.workflow.assert_called_with('inpaint_official')
            sys.path.append(str(ROOT/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages'))
            from PIL import Image
            Image.new('RGB',(128,128),'red').save(root/'in.png')
            Image.new('L',(128,128),0).save(root/'mask.png')
            Image.new('RGB',(128,128),'blue').save(generated)
            with patch('radeon_edit.uses_radeon',return_value=True), \
                 patch('native_flux.plan',return_value={'model_variant':'uncensored'}) as plan, \
                 patch('native_flux.edit',return_value={'files':[str(generated)]}) as edit, \
                 patch.object(media_edit,'private_path',return_value=root):
                output=media_edit._comfy_inpaint_image(root/'in.png',root/'mask.png','teapot',variant='uncensored')
                plan.assert_called_once_with(variant='uncensored')
                self.assertEqual(edit.call_args.args[0]['model_variant'],'uncensored')
                with Image.open(output) as im:self.assertEqual(im.getpixel((0,0)),(255,0,0))

    def test_prompt_content_never_authorizes_alternate(self):
        for prompt in ('a flower', 'a blood red sunset', 'use alternate colors',
                       'write the word uncensored on a sign', 'previous attempt refused',
                       'an explicit architectural blueprint', ''):
            self.assertEqual(ai_tools.select_variant(prompt)[0], 'official')
        self.assertEqual(ai_tools.select_variant('a flower', True)[0], 'uncensored')
        self.assertEqual(ai_tools.select_variant('uncensored', False, True)[0], 'official')
        with self.assertRaises(ValueError):
            ai_tools.select_variant('anything', True, True)

    def test_catalog_cli_never_touches_profile_or_workers(self):
        output = io.StringIO()
        with patch.object(sys, 'argv', ['ai_tools.py', 'model-variants', '--tool', 'sfx']), \
             patch.object(ai_tools, 'load_config', side_effect=AssertionError('config')), \
             patch.object(runtime, 'detect_hardware', side_effect=AssertionError('hardware')), \
             patch.object(ai_tools.subprocess, 'Popen', side_effect=AssertionError('worker')), \
             redirect_stdout(output):
            with self.assertRaises(SystemExit) as stopped:
                ai_tools.main()
        self.assertEqual(stopped.exception.code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['default'], 'standard')
        self.assertFalse(result['hardware_probed'])
        self.assertFalse(result['files_checked'])
        self.assertIn('not censorship', result['models'][0]['notes'])

    def test_standard_guest_registered_catalog_is_direct_argv(self):
        boot = ROOT/'Runtime/BootstrapPython/python.exe'
        result = registered_media_argv('python Agent/ai_tools.py model-variants --tool video', ROOT, boot)
        self.assertEqual(result, [str(boot), str(ROOT/'Agent/ai_tools.py'), 'model-variants', '--tool', 'video'])
        with self.assertRaises(PermissionError):
            registered_media_argv('python Agent/ai_tools.py model-variants; whoami', ROOT, boot)

    def test_missing_assets_never_report_present(self):
        with tempfile.TemporaryDirectory() as folder:
            result = variants.catalog('video-small', root=folder, check_files=True)
        row = result['models'][0]
        self.assertFalse(row['standard'][0]['present_readable'])
        self.assertFalse(row['uncensored'][0]['present_readable'])
        self.assertFalse(row['uncensored'][0]['size_matches'])
        with self.assertRaises(ValueError): variants.catalog('invented-tool')

    def test_combined_tools_expose_all_model_stages(self):
        ids = {row['id'] for row in variants.catalog('dialogue-video')['models']}
        self.assertTrue({'wan22', 'vace', 'voice', 'musetalk', 'music'} <= ids)
        row = next(row for row in variants.catalog('image')['models'] if row['id']=='flux-text-encoder')
        self.assertEqual(row['uncensored'][0]['bytes'], 16381516808)
        self.assertEqual(row['status'], 'parallel')

    def test_auto_does_not_select_an_explicit_only_model_even_if_it_fits(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(runtime, 'GIB', 1024):
            root = Path(folder); (root/'alternate.gguf').write_bytes(b'x')
            policy = {'models': [{'id':'alternate', 'path':'alternate.gguf', 'layers':1,
                                  'automatic':False, 'cpu_auto':True}], 'context_tokens':512}
            hardware = {'ram_available_bytes':32*1024}
            with self.assertRaisesRegex(RuntimeError, 'explicit model selection required'):
                runtime.select_model(root, hardware, {'gpu':None}, policy)
            policy['selection']='alternate'
            self.assertEqual(runtime.select_model(root, hardware, {'gpu':None}, policy)['selected']['id'], 'alternate')

    def test_native_alternate_admission_selects_exact_weights_with_same_limits(self):
        engine = {'backend':'cpu','engine':'sdcpp-cpu','device':'cpu','executable':'engine.exe'}
        hardware = {'ram_available_bytes':16*video.GIB}
        sizes = {**video.SIZES, video.WAN_ALTERNATE:2838077328}
        def fake_path(root, relative):
            return SimpleNamespace(is_file=lambda: True, stat=lambda: SimpleNamespace(st_size=sizes[relative]))
        with patch.object(video,'engine_plan',return_value=engine), patch.object(video,'portable_path',side_effect=fake_path):
            plan = video.video_plan(ROOT, hardware=hardware, variant='uncensored')
            self.assertEqual(plan['model_path'],video.WAN_ALTERNATE)
            self.assertEqual(plan['min_free_ram_bytes'],3*video.GIB)
            with self.assertRaisesRegex(RuntimeError,'14 GiB'):
                video.video_plan(ROOT, hardware={'ram_available_bytes':10*video.GIB},variant='uncensored')
        argv = video.command(plan, ROOT, 'a teapot rotating', None, 5, ROOT/'synthetic.avi', 1)
        self.assertEqual(argv[argv.index('--diffusion-model')+1],str(ROOT/video.WAN_ALTERNATE))
        plan['model_path']=video.WAN
        with self.assertRaisesRegex(ValueError,'admitted variant'):
            video.command(plan,ROOT,'teapot',None,5,ROOT/'synthetic.avi',1)


if __name__ == '__main__': unittest.main()
