"""Deterministic deadline/progress contracts; no server, Tk or live profile."""
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'ControlCenter'))
from chat_progress import ResponseStalled, ResponseWatch, WatchedSocket


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now
    def advance(self, seconds): self.now += seconds


class ResponseWatchTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.cancel = threading.Event()
        self.notify = Mock()
        self.abort = Mock()

    def watch(self, **options):
        return ResponseWatch(self.notify, self.cancel, self.abort, clock=self.clock, **options)

    def test_regular_progress_includes_elapsed_and_phase_even_while_reasoning(self):
        watch = self.watch()
        self.clock.advance(19); watch.poll(); self.notify.assert_not_called()
        watch.touch('reasoning'); self.clock.advance(1); watch.poll()
        message = self.notify.call_args.args[0]
        self.assertIn('reasoning', message); self.assertIn('20s elapsed', message); self.assertIn('1s since', message)
        for _ in range(20): self.clock.advance(1); watch.touch('reasoning'); watch.poll()
        self.assertEqual(self.notify.call_count, 2); self.abort.assert_not_called()

    def test_quiet_deadline_aborts_once_with_nontransport_error(self):
        watch = self.watch()
        self.clock.advance(90); watch.poll(); watch.poll()
        self.abort.assert_called_once(); self.assertEqual(watch.error.reason, 'idle')
        self.assertIsInstance(watch.error, RuntimeError); self.assertNotIsInstance(watch.error, OSError)
        with self.assertRaises(ResponseStalled): watch.raise_if_expired()
        self.assertFalse(watch.touch()); self.notify.assert_not_called()

    def test_useful_deltas_reset_idle_but_not_total_deadline(self):
        watch = self.watch(total_timeout=100)
        for _ in range(4): self.clock.advance(20); watch.touch(); watch.poll()
        self.clock.advance(20); watch.poll()
        self.assertEqual(watch.error.reason, 'total'); self.abort.assert_called_once()

    def test_visible_text_may_extend_original_total_budget_without_resetting_clock(self):
        watch = self.watch(total_timeout=180, idle_timeout=600)
        self.clock.advance(179); watch.touch('writing the reply', total_timeout=300)
        self.clock.advance(120); watch.poll(); self.abort.assert_not_called()
        self.clock.advance(1); watch.poll()
        self.assertEqual(watch.error.reason, 'total'); self.assertEqual(watch.error.elapsed, 300)

    def test_late_delta_cannot_extend_an_already_expired_budget(self):
        watch = self.watch(total_timeout=180, idle_timeout=600)
        self.clock.advance(181)
        self.assertFalse(watch.touch('writing the reply', total_timeout=300))
        self.abort.assert_called_once(); self.assertEqual(watch.error.reason, 'total')
        self.assertEqual(watch.total_timeout, 180)

    def test_cancellation_never_becomes_a_stall_or_aborts_another_request(self):
        watch = self.watch(); self.cancel.set(); self.clock.advance(500); watch.poll()
        watch.raise_if_expired(); self.abort.assert_not_called(); self.notify.assert_not_called()
        self.cancel.clear(); watch.poll(); self.abort.assert_not_called()

    def test_user_stop_takes_precedence_over_already_expired_watch(self):
        watch = self.watch(); self.clock.advance(90); watch.poll(); self.cancel.set()
        watch.raise_if_expired(); self.assertFalse(watch.__exit__(None, None, None))

    def test_context_exit_replaces_socket_error_with_typed_deadline(self):
        watch = self.watch()
        with self.assertRaises(ResponseStalled) as caught:
            with watch:
                self.clock.advance(90); watch.poll()
                raise OSError('owned socket closed by monitor')
        self.assertIsInstance(caught.exception.__cause__, OSError)
        self.assertFalse(watch._thread.is_alive())

    def test_normal_transport_error_is_not_disguised_or_retried(self):
        watch = self.watch()
        with self.assertRaisesRegex(OSError, 'original transport error'):
            with watch: raise OSError('original transport error')
        self.assertFalse(watch._thread.is_alive()); self.abort.assert_not_called()

    def test_stop_joins_monitor_and_prevents_late_events(self):
        watch = self.watch()
        with watch: pass
        self.assertFalse(watch._thread.is_alive())
        self.clock.advance(1000); watch.poll(); watch.touch(); watch.poll()
        self.notify.assert_not_called(); self.abort.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'reused'): watch.__enter__()

    def test_notify_failure_does_not_abort_inference(self):
        self.notify.side_effect = RuntimeError('synthetic renderer error')
        watch = self.watch(); self.clock.advance(20); watch.poll()
        self.assertIsNone(watch.error); self.abort.assert_not_called()

    def test_abort_is_outside_lock_and_failure_preserves_typed_deadline(self):
        watch = self.watch(); acquired = threading.Event()
        def abort():
            def take_lock():
                with watch._lock: acquired.set()
            thread = threading.Thread(target=take_lock); thread.start()
            self.assertTrue(acquired.wait(1)); thread.join()
            raise OSError('already closed')
        watch.abort = abort; self.clock.advance(90); watch.poll()
        with self.assertRaises(ResponseStalled): watch.raise_if_expired()

    def test_no_stale_notice_after_stop_during_blocked_notification(self):
        entered = threading.Event(); release = threading.Event(); stopped = threading.Event()
        def notify(_): entered.set(); release.wait(1)
        watch = ResponseWatch(notify, self.cancel, self.abort, clock=self.clock)
        self.clock.advance(20)
        runner = threading.Thread(target=watch.poll); runner.start()
        self.assertTrue(entered.wait(1))
        stopper = threading.Thread(target=lambda: (watch.stop(), stopped.set())); stopper.start()
        self.assertFalse(stopped.is_set()); release.set()
        runner.join(1); stopper.join(1)
        self.assertTrue(stopped.is_set()); self.assertFalse(runner.is_alive()); self.assertFalse(stopper.is_alive())
        self.clock.advance(500); watch.poll(); self.abort.assert_not_called()

    def test_invalid_limits_are_rejected(self):
        for value in (0, -1, float('nan'), float('inf'), True, '90'):
            for field in ('idle_timeout', 'total_timeout', 'progress_interval', 'tick'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.watch(**{field:value})

    def test_http_socket_close_retains_body_file_until_reader_is_closed(self):
        left, right = socket.socketpair()
        reader = None
        try:
            with self.watch() as watch:
                wrapped = WatchedSocket(left, watch)
                reader = wrapped.makefile('rb')
                right.sendall(b'body after Connection:close'); right.shutdown(socket.SHUT_WR)
                wrapped.close()
                self.assertEqual(reader.read(), b'body after Connection:close')
                self.assertNotEqual(left.fileno(), -1, 'The SocketIO descriptor reference was lost')
                reader.close()
                self.assertEqual(left.fileno(), -1)
        finally:
            if reader is not None: reader.close()
            left.close(); right.close()

    def test_blocked_request_upload_obeys_deadline_without_reader_thread(self):
        left, right = socket.socketpair()
        try:
            left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
            right.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
            watch = ResponseWatch(self.notify, self.cancel, self.abort, idle_timeout=.06,
                                  total_timeout=.2, progress_interval=.02, tick=.005)
            with self.assertRaises(ResponseStalled):
                with watch: WatchedSocket(left, watch).sendall(b'x' * (2*1024**2))
            self.assertFalse(watch._thread.is_alive()); self.abort.assert_called_once()
        finally:
            left.close(); right.close()


if __name__ == '__main__': unittest.main()
