"""Chat model selection coverage; saved-conversation selection has its own suite."""
from pathlib import Path
import sys,tempfile,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
from chat_selection import choice_changes,tier_for_model


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.models=[{'id':'qwen1.7-q8','path':'fast.gguf','variant':'standard'},
                     {'id':'qwen4-q4','path':'balanced.gguf','variant':'standard'},
                     {'id':'qwen27-standard-q4','path':'deep.gguf','projector':'vision.gguf','variant':'standard'}]
        for name in ('fast.gguf','balanced.gguf','deep.gguf','vision.gguf'):(self.root/name).write_bytes(b'synthetic model marker')
        self.policy={'selection':'qwen4-q4','variant_preference':'standard','models':self.models}
    def test_explicit_size_selects_matching_installed_model(self):
        self.assertEqual(choice_changes(self.root,self.policy,level='fast')['selection'],'qwen1.7-q8')
        self.assertEqual(choice_changes(self.root,self.policy,level='balanced')['selection'],'qwen4-q4')
    def test_missing_projector_refuses_vision_selection(self):
        (self.root/'vision.gguf').unlink()
        with self.assertRaises(ValueError):choice_changes(self.root,self.policy,level='deep')
    def test_missing_weight_does_not_silently_change_size(self):
        (self.root/'fast.gguf').unlink()
        with self.assertRaises(ValueError):choice_changes(self.root,self.policy,level='fast')
    def test_unknown_selection_and_tier_refused(self):
        with self.assertRaises(ValueError):choice_changes(self.root,self.policy,selection='unconfigured')
        with self.assertRaises(ValueError):choice_changes(self.root,self.policy,level='unknown')
    def test_auto_selection_preserves_explicit_standard_preference(self):
        self.assertEqual(choice_changes(self.root,self.policy,selection='auto'),{'selection':'auto','variant_preference':'standard'})
    def test_known_tiers_are_stable(self):
        self.assertEqual(tier_for_model('qwen4-q4'),'balanced');self.assertEqual(tier_for_model('qwen27-standard-q4'),'deep');self.assertIsNone(tier_for_model('missing'))


if __name__=='__main__':unittest.main()
