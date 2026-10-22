import base64
import gzip
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
import vm_runner as vm
from mission_runner import Missions

class VMTests(unittest.TestCase):
    def test_low_host_ram_fails_before_starting_guest(self):
        with patch.object(vm, "memory_info", return_value=(8*1024**3, 512*1024**2)):
            with self.assertRaisesRegex(RuntimeError, "available host RAM"):
                vm.preflight()

    def test_no_network_shares_or_emulation_fallback(self):
        plan = {"executable": "qemu", "firmware": "firmware", "guest": "guest", "accelerator": "whpx"}
        args = vm.command_line(plan, "initramfs")
        self.assertEqual(args[args.index("-accel")+1], "whpx")
        self.assertEqual(args[args.index("-nic")+1], "none")
        self.assertEqual(args[args.index("-monitor")+1], "none")
        for prohibited in ("-virtfs", "-fsdev", "-drive", "-netdev", "-qmp", "-device", "tcg"):
            self.assertNotIn(prohibited, args)

    def test_guest_output_is_decoded_as_data(self):
        nonce = "a"*32
        data = (f"PORTALVM_{nonce}_BEGIN\nEXIT 7\nSTATE_EXIT 0\nOUTPUT\n".encode()
                + base64.b64encode(b"$(host command)\n") + b"\nSTATE\n"
                + base64.b64encode(b"opaque workspace") + f"\nPORTALVM_{nonce}_END\n".encode())
        result, state = vm.decode_result(data, nonce)
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["output"], "$(host command)\n")
        self.assertEqual(state, b"opaque workspace")
        with self.assertRaises(RuntimeError):
            vm.decode_result(data, "b"*32)
        with self.assertRaises(RuntimeError):
            vm.decode_result(data+data, nonce)

    def test_oversized_workspace_and_command_rejected_before_write(self):
        with self.assertRaises(ValueError):
            vm.build_initramfs("absent", "true", "a"*32, b"x"*(vm.STATE_LIMIT+1))
        with self.assertRaises(ValueError):
            vm.build_initramfs("absent", "x"*16001, "a"*32)

    def test_initramfs_keeps_command_out_of_control_script(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "base"
            base.write_bytes(b"UPSTREAM")
            result = vm.build_initramfs(base, "echo 'untrusted payload'", "a"*32)
            self.assertEqual(base.read_bytes(), b"UPSTREAM")
            extra = gzip.decompress(result[len(b"UPSTREAM"):])
            self.assertIn(b"portal-command.sh", extra)
            self.assertEqual(extra.count(b"echo 'untrusted payload'"), 1)

    def test_vm_mission_routes_shell_only_to_guest(self):
        with tempfile.TemporaryDirectory() as td:
            store = Missions(Path(td))
            with patch.object(vm, "preflight", return_value={}):
                m = store.create("Guest test", "vm")
            with patch.object(vm, "run_command", return_value={"exit_code": 0}) as run, patch("mission_runner.subprocess.Popen") as host:
                store.execute(m, {"action": "shell", "command": "id"})
                run.assert_called_once()
                host.assert_not_called()
            for action in ({"action": "read_file", "path": "Agent/mission_runner.py"}, {"action": "diagnostics"}):
                with self.assertRaises(PermissionError):
                    store.execute(m, action)

    def test_stop_prevents_vm_start(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            folder = root / "Data/VMTests/stop"
            folder.mkdir(parents=True)
            stop = folder / "STOP"
            stop.touch()
            with patch.object(vm, "preflight") as preflight:
                with self.assertRaisesRegex(RuntimeError, "stopped"):
                    vm.run_command("echo no", folder, root, stop=stop)
                preflight.assert_not_called()

    def test_parent_waits_for_subtask_and_receives_result(self):
        with tempfile.TemporaryDirectory() as td:
            store = Missions(Path(td))
            parent = store.create("Parent")
            parent = store.run(parent["id"], 2, model=lambda _: {"action": "subtask", "objective": "Child"})
            self.assertEqual(parent["status"], "waiting")
            self.assertEqual(parent["steps"], 1)
            child = store.run(parent["children"][0], model=lambda _: {"action": "complete", "text": "child verified"})
            self.assertEqual(child["status"], "complete")
            parent["next_run_at"] = 0
            store.save(parent)
            parent = store.run(parent["id"], model=lambda _: {"action": "complete", "text": "parent verified"})
            self.assertEqual(parent["status"], "complete")

if __name__ == "__main__":
    unittest.main()
