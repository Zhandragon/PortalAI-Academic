"""Synthetic accounting checks; never open real held-out responses."""
import copy
import sys
import unittest
from pathlib import Path
LAB = Path(__file__).resolve().parent
sys.path[:0] = [str(LAB), str(LAB.parents[2] / 'Tools/WeightSpace')]
from audit_confirmation import recompute
from experiment import paired_summary


def fixture():
    ids = [str(i) for i in range(1152)]
    results = {arm: {key: {'id': key, 'grading': {'correct': int(key) % 3 != 0 or (arm == 'candidate' and int(key) % 11 == 0)},
                         'finish': 'stop', 'seconds': 1.0} for key in ids} for arm in ('baseline', 'candidate')}
    scores = {arm: {key: row['grading']['correct'] for key, row in values.items()} for arm, values in results.items()}
    paired = paired_summary(scores['baseline'], scores['candidate'])
    summary = {'paired': paired, 'latency_ratio': 1.0, 'cutoffs': {'baseline': 0, 'candidate': 0},
               'eligible_for_separate_final_benchmarks': paired['lower_95'] > 0}
    return results, ids, summary


class AuditTests(unittest.TestCase):
    def test_complete_evidence_recomputes(self):
        results, ids, summary = fixture()
        self.assertEqual(recompute(results, ids, summary)['recomputed_paired'], summary['paired'])

    def test_insertion_order_rounding_is_tolerated(self):
        results, ids, summary = fixture()
        results = {arm: dict(reversed(list(values.items()))) for arm, values in results.items()}
        self.assertEqual(recompute(results, ids, summary)['recomputed_paired']['rescues'], summary['paired']['rescues'])

    def test_missing_extra_and_duplicate_cases_rejected(self):
        for mode in ('missing', 'extra', 'duplicate'):
            results, ids, summary = fixture()
            if mode == 'missing':
                results['candidate'].pop(ids[-1])
            elif mode == 'extra':
                results['candidate']['extra'] = copy.deepcopy(results['candidate'][ids[-1]])
            else:
                ids[-1] = ids[0]
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                recompute(results, ids, summary)

    def test_changed_summary_score_rejected(self):
        results, ids, summary = fixture()
        summary['paired']['candidate_correct'] += 1
        with self.assertRaises(ValueError):
            recompute(results, ids, summary)

    def test_changed_latency_and_cutoffs_rejected(self):
        for field in ('latency_ratio', 'cutoffs'):
            results, ids, summary = fixture()
            summary[field] = 1.01 if field == 'latency_ratio' else {'baseline': 1, 'candidate': 0}
            with self.subTest(field=field), self.assertRaises(ValueError):
                recompute(results, ids, summary)

    def test_gate_cannot_be_flipped(self):
        results, ids, summary = fixture()
        summary['eligible_for_separate_final_benchmarks'] = not summary['eligible_for_separate_final_benchmarks']
        with self.assertRaises(ValueError):
            recompute(results, ids, summary)


if __name__ == '__main__':
    unittest.main()
