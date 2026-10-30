from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "ControlCenter"))
import native_chat


class SmallModelChatTests(unittest.TestCase):
    def setUp(self):
        policy = patch('runtime_policy.load_effective_policy', return_value={'variant_preference':'uncensored','media':{'media_variant':'auto'}})
        policy.start(); self.addCleanup(policy.stop)

    def test_compact_prompt_preserves_custom_instructions(self):
        panel = SimpleNamespace(root=ROOT, settings={"use_master_instructions": True},
                                store=SimpleNamespace(custom_instructions=lambda: "User's specific requirement"),
                                _runtime_context_limit=lambda: 8192)
        prompt = native_chat.NativeChat.system_prompt(panel)
        self.assertIn("User's specific requirement", prompt)
        self.assertIn("Optional manual:", prompt)
        self.assertIn("Use known tool syntax directly.", prompt)
        self.assertLess(len(prompt), 5000)

    def test_large_model_uses_compact_guide_unless_full_manual_requested(self):
        panel = SimpleNamespace(root=ROOT, settings={"use_master_instructions": True},
                                store=SimpleNamespace(custom_instructions=lambda: ""),
                                _runtime_context_limit=lambda: 32768)
        self.assertLess(len(native_chat.NativeChat.system_prompt(panel)), 5000)
        panel.settings["include_full_manual"]=True
        self.assertGreater(len(native_chat.NativeChat.system_prompt(panel)), 30000)


if __name__ == "__main__":
    unittest.main()
