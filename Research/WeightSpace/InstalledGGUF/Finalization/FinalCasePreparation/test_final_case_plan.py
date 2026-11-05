"""Synthetic CPU cases; held-out model outputs are never used by these tests."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from final_case_plan import adapt_row, normalized, select_mmlu, screen_cases, sample_requests, stable_seed


class FinalCasePlanTests(unittest.TestCase):
    def test_gsm_answer_uses_delimited_value_only(self):
        row = {'question': 'How many?', 'answer': 'Work: 1 + 2 = 3\n#### 3'}
        case = adapt_row('GSM8K', row, 4)
        self.assertEqual(case['answer'], '3')
        self.assertNotIn('Work:', case['prompt'])
        with self.assertRaises(ValueError):
            adapt_row('GSM8K', dict(row, answer='3'), 4)

    def test_math_multicomponent_answer_is_preserved(self):
        case = adapt_row('OlympiadBench', {'id': 7, 'question': 'Compute both.', 'final_answer': ['1, 2']}, 0)
        self.assertEqual(case['answer'], '1, 2')
        with self.assertRaises(ValueError):
            adapt_row('OlympiadBench', {'id': 7, 'question': 'Compute both.', 'final_answer': ['1', '2']}, 0)

    def test_choice_does_not_include_reference_reasoning(self):
        row = {'question_id': 8, 'question': 'Which?', 'options': ['First', 'Second'],
               'answer': 'B', 'answer_index': 1, 'cot_content': 'SECRET REFERENCE'}
        case = adapt_row('MMLU-Pro', row, 0)
        self.assertIn('A. First\nB. Second', case['prompt'])
        self.assertNotIn('SECRET', case['prompt'])
        self.assertEqual(case['domain'], 'reasoning')
        with self.assertRaises(ValueError):
            adapt_row('MMLU-Pro', dict(row, answer_index=0), 0)

    def test_ifeval_prompt_is_byte_for_byte_preserved(self):
        row = {'key': 8, 'prompt': ' Keep this spacing.\n', 'instruction_id_list': ['x'], 'kwargs': [{}]}
        self.assertEqual(adapt_row('IFEval', row, 0)['prompt'], row['prompt'])
        with self.assertRaises(ValueError):
            adapt_row('IFEval', dict(row, kwargs=[]), 0)

    def test_hash_selection_is_independent_of_input_order(self):
        rows = [{'question_id': i} for i in range(30)]
        self.assertEqual(select_mmlu(rows, 10), select_mmlu(list(reversed(rows)), 10))
        self.assertEqual(len(select_mmlu(rows, 10)), 10)
        with self.assertRaises(ValueError):
            select_mmlu(rows + [rows[0]], 10)

    def test_overlap_is_checked_before_instruction_suffixes(self):
        cases = [adapt_row('GSM8K', {'question': text, 'answer': '#### 1'}, i)
                 for i, text in enumerate([' already   used ', 'NEW', 'new'])]
        selected, excluded = screen_cases(cases, [('old', 'ALREADY USED')])
        self.assertEqual([row['id'] for row in selected], ['final-GSM8K:1'])
        self.assertEqual([row['matched_id'] for row in excluded], ['old', 'final-GSM8K:1'])

    def test_duplicate_ids_fail_instead_of_being_dropped(self):
        case = adapt_row('GSM8K', {'question': 'x', 'answer': '#### 1'}, 0)
        with self.assertRaises(ValueError):
            screen_cases([case, copy.deepcopy(case)], [])

    def test_paired_requests_use_fixed_distinct_sample_seeds(self):
        cases = [{'id': 'final-test:1', 'dataset': 'test'}]
        requests = sample_requests(cases, {'test': 3})
        self.assertEqual(requests, sample_requests(cases, {'test': 3}))
        self.assertEqual(len({row['seed'] for row in requests}), 3)
        self.assertEqual(requests[1]['seed'], stable_seed(cases[0]['id'], 1))
        with self.assertRaises(ValueError):
            sample_requests(cases, {'test': True})

    def test_normalization_does_not_claim_semantic_matching(self):
        self.assertEqual(normalized(' A\nB '), 'a b')
        self.assertNotEqual(normalized('one plus two'), normalized('1+2'))


if __name__ == '__main__':
    unittest.main()
