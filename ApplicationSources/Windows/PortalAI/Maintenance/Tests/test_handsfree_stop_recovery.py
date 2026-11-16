"""Headless cancellation races: no microphone, model, account, or visible window."""
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ('ControlCenter', 'Agent')]
from native_chat import NativeChat, ActiveHTTP
from chat_voice import VoiceIO, VoiceTurn
from writer_jobs import WriterJobs


class StopRecoveryTests(unittest.TestCase):
    def setUp(self):
        p = self.p = NativeChat.__new__(NativeChat)
        p.root = ROOT
        p.app = Mock()
        p.COL = dict(panel='#111111', panel2='#222222', muted='#aaaaaa', text='#ffffff',
                     bad='#ff0000', cyan='#00ffff', gold='#aaaa00')
        p.session = {'id': 'stop-fixture', 'title': 'Chat', 'messages': [{'role': 'user', 'content': 'Question'}]}
        p.store = Mock()
        p.settings = {}
        p.ev = queue.Queue()
        p._stream_pump_budget_ms = 1000
        p.busy = True
        p.cancel_event = threading.Event()
        p.active_http = ActiveHTTP()
        p._writer_jobs = WriterJobs()
        p._active_request_worker = None
        p.conversation_active = threading.Event()
        p.conversation_active.set()
        p.conversation_thread = None
        p.conversation_capture_stream = p.conversation_capture_proc = None
        p.conversation_capture_lock = threading.Lock()
        p._conversation_io = VoiceIO(ROOT, lambda: None)
        p._conversation_request = VoiceTurn('stop-fixture', 'Question', request_index=0)
        p._mic_voice = None
        p.mic_proc = p.mic_stream = None
        p._live_thinking_block = p._live_tool_block = None
        p._trace_blocks = []
        p.pending_attachments = []
        for name in ('memory', 'tool_runtime', 'effort', 'stop_btn', 'send_btn', 'session_list',
                     'model_lbl', 'conversation_btn', 'mic_btn', 'prompt', '_check_login',
                     '_notice', '_resize_prompt', 'update_attachment_label', 'chat_insert',
                     '_set_llm_dot', '_activity_event', 'finish_trace_block',
                     'refresh_sessions_labels_only', 'refresh_status', 'update_token_label',
                     '_schedule_model_probe', '_maybe_schedule_auto_title', '_schedule_memory_maintenance'):
            setattr(p, name, Mock())
        self.addCleanup(self.finish)

    def finish(self):
        self.p.cancel_event.set()
        self.p._writer_jobs.close()
        self.assertTrue(self.p._writer_jobs.wait(3)['stopped'])

    def pump(self):
        with patch('voice_layout.sync_voice_view'), patch('command_palette.notify'):
            self.p._pump()

    def test_end_cancels_reply_promptly_and_recovers_send_after_slow_cleanup(self):
        p = self.p
        entered, release = threading.Event(), threading.Event()
        p.tool_runtime.cancel.side_effect = lambda: (entered.set(), release.wait(3))
        p._start_request_worker(target=lambda: p.cancel_event.wait(3), daemon=True)
        try:
            started = time.monotonic()
            p.stop_conversation_mode()
            self.assertLess(time.monotonic() - started, .25)
            self.assertTrue(p.cancel_event.is_set())
            self.assertFalse(p.conversation_active.is_set())
            self.assertTrue(p._conversation_io.cancelled.is_set())
            self.assertTrue(entered.wait(1))
            p._active_request_worker.join(1)
            self.pump()
            self.assertTrue(p.busy)
            self.assertTrue(p.cancel_event.is_set())
            p.send_btn.configure.assert_any_call(state='normal', text='Queue')
            p.stop_generation()  # Repeated Stop does not spawn another cleanup.
            p.tool_runtime.cancel.assert_called_once()
        finally:
            release.set()
            cleanup = getattr(p, '_request_cleanup', None)
            if cleanup is not None:
                cleanup.join(2)
        self.pump()
        self.assertFalse(p.busy)
        self.assertFalse(p.cancel_event.is_set())
        p.send_btn.configure.assert_any_call(state='normal', text='Send')

    def test_typing_followup_ends_capture_without_cancelling_current_answer(self):
        p = self.p
        p._queue_followup('Follow up')
        self.assertEqual(p._followup_state().peek().text, 'Follow up')
        self.assertFalse(p.conversation_active.is_set())
        self.assertFalse(p.cancel_event.is_set())
        p.tool_runtime.cancel.assert_not_called()

    def test_stop_keeps_ui_available_while_http_close_is_blocked(self):
        p = self.p
        entered, release = threading.Event(), threading.Event()
        p.active_http.conn = Mock()
        p.active_http.conn.close.side_effect = lambda: (entered.set(), release.wait(3))
        try:
            started = time.monotonic()
            p.stop_generation()
            self.assertLess(time.monotonic() - started, .25)
            self.assertTrue(p.cancel_event.is_set())
            self.assertTrue(entered.wait(1))
            p.send_btn.configure.assert_any_call(state='normal', text='Queue')
        finally:
            release.set()
            cleanup = getattr(p, '_request_cleanup', None)
            if cleanup is not None:
                cleanup.join(2)
        p.tool_runtime.cancel.assert_called_once()

    def test_orb_interrupt_cancels_streaming_reply_but_keeps_listening_mode(self):
        p = self.p
        p.interrupt_voice_reply()
        self.assertTrue(p.cancel_event.is_set())
        self.assertTrue(p._conversation_io.interrupted.is_set())
        self.assertTrue(p.conversation_active.is_set())
        self.assertFalse(p._conversation_io.cancelled.is_set())

    def test_late_voice_interrupt_cannot_cancel_another_turn(self):
        p = self.p
        p.ev.put(('conversation_interrupt', VoiceTurn('stop-fixture', 'Old question')))
        self.pump()
        self.assertFalse(p.cancel_event.is_set())
        p.ev.put(('conversation_interrupt', p._conversation_request))
        self.pump()
        self.assertTrue(p.cancel_event.is_set())

    def test_worker_exit_without_target_completion_recovers_composer(self):
        p = self.p
        def fail():
            raise RuntimeError('failure before worker try/finally')
        with patch('threading.excepthook') as hook:
            p._start_request_worker(target=fail, daemon=True)
            p._active_request_worker.join(1)
            hook.assert_called_once()
        self.pump()
        self.assertFalse(p.busy)
        self.assertTrue(p._followup_state().paused)
        p.send_btn.configure.assert_any_call(state='normal', text='Send')

    def test_duplicate_completion_is_fenced_from_new_worker(self):
        p = self.p
        old, current = Mock(), Mock()
        current.is_alive.return_value = False
        p._active_request_worker = current
        p.ev.put(('done', old))
        self.pump()
        self.assertTrue(p.busy)
        self.assertIs(p._active_request_worker, current)
        self.assertFalse(p._conversation_request.done.is_set())

    def test_stop_restores_send_after_cancelling_history_load(self):
        p = self.p
        p.busy = False
        pending = {'cancel': threading.Event()}
        p._session_load_request = pending
        p.stop_generation()
        self.assertTrue(pending['cancel'].is_set())
        p.send_btn.configure.assert_called_with(state='normal', text='Send')

    def test_cancel_wakes_real_watched_socket_and_releases_reader(self):
        p = self.p
        left, right = socket.socketpair()
        from chat_progress import WatchedSocket, ResponseWatch
        watch = ResponseWatch(Mock(), p.cancel_event, Mock(), idle_timeout=5, total_timeout=10)
        reader = WatchedSocket(left, watch).makefile('rb')
        p.active_http.sock = left
        conn = p.active_http.conn = Mock()
        conn.close.side_effect = reader.close
        entered = threading.Event()
        def read():
            entered.set()
            try:
                reader.readline()
            except InterruptedError:
                pass
            finally:
                conn.close()
        worker = threading.Thread(target=read)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            started = time.monotonic()
            p.cancel_event.set()
            p.cancel_http()
            self.assertLess(time.monotonic() - started, .25)
            worker.join(1)
            self.assertFalse(worker.is_alive())
        finally:
            right.close()
            left.close()
            worker.join(1)


if __name__ == '__main__':
    unittest.main()
