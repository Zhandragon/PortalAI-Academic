import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'ControlCenter')]
import runtime_policy as runtime
import effort_policy as effort
import chat_vision_policy as vision
import model_preferences
from chat_effort_ui import requires_vision, model_label


class VisionPolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        scale = patch.object(runtime, 'GIB', 1024)
        scale.start(); self.addCleanup(scale.stop)
        self.hw = {'system': 'Windows', 'machine': 'AMD64', 'ram_total_bytes': 32*1024,
                   'ram_available_bytes': 20*1024, 'gpus': []}
        self.backend = {'backend': 'cpu', 'device': 'none', 'executable': 'fixture', 'gpu': None}
        self.policy = {'selection': 'qwen4-q4', 'variant_preference': 'standard', 'context_tokens': 8192,
                       'vision_routing': 'automatic', 'models': [], 'storage': {
                           'minimum_free_gib': 1, 'minimum_free_fraction': 0, 'output_reserve_gib': 1}}
        for name, variant in [('qwen4-q4', 'standard'), ('qwen4-abliterated-q4', 'abliterated')]:
            self.add_model(name, variant, 2500, False)
        for variant, sizes in vision.VISION_MODELS.items():
            self.add_model(sizes['small'], variant, 1100, True)
            self.add_model(sizes['balanced'], variant, 2500, True)

    def add_model(self, name, variant, size, projector):
        model = {'id': name, 'variant': variant, 'path': name+'.gguf', 'layers': 28,
                 'max_context_tokens': 8192, 'automatic': not projector,
                 'automatic_uncensored': False, 'cpu_auto': True, 'vision_only': projector}
        (self.root / model['path']).write_bytes(b'x'*size)
        if projector:
            model['projector'] = name+'.mmproj'
            (self.root / model['projector']).write_bytes(b'p'*820)
        self.policy['models'].append(model)

    def plan(self, level='balanced', **kwargs):
        with patch.object(runtime, 'choose_backend', return_value=self.backend):
            return effort.require_chat_plan(level, self.root, policy=self.policy,
                hardware=self.hw, require_vision=True, **kwargs)

    def test_balanced_image_uses_4b_without_mutating_saved_text_choice(self):
        before = copy.deepcopy(self.policy)
        result = self.plan()
        self.assertEqual(result['selection'], 'qwen-vl4-q4')
        self.assertEqual(self.policy, before)
        self.assertTrue(result['vision_request'])
        self.assertIn('--mmproj', result['command'])
        self.assertIn('--no-mmproj-offload', result['command'])

    def test_fast_image_uses_only_2b(self):
        self.assertEqual(self.plan('fast')['selection'], 'qwen-vl2-q4')
        row = next(m for m in self.policy['models'] if m['id']=='qwen-vl2-q4')
        (self.root / row['projector']).unlink()
        with self.assertRaisesRegex(RuntimeError, 'matching vision'):
            self.plan('fast')

    def test_current_free_ram_falls_back_to_2b_with_reserves(self):
        self.hw['ram_available_bytes'] = 7*1024
        self.assertEqual(self.plan()['selection'], 'qwen-vl2-q4')
        self.hw['ram_available_bytes'] = 3*1024
        with self.assertRaisesRegex(RuntimeError, 'RAM/VRAM'):
            self.plan()

    def test_missing_projector_falls_back_without_changing_variant(self):
        row = next(m for m in self.policy['models'] if m['id']=='qwen-vl4-q4')
        (self.root / row['projector']).unlink()
        self.assertEqual(self.plan()['selection'], 'qwen-vl2-q4')

    def test_uncensored_never_silently_uses_standard_vision(self):
        self.policy.update(selection='qwen4-abliterated-q4', variant_preference='uncensored')
        self.assertEqual(self.plan()['selection'], 'qwen-vl4-abliterated-q4')
        for m in self.policy['models']:
            if m.get('projector') and m['variant']=='uncensored':
                (self.root / m['path']).unlink()
        with self.assertRaisesRegex(RuntimeError, 'matching vision'):
            self.plan()

    def test_off_refuses_text_pin_and_explicit_vision_remains_pinned(self):
        self.policy['vision_routing'] = 'off'
        with self.assertRaisesRegex(RuntimeError, 'Enable Automatic image vision'):
            self.plan()
        self.policy['selection'] = 'qwen-vl4-q4'
        self.assertEqual(self.plan()['selection'], 'qwen-vl4-q4')
        self.hw['ram_available_bytes'] = 6*1024
        with self.assertRaises(RuntimeError): self.plan()

    def test_text_request_excludes_companions_and_keeps_original_pin(self):
        with patch.object(runtime, 'choose_backend', return_value=self.backend):
            result = effort.require_chat_plan('balanced', self.root, policy=self.policy, hardware=self.hw)
        self.assertEqual(result['selection'], 'qwen4-q4')
        self.assertFalse(result['vision_request'])
        self.assertTrue(all(not m.get('vision_only') for m in runtime.automatic_models(self.policy)))

    def test_preview_is_capacity_only_and_real_admission_uses_free_memory(self):
        self.hw['ram_available_bytes'] = 3*1024
        with patch.object(runtime, 'choose_backend', return_value=self.backend):
            preview = effort.capabilities(self.root, policy=self.policy, hardware=self.hw, require_vision=True)
        self.assertEqual(preview['profiles']['balanced']['selection'], 'qwen-vl4-q4')
        self.assertTrue(preview['preview_only'])
        with self.assertRaises(RuntimeError): self.plan()

    def test_shared_gpu_memory_is_not_counted_as_extra_ram(self):
        self.backend.update(backend='vulkan', device='Vulkan0', gpu={
            'free_bytes': 20*1024, 'total_bytes': 20*1024, 'shared_memory': True})
        self.hw['ram_available_bytes'] = 3*1024
        with self.assertRaises(RuntimeError): self.plan()

    def test_policy_signature_changes_with_routing_toggle(self):
        before = effort.chat_policy_signature(self.policy)
        self.policy['vision_routing'] = 'off'
        self.assertNotEqual(before, effort.chat_policy_signature(self.policy))

    def test_all_four_pairs_request_minimum_image_tokens(self):
        for variant, names in vision.VISION_MODELS.items():
            for identity in names.values():
                self.policy['selection'] = identity
                plan = self.plan('fast')
                self.assertEqual(plan['model']['image_min_tokens'], 1024)
                self.assertEqual(plan['command'][plan['command'].index('--image-min-tokens')+1], '1024')
                self.assertGreaterEqual(plan['model']['image_buffer_bytes'], runtime.GIB // 2)

    def test_small_vision_does_not_silently_raise_too_small_context(self):
        self.policy['context_tokens'] = 2048
        with self.assertRaisesRegex(RuntimeError, '4096 context'):
            self.plan('fast')
        self.assertEqual(self.policy['context_tokens'], 2048)

    def test_larger_minimum_increases_ram_and_context_requirement(self):
        row = next(m for m in self.policy['models'] if m['id']=='qwen-vl2-q4')
        before = self.plan('fast')['model']
        row['image_min_tokens'] = 2048
        after = self.plan('fast')['model']
        self.assertEqual(after['estimated_ram_bytes']-before['estimated_ram_bytes'], runtime.GIB // 2)
        self.policy['context_tokens'] = 4096
        with self.assertRaisesRegex(RuntimeError, '5120 context'):
            self.plan('fast')

    def test_image_ram_headroom_is_admitted_before_loading(self):
        plan = self.plan('fast')['model']
        self.hw['ram_available_bytes'] = plan['estimated_ram_bytes'] + 2*runtime.GIB
        # Pin the context to keep this test about memory, not automatic fallback.
        self.policy['selection'] = 'qwen-vl2-q4'
        self.assertEqual(self.plan()['selection'], 'qwen-vl2-q4')
        self.hw['ram_available_bytes'] -= 1
        with self.assertRaisesRegex(RuntimeError, 'RAM/VRAM'):
            self.plan()

    def test_text_plan_has_no_image_flag_or_encoder_headroom(self):
        with patch.object(runtime, 'choose_backend', return_value=self.backend):
            plan = effort.require_chat_plan('fast', self.root, policy=self.policy, hardware=self.hw)
        self.assertNotIn('--image-min-tokens', plan['command'])
        self.assertNotIn('image_buffer_bytes', plan['model'])

    def test_regular_build_plan_has_same_small_vision_command(self):
        self.policy['selection'] = 'qwen-vl2-q4'
        with patch.object(runtime, 'choose_backend', return_value=self.backend):
            plan = runtime.build_plan(self.root, self.hw, self.policy)
        self.assertEqual(plan['command'][plan['command'].index('--image-min-tokens')+1], '1024')

    def test_retired_pair_is_rejected_even_with_stale_profile(self):
        self.policy['selection'] = 'qwen-vl2-abliterated-q4'
        row = next(m for m in self.policy['models'] if m['id']==self.policy['selection'])
        row['path'] = 'Qwen3-VL-2B-Instruct-abliterated.Q4_K_M.gguf'
        (self.root/row['path']).write_bytes(b'x'*1100)
        with self.assertRaisesRegex(RuntimeError, 'previous 2B Abliterated'):
            self.plan('fast')

    def test_loading_signature_includes_minimum_and_code_revision(self):
        before = effort.chat_policy_signature(self.policy)
        self.assertEqual(before['vision_runtime_revision'], runtime.SMALL_VISION_RUNTIME_REVISION)
        self.policy['models'][-1]['image_min_tokens'] = 2048
        self.assertNotEqual(before, effort.chat_policy_signature(self.policy))

    def test_manifest_profiles_and_catalog_use_matching_replacement(self):
        import model_variants
        assets = json.loads((ROOT/'Agent/small_vision_assets.json').read_text())
        pair = [a for a in assets if a['variant']=='uncensored' and '2B' in a['path']]
        self.assertEqual(len(pair), 2)
        self.assertTrue(all(a['revision']=='5ed601c9635da33a268c3b491c1348d1db39e71a' for a in pair))
        self.assertEqual({a['sha256'] for a in pair}, {
            '2e52340effacd3db285bcc0558b325f87830c9c0f003c11b339660b8301b935a',
            '3c334d6d2d95d20521465c673ad5538331cd4e058d6a80dede3036ad4fa532e4'})
        rows = next(x for x in model_variants.CATALOG if x['id']=='qwen-vl2')['uncensored']
        self.assertEqual({(x['path'],x['bytes']) for x in rows}, {(x['path'],x['bytes']) for x in pair})
        cfg = json.loads((ROOT/'Agent/hardware_profiles.json').read_text())
        model = next(x for x in cfg['models'] if x['id']=='qwen-vl2-abliterated-q4')
        self.assertEqual({model['path'],model['projector']}, {x['path'] for x in pair})
        self.assertIn('mmproj-Huihui-Qwen3-VL-2B-Instruct-abliterated-F16.gguf', model['projector'])

    def test_preference_validation_and_merge_preserve_other_choices(self):
        changed = model_preferences.merge(self.policy, {'vision_routing': 'off'})
        self.assertEqual(changed['selection'], 'qwen4-q4')
        self.assertEqual(changed['vision_routing'], 'off')
        self.assertEqual(model_preferences.personal(changed)['vision_routing'], 'off')
        with self.assertRaises(ValueError): model_preferences.validate({'vision_routing': True})

    def test_words_alone_do_not_request_vision_and_active_images_do(self):
        self.assertFalse(requires_vision({'messages': [{'role':'user','content':'Talk about image models'}]}))
        messages = [{'role':'user','content':[{'type':'image_url','image_url':{'url':'fixture'}}]},
                    {'role':'user','content':'What color was it?'}]
        self.assertTrue(requires_vision({'messages':messages}))
        self.assertFalse(requires_vision({'messages':messages,'context_state':{'cursor':1}}))
        self.assertEqual(model_label('qwen-vl2-abliterated-q4'), '2B Vision Abliterated')


if __name__ == '__main__': unittest.main()
