"""High-resolution Windows window icons, without changing Tk's DPI or chrome.

Tk 8.6's iconbitmap default supplies a 32px/16px class-icon pair. Explorer can
enlarge that pair on scaled displays. Give the actual native wrapper explicit
256px/64px icons from the existing multiresolution artwork instead. Reattach
after Tk recreates its wrapper; never subclass the Windows message procedure.
"""
from __future__ import annotations

import os
from pathlib import Path


class WindowIcons:
    def __init__(self, app, path):
        import ctypes
        from ctypes import wintypes as w

        self.app = app
        self._closed = False
        self._pending = None
        self._bindings = []
        self._windows = set()
        self._icons = {}
        self._ctypes = ctypes
        self._pid_type = w.DWORD
        self._api = ctypes.WinDLL('user32', use_last_error=True)
        for name, args, result in (
            ('LoadImageW', [w.HINSTANCE, w.LPCWSTR, w.UINT, ctypes.c_int, ctypes.c_int, w.UINT], w.HANDLE),
            ('DestroyIcon', [w.HICON], w.BOOL),
            ('GetAncestor', [w.HWND, w.UINT], w.HWND),
            ('GetWindowThreadProcessId', [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            ('SendMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], ctypes.c_ssize_t),
        ):
            function = getattr(self._api, name)
            function.argtypes = args
            function.restype = result
        try:
            # LR_LOADFROMFILE, without LR_SHARED: these handles belong to us.
            for kind, pixels in ((1, 256), (0, 64)):
                handle = self._api.LoadImageW(None, str(Path(path)), 1, pixels, pixels, 0x10)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                self._icons[kind] = handle
            for event in ('<Map>', '<Configure>'):
                self._bindings.append((event, app.bind(event, self._changed, add='+')))
            self._bindings.append(('<Destroy>', app.bind('<Destroy>', self._destroyed, add='+')))
            self._queue()
        except Exception:
            self.close()
            raise

    def _owned(self, hwnd):
        pid = self._pid_type()
        return bool(hwnd and self._api.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid))
                    and pid.value == os.getpid())

    def _changed(self, event):
        if event.widget is self.app:
            self._queue()

    def _queue(self):
        if not self._closed and self._pending is None:
            self._pending = self.app.after_idle(self.refresh)

    def refresh(self):
        self._pending = None
        if self._closed:
            return
        # GA_ROOT finds Tk's current outer wrapper after overrideredirect/map.
        hwnd = self._api.GetAncestor(self.app.winfo_id(), 2)
        if not self._owned(hwnd):
            return
        # Forget destroyed wrappers; don't accumulate handles across remapping.
        self._windows = {old for old in self._windows if self._owned(old)}
        self._windows.add(hwnd)
        for kind, handle in self._icons.items():
            # WM_GETICON / WM_SETICON. Avoid redundant native updates on resize.
            if self._api.SendMessageW(hwnd, 0x7F, kind, 0) != handle:
                self._api.SendMessageW(hwnd, 0x80, kind, handle)

    def _destroyed(self, event):
        if event.widget is self.app:
            self.close()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._pending is not None:
            try:
                self.app.after_cancel(self._pending)
            except Exception:
                pass
            self._pending = None
        for event, binding in self._bindings:
            try:
                self.app.unbind(event, binding)
            except Exception:
                pass
        self._bindings.clear()
        for hwnd in self._windows:
            if self._owned(hwnd):
                for kind, handle in self._icons.items():
                    if self._api.SendMessageW(hwnd, 0x7F, kind, 0) == handle:
                        self._api.SendMessageW(hwnd, 0x80, kind, 0)
        self._windows.clear()
        # Never destroy the class icons owned by Tk or another component.
        for handle in self._icons.values():
            self._api.DestroyIcon(handle)
        self._icons.clear()


def install(app, path):
    """Keep Tk's existing icon as fallback if Windows icon setup is unavailable."""
    if os.name != 'nt':
        return None
    previous = getattr(app, '_portalai_window_icons', None)
    if previous is not None:
        return previous
    try:
        icons = WindowIcons(app, path)
    except (OSError, RuntimeError):
        return None
    app._portalai_window_icons = icons
    return icons
