import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Windows'))
import model_choices as models


class ModelChoices(unittest.TestCase):
    def setUp(self):
        self.manifest = {'components': [
            {'id': 'core-runtime', 'required': True, 'artifacts': []},
            {'id': 'musicgen-cpu-models', 'required': True, 'artifacts': [
                {'id': 'weights', 'url': 'https://example.com/model.safetensors',
                 'sha256': 'a'*64, 'bytes': 1234, 'members': [{'dest': 'unchanged'}]}]},
            {'id': 'text-small', 'required': True, 'artifacts': []}]}

    def test_policy_preserves_pins_and_makes_models_optional(self):
        before = copy.deepcopy(self.manifest)
        after = models.apply_policy(self.manifest)
        self.assertEqual(self.manifest, before)
        for old, new in zip(before['components'], after['components']):
            self.assertEqual(old['artifacts'], new['artifacts'])
            self.assertEqual(new['required'], new['id'] == 'core-runtime')

    def test_dependencies_and_old_reviews_cannot_authorize_downloads(self):
        manifest = models.apply_policy(self.manifest)
        chosen = manifest['components']
        consent = {c['id']: c['model_choice']['review_digest'] for c in chosen if 'model_choice' in c}
        models.validate_consent(manifest, chosen, list(consent), consent)
        for selected, approval in (([], consent), (list(consent), {}), (list(consent), {k:'0'*64 for k in consent})):
            with self.assertRaises(ValueError):
                models.validate_consent(manifest, chosen, selected, approval)
        chosen[1]['model_choice']['restrictions'] = 'changed'
        with self.assertRaises(ValueError):
            models.validate_consent(manifest, chosen, list(consent), consent)

    def test_custom_model_requires_pin_source_license_and_explicit_choice(self):
        request = dict(url='https://example.com/different.gguf', sha256='b'*64,
                       bytes=123456, label='My model', license_url='https://example.com/LICENSE',
                       variant='standard', accepted=True)
        self.assertEqual(models.validate_custom_request(request), request)
        for change in ({'accepted':False}, {'url':'http://example.com/a.gguf'},
                       {'url':'https://user:password@example.com/a.gguf'},
                       {'url':'https://example.com/code.py'}, {'sha256':'bad'},
                       {'bytes':True}, {'variant':'unknown'}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                models.validate_custom_request({**request, **change})
        with self.assertRaises(ValueError):
            models.validate_custom_request({**request, 'variant':'uncensored'}, academic=True)


if __name__ == '__main__':
    unittest.main()
