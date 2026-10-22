"""The compact native guide must advertise executable, bounded tool routes."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
sys.path.insert(0, str(ROOT / "ControlCenter"))

from assistant_guidance import REVISION, host_guidance, tool_launcher
from account_tool_policy import registered_media_argv


class AssistantGuidanceTests(unittest.TestCase):
    def test_platform_routes_are_accepted_without_host_python(self):
        # The exact documented prefixes must dispatch as direct registered argv,
        # including when the actual process cwd is an account workspace.
        boot = ROOT / "Runtime/BootstrapPython/python.exe"
        for platform_name in ("win32", "linux"):
            with self.subTest(platform_name=platform_name):
                prefix = tool_launcher(platform_name)
                for script, operation in (("ai_tools.py", "voice-say"),
                                          ("web_tools.py", "image-search")):
                    command = f'{prefix} Agent/{script} {operation} "a specific public subject"'
                    argv = registered_media_argv(command, ROOT, boot)
                    self.assertEqual(argv, [str(boot), str(ROOT / "Agent" / script),
                                            operation, "a specific public subject"])

    def test_guide_is_bounded_and_independent_of_private_root_state(self):
        for platform_name in ("win32", "linux"):
            first = host_guidance(ROOT, platform_name=platform_name)
            missing = host_guidance(Path("not-an-existing-profile-root"), platform_name=platform_name)
            self.assertEqual(first, missing)
            self.assertLess(len(first), 4000)
            self.assertIn(REVISION, first)
            self.assertIn("Your conversational name is Nice", first)
            self.assertIn("structured function tools", first)
            self.assertNotIn(str(ROOT), first)

    def test_linux_guide_never_directs_a_windows_launcher(self):
        guide = host_guidance(ROOT, platform_name="linux")
        self.assertIn("python Agent/ai_tools.py", guide)
        self.assertIn("python Agent/web_tools.py search", guide)
        self.assertNotIn("portable_python.cmd", guide)
        self.assertNotIn("python.exe", guide)

    def test_runtime_limits_survive_compact_guidance(self):
        guide = host_guidance(ROOT)
        for required in ("evidence-guided plan", "elapsed time and progress", "image_url and page_url",
                         "Search limits do not block other requested work",
                         "not limited to Wikipedia", "_portableai.terminal_result:true",
                         "English-only CPU Piper", "voice-clone/voice-design",
                         "signed-in account", "incremental snapshots", "account denials",
                         "Only explicitly armed missions run", "Never escalate mode",
                         "Stop/Exit disarms", "not an OS sandbox", "reply cap are separate"):
            with self.subTest(required=required):
                self.assertIn(required, guide)

    def test_image_fetch_edit_clarification_and_timeout_recovery_are_explicit(self):
        guide = host_guidance(ROOT)
        for required in ('fetch URL returns readable text AND images/image_urls',
                         'Use these with download-image', 'Ask for the desired edit if unspecified',
                         'Downloading verifies bytes, not subject identity',
                         'Never guess URL variants after a 404',
                         'Timeouts preserve completed results', 'never replay uncertain effects',
                         'Report the blocker instead of ending silently'):
            with self.subTest(required=required):self.assertIn(required, guide)

    def test_master_has_no_superseded_execution_claims(self):
        master = (ROOT / "PortableAI_Master_Instructions_v45.txt").read_text(encoding="utf-8")
        for old in ("Use Qwen3-TTS for speech.", "- faster-whisper large-v3-turbo",
                    "Only explicit `protein.minimize platform=cuda`", "http://127.0.0.1:8765/",
                    "at most two meaningful refinements"):
            self.assertNotIn(old, master)
        for current in ("Operational guidance revision: " + REVISION, "platform=opencl",
                        'voice-say "<text>"', "video-small", "not image-to-video",
                        "image-search -> actual image_url/page_url", "hydration ledgers"):
            self.assertIn(current, master)


if __name__ == "__main__":
    unittest.main()
