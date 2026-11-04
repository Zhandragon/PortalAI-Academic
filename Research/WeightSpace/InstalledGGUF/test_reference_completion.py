"""CPU-only reference-format regression; no model or native backend is loaded."""
import ast
from pathlib import Path
import unittest

source=Path(__file__).with_name('causal_screen.py')
tree=ast.parse(source.read_text(encoding='utf-8-sig'))
node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='reference_completion')
scope={}
exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),scope)
reference_completion=scope['reference_completion']

class ReferenceCompletionTests(unittest.TestCase):
    def test_qwen3_is_byte_identical_to_previous_format(self):
        prompt='<|im_start|>user\nQuestion<|im_end|>\n<|im_start|>assistant\n'
        for solution,answer in [('Work it out.',42),('First line.\nSecond line.','3/7'),(r'Use \\sqrt{9}.','3')]:
            with self.subTest(answer=answer):
                old='<think>\n'+solution+'\n</think>\n\\boxed{'+str(answer)+'}<|im_end|>'
                self.assertEqual(reference_completion(prompt,solution,answer),old)

    def test_qwen35_does_not_duplicate_opening(self):
        prompt='<|im_start|>assistant\n<think>\n'
        actual=reference_completion(prompt,'Work it out.',42)
        self.assertEqual(actual,'Work it out.\n</think>\n\\boxed{42}<|im_end|>')
        self.assertEqual((prompt+actual).count('<think>'),1)
        self.assertEqual((prompt+actual).count('</think>'),1)

    def test_template_trailing_whitespace_is_preserved(self):
        for ending in ('<think>','<think>\n','<think>\r\n','<think>\n\n'):
            with self.subTest(ending=ending):
                prompt='<|im_start|>assistant\n'+ending
                actual=reference_completion(prompt,'Solution',7)
                self.assertTrue(actual.startswith('Solution\n</think>'))
                self.assertTrue((prompt+actual).startswith(prompt))

    def test_marker_in_user_text_does_not_suppress_assistant_opening(self):
        prompt='<|im_start|>user\nExplain <think>.<|im_end|>\n<|im_start|>assistant\n'
        self.assertTrue(reference_completion(prompt,'Solution',7).startswith('<think>\n'))

    def test_solution_and_answer_are_not_rewritten(self):
        solution='Use {x} and y.\nThen simplify.'
        answer=r'\frac{2}{3}'
        actual=reference_completion('<|im_start|>assistant\n<think>\n',solution,answer)
        self.assertEqual(actual,solution+'\n</think>\n\\boxed{'+answer+'}<|im_end|>')

if __name__=='__main__':unittest.main()
