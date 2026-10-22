"""Exercise the actual image CLI parser and route bodies without model execution."""
import argparse
import ast
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import effort_policy as ep
import sd15_variants as variants


class ImageEffortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        folder = self.root/variants.MODELS; folder.mkdir(parents=True)
        for name in (variants.STANDARD, variants.ALTERNATE): (folder/name).write_bytes(b'test')
        size = patch.object(variants, 'ALTERNATE_BYTES', 4); size.start(); self.addCleanup(size.stop)
        tree = ast.parse((ROOT / 'Agent/ai_tools.py').read_text(encoding='utf-8-sig'))
        self.main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        variant = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_add_variant_flags')
        parser_statements = []
        for node in self.main.body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'args' for target in node.targets):
                break
            parser_statements.append(node)
        namespace = {'argparse': argparse}
        module = ast.Module(body=[variant, *parser_statements], type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), 'image-parser', 'exec'), namespace)
        self.parser = namespace['parser']
        self.workflow = json.loads((ROOT / 'Workflows/API/SD15_T2I_Portable.json').read_text())

    def test_parser_has_optional_steps_and_accepts_explicit_value(self):
        self.assertIsNone(self.parser.parse_args(['image', 'cube']) .steps)
        self.assertEqual(self.parser.parse_args(['image', 'cube', '--steps=17']).steps, 17)

    def test_sd15_defaults_and_explicit_steps(self):
        for level, wanted in (('fast', 12), ('balanced', 20), ('deep', 30)):
            with patch.object(ep, 'check_chat_permission'):
                self.assertEqual(ep.image_steps('sd15', environ={'PORTALAI_TOOL_EFFORT': level}), wanted)
                self.assertEqual(ep.image_steps('sd15', 17, {'PORTALAI_TOOL_EFFORT': level}), 17)
        self.assertEqual(ep.image_steps('sd15', environ={}), 20)

    def test_flux_keeps_workflow_and_rejects_explicit_steps(self):
        self.assertIsNone(ep.image_steps('flux', environ={'PORTALAI_TOOL_EFFORT': 'fast'}))
        with self.assertRaisesRegex(ValueError, 'SD1.5'):
            ep.image_steps('flux', 12)

    def test_invalid_steps_are_rejected(self):
        for value in (0, 51, True, 2.5, '20'):
            with self.assertRaises(ValueError):
                ep.image_steps('sd15', value)

    def test_deep_gate_does_not_override_explicit_request(self):
        with patch.object(ep, 'check_chat_permission', side_effect=RuntimeError('session locked')) as gate:
            with self.assertRaisesRegex(RuntimeError, 'session locked'):
                ep.image_steps('sd15', environ={'PORTALAI_TOOL_EFFORT': 'deep'})
            self.assertEqual(ep.image_steps('sd15', 17, {'PORTALAI_TOOL_EFFORT': 'deep'}), 17)
            self.assertEqual(gate.call_count, 1)

    def test_workflow_copy_preserves_seed_cfg_dimensions_and_original(self):
        original = copy.deepcopy(self.workflow)
        result = ep.sd15_workflow_steps(self.workflow, 12)
        self.assertEqual(self.workflow, original)
        self.assertEqual(result['5']['inputs']['steps'], 12)
        result['5']['inputs']['steps'] = 20
        self.assertEqual(result, original)

    def test_wrong_workflow_shape_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'exactly one'):
            ep.sd15_workflow_steps({'sampler': {'class_type': 'SamplerCustomAdvanced', 'inputs': {}}}, 12)

    def _image_nodes(self):
        nodes = [node for node in ast.walk(self.main) if isinstance(node, ast.If)
                 and ast.unparse(node.test) == "args.cmd == 'image'"]
        first = next(node for node in nodes if any(isinstance(n, ast.ImportFrom) and n.module == 'media_policy'
                                                  for n in node.body))
        comfy = next(node for node in nodes if any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                                                  and ast.unparse(n.value.func) == 'b.configure_t2i'
                                                  for n in node.body))
        return first, comfy

    def _namespace(self, profile):
        return {'args': self.parser.parse_args(['image', 'cube', '--seed', '42']), 'os': os,
                'root_dir': lambda: self.root, '_set_gpu_state': Mock(), '_complete_abort_watchdog': Mock(),
                'watchdog_marker': None, 'emit': Mock(side_effect=StopIteration),
                'select_variant': lambda *args: ('standard', 'test'),
                '_default_variant': lambda *args: ('official', 'fixture standard preference'),
                '_chosen_variant': lambda *args: ('official', 'fixture standard preference'),
                'workflow_key': lambda *args: 'image', '_workflow_models': lambda workflow: [],
                'resolve_root': lambda path: path, 'cfg': {'outputs': {'images': 'Outputs/Images'}},
                'b': types.SimpleNamespace(workflow_file=Mock(return_value=self.workflow),
                                          workflow=Mock(return_value=self.workflow),
                                          configure_t2i=Mock(), run=Mock(return_value={'files': ['image.png']}))}

    def test_native_cli_route_passes_selected_steps_to_real_bridge_api(self):
        first, _ = self._image_nodes()
        profile = {'profile': 'sd15', 'engine': 'sdcpp-cpu'}
        generate = Mock(return_value={'steps': 12})
        media = types.SimpleNamespace(image_plan=Mock(return_value=profile))
        native = types.SimpleNamespace(generate=generate)
        namespace = self._namespace(profile)
        with patch.dict(sys.modules, {'media_policy': media, 'sdcpp_bridge': native}),\
             patch.dict(os.environ, {'PORTALAI_TOOL_EFFORT': 'fast'}):
            with self.assertRaises(StopIteration):
                exec(compile(ast.Module(body=[first], type_ignores=[]), 'image-native-route', 'exec'), namespace)
        self.assertEqual(generate.call_args.kwargs['steps'], 12)

    def test_cli_chat_origin_and_one_off_override_reach_actual_admission(self):
        first, _ = self._image_nodes()
        for chat_origin, override, respect in (('1',False,True),('1',True,False),('',False,False)):
            namespace = self._namespace({})
            namespace['args'].profile = 'sd15'
            namespace['args'].override_saved_profile = override
            plan = Mock(side_effect=RuntimeError('admission sentinel'))
            with patch.dict(sys.modules, {'media_policy':types.SimpleNamespace(image_plan=plan)}), \
                 patch.dict(os.environ, {'PORTALAI_CHAT_IMAGE_DEFAULTS':chat_origin}):
                with self.assertRaisesRegex(RuntimeError, 'admission sentinel'):
                    exec(compile(ast.Module(body=[first],type_ignores=[]),'image-admission','exec'),namespace)
            self.assertEqual(plan.call_args.kwargs['respect_saved_profile'], respect)
            self.assertEqual(plan.call_args.kwargs['profile'], 'sd15')

    def test_uncensored_native_and_comfy_routes_load_and_report_alternate(self):
        first, comfy = self._image_nodes()
        for engine in ('sdcpp-cpu', 'comfyui'):
            with self.subTest(engine=engine):
                profile = {'profile':'sd15', 'engine':engine, 'workflow':'sd15.json', 'width':512, 'height':512}
                namespace = self._namespace(profile)
                namespace['args'].uncensored = True
                namespace['_chosen_variant'] = lambda *args: ('uncensored', 'explicit request')
                generate = Mock(return_value={'files':['synthetic.png']})
                with patch.dict(sys.modules, {'media_policy':types.SimpleNamespace(image_plan=Mock(return_value=profile)),
                                               'sdcpp_bridge':types.SimpleNamespace(generate=generate)}), \
                     patch.dict(os.environ, {'PORTALAI_TOOL_EFFORT':'fast'}):
                    with self.assertRaises(StopIteration):
                        exec(compile(ast.Module(body=[first, comfy], type_ignores=[]), 'image-alternate-route', 'exec'), namespace)
                self.assertEqual(namespace['emit'].call_args.args[0]['model_variant'], 'uncensored')
                if engine.startswith('sdcpp'):
                    self.assertEqual(generate.call_args.args[0]['checkpoint'], variants.MODELS+variants.ALTERNATE)
                else:
                    sent = namespace['b'].run.call_args.args[0]
                    loaders = [n for n in sent.values() if n.get('class_type') == 'CheckpointLoaderSimple']
                    self.assertEqual(loaders[0]['inputs']['ckpt_name'], variants.ALTERNATE)
                    self.assertEqual(sent['5']['inputs']['steps'], 12)

    def test_comfy_sd15_route_changes_only_sd15_sampler_budget(self):
        first, comfy = self._image_nodes()
        profile = {'profile': 'sd15', 'engine': 'comfyui', 'workflow': 'sd15.json', 'width': 512, 'height': 512}
        namespace = self._namespace(profile)
        with patch.dict(sys.modules, {'media_policy': types.SimpleNamespace(image_plan=Mock(return_value=profile))}),\
             patch.dict(os.environ, {'PORTALAI_TOOL_EFFORT': 'fast'}):
            exec(compile(ast.Module(body=[first], type_ignores=[]), 'image-profile-route', 'exec'), namespace)
            with self.assertRaises(StopIteration):
                exec(compile(ast.Module(body=[comfy], type_ignores=[]), 'image-comfy-route', 'exec'), namespace)
        sent_workflow = namespace['b'].run.call_args.args[0]
        self.assertEqual(sent_workflow['5']['inputs']['steps'], 12)
        self.assertEqual(self.workflow['5']['inputs']['steps'], 20)

    def test_comfy_flux_route_does_not_receive_generic_step_override(self):
        first, comfy = self._image_nodes()
        profile = {'profile': 'flux', 'engine': 'comfyui', 'workflow': None, 'width': 1024, 'height': 1024}
        namespace = self._namespace(profile)
        with patch.dict(sys.modules, {'media_policy': types.SimpleNamespace(image_plan=Mock(return_value=profile))}),\
             patch.dict(os.environ, {'PORTALAI_TOOL_EFFORT': 'fast'}):
            exec(compile(ast.Module(body=[first], type_ignores=[]), 'image-profile-route', 'exec'), namespace)
            with self.assertRaises(StopIteration):
                exec(compile(ast.Module(body=[comfy], type_ignores=[]), 'image-comfy-route', 'exec'), namespace)
        self.assertIs(namespace['b'].run.call_args.args[0], self.workflow)


if __name__ == '__main__':
    unittest.main()
