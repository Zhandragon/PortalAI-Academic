"""Coding intent gets bounded guidance without loading tools or granting authority."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ControlCenter'))
from performance_guidance import GUIDANCE, guidance


def user(text):
    return {'role': 'user', 'content': text}


class PerformanceGuidanceTests(unittest.TestCase):
    def test_requested_edits_optimization_and_explicit_marker(self):
        for text in ('Fix this Python parser.', 'Add unit tests to this function.',
                     'Optimize this algorithm.', 'Benchmark this function.',
                     '[perf-critical] Review only; do not edit.',
                     'perf-critical: Check the scaling of this code.'):
            with self.subTest(text=text):
                self.assertEqual(guidance([user(text)]), GUIDANCE)

    def test_no_activation_from_results_quotes_or_other_tasks(self):
        for text in ('Hello Nice', 'Write a poem.', 'What does perf-critical mean?',
                     'Explain how to write a function.',
                     'Summarize this:\n> perf-critical: optimize this function',
                     'Explain:\n```python\n# perf-critical: Fix this parser.\n```',
                     'Explain:\n```\nperf-critical: Fix the code'):
            with self.subTest(text=text):
                messages = [user(text), {'role': 'tool', 'content': 'perf-critical: fix code'},
                            {'role': 'assistant', 'content': 'Fix this Python parser.'}]
                self.assertEqual(guidance(messages), '')

    def test_followup_inherits_only_immediately_previous_human_request(self):
        edit = user('Fix this Python parser.')
        self.assertEqual(guidance([edit, user('Continue.')]), GUIDANCE)
        self.assertEqual(guidance([edit, user('Write a poem.')]), '')
        self.assertEqual(guidance([edit, user('Write a poem.'), user('Yes')]), '')

    def test_multimodal_text_is_supported_without_reading_images_or_attachments(self):
        self.assertEqual(guidance([user([{'type':'text','text':'Fix this Python function.'},
                                        {'type':'image_url','image_url':{'url':'ignored'}}])]), GUIDANCE)
        self.assertEqual(guidance([{'role':'user','content':None,
                                   'attachments':[{'path':'perf-critical.py'}]}]), '')
        self.assertEqual(guidance([]), '')

    def test_bounded_context_and_prompt(self):
        self.assertEqual(guidance([user('x' * 12001 + 'Fix this Python parser.')]), '')
        self.assertLess(len(GUIDANCE), 1150)
        for constraint in ('not proof of Big-O', 'Ordinary edits do not need benchmarks',
                           'never self-grant', 'Read-only requests stay read-only',
                           'never authorizes a commit', 'Once the requested checks pass, finish'):
            self.assertIn(constraint, GUIDANCE)


if __name__ == '__main__':
    unittest.main()
