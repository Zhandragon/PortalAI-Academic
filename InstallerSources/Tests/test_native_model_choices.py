import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
APP=REPO/'ApplicationSources/Linux/PortalAI'
sys.path[:0]=[str(APP/'Tools'),str(APP/'Agent'),str(REPO/'InstallerSources/Windows')]
import choose_optional_models as native
import import_foundation_assets as foundation
import model_choices

class NativeModelChoices(unittest.TestCase):
    def test_harness_only_downloads_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(foundation,'install') as download:
            self.assertEqual(native.install_choices({'selected':[],'accepted':False},Path(tmp)),{'suggested':[],'custom':False})
            download.assert_not_called()

    def test_selection_requires_review_and_keeps_notice(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(foundation,'install') as download:
            root=Path(tmp)
            with self.assertRaises(ValueError):native.install_choices({'selected':['qwen1.7-q8'],'accepted':False},root)
            download.assert_not_called()
            native.install_choices({'selected':['qwen1.7-q8'],'accepted':True},root)
            self.assertEqual([call.args[0]['id'] for call in download.call_args_list],['qwen1.7-q8','qwen-license'])

    def test_academic_rejects_full_suggestion_without_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(foundation,'install') as download:
            root=Path(tmp);(root/'Agent').mkdir();(root/'Agent/academic_policy.py').touch()
            self.assertEqual({r['id'] for r in native.catalog(root)},{'qwen1.7-q8','qwen4-q4'})
            with self.assertRaises(ValueError):native.install_choices({'selected':['qwen1.7-abliterated-q8'],'accepted':True},root)
            download.assert_not_called()

    def test_academic_custom_exclusion_is_not_just_a_label(self):
        model=dict(url='https://example.com/plain-name.gguf',sha256='a'*64,bytes=2000,label='Plain name',license_url='https://example.com/LICENSE',variant='standard',accepted=True)
        manifest={'upgrade':{'edition':'Academic'},'components':[],'academic_custom_model_exclusions':['a'*64]}
        with self.assertRaises(ValueError):model_choices.with_custom_model(manifest,model)
        with self.assertRaises(ValueError):model_choices.with_custom_model({**manifest,'academic_custom_model_exclusions':[]},{**model,'variant':'uncensored'})
        allowed,key=model_choices.with_custom_model({**manifest,'academic_custom_model_exclusions':[]},model)
        self.assertEqual(key,'custom-'+'a'*64)
        self.assertEqual(allowed['components'][0]['artifacts'][0]['sha256'],'a'*64)

if __name__=='__main__':unittest.main()
