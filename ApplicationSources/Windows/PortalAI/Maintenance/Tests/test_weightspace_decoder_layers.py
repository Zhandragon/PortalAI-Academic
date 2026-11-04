"""The capture topology must follow the main decoder, excluding NextN blocks."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Tools/WeightSpace'))
import native_forward


class DecoderLayerTests(unittest.TestCase):
    def metadata(self, total, nextn=None):
        values = {'general.architecture': 'qwen35', 'qwen35.block_count': total,
                  'tokenizer.chat_template': 'template', 'qwen35.context_length': 262144}
        if nextn is not None:
            values['qwen35.nextn_predict_layers'] = nextn
        fields = {key: SimpleNamespace(contents=lambda value=value: value)
                  for key, value in values.items()}
        with patch.object(native_forward.gguf, 'GGUFReader', return_value=SimpleNamespace(fields=fields)):
            return native_forward.metadata('unused.gguf')

    def test_nextn_is_excluded_from_main_capture_count(self):
        result = self.metadata(65, 1)
        self.assertEqual(result['layers'], 64)
        self.assertEqual(result['total_layers'], 65)
        self.assertEqual(result['mtp_layers'], 1)
        self.assertEqual(result['template'], 'template')
        self.assertEqual(result['training_context'], 262144)

    def test_absent_nextn_preserves_ordinary_decoder(self):
        result = self.metadata(28)
        self.assertEqual((result['layers'], result['total_layers'], result['mtp_layers']), (28, 28, 0))

    def test_explicit_zero_and_multiple_nextn_blocks(self):
        self.assertEqual(self.metadata(36, 0)['layers'], 36)
        self.assertEqual(self.metadata(66, 2)['layers'], 64)

    def test_invalid_counts_fail_instead_of_silently_skipping_layers(self):
        for total, nextn in [(0, 0), (-1, 0), (65, -1), (65, 65), (65, 66),
                             (65.5, 1), (65, 1.5), (True, 0), (65, True), ('65', 1)]:
            with self.subTest(total=total, nextn=nextn), self.assertRaises(ValueError):
                self.metadata(total, nextn)


if __name__ == '__main__':
    unittest.main()
