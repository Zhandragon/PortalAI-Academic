"""Synthetic checks of complete-pair accounting and explicit score weighting."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from final_case_plan import sample_requests
from final_metrics import summarize


def fixture():
    cases = [{'id': 'a', 'dataset': 'large', 'domain': 'math'},
             {'id': 'b', 'dataset': 'large', 'domain': 'math'},
             {'id': 'c', 'dataset': 'small', 'domain': 'math'},
             {'id': 'd', 'dataset': 'coding', 'domain': 'coding'}]
    plan = {'cases': cases, 'samples_per_case': {'large': 2, 'small': 1, 'coding': 1}}
    plan['requests'] = sample_requests(cases, plan['samples_per_case'])
    results = {arm: {request['id']: {'id': request['id'], 'grading': {'correct': arm == 'candidate'},
                                   'finish': 'stop', 'seconds': 1.0, 'tokens': 3}
                    for request in plan['requests']} for arm in ('baseline', 'candidate')}
    return plan, results


class FinalMetricsTests(unittest.TestCase):
    def test_complete_results_are_accounted_without_promoting(self):
        plan, results = fixture()
        report = summarize(plan, results)
        self.assertEqual(report['unique_questions'], 4)
        self.assertEqual(report['requests_per_arm'], 6)
        self.assertEqual(report['domains']['math']['gain'], 1)
        self.assertEqual(report['missing_required_domains'], ['instruction', 'tools'])
        self.assertIsNone(report['required_domain_mean_gain'])
        self.assertFalse(report['promotion_permitted'])

    def test_repetitions_and_dataset_sizes_do_not_inflate_primary_weight(self):
        plan, results = fixture()
        for key in ('a/sample-1', 'b/sample-0', 'b/sample-1'):
            results['candidate'][key]['grading']['correct'] = False
        # Large dataset: (.5 + 0) / 2 = .25. Small dataset: 1.
        self.assertEqual(summarize(plan, results)['domains']['math']['candidate_accuracy'], .625)

    def test_missing_result_refuses_partial_score(self):
        plan, results = fixture()
        del results['candidate']['a/sample-0']
        with self.assertRaises(ValueError):
            summarize(plan, results)

    def test_extra_result_refuses_score(self):
        plan, results = fixture()
        results['candidate']['unplanned'] = results['candidate']['a/sample-0']
        with self.assertRaises(ValueError):
            summarize(plan, results)

    def test_changed_plan_seed_refuses_score(self):
        plan, results = fixture()
        plan['requests'][0]['seed'] ^= 1
        with self.assertRaises(ValueError):
            summarize(plan, results)

    def test_cutoffs_are_retained_even_if_answer_was_correct(self):
        plan, results = fixture()
        results['candidate']['a/sample-0']['finish'] = 'length'
        report = summarize(plan, results)
        self.assertEqual(report['telemetry']['candidate']['cutoffs'], 1)
        self.assertEqual(report['domains']['math']['candidate_accuracy'], 1)

    def test_bad_telemetry_and_nonboolean_grades_are_rejected(self):
        for field, value in [('seconds', 0), ('seconds', float('nan')), ('tokens', -1), ('tokens', True), ('finish', 'error'), ('grading', {'correct': 1})]:
            plan, results = fixture()
            results['candidate']['a/sample-0'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                summarize(plan, results)

    def test_grader_infrastructure_failure_is_not_a_wrong_answer(self):
        plan, results = fixture()
        results['candidate']['a/sample-0']['grading'] = {'correct': False, 'infrastructure_error': True}
        with self.assertRaises(ValueError):
            summarize(plan, results)

    def test_latency_ratio_includes_all_samples(self):
        plan, results = fixture()
        results['candidate']['a/sample-0']['seconds'] = 7
        self.assertEqual(summarize(plan, results)['native_generation_latency_ratio'], 2)

    def test_required_domain_gain_waits_for_all_domains(self):
        plan, results = fixture()
        for identity, domain in [('e', 'tools'), ('f', 'instruction')]:
            plan['cases'].append({'id': identity, 'dataset': domain, 'domain': domain})
            plan['samples_per_case'][domain] = 1
        plan['requests'] = sample_requests(plan['cases'], plan['samples_per_case'])
        for request in plan['requests'][6:]:
            for arm in results:
                results[arm][request['id']] = {'id': request['id'], 'grading': {'correct': arm == 'candidate'},
                                              'finish': 'stop', 'seconds': 1, 'tokens': 1}
        report = summarize(plan, results)
        self.assertEqual(report['required_domain_mean_gain'], 1)
        self.assertFalse(report['promotion_permitted'])


if __name__ == '__main__':
    unittest.main()
