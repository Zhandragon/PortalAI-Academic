"""Honest model progress and bounded inference waits, without replaying actions.

The caller owns the HTTP connection.  Only its supplied abort callback may close
that connection; this helper never starts inference, retries, or touches tools.
Notifications must be quick/nonblocking (normally a GUI event-queue put).
"""
from __future__ import annotations

import math
import io
import select
import threading
import time


class ResponseStalled(RuntimeError):
    """A local inference deadline, deliberately not a retryable transport error."""

    def __init__(self, *, phase, reason, elapsed, quiet):
        self.phase = phase
        self.reason = reason
        self.elapsed = elapsed
        self.quiet = quiet
        detail = (f'no useful model output for {quiet:.0f} seconds' if reason == 'idle'
                  else f'the response exceeded its {elapsed:.0f}-second time budget')
        super().__init__(f'Nice could not finish {phase}: {detail}. '
                         'This inference was interrupted; completed tools must not be replayed.')


def _check_io(watch):
    if watch.cancel.is_set():
        raise InterruptedError('The current model request was cancelled')
    watch.poll()
    watch.raise_if_expired()


class _WatchedReader(io.RawIOBase):
    """A single nonblocking reader, retaining SocketIO's file reference."""

    def __init__(self, raw, watch):
        super().__init__()
        self.raw = raw
        self.watch = watch

    def readable(self):
        return True

    def fileno(self):
        return self.raw.fileno()

    def readinto(self, buffer):
        if self.closed:
            raise ValueError('Read from closed watched socket')
        if not len(buffer):
            return 0
        while True:
            _check_io(self.watch)
            try:
                ready, _, _ = select.select([self.raw], [], [], .05)
            except (OSError, ValueError):
                _check_io(self.watch)
                raise
            if not ready:
                continue
            _check_io(self.watch)
            try:
                count = self.raw.readinto(buffer)
            except (BlockingIOError, InterruptedError):
                continue
            if count is not None:
                return count

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class WatchedSocket:
    """Cancellable HTTP socket I/O without background reader threads.

    Wrap only this request's newly connected, plain HTTP socket before sending
    the request.  It becomes nonblocking; HTTPConnection's sendall and makefile
    calls are handled here with select and the response deadline.  No other
    component may concurrently read/write this socket.  Keep the ORIGINAL socket
    for the caller's owned shutdown callback.  The monitor must not close a
    BufferedReader: the inference thread closes its response/connection.

    SocketIO still holds its ordinary descriptor reference, so HTTPConnection
    may close its socket after headers with Connection:close while the response
    body remains readable until that response is explicitly closed.
    """

    def __init__(self, sock, watch):
        self.socket = sock
        self.watch = watch
        sock.setblocking(False)

    def __getattr__(self, name):
        return getattr(self.socket, name)

    def sendall(self, data, flags=0):
        remaining = memoryview(data)
        while remaining:
            _check_io(self.watch)
            try:
                _, ready, _ = select.select([], [self.socket], [], .05)
            except (OSError, ValueError):
                _check_io(self.watch)
                raise
            if not ready:
                continue
            _check_io(self.watch)
            try:
                written = self.socket.send(remaining[:65536], flags)
            except (BlockingIOError, InterruptedError):
                continue
            if not written:
                raise ConnectionError('The model connection closed during request upload')
            remaining = remaining[written:]

    def makefile(self, mode='r', buffering=None, *, encoding=None, errors=None, newline=None):
        if mode != 'rb' or any(value is not None for value in (encoding, errors, newline)):
            raise ValueError('WatchedSocket supports binary HTTP response reads only')
        raw = self.socket.makefile('rb', buffering=0)
        wrapped = _WatchedReader(raw, self.watch)
        if buffering == 0:
            return wrapped
        try:
            size = io.DEFAULT_BUFFER_SIZE if buffering is None or buffering < 0 else buffering
            return io.BufferedReader(wrapped, buffer_size=size)
        except BaseException:
            wrapped.close()
            raise


def _positive(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise ValueError(f'{name} must be a finite positive number')
    return float(value)


def _label(value):
    text = ' '.join(str(value).split())[:120]
    return text or 'preparing a response'


class ResponseWatch:
    """One joined monitor for a single HTTP inference, with injectable time.

    ``touch`` means a useful content/reasoning/tool-argument delta, not a socket
    keepalive.  Its optional total_timeout updates the deadline measured from
    the ORIGINAL start; it never resets the response's elapsed time.

    ``poll`` is public for deterministic fake-clock tests.  Normal callers use
    ``with ResponseWatch(...) as watch`` and call ``watch.touch(...)`` as output
    arrives.  __exit__ joins before raising a deadline error, including when
    abort made the HTTP reader raise OSError.  This prevents transport retry.
    """

    def __init__(self, notify, cancel, abort, *, phase='preparing a response',
                 idle_timeout=90, total_timeout=300, progress_interval=20,
                 clock=time.monotonic, tick=.25):
        if not callable(notify) or not callable(abort) or not callable(clock):
            raise TypeError('notify, abort and clock must be callable')
        if not callable(getattr(cancel, 'is_set', None)):
            raise TypeError('cancel must provide is_set()')
        self.notify = notify
        self.cancel = cancel
        self.abort = abort
        self.clock = clock
        self.idle_timeout = _positive(idle_timeout, 'idle_timeout')
        self.total_timeout = _positive(total_timeout, 'total_timeout')
        self.progress_interval = _positive(progress_interval, 'progress_interval')
        self.tick = _positive(tick, 'tick')
        self.phase = _label(phase)
        self.started = float(clock())
        self.last_progress = self.started
        self.last_notice = self.started
        self.error = None
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._active = True
        self._thread = None

    def __enter__(self):
        with self._lock:
            if self._thread is not None or not self._active:
                raise RuntimeError('A response watch cannot be reused')
            self._thread = threading.Thread(target=self._run, name='PortalAIResponseWatch', daemon=True)
            self._thread.start()
        return self

    def _run(self):
        while not self._stop.wait(self.tick):
            self.poll()

    def touch(self, phase=None, *, total_timeout=None):
        """Record useful model progress; return False after cancellation/expiry."""
        total = None if total_timeout is None else _positive(total_timeout, 'total_timeout')
        with self._lock:
            if not self._active or self.cancel.is_set():
                return False
            now = float(self.clock())
            if now < min(self.last_progress+self.idle_timeout, self.started+self.total_timeout):
                self.last_progress = now
                if phase is not None:
                    self.phase = _label(phase)
                if total is not None:
                    self.total_timeout = total
                return True
        # A late delta cannot revive an expired response between monitor ticks.
        self.poll()
        return False

    def poll(self):
        """Evaluate time and emit at most one notice/abort; never runs a tool."""
        expired = False
        with self._lock:
            if not self._active:
                return
            if self.cancel.is_set():
                self._active = False
                self._stop.set()
                return
            now = float(self.clock())
            elapsed = max(0., now - self.started)
            quiet = max(0., now - self.last_progress)
            idle_deadline = self.last_progress + self.idle_timeout
            total_deadline = self.started + self.total_timeout
            if now >= min(idle_deadline, total_deadline):
                reason = 'idle' if idle_deadline <= total_deadline else 'total'
                self.error = ResponseStalled(phase=self.phase, reason=reason, elapsed=elapsed, quiet=quiet)
                self._active = False
                self._stop.set()
                expired = True
            elif now - self.last_notice >= self.progress_interval:
                self.last_notice = now
                message = (f'Nice is {self.phase} ({elapsed:.0f}s elapsed; '
                           f'{quiet:.0f}s since useful model output). Stop remains available.')
                # Keep notification inside the lock so stop() cannot return and
                # then receive a stale update from this request.
                try:
                    self.notify(message)
                except Exception:
                    pass  # Presentation failure must not kill useful inference.
        if expired:
            # Never hold the watch lock while touching an owned socket.
            try:
                self.abort()
            except Exception:
                pass  # The typed deadline still wins when the reader unwinds.

    def stop(self):
        """Join the sole monitor. No notifications can follow successful return."""
        with self._lock:
            self._active = False
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join()

    def raise_if_expired(self):
        if self.error is not None and not self.cancel.is_set():
            raise self.error

    def __exit__(self, exc_type, exc, traceback):
        self.stop()
        if self.error is not None and not self.cancel.is_set():
            raise self.error from exc
        return False
