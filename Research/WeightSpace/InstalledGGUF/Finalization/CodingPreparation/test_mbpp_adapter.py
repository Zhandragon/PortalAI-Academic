"""CPU-only adapter boundaries; no model inference or test-string execution."""
import ast
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from mbpp_adapter import adapt, UnsupportedCase, json_value


def row(code='def double(x):\n    return x * 2', tests=None):
    return {'task_id': 1, 'prompt': 'Double a number.', 'code': code, 'test_imports': [],
            'test_list': tests or ['assert double(2) == 4', 'assert double(-3) == -6']}


class AdapterTests(unittest.TestCase):
    def test_simple_reference_and_all_checks_preserved(self):
        value = adapt(row())
        self.assertEqual(value['case']['checks'], [[[2], 4], [[-3], -6]])
        self.assertEqual(value['original_test_count'], 2)
        self.assertIn('def solve(x):', value['case']['prompt'])
        self.assertNotIn('return x * 2', value['case']['prompt'])
        self.assertIn('def solve(x):', value['reference_source'])

    def test_recursive_function_reference_is_renamed(self):
        value = adapt(row('def double(x):\n    return 0 if x == 0 else 2 + double(x - 1)', ['assert double(2) == 4']))
        names = [node.id for node in ast.walk(ast.parse(value['reference_source'])) if isinstance(node, ast.Name)]
        self.assertIn('solve', names)
        self.assertNotIn('double', names)

    def test_json_list_dictionary_and_none_are_preserved(self):
        value = adapt(row('def double(x):\n    return x', ['assert double({"a": [None, True, -1.5]}) == {"a": [None, True, -1.5]}']))
        self.assertEqual(value['case']['checks'][0][0], [{'a': [None, True, -1.5]}])

    def test_unsupported_literals_do_not_silently_change_types(self):
        for value in [(1, 2), {1, 2}, {1: 'a'}, b'a', complex(1, 2), float('inf')]:
            with self.subTest(value=repr(value)), self.assertRaises(UnsupportedCase):
                json_value(value)

    def test_nonliteral_argument_is_never_executed(self):
        for text in ['assert double(open("should-not-exist")) == 4', 'assert double([1] * 2) == [1, 1]']:
            with self.subTest(text=text), self.assertRaises(UnsupportedCase):
                adapt(row(tests=[text]))

    def test_import_and_multistatement_tests_rejected(self):
        for text in ['import os\nassert double(2) == 4', 'assert double(2) == 4\nprint(1)']:
            with self.subTest(text=text), self.assertRaises(UnsupportedCase):
                adapt(row(tests=[text]))

    def test_non_equality_keyword_and_multiple_entries_rejected(self):
        for tests in [['assert double(2) > 3'], ['assert double(x=2) == 4'],
                      ['assert double(2) == 4', 'assert other(2) == 4']]:
            with self.subTest(tests=tests), self.assertRaises(UnsupportedCase):
                adapt(row(tests=tests))

    def test_solve_collision_rejected(self):
        with self.assertRaises(UnsupportedCase):
            adapt(row('def solve(x):\n    return x\ndef double(x):\n    return solve(x) * 2'))

    def test_reference_imports_rejected(self):
        with self.assertRaises(UnsupportedCase):
            adapt(row('import math\ndef double(x):\n    return x * 2'))

    def test_owned_reference_check_rejects_mutation(self):
        from final_evaluation import grade
        good = adapt(row())
        self.assertTrue(grade(good['case'], good['reference_source'])['correct'])
        bad = adapt(row('def double(x):\n    x.append(2)\n    return x', ['assert double([1]) == [1, 2]']))
        self.assertFalse(grade(bad['case'], bad['reference_source'])['correct'])


if __name__ == '__main__':
    unittest.main()
