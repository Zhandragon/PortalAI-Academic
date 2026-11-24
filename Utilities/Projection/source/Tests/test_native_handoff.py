"""Synthetic host and existing transport regression tests; no desktop effects."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path[:0] = [str(ROOT / "app")]
from host_runtime import default_target
sys.path.insert(0, str(default_target() / "Agent"))
import native_handoff as h
spec = importlib.util.spec_from_file_location("portalai_target", ROOT / "app/portalai_target.py")
target = importlib.util.module_from_spec(spec)
sys.modules["portalai_target"] = target
spec.loader.exec_module(target)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        for module in (h, target.time):
            clock = patch.object(module, "monotonic", lambda: self.now)
            clock.start()
            self.addCleanup(clock.stop)
        self.manager = target.Manager(ROOT, Mock())
        self.manager.native_chat_endpoint = Mock(return_value=({"hwnd": 500}, {"port": 12345, "token": "x" * 40}))

    def request(self, operation, viewer="b" * 32, *, bad_ack=False):
        payload = {"operation": operation, "viewer": viewer, "request_id": "a" * 32}
        response = Mock(status=200)
        response.read.return_value = json.dumps({"accepted": not bad_ack, "request_id": payload["request_id"], "operation": operation}).encode()
        connection = Mock()
        connection.getresponse.return_value = response
        with patch("http.client.HTTPConnection", return_value=connection):
            if operation == "stop":
                return self.manager.native_chat(payload, self.now + 3)
            return self.manager.native_ui(payload, self.now + 3)

    def test_chat_then_workflow_boundary_is_two_seconds(self):
        self.request("stop")
        self.now = 1.99
        with self.assertRaises(PermissionError):
            self.request("invoke", "c" * 32)
        self.now = 2
        self.request("invoke", "c" * 32)
        self.assertEqual(self.manager.viewer, ("c" * 32, 4))

    def test_workflow_then_chat_boundary_is_two_seconds(self):
        self.request("invoke")
        self.now = 2
        self.request("stop", "c" * 32)

    def test_idle_and_read_only_remote_sessions_have_no_controller(self):
        self.assertIsNone(self.manager.viewer)
        self.request("describe")
        self.assertIsNone(self.manager.viewer)
        self.assertIsNone(getattr(self.manager, "_native_hold", None))

    def test_inflight_hold_blocks_other_viewer_even_past_legacy_timeout(self):
        with h.action(self.manager, "b" * 32):
            self.now = 31
            with self.assertRaises(PermissionError):
                self.manager._lease("c" * 32)
        self.now = 33
        self.manager._lease("c" * 32)

    def test_out_of_order_completion_retains_last_active_hold(self):
        first = h.action(self.manager, "b" * 32)
        second = h.action(self.manager, "b" * 32)
        first.__enter__()
        second.__enter__()
        first.__exit__(None, None, None)
        with self.assertRaises(PermissionError):
            self.manager._lease("c" * 32)
        second.__exit__(None, None, None)
        self.assertEqual(self.manager.viewer[1], 2)

    def test_unknown_ack_keeps_bounded_fallback_without_active_hold_leak(self):
        with self.assertRaises(RuntimeError):
            self.request("invoke", bad_ack=True)
        self.assertIsNone(self.manager._native_hold)
        self.now = 2
        with self.assertRaises(PermissionError):
            self.request("stop", "c" * 32)
        self.now = 30
        self.request("stop", "c" * 32)

    def test_newer_legacy_reservation_is_not_shortened(self):
        with h.action(self.manager, "b" * 32):
            self.manager._lease("b" * 32)
            reservation = self.manager.viewer
        self.assertIs(self.manager.viewer, reservation)


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HandoffTests)
    for filename in ("test_native_chat_host.py", "test_native_workflow_transport.py"):
        spec = importlib.util.spec_from_file_location(Path(filename).stem, ROOT / "Tests" / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    raise SystemExit(not result.wasSuccessful())
