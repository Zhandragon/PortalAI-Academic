"""CPU-only synthetic boundary checks; no real confirmation scores are altered."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from campaign_verdict import campaign_verdict, model_verdict


def fixture(lower=-0.01):
    paired = {'n': 1152, 'lower_95': lower, 'baseline_correct': 900, 'candidate_correct': 901}
    return {'status': 'discovery screen complete',
            'discovery': {'production_model_changed': False, 'eligible_for_independent_confirmation': True,
                          'model_receipts': {'candidate': {'candidate_sha256': 'a' * 64}}},
            'independent_confirmation': {'paired': paired, 'production_model_changed': False,
                'base_unchanged': True, 'frozen_candidate_sha256': 'a' * 64,
                'eligible_for_separate_final_benchmarks': lower > 0},
            'confirmation_audit': {'passed': True, 'completed_cases_per_arm': {'baseline': 1152, 'candidate': 1152},
                                   'recomputed_paired': copy.deepcopy(paired), 'frozen_candidate_sha256': 'a' * 64}}


class VerdictTests(unittest.TestCase):
    def test_negative_complete_preserves_original(self):
        value = model_verdict(fixture())
        self.assertTrue(value['complete'])
        self.assertFalse(value['promotion_allowed'])

    def test_positive_cannot_skip_final_benchmarks(self):
        value = model_verdict(fixture(0.01))
        self.assertFalse(value['complete'])
        self.assertFalse(value['promotion_allowed'])
        self.assertEqual(value['stage'], 'final_benchmarks_required')

    def test_missing_audit_is_pending(self):
        row = fixture()
        del row['confirmation_audit']
        self.assertFalse(model_verdict(row)['complete'])

    def test_partial_case_count_cannot_finalize(self):
        row = fixture()
        row['confirmation_audit']['completed_cases_per_arm']['candidate'] = 1151
        with self.assertRaises(ValueError):
            model_verdict(row)

    def test_wrong_candidate_is_rejected(self):
        row = fixture()
        row['discovery']['model_receipts']['candidate']['candidate_sha256'] = 'b' * 64
        with self.assertRaises(ValueError):
            model_verdict(row)

    def test_summary_mismatch_is_rejected(self):
        row = fixture()
        row['confirmation_audit']['recomputed_paired']['candidate_correct'] += 1
        with self.assertRaises(ValueError):
            model_verdict(row)

    def test_zero_bound_is_not_success(self):
        self.assertEqual(model_verdict(fixture(0))['stage'], 'confirmation_not_established')

    def test_nonfinite_bound_is_rejected(self):
        for lower in (float('nan'), float('inf'), float('-inf')):
            with self.subTest(lower=lower), self.assertRaises(ValueError):
                model_verdict(fixture(lower))

    def test_all_six_tracks_are_required(self):
        with self.assertRaises(ValueError):
            campaign_verdict({'27-abliterated': fixture()})

    def test_one_open_track_keeps_campaign_open(self):
        models = {size + '-' + variant: {'status': 'discovery complete without supported contrast'}
                  for size in ('1.7', '4', '27') for variant in ('standard', 'abliterated')}
        models['27-abliterated'] = fixture(0.01)
        self.assertFalse(campaign_verdict(models)['campaign_complete'])
        models['27-abliterated'] = fixture(-0.01)
        self.assertTrue(campaign_verdict(models)['campaign_complete'])


if __name__ == '__main__':
    unittest.main()
