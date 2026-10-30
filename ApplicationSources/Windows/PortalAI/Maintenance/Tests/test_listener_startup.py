"""Regression coverage for PID-snapshot/socket-probe startup races."""
import contextlib
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'Agent'))
import service_manager as service
import chat_model_switch as switch


@unittest.skipUnless(os.name == 'nt', 'Windows process-image ownership')
class ListenerStartupTests(unittest.TestCase):
    def scenario(self, snapshots, probes, images=None):
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.pids = stack.enter_context(patch.object(service, '_listening_pids', side_effect=snapshots))
        self.probe = stack.enter_context(patch.object(service, 'port_open', side_effect=probes))
        stack.enter_context(patch.object(service.time, 'sleep'))
        stack.enter_context(patch.object(service, '_process_command_line', return_value='test process'))
        stack.enter_context(patch.object(service, 'root_dir', return_value=ROOT))
        stack.enter_context(patch.object(service, '_process_image_path',
                                        side_effect=lambda pid: (images or {}).get(pid)))

    def test_owned_child_binds_between_snapshot_and_probe(self):
        self.scenario([[], [1234]], [True], {1234: str(ROOT/'LLM/llama-server.exe')})
        result = switch._owned_listener()
        self.assertTrue(result['portable_qwen'])
        self.assertEqual([row['pid'] for row in result['listeners']], [1234])
        self.assertEqual(self.pids.call_count, 2)

    def test_delayed_os_snapshot_is_refreshed(self):
        self.scenario([[], [], [], [1234]], [True, True, True],
                      {1234: str(ROOT/'LLM/llama-server.exe')})
        self.assertTrue(switch._owned_listener()['portable_qwen'])
        self.assertEqual(self.pids.call_count, 4)

    def test_foreign_child_appearing_after_snapshot_is_refused(self):
        self.scenario([[], [1234]], [True], {1234: str(ROOT.parent/'Other/llama-server.exe')})
        with self.assertRaisesRegex(RuntimeError, 'outside this portable root'):
            switch._owned_listener()

    def test_unidentifiable_open_socket_is_bounded_and_refused(self):
        self.scenario([[], [], [], []], [True, True, True, True])
        with self.assertRaisesRegex(RuntimeError, 'ownership could not be verified'):
            switch._owned_listener()
        self.assertEqual(self.pids.call_count, 4)

    def test_socket_disappearing_during_refresh_is_offline(self):
        self.scenario([[], []], [True, False])
        self.assertEqual(switch._owned_listener(),
                         {'open': False, 'portable_qwen': False, 'listeners': []})

    def test_closed_socket_does_not_retry(self):
        self.scenario([[]], [False])
        self.assertFalse(switch._owned_listener()['open'])
        self.assertEqual(self.pids.call_count, 1)

    def test_mixed_owned_and_foreign_listeners_are_never_adopted(self):
        self.scenario([[1234, 5678], [1234, 5678]], [],
                      {1234: str(ROOT/'LLM/llama-server.exe'),
                       5678: str(ROOT.parent/'Other/llama-server.exe')})
        self.assertFalse(service._listener_identity()['portable_qwen'])
        with self.assertRaisesRegex(RuntimeError, 'outside this portable root'):
            switch._owned_listener()

    def test_unreadable_process_identity_is_refused(self):
        self.scenario([[1234]], [], {})
        with self.assertRaises(RuntimeError):
            switch._owned_listener()


if __name__ == '__main__':
    unittest.main()
