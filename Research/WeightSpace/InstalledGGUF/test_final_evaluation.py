"""CPU-only checks against upstream IFEval using synthetic prompts/answers."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from final_evaluation import grade


class FinalEvaluationTests(unittest.TestCase):
    def test_choice_uses_only_final_last_box(self):
        case = {'kind': 'choice', 'answer': 'B'}
        self.assertTrue(grade(case, '<think>Maybe \\boxed{A}</think>\\boxed{B}')['correct'])
        self.assertFalse(grade(case, 'The answer is B.')['correct'])
        self.assertFalse(grade(case, '\\boxed{B}, then \\boxed{C}')['correct'])

    def test_ifeval_keyword_and_punctuation(self):
        case = {'kind': 'ifeval', 'key': 1, 'prompt': 'Use turquoise and no comma.',
                'instruction_id_list': ['keywords:existence', 'punctuation:no_comma'],
                'kwargs': [{'keywords': ['turquoise']}, {}]}
        good = grade(case, '<think>Planning, briefly.</think>A turquoise portal.')
        self.assertTrue(good['correct'])
        self.assertTrue(good['loose_prompt_correct'])
        self.assertFalse(good['host_nltk_data_used'])
        self.assertFalse(grade(case, 'A turquoise, portal.')['correct'])

    def test_ifeval_sentence_tokenizer(self):
        case = {'kind': 'ifeval', 'key': 2, 'prompt': 'Write fewer than three sentences.',
                'instruction_id_list': ['length_constraints:number_sentences'],
                'kwargs': [{'num_sentences': 3, 'relation': 'less than'}]}
        self.assertTrue(grade(case, 'One sentence. Another sentence!')['correct'])
        self.assertFalse(grade(case, 'One sentence. Another sentence! A third sentence.')['correct'])

    def test_empty_ifeval_response_is_wrong(self):
        case = {'kind': 'ifeval', 'key': 3, 'prompt': 'Do not use a comma.',
                'instruction_id_list': ['punctuation:no_comma'], 'kwargs': [{}]}
        self.assertFalse(grade(case, '')['correct'])


if __name__ == '__main__':
    unittest.main()
