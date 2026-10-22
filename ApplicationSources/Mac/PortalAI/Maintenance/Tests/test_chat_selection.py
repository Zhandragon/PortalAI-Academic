"""Size and variant are independent; explicit pairs remain pinned at admission."""
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
import chat_selection as selection
import effort_policy as effort
import runtime_policy as runtime
import test_effort_policy as fixtures


class ChatSelectionTests(unittest.TestCase):
    setUp = fixtures.EffortPolicyTests.setUp

    def test_each_size_has_independent_standard_and_uncensored_choices(self):
        for variant in ('standard', 'uncensored'):
            for level, choices in selection.TIERS.items():
                changes = selection.choice_changes(self.root, self.policy, level=level,
                                                    uncensored=variant == 'uncensored')
                self.assertEqual(changes, {'selection': choices[variant][0], 'variant_preference': variant})
                policy = {**self.policy, **changes}
                admitted = effort.require_chat_plan(level, self.root, hardware=self.hw, policy=policy)
                self.assertEqual(admitted['selection'], changes['selection'])
                self.assertEqual(runtime.model_variant(admitted['model']), variant)

    def test_checkbox_keeps_size_and_preserves_an_existing_matching_quantization(self):
        self.policy.update(selection='qwen27-q5', variant_preference='standard')
        self.assertEqual(selection.selected_variant(self.policy), 'uncensored')
        self.assertEqual(selection.choice_changes(self.root, self.policy, level='deep')['selection'], 'qwen27-q5')
        self.assertEqual(selection.choice_changes(self.root, self.policy, uncensored=False)['selection'], 'qwen27-standard-q4')

    def test_missing_counterpart_does_not_silently_choose_another_size_or_variant(self):
        self.policy['selection'] = 'qwen1.7-q8'
        model = next(m for m in self.policy['models'] if m['id'] == 'qwen1.7-abliterated-q8')
        (self.root/model['path']).unlink()
        with self.assertRaisesRegex(ValueError, 'not installed'):
            selection.choice_changes(self.root, self.policy, uncensored=True)

    def test_size_preview_is_independent_of_current_pin_but_runtime_still_honors_it(self):
        self.policy['selection'] = 'qwen4-q4'
        preview = effort.capabilities(self.root, hardware=self.hw, policy=self.policy, size_choices=True)
        self.assertEqual([preview['profiles'][level]['selection'] for level in effort.LEVELS],
                         ['qwen1.7-q8', 'qwen4-q4', 'qwen27-standard-q4'])
        pinned = effort.capabilities(self.root, hardware=self.hw, policy=self.policy)
        self.assertTrue(all(plan['selection'] == 'qwen4-q4' for plan in pinned['profiles'].values()))

    def test_saved_explicit_model_resolves_old_effort_conflict_without_rewriting(self):
        self.policy.update(selection='qwen1.7-abliterated-q8', effort={'chat': 'deep', 'tools': 'deep'})
        path = self.root/'Agent/hardware_profiles.json'; runtime.atomic_json(path, self.policy)
        before = path.read_bytes()
        self.assertEqual(effort.load_preferences(self.root), {'chat': 'fast', 'tools': 'deep'})
        self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__': unittest.main()
