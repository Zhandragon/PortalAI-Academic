"""Hardware-family selection and checkpoint identity without live user state."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import sd15_variants as variants
import sdcpp_bridge as sd
import media_policy as media
import model_variants as catalog
from media_tool_api import image_arguments


class SD15VariantsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        folder = self.root/variants.MODELS; folder.mkdir(parents=True)
        for name in (variants.STANDARD, variants.ALTERNATE): (folder/name).write_bytes(b'test')
        size = patch.object(variants, 'ALTERNATE_BYTES', 4); size.start(); self.addCleanup(size.stop)
        self.plan = dict(profile='sd15', engine='sdcpp-cpu', backend='cpu', device='cpu',
                         executable='engine.exe', width=128, height=128)
        self.hw = dict(system='Windows', machine='AMD64', ram_available_bytes=24*sd.GIB, gpus=[])

    def test_native_argv_uses_selected_named_checkpoint_and_relocated_root(self):
        for variant, name in [('official',variants.STANDARD), ('standard',variants.STANDARD), ('uncensored',variants.ALTERNATE)]:
            plan = variants.select_plan(self.plan, self.root, variant)
            command = sd.command(plan, self.root, 'a teapot', '', 42, self.root/'output.png', steps=2)
            self.assertEqual(command[command.index('-m')+1], str(self.root/variants.MODELS/name))
            self.assertEqual(plan['width'], 128)
            self.assertEqual(plan['engine'], 'sdcpp-cpu')
        with self.assertRaises(ValueError): variants.select_plan(self.plan, self.root, '../other.safetensors')

    def test_missing_or_truncated_explicit_alternate_never_loads_standard(self):
        (self.root/variants.MODELS/variants.ALTERNATE).write_bytes(b'x')
        with self.assertRaisesRegex(RuntimeError, 'missing/incomplete'):
            variants.select_plan(self.plan, self.root, 'uncensored')
        (self.root/variants.MODELS/variants.ALTERNATE).unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing/incomplete'):
            sd.command({**self.plan, 'model_variant':'uncensored'}, self.root, 'teapot', '', 1, self.root/'out.png')
        self.assertEqual(variants.checkpoint(self.root,'standard').name, variants.STANDARD)

    def test_comfy_changes_only_checkpoint_and_leaves_source_graph_intact(self):
        workflow = json.loads((ROOT/'Workflows/API/SD15_T2I_Portable.json').read_text())
        original = copy.deepcopy(workflow)
        changed = variants.configure_workflow(workflow,self.root,'uncensored')
        loader = next(n for n in changed.values() if n.get('class_type') == 'CheckpointLoaderSimple')
        self.assertEqual(loader['inputs']['ckpt_name'], variants.ALTERNATE)
        loader['inputs']['ckpt_name'] = variants.STANDARD
        self.assertEqual(changed, original); self.assertEqual(workflow, original)
        with self.assertRaises(RuntimeError): variants.configure_workflow({},self.root,'uncensored')

    def test_saved_preference_selects_alternate_but_reports_missing_fallback(self):
        rows = copy.deepcopy(catalog.CATALOG)
        next(row for row in rows if row['id']=='sd15')['uncensored'][0]['bytes'] = 4
        with patch.object(catalog,'CATALOG',rows):
            self.assertEqual(catalog.first_pass(self.root,'sd15',policy={})[0],'official')
            policy = {'media':{'media_variant':'uncensored'}}
            self.assertEqual(catalog.first_pass(self.root,'sd15',policy=policy)[0],'uncensored')
            (self.root/variants.MODELS/variants.ALTERNATE).unlink()
            variant, reason = catalog.first_pass(self.root,'sd15',policy=policy)
            self.assertEqual(variant,'official'); self.assertIn('fallback',reason)

    def test_amd_uncensored_keeps_native_profile_instead_of_forcing_flux(self):
        argv = image_arguments({'prompt':'teapot','variant':'uncensored'})
        self.assertNotIn('--profile',argv)
        with patch.object(sd,'engine_plan',return_value=self.plan):
            for variant in ('standard','uncensored'):
                plan = media.image_plan(self.root, engine='sdcpp-cpu', variant=variant, hardware=self.hw, policy={})
                self.assertEqual(plan['profile'],'sd15')
            with self.assertRaisesRegex(RuntimeError,'SD1.5 only'):
                media.image_plan(self.root,profile='flux',engine='sdcpp-cpu',variant='uncensored',hardware=self.hw,policy={})

    def test_auto_cuda_admission_budgets_alternate_not_standard_flux(self):
        hw = {**self.hw,'gpus':[{'index':0,'backend':'cuda','free_bytes':18*sd.GIB}]}
        self.assertEqual(media.image_plan(self.root,hardware=hw,policy={},variant='standard')['profile'],'flux')
        self.assertEqual(media.image_plan(self.root,hardware=hw,policy={},variant='uncensored')['profile'],'sd15')
        self.assertEqual(media.image_plan(self.root,hardware=hw,policy={'media':{'media_variant':'uncensored'}})['profile'],'sd15')
        with patch.object(catalog,'require_flux_alternate',return_value={}):
            self.assertEqual(media.image_plan(self.root,hardware=hw,policy={},variant='uncensored')['profile'],'flux')


if __name__ == '__main__': unittest.main()
