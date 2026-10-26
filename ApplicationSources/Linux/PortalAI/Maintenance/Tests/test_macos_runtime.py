"""Host-independent checks for macOS backend selection and account-stop planning."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "Agent")]

import profile_shutdown
import runtime_policy


class MacRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.server = self.root / "LLM/backends/macos-metal/bin/llama-server"
        self.server.parent.mkdir(parents=True)
        self.server.touch()
        self.hardware = {"system": "Darwin", "machine": "arm64", "ram_total_bytes": 16 * 1024**3,
                         "ram_available_bytes": 12 * 1024**3, "gpus": []}

    def test_auto_prefers_metal_device_with_unified_memory_budget(self):
        with patch.object(runtime_policy, "run_probe", return_value="Metal0: Apple GPU\n"):
            result = runtime_policy.choose_backend(self.root, self.hardware, probe=True)
        self.assertEqual(result["backend"], "metal")
        self.assertEqual(result["device"], "Metal0")
        self.assertTrue(result["gpu"]["shared_memory"])
        self.assertEqual(result["gpu"]["free_bytes"], self.hardware["ram_available_bytes"])

    def test_auto_falls_back_to_cpu_when_no_metal_device_is_reported(self):
        def probe(argv):
            return "" if "--list-devices" in argv else "llama.cpp version"
        with patch.object(runtime_policy, "run_probe", side_effect=probe):
            result = runtime_policy.choose_backend(self.root, self.hardware, probe=True)
        self.assertEqual(result["backend"], "cpu")
        self.assertEqual(result["device"], "none")

    def test_macos_storage_policy_overrides_the_windows_source_default_only_on_macos(self):
        (self.root / "Agent").mkdir()
        (self.root / "Maintenance/Imports").mkdir(parents=True)
        (self.root / "Agent/hardware_profiles.json").write_text(
            '{"storage":{"minimum_free_gib":50,"minimum_free_fraction":0.1,'
            '"output_reserve_gib":100}}', encoding="utf-8")
        (self.root / "Maintenance/Imports/macos-storage-policy.json").write_text(
            '{"storage":{"minimum_free_gib":10,"minimum_free_fraction":0.1,'
            '"output_reserve_gib":5}}', encoding="utf-8")
        with patch.object(runtime_policy.sys, "platform", "darwin"):
            mac_policy = runtime_policy.load_policy(self.root)
        self.assertEqual(mac_policy["storage"], {"minimum_free_gib": 10,
                         "minimum_free_fraction": 0.1, "output_reserve_gib": 5})
        with patch.object(runtime_policy.sys, "platform", "win32"):
            windows_policy = runtime_policy.load_policy(self.root)
        self.assertEqual(windows_policy["storage"]["minimum_free_gib"], 50)

    def test_account_shutdown_plan_accepts_only_dedicated_portalai_groups(self):
        root_exe = self.root / "Runtime/MacPython/bin/python3.12"
        leader = {"pid": 90, "group": 90, "start": 10, "executable": str(root_exe), "identity": {}}
        child = {"pid": 91, "group": 90, "start": 11, "executable": "/bin/sh", "identity": {}}
        rows = {90: leader, 91: child}
        self.assertEqual(profile_shutdown._mac_plan(self.root, rows, rows), {90: leader})

        rows[90] = {**leader, "executable": "/usr/bin/python3"}
        with self.assertRaisesRegex(profile_shutdown.QuiescenceError, "escaped"):
            profile_shutdown._mac_plan(self.root, rows, rows)

    def test_account_shutdown_plan_rejects_groups_without_an_owned_leader(self):
        child = {"pid": 91, "group": 90, "start": 11, "executable": "/bin/sh", "identity": {}}
        with self.assertRaisesRegex(profile_shutdown.QuiescenceError, "escaped"):
            profile_shutdown._mac_plan(self.root, {91: child}, {91: child})


if __name__ == "__main__":
    unittest.main()
