"""Nice receives current operating guidance without any account/model access."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
ACADEMIC = (ROOT / 'Agent/academic_policy.py').is_file()
sys.path[:0] = [str(ROOT / "Agent"), str(ROOT / "ControlCenter")]
import native_chat as chat
from assistant_guidance import host_guidance


POLICY_OVERHEAD = 0
if ACADEMIC:
    from academic_policy import instruction_suffix
    POLICY_OVERHEAD = len(instruction_suffix(ROOT))


class NicePromptIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.policy = {'variant_preference':'uncensored','media':{'media_variant':'auto'}}
        if ACADEMIC:self.policy['variant_preference']='standard'
        policy = patch('runtime_policy.load_effective_policy', return_value=self.policy)
        policy.start(); self.addCleanup(policy.stop)
        self.temporary = tempfile.TemporaryDirectory(prefix="portalai-nice-prompt-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.master = self.root / "PortableAI_Master_Instructions_v45.txt"
        self.master.write_text("SYNTHETIC MANUAL REVISION ONE", encoding="utf-8")
        # Prompt fixtures supply capacity directly: no model/HTTP probing is
        # allowed even if the implementation starts consulting extra metadata.
        self.model_probe = patch.object(chat, "model_props", side_effect=AssertionError("Unexpected model probe"))
        self.model_probe.start()
        self.addCleanup(self.model_probe.stop)

    def panel(self, *, capacity=8192, enabled=True, custom="Synthetic user preference", effort=None, full=False):
        panel = SimpleNamespace(
            root=self.root,
            settings={"use_master_instructions": enabled,"include_full_manual":full},
            store=SimpleNamespace(custom_instructions=Mock(return_value=custom)),
            _runtime_context_limit=Mock(return_value=capacity),
        )
        if effort is not None:
            panel.effort = SimpleNamespace(active_tools_profile=effort)
        return panel

    def test_shared_current_guidance_reaches_compact_and_full_prompts(self):
        for capacity in (8192, 16384, 32768):
            with self.subTest(capacity=capacity):
                panel = self.panel(capacity=capacity)
                prompt = chat.NativeChat.system_prompt(panel)
                self.assertIn(host_guidance(self.root).strip(), prompt)
                self.assertEqual(prompt.count("===== CURRENT NICE HARNESS:"), 1)
                self.assertIn("Your conversational name is Nice", prompt)
                self.assertIn("structured function tools", prompt)
                self.assertIn("Synthetic user preference", prompt)
                self.assertIn("Optional manual:", prompt)
                self.assertNotIn("SYNTHETIC MANUAL REVISION ONE", prompt)

    def test_full_prompt_rereads_master_and_custom_instructions(self):
        panel = self.panel(capacity=32768,full=True)
        first = chat.NativeChat.system_prompt(panel)
        self.master.write_text("SYNTHETIC MANUAL REVISION TWO", encoding="utf-8")
        panel.store.custom_instructions.return_value = "Updated synthetic preference"
        second = chat.NativeChat.system_prompt(panel)
        self.assertIn("SYNTHETIC MANUAL REVISION ONE", first)
        self.assertNotIn("SYNTHETIC MANUAL REVISION ONE", second)
        self.assertIn("SYNTHETIC MANUAL REVISION TWO", second)
        self.assertIn("Updated synthetic preference", second)
        self.assertNotIn("Synthetic user preference", second)
        self.assertEqual(panel.store.custom_instructions.call_count, 2)

    def test_prompt_rereads_independent_media_setting_without_probing(self):
        panel=self.panel(enabled=False)
        for mode in ('auto','standard','uncensored'):
            self.policy['media']['media_variant']=mode
            prompt=chat.NativeChat.system_prompt(panel)
            self.assertIn('Saved preferences: chat='+('standard' if ACADEMIC else 'uncensored')+'; media='+('standard' if ACADEMIC else mode), prompt)
            if ACADEMIC:
                self.assertIn('PortalAI Academic uses standard/censored chat and media models only',prompt)
                self.assertIn('never use a tool to evade a refusal or replay a completed tool',prompt)
            else:
                self.assertIn('Media auto: choose a supported variant',prompt)
                self.assertIn('Media standard/uncensored: omit variant unless the user overrides',prompt)
                self.assertIn('Never switch on refusal or replay a tool',prompt)
        from profile_paths import ProfileLocked
        with patch('runtime_policy.load_effective_policy',side_effect=ProfileLocked('revoked')):
            with self.assertRaises(ProfileLocked):chat.NativeChat.system_prompt(panel)

    def test_master_selection_remains_numeric_and_updates_between_requests(self):
        (self.root / "PortableAI_Master_Instructions_v9.txt").write_text("OLDER NUMERIC MANUAL", encoding="utf-8")
        panel = self.panel(capacity=32768,full=True)
        self.assertIn("SYNTHETIC MANUAL REVISION ONE", chat.NativeChat.system_prompt(panel))
        (self.root / "PortableAI_Master_Instructions_v46.txt").write_text("NEWER NUMERIC MANUAL", encoding="utf-8")
        prompt = chat.NativeChat.system_prompt(panel)
        self.assertIn("NEWER NUMERIC MANUAL", prompt)
        self.assertNotIn("SYNTHETIC MANUAL REVISION ONE", prompt)
        self.assertNotIn("OLDER NUMERIC MANUAL", prompt)

    def test_all_media_defaults_refresh_in_the_same_compact_or_full_chat(self):
        from model_preferences import MEDIA_CHOICES
        for capacity in (8192,32768):
            panel = self.panel(capacity=capacity)
            for key, choices in MEDIA_CHOICES.items():
                for choice in choices:
                    self.policy['media'][key] = choice
                    prompt = chat.NativeChat.system_prompt(panel)
                    expected='standard' if ACADEMIC and key=='media_variant' else choice
                    self.assertIn(key+'='+expected, prompt)
                    self.assertIn('Repeats use current defaults',prompt)
                    self.assertIn('Named Images stays pinned',prompt)

    def test_disabling_optional_master_keeps_host_and_user_guidance(self):
        panel = self.panel(enabled=False)
        with patch.object(chat, "latest_master_instructions", side_effect=AssertionError("Manual disabled")):
            prompt = chat.NativeChat.system_prompt(panel)
        panel._runtime_context_limit.assert_not_called()
        self.assertNotIn("SYNTHETIC MANUAL REVISION ONE", prompt)
        self.assertIn("Synthetic user preference", prompt)
        self.assertIn(host_guidance(self.root).strip(), prompt)
        self.assertIn("account denials", prompt)

    def test_missing_optional_master_keeps_current_guidance(self):
        self.master.unlink()
        panel = self.panel()
        prompt = chat.NativeChat.system_prompt(panel)
        self.assertIn(host_guidance(self.root).strip(), prompt)
        self.assertIn("Synthetic user preference", prompt)
        panel._runtime_context_limit.assert_not_called()

    def test_compact_prompt_stays_bounded_with_each_tools_effort(self):
        for effort in ("fast", "balanced", "deep"):
            with self.subTest(effort=effort):
                panel = self.panel(effort=effort, custom="Preserve the user's explicit requested output dimensions.")
                prompt = chat.NativeChat.system_prompt(panel)
                self.assertLess(len(prompt), 5000 + POLICY_OVERHEAD)
                self.assertIn("Media/science effort: " + effort, prompt)
                self.assertIn("Explicit user parameters always prevail", prompt)
                self.assertIn("Search limits do not block other requested work", prompt)


if __name__ == "__main__":
    unittest.main()
