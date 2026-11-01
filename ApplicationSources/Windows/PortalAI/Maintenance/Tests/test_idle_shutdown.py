"""Idle background resources must finish before verified account sealing."""
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
from native_chat import NativeChat, ToolRuntime
from knowledge_monitor import KnowledgeMonitor
from writer_jobs import WriterJobs
from workspace_services import register, close_all, unregister


class IdleShutdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def chat(self):
        chat = NativeChat.__new__(NativeChat)
        chat.root = self.root
        chat.app = Mock()
        chat.busy = False
        chat.conversation_active = threading.Event()
        chat._closing = False
        chat._writer_jobs = WriterJobs()
        chat.memory = Mock()
        chat._stop_embedded_media = Mock()
        chat.release_audio_capture = Mock()
        chat.stop_generation = Mock()
        chat.drop_target = None
        runtime = ToolRuntime.__new__(ToolRuntime)
        runtime.root = self.root
        runtime._lock = threading.RLock()
        runtime._proc = None
        runtime.profile = SimpleNamespace(identity=None)
        chat.tool_runtime = runtime
        return chat

    def monitor(self, chat):
        with patch('knowledge_monitor.guard', return_value=lambda:None):
            monitor = KnowledgeMonitor(chat)
        chat._knowledge_monitor = monitor
        register(self.root, monitor)
        monitor.thread = chat._writer_jobs.thread(target=monitor.run, name='PortalAI-document-monitor')
        monitor.thread.start()
        self.addCleanup(monitor.thread.join, 2)
        self.addCleanup(monitor.close)
        return monitor

    def shutdown(self, chat):
        # Keep this regression independent of host desktop and agent services;
        # the real ToolRuntime.cancel and resource registry are exercised.
        with patch('desktop_control.revoke'), patch('agent_collaboration.close_profile'):
            chat.shutdown()

    def test_idle_shutdown_cancels_and_joins_real_document_monitor(self):
        chat = self.chat(); monitor = self.monitor(chat)
        self.assertTrue(monitor.thread.is_alive())
        self.shutdown(chat)
        self.assertTrue(chat.wait_for_writers(2)['stopped'])
        self.assertTrue(monitor.stopped.is_set())
        self.assertFalse(monitor.thread.is_alive())
        chat.stop_generation.assert_not_called()
        self.assertEqual(chat.tool_runtime._cancel_epoch, 1)

    def test_closing_guard_stops_monitor_even_if_primary_cleanup_failed(self):
        chat = self.chat()
        with patch('knowledge_monitor.guard', return_value=Mock()) as factory:
            monitor = KnowledgeMonitor(chat)
        chat._closing = True
        with self.assertRaisesRegex(RuntimeError, 'monitor stopped'):monitor.check()
        factory.return_value.assert_not_called()

    def test_unrelated_cleanup_failure_still_stops_idle_monitor(self):
        chat = self.chat(); monitor = self.monitor(chat)
        chat.memory.cancel_active.side_effect = RuntimeError('synthetic')
        with self.assertRaisesRegex(RuntimeError, 'cleanup needs retry'):self.shutdown(chat)
        self.assertTrue(chat.wait_for_writers(2)['stopped'])
        self.assertTrue(monitor.stopped.is_set())

    def test_failed_resource_is_retained_and_shutdown_retry_closes_it(self):
        chat = self.chat(); resource = Mock()
        resource.close.side_effect = [RuntimeError('synthetic close failure'), None]
        register(self.root, resource)
        self.addCleanup(unregister, self.root, resource)
        with self.assertRaisesRegex(RuntimeError, 'cleanup needs retry'):self.shutdown(chat)
        self.assertEqual(resource.close.call_count, 1)
        self.shutdown(chat)
        self.assertEqual(resource.close.call_count, 2)
        self.assertEqual(close_all(self.root), [])
        self.assertTrue(chat.wait_for_writers(0)['stopped'])

    def test_all_resources_are_attempted_after_one_close_fails(self):
        first = Mock(); second = Mock()
        first.close.side_effect = RuntimeError('synthetic')
        register(self.root, first);register(self.root, second)
        self.addCleanup(unregister, self.root, first)
        self.assertEqual(len(close_all(self.root)), 1)
        first.close.assert_called_once();second.close.assert_called_once()
        first.close.side_effect = None
        self.assertEqual(close_all(self.root), [])
        self.assertEqual(first.close.call_count, 2)
        second.close.assert_called_once()


if __name__ == '__main__': unittest.main()
