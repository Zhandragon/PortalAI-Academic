from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
import mission_modes as modes
import vm_runner
from mission_runner import Missions


class ModeBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Missions(Path(temp.name))

    def test_observe_action_cannot_promote_itself_to_full(self):
        mission = self.store.create("Observe")
        with patch("mission_runner.subprocess.Popen") as host:
            with self.assertRaises(PermissionError):
                self.store.execute(mission, {"action": "shell", "mode": "full", "command": "echo no"})
        host.assert_not_called()

    def test_vm_cannot_request_host_reads_or_diagnostics(self):
        with patch.object(vm_runner, "preflight", return_value={}):
            mission = self.store.create("VM", "vm")
        for action in ("read_file", "diagnostics"):
            with self.assertRaises(PermissionError):
                self.store.execute(mission, {"action": action, "path": "Agent/mission_runner.py", "mode": "full"})

    def test_vm_failure_never_retries_in_host_shell(self):
        with patch.object(vm_runner, "preflight", return_value={}):
            mission = self.store.create("VM", "vm")
        with patch.object(vm_runner, "run_command", side_effect=RuntimeError("No hardware virtualization")) as guest, patch("mission_runner.subprocess.Popen") as host:
            with self.assertRaisesRegex(RuntimeError, "virtualization"):
                self.store.execute(mission, {"action": "shell", "mode": "full", "command": "id"})
            guest.assert_called_once(); host.assert_not_called()

    def test_subtask_inherits_mode_despite_requested_override(self):
        with patch.object(vm_runner, "preflight", return_value={}):
            for mode in modes.MODES:
                parent = self.store.create("Parent", mode)
                self.store.execute(parent, {"action": "subtask", "objective": "Child", "mode": "full"})
                child = self.store.load(parent["children"][0])
                self.assertEqual(child["mode"], mode)

    def test_invalid_saved_mode_fails_before_writing_notes(self):
        mission = self.store.create("Test")
        mission["mode"] = "unexpected"
        with self.assertRaises(ValueError):
            self.store.execute(mission, {"action": "note", "text": "must not be saved"})
        self.assertFalse((self.store.folder(mission["id"])/"notes.txt").exists())

    def test_unrecognized_action_cannot_execute_in_any_mode(self):
        for mode in modes.MODES:
            with self.assertRaises(PermissionError): modes.authorize_action(mode, "host_shell")
            with self.assertRaises(PermissionError): modes.authorize_action(mode, ["shell"])

    def test_preflight_failure_is_reported_without_guest_or_host_fallback(self):
        with patch.object(vm_runner, "preflight", side_effect=RuntimeError("Feature unavailable")), patch.object(vm_runner, "run_command") as guest:
            result = modes.readiness(self.store.root, probe=True)
        self.assertFalse(result["vm"]["ready"]); self.assertFalse(result["vm"]["guest_executed"])
        self.assertIn("Feature unavailable", result["vm"]["error"]); guest.assert_not_called()

    def test_prerequisite_check_does_not_claim_live_validation(self):
        with patch.object(vm_runner, "preflight", return_value={}), patch.object(vm_runner, "run_command") as guest:
            result = modes.readiness(self.store.root)
        self.assertTrue(result["vm"]["ready"]); self.assertFalse(result["vm"]["guest_executed"])
        self.assertIn("not booted", result["vm"]["assurance"]); guest.assert_not_called()

    def test_failed_guest_probe_is_not_reported_ready(self):
        with patch.object(vm_runner, "preflight", return_value={}), patch.object(vm_runner, "run_command", return_value={"exit_code": 1, "output": "failed"}):
            result = modes.readiness(self.store.root, probe=True)
        self.assertFalse(result["vm"]["ready"]); self.assertTrue(result["vm"]["guest_executed"])


if __name__ == "__main__": unittest.main()
