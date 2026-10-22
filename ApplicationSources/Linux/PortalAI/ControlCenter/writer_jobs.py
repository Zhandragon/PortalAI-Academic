"""Track every background writer before starting it; close prevents late work."""
import threading
import time


class WriterJobs:
    def __init__(self):
        self._lock = threading.RLock()
        self._threads = set()
        self._closed = False

    def thread(self, *, target, args=(), kwargs=None, name=None, daemon=True):
        group = self
        class WriterThread(threading.Thread):
            def start(self):
                with group._lock:
                    if group._closed:
                        raise RuntimeError('PortalAI is closing; new background work is disabled')
                    group._threads.add(self)
                    try:
                        super().start()
                    except BaseException:
                        group._threads.discard(self)
                        raise

            def run(self):
                try:
                    super().run()
                finally:
                    with group._lock:
                        group._threads.discard(self)
        return WriterThread(target=target, args=args, kwargs=kwargs or {}, name=name, daemon=daemon)

    def close(self):
        with self._lock:
            self._closed = True

    def wait(self, timeout=30):
        """Called off Tk's thread after cancellation, never promises forced exit."""
        deadline = time.monotonic() + max(0, timeout)
        with self._lock:
            if not self._closed:
                raise RuntimeError('Close the writer gate before verifying quiescence')
            threads = list(self._threads)
        for thread in threads:
            if thread is threading.current_thread():
                continue
            thread.join(timeout=max(0, deadline-time.monotonic()))
        with self._lock:
            alive = [t.name for t in self._threads if t.is_alive()]
        return {'stopped': not alive, 'remaining': sorted(alive)}
