"""Deferred chat reads cannot block Tk or publish after Stop/login changes."""
import queue
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter', 'Agent', 'Maintenance/Tests')]
import test_chat_hydration as fixtures
import native_chat as chat
from profile_paths import ProfileLocked


class ChatLoadingTests(unittest.TestCase):
    setUp = fixtures.ChatHydrationTests.setUp
    tearDown = fixtures.ChatHydrationTests.tearDown
    panel = fixtures.ChatHydrationTests.panel
    revoke = fixtures.ChatHydrationTests.revoke

    def loading_panel(self):
        panel = self.panel()
        panel.model_lbl = Mock(); panel.COL = {'muted': '#888'}
        panel._apply_loaded_session = Mock(); panel.refresh_status = Mock()
        return panel

    def test_selection_read_is_tracked_and_not_on_caller_thread(self):
        panel = self.loading_panel(); caller = threading.get_ident(); threads = []
        def read(sid): threads.append(threading.get_ident()); return {'id': sid}
        panel.store.load_session = read
        panel.load_session('old-chat')
        kind, data = panel.ev.get(timeout=3)
        self.assertEqual(kind, 'session_loaded')
        self.assertNotEqual(threads, [caller])
        panel._apply_loaded_session.assert_not_called()
        panel._finish_session_load(data)
        panel._apply_loaded_session.assert_called_once_with({'id': 'old-chat'})

    def test_newer_selection_rejects_old_completion(self):
        panel = self.loading_panel(); panel.store.load_session = lambda sid: {'id': sid}
        panel.load_session('first'); _, first = panel.ev.get(timeout=3)
        panel.load_session('second'); _, second = panel.ev.get(timeout=3)
        panel._finish_session_load(first)
        panel._apply_loaded_session.assert_not_called()
        panel._finish_session_load(second)
        panel._apply_loaded_session.assert_called_once_with({'id': 'second'})

    def test_stop_rejects_queued_completion(self):
        panel = self.loading_panel(); panel.store.load_session = lambda sid: {'id': sid}
        panel.load_session('first'); _, data = panel.ev.get(timeout=3)
        panel.stop_generation(); panel._finish_session_load(data)
        panel._apply_loaded_session.assert_not_called()

    def test_revocation_rejects_queued_completion(self):
        panel = self.loading_panel(); panel.store.load_session = lambda sid: {'id': sid}
        panel.load_session('first'); _, data = panel.ev.get(timeout=3)
        self.revoke()
        with self.assertRaises(ProfileLocked): panel._finish_session_load(data)
        panel._apply_loaded_session.assert_not_called()

    def test_search_reads_on_worker_and_finds_body_and_attachment_names(self):
        panel = self.loading_panel(); caller = threading.get_ident(); threads = []
        rows = [{'id': 'a', 'title': 'Title'}, {'id': 'b', 'title': 'Another title'}]
        panel.store.list_sessions = lambda: rows
        def read(sid):
            threads.append(threading.get_ident())
            return {'messages': [{'content': 'Needle' if sid == 'a' else '',
                                  'attachments': [{'name': 'needle.txt'}] if sid == 'b' else []}]}
        panel.store.load_session = read
        panel.history_search = SimpleNamespace(get=lambda: 'needle')
        panel.refresh_sessions_labels_only = Mock()
        self.assertEqual(panel._filtered_sessions(), [])
        kind, data = panel.ev.get(timeout=3)
        self.assertEqual(kind, 'history_search_ready')
        self.assertTrue(all(ident != caller for ident in threads))
        panel._finish_history_search(data)
        self.assertEqual(panel._filtered_sessions(), rows)
        self.assertEqual(len(threads), 2)


if __name__ == '__main__': unittest.main()
