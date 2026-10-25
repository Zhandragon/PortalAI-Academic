"""Coalesced, account-scoped presentation reads; workers never call Tk.

Results are display data only. Mutating commands must still reload and validate
their authoritative records. The application's WriterJobs gate owns each read,
including any lazy restoration or derived-index/date repair it triggers.
"""
import queue
import threading
import tkinter as tk


def visible(widget):
    if widget.winfo_ismapped():
        return True
    # Projection can inspect a page without mapping it on the local desktop.
    native = getattr(widget.winfo_toplevel(), '_portalai_native_workflow', None)
    overrides = tuple(getattr(native, 'overrides', {}).values())
    current = widget
    while current is not None:
        if any(current is override for override in overrides):
            return True
        current = getattr(current, 'master', None)
    return False


class RecordRefresh:
    def __init__(self, owner, load, apply, *, check, error, jobs=None):
        self.owner, self.load, self.apply = owner, load, apply
        self.check, self.error, self.jobs = check, error, jobs
        self.closed = threading.Event()
        self.results = queue.Queue(maxsize=1)
        self.running = False
        self.wanted = None
        self.version = 0
        self.timer = owner.after(40, self.poll)
        owner.bind('<Destroy>', self._destroy, add='+')
        owner.bind('<Unmap>', self._unmap, add='+')
        owner._record_refreshes = getattr(owner, '_record_refreshes', []) + [self]

    def request(self, request, *, invalidate=False):
        if self.closed.is_set():
            return
        if not visible(self.owner):
            self.discard()
            return
        if request != self.wanted or invalidate:
            self.version += 1
        self.wanted = request
        if not self.running:
            self._start()

    def discard(self):
        self.version += 1
        self.wanted = None

    def _unmap(self, event):
        if event.widget is self.owner and not visible(self.owner):
            self.discard()

    def _start(self):
        request, version = self.wanted, self.version
        if request is None or self.closed.is_set():
            return
        self.running = True
        def worker():
            value = failure = None
            try:
                self.check()
                value = self.load(request)
                self.check()
            except Exception as exc:
                failure = exc
            if not self.closed.is_set():
                self.results.put_nowait((version, value, failure))
        try:
            factory = self.jobs.thread if self.jobs is not None else threading.Thread
            factory(target=worker, name='PortalAIRecordDisplay', daemon=True).start()
        except Exception as exc:
            self.running = False
            self.wanted = None
            self.error(exc)

    def poll(self):
        self.timer = None
        if self.closed.is_set():
            return
        try:
            version, value, failure = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.running = False
            if not visible(self.owner):
                self.discard()
            elif version == self.version and self.wanted is not None:
                try:
                    self.check()  # Recheck the login immediately before publication.
                    if failure is not None:
                        raise failure
                    self.apply(value)
                except Exception as exc:
                    self.error(exc)
            elif self.wanted is not None:
                self._start()  # Only the newest changed selection/filter survives.
        if not self.closed.is_set():
            self.timer = self.owner.after(40, self.poll)

    def _destroy(self, event):
        if event.widget is self.owner:
            self.close()

    def close(self):
        self.closed.set()
        self.discard()
        if self.timer is not None:
            try:
                self.owner.after_cancel(self.timer)
            except tk.TclError:
                pass
            self.timer = None
        try:
            while True:
                self.results.get_nowait()
        except queue.Empty:
            pass
