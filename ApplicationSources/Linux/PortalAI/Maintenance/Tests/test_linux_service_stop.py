"""Linux service stop must call the exact-identity stop helper, never a predicate."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


class LinuxServiceStopTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / "Agent/.runtime").mkdir(parents=True)
        self.row = {"pid": 456, "start_ticks": 789, "uid": 1000,
                    "executable": str(self.root / "Runtime/LinuxPython/bin/python3"),
                    "argv": ["python3", "ComfyUI/main.py"]}
        self.record = self.root / "Agent/.runtime/linux-comfyui.json"
        self.record.write_text(json.dumps(self.row), encoding="utf-8")
        self.linux = types.ModuleType("linux_process")
        self.linux.identity = Mock(return_value=self.row)
        self.linux.owned = Mock(return_value=True)
        self.linux.stop = Mock()
        self.linux.is_llama = Mock(return_value=False)
        tree = ast.parse((ROOT / "Agent/service_manager.py").read_text(encoding="utf-8-sig"))
        node = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "stop")
        self.namespace = {"os": types.SimpleNamespace(name="posix"), "json": json,
                          "time": types.SimpleNamespace(time=lambda: 100, sleep=Mock()),
                          "normalize_service": lambda value: value,
                          "SERVICES": {"comfyui": {"port": 8188}, "acestep": {"port": 8001}},
                          "_listening_pids": Mock(return_value=[456]),
                          "_managed_pid": Mock(return_value=456), "_forget_pid": Mock(),
                          "port_open": Mock(return_value=False), "root_dir": lambda: self.root}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "service_manager.stop", "exec"), self.namespace)
        modules = patch.dict(sys.modules, {"linux_process": self.linux})
        modules.start()
        self.addCleanup(modules.stop)

    def test_registered_owned_comfy_service_is_actually_stopped(self):
        result = self.namespace["stop"]("comfyui")
        self.linux.stop.assert_called_once_with(self.row, self.root)
        self.linux.is_llama.assert_not_called()
        self.assertEqual(result["killed_pids"], [456])

    def test_foreign_listener_is_never_stopped(self):
        self.linux.owned.return_value = False
        with self.assertRaisesRegex(RuntimeError, "unregistered"):
            self.namespace["stop"]("comfyui")
        self.linux.stop.assert_not_called()

    def test_stale_registered_identity_is_never_stopped(self):
        self.record.write_text(json.dumps({**self.row, "start_ticks": 788}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unregistered"):
            self.namespace["stop"]("comfyui")
        self.linux.stop.assert_not_called()

    def test_missing_registration_is_never_stopped(self):
        self.record.unlink()
        with self.assertRaisesRegex(RuntimeError, "unregistered"):
            self.namespace["stop"]("comfyui")
        self.linux.stop.assert_not_called()

    def test_stop_all_recurses_into_service_function_without_import_shadowing(self):
        self.namespace["_listening_pids"].return_value = []
        self.namespace["_managed_pid"].return_value = None
        result = self.namespace["stop"]("all")
        self.assertEqual(set(result), {"comfyui", "acestep"})
        self.assertTrue(all(value["already_stopped"] for value in result.values()))


if __name__ == "__main__":
    unittest.main()
