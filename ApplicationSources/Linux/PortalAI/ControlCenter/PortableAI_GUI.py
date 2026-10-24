# PORTALAI_V15_138O_CONTROLS_3X2_DEFAULT
# PORTALAI_V15_138N_UI_PERFORMANCE_FIX
# PORTALAI_V15_138M_DEFAULT_NAV_FIT_FIX
# PORTALAI_V15_138L_DEFAULT_SINGLE_ROW_NAV_FIX
# PORTALAI_V15_138K_COMPACT_COLLAPSED_HEIGHT_FIX
# PORTALAI_V15_138J_COMPACT_CHAT_RESTORE_ATTACH_WIDEN
# PORTALAI_V15_138I_COMPACT_DENSE_BRAND_FIX
# PORTALAI_V15_138H_COMPACT_EXPANDED_REFLOW_BRANDTEXT
# PORTALAI_V15_138G_COMPACT_LAYOUT_BRAND_NUDGE
# PORTALAI_V15_138F_HERO_ALPHA_HOVER_ATTACH
# PORTALAI_V15_138E_HERO_CONTEXT_ATTACH_FIX
# PORTALAI_V15_138D_WELCOME_BRIGHTNESS_ALIGNMENT
# PORTALAI_V15_138C_UI_RESPONSIVENESS
# PORTALAI_V15_138B_VISUAL_LAYOUT_FIX
# PORTALAI_LAYOUT_HARDENING_v15_138
# PORTALAI_COMPACT_LAYOUT_v15_137B
# PORTALAI_BRAND_COMPACT_v15_137A
# PORTALAI_FRONTEND_INTERACTION_FIX_v15_136B
# PORTALAI_SMALLCAPS_WATERMARK_FIX_v15_136A
# PORTALAI_FRONTEND_REFRESH_v15_136
# PORTABLEAI_ORNATE_UI_v15_135
# PORTABLEAI_LIFECYCLE_UI_SYNC_v15_134c
# PORTABLEAI_LIFECYCLE_UI_SYNC_v15_134a
# PORTABLEAI_QWEN_BASELINE_RESTORE_v15_133
# PORTABLEAI_STARTUP_WIRING_v15_132B
# PORTABLEAI_LIFECYCLE_REBUILD_v15_132
# PORTABLEAI_START_TRAY_TRANSPARENT_v15_131B
# PORTABLEAI_STARTUP_RECOVERY_v15_131A
# PORTABLEAI_SCIENCE_CAPABILITY_SYNC_v15_130
# PORTABLEAI_INSTALLED_CAPABILITY_SYNC_v15_128E
# PORTABLEAI_QWEN_THEME_CLEANUP_v15_125
# PORTABLEAI_RESPONSIVE_UI_v15_123B
# PORTABLEAI_ELEGANT_NATIVE_UI_v15_120
# PORTABLEAI_RUNTIME_RESTORE_v15_119A
# PORTABLEAI_INTERACTION_RECOVERY_v15_118
# PORTABLEAI_EVENT_LOOP_v15_117
from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
# PORTABLEAI_ELEGANT_TECH_UI_v15_112
from elegant_ui import (
    RoundedButton, apply_root_typography,
    display_font, ui_font, mono_font,
)
from pathlib import Path
from portable_runtime import bootstrap_python
from runtime_health import qwen_health
from tkinter.scrolledtext import ScrolledText
from urllib.parse import urlparse
import webbrowser
from elegant_native_ui import ElegantButton
from maintenance_cleanup import preview_cleanup, execute_cleanup
from ui_extensions import DocumentationPanel, ContextHelpManager, ResponsiveFlow, ResponsiveGrid, bind_responsive_wrap
from ornate_ui import (ConnectedBorder, FiligreeScrollbar, RoundedWindowController, WelcomeFiligree,
    heading_font as ornate_heading_font, nav_font as ornate_nav_font, install_separator, install_title_filigree,
    theme_native_scrollbars, work_area_geometry)
from portal_frontend_v15136 import (
    portal_display_font, portal_body_font, display_caps, rebrand_widget_tree,
    decorate_help_page, decorate_welcome_note, upgrade_vertical_scrollbars,
    apply_gold_scrollbar_palette, install_native_chat_frontend, close_native_chat_frontend,
    install_dynamic_tab_scaler, install_compact_mode,
    install_wordmark_label,
    install_responsive_nav_layout,
    install_responsive_controls,
)


def main(authenticated=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ns = ap.parse_args()
    root = Path(ns.root).resolve()

    # One Control Center per Windows logon session. Besides preventing accidental
    # duplicate controllers, this also makes any stale caption-only wrapper from an
    # older build easy to distinguish from a genuinely second running instance.
    from account_switch import SwitchTicket
    if authenticated is not None and (not isinstance(authenticated,SwitchTicket) or authenticated.root!=root):
        raise PermissionError('Invalid account handoff')
    single_instance_mutex = authenticated.instance_mutex if authenticated else None
    if os.name == "nt" and single_instance_mutex is None:
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            single_instance_mutex = kernel32.CreateMutexW(None, False, "Local\\Zhandragon.PortableAI.ControlCenter")
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                try:
                    hwnd = user32.FindWindowW(None, "PortalAI Control Center") or user32.FindWindowW(None, "PortableAI Control Center")
                    if hwnd:
                        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                except Exception:
                    pass
                return 0
        except Exception:
            single_instance_mutex = None

    sys.path.insert(0, str(root / "ControlCenter"))
    from portableai_common import (
        hidden_popen, hidden_run, http_json, http_text, parse_prom_metric,
        port_open, process_named, pythonw_executable, runtime_dir,
        iter_processes, process_command_line,
    )

    runtime = runtime_dir(root)
    event_q: queue.Queue = queue.Queue()
    force_scan = threading.Event()
    stop_worker = threading.Event()
    next_account = None

    LIGHT_COLORS = {
        # Warm ivory base + dark graphite shadowing + deeper metallic gold.
        "bg": "#EEE7DC",
        "panel": "#F8F3EA",
        "panel2": "#E9E0D2",
        "panel3": "#DED1BC",
        "card": "#FFFDF8",
        "card_hover": "#F7F0E5",
        "text": "#202224",
        "muted": "#625E59",
        "muted2": "#7C725F",
        "accent": "#3E91A2",
        "accent2": "#1F6F82",
        "good": "#2E8062",
        "warn": "#9D7027",
        "bad": "#A9514C",
        "button": "#E6DCCB",
        "button_hover": "#D9CBB3",
        "danger": "#7C403E",
        "danger_hover": "#66312F",
        "border": "#7B5A22",
        "gold_mid": "#A87D32",
        "gold_shine": "#D9BE78",
        "outline": "#343638",
        "border_soft": "#6E6E6B",
        "shadow": "#1E2022",
        "model_bg": "#F3ECE1",
    }

    DARK_COLORS = {
        # Dark mode intentionally inverts the ivory/graphite relationship while
        # preserving metallic gold and turquoise as the signature accents.
        "bg": "#111315",
        "panel": "#1C1E20",
        "panel2": "#252729",
        "panel3": "#302D27",
        "card": "#242628",
        "card_hover": "#2D3032",
        "text": "#F2ECE2",
        "muted": "#B7AFA4",
        "muted2": "#9D9282",
        "accent": "#58AFC1",
        "accent2": "#7CC4D3",
        "good": "#63B88E",
        "warn": "#C89B4A",
        "bad": "#D17770",
        "button": "#2A2D2F",
        "button_hover": "#363A3D",
        "danger": "#6C3534",
        "danger_hover": "#83423F",
        "border": "#806027",
        "gold_mid": "#B0863A",
        "gold_shine": "#D6BA70",
        "outline": "#070809",
        "border_soft": "#4B4E50",
        "shadow": "#000000",
        "model_bg": "#101214",
    }

    THEMES = {"light": LIGHT_COLORS, "dark": DARK_COLORS}
    theme_pref_path = runtime / "control_center_theme.json"
    theme_mode = "light"
    try:
        if theme_pref_path.exists():
            saved_theme = json.loads(theme_pref_path.read_text(encoding="utf-8"))
            if isinstance(saved_theme, dict) and saved_theme.get("theme") in THEMES:
                theme_mode = str(saved_theme["theme"])
    except Exception:
        pass
    COLORS = dict(THEMES[theme_mode])

    def ensure_windows_chrome(window: tk.Tk) -> None:
        """Compatibility stub for restore paths.

        v15.74 uses a custom PortableAI title bar and border on Windows instead of
        the default system chrome.  The function remains for safe call sites such as
        tray restore, but it does not reapply the standard white Windows frame.
        """
        return

    class WindowsTrayIcon:
        """Native Windows notification-area icon with no third-party dependency.

        The Win32 callback runs on its own message thread.  It never touches Tk
        directly; tray actions are placed onto the existing thread-safe event queue
        and executed by the Tk main thread in pump().
        """
        WM_TRAY = 0x8000 + 20
        WM_SHOW_ICON = 0x8000 + 21
        WM_HIDE_ICON = 0x8000 + 22
        WM_CLOSE_TRAY = 0x8000 + 23
        ID_RESTORE = 41001
        ID_STOP = 41002
        ID_EXIT = 41003
        ID_CHAT = 41004
        ID_NEW_CHAT = 41005
        ID_RUNTIME = 41006
        ID_INSTALLED = 41007
        ID_STARTUP = 41008
        ID_SYSTEM_TEST = 41009
        ID_REPORTS = 41010
        ID_THEME = 41011
        ID_HELP = 41012
        ID_SETTINGS = 41013
        ID_MAINTENANCE = 41014
        ID_ACTIVITY = 41015
        ID_MISSIONS = 41016
        ID_ACCOUNTS = 41017

        def __init__(self, root_path: Path, events: queue.Queue):
            self.root_path = root_path
            self.events = events
            self.hwnd = 0
            self._thread = None
            self._ready = threading.Event()
            self._state_changed = threading.Event()
            self._visible = False
            self._wndproc_ref = None

        def _post(self, message: int) -> bool:
            if os.name != "nt" or not self.hwnd:
                return False
            try:
                import ctypes
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW(ctypes.c_void_p(self.hwnd), message, 0, 0)
                return True
            except Exception:
                return False

        def start(self) -> bool:
            if os.name != "nt":
                return False
            if self._thread and self._thread.is_alive():
                return self._ready.wait(1.0)
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._message_loop,
                name="PortableAITray",
                daemon=True,
            )
            self._thread.start()
            return self._ready.wait(1.5) and bool(self.hwnd)

        def show(self) -> bool:
            if not self.start():
                return False
            self._state_changed.clear()
            if not self._post(self.WM_SHOW_ICON):
                return False
            # Do not hide the Tk window until Explorer confirms that the tray icon
            # was actually added; otherwise a Shell_NotifyIcon failure could make
            # the controller unreachable.
            self._state_changed.wait(1.0)
            return bool(self._visible)

        def hide(self) -> None:
            self._state_changed.clear()
            if self._post(self.WM_HIDE_ICON):
                self._state_changed.wait(0.5)

        def close(self) -> None:
            self._post(self.WM_CLOSE_TRAY)

        def _message_loop(self) -> None:
            if os.name != "nt":
                self._ready.set()
                return
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(
                LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_ubyte * 8),
                ]

            class NOTIFYICONDATAW(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.DWORD),
                    ("hWnd", wintypes.HWND),
                    ("uID", wintypes.UINT),
                    ("uFlags", wintypes.UINT),
                    ("uCallbackMessage", wintypes.UINT),
                    ("hIcon", wintypes.HANDLE),
                    ("szTip", wintypes.WCHAR * 128),
                    ("dwState", wintypes.DWORD),
                    ("dwStateMask", wintypes.DWORD),
                    ("szInfo", wintypes.WCHAR * 256),
                    ("uTimeoutOrVersion", wintypes.UINT),
                    ("szInfoTitle", wintypes.WCHAR * 64),
                    ("dwInfoFlags", wintypes.DWORD),
                    ("guidItem", GUID),
                    ("hBalloonIcon", wintypes.HANDLE),
                ]

            class WNDCLASSW(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HANDLE),
                    ("hCursor", wintypes.HANDLE),
                    ("hbrBackground", wintypes.HANDLE),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            # Explicit 64-bit-safe Win32 signatures.  Without these, ctypes may
            # assume a 32-bit integer return for HWND/HMENU/HICON values.
            kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
            user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
            user32.RegisterClassW.restype = wintypes.ATOM
            user32.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                wintypes.HWND, wintypes.HANDLE, wintypes.HINSTANCE, ctypes.c_void_p,
            ]
            user32.CreateWindowExW.restype = wintypes.HWND
            user32.DefWindowProcW.argtypes = [
                wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            ]
            user32.DefWindowProcW.restype = LRESULT
            user32.DestroyWindow.argtypes = [wintypes.HWND]
            user32.DestroyWindow.restype = wintypes.BOOL
            user32.PostQuitMessage.argtypes = [ctypes.c_int]
            user32.PostQuitMessage.restype = None
            user32.CreatePopupMenu.argtypes = []
            user32.CreatePopupMenu.restype = wintypes.HMENU
            user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
            user32.AppendMenuW.restype = wintypes.BOOL
            user32.DestroyMenu.argtypes = [wintypes.HMENU]
            user32.DestroyMenu.restype = wintypes.BOOL
            user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            user32.GetCursorPos.restype = wintypes.BOOL
            user32.SetForegroundWindow.argtypes = [wintypes.HWND]
            user32.SetForegroundWindow.restype = wintypes.BOOL
            user32.TrackPopupMenu.argtypes = [
                wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
            ]
            user32.TrackPopupMenu.restype = wintypes.UINT
            user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostMessageW.restype = wintypes.BOOL
            user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.LoadImageW.restype = wintypes.HANDLE
            user32.LoadIconW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
            user32.LoadIconW.restype = wintypes.HANDLE
            shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
            shell32.Shell_NotifyIconW.restype = wintypes.BOOL

            NIM_ADD, NIM_DELETE = 0x00000000, 0x00000002
            NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
            WM_DESTROY, WM_NULL = 0x0002, 0x0000
            WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0202, 0x0203
            WM_RBUTTONUP, WM_CONTEXTMENU = 0x0205, 0x007B
            TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
            MF_STRING, MF_SEPARATOR = 0x0000, 0x0800
            IMAGE_ICON = 1
            LR_LOADFROMFILE, LR_DEFAULTSIZE = 0x0010, 0x0040
            IDI_APPLICATION = 32512

            hinstance = kernel32.GetModuleHandleW(None)
            class_name = f"PortableAITrayWindow_{os.getpid()}"
            nid = NOTIFYICONDATAW()

            def load_icon():
                for candidate in (
                    self.root_path / "ControlCenter" / "PortableAI.ico",
                    self.root_path / "PortableAI.ico",
                    self.root_path / "portableai.ico",
                ):
                    if candidate.exists():
                        try:
                            h = user32.LoadImageW(
                                None, str(candidate), IMAGE_ICON, 0, 0,
                                LR_LOADFROMFILE | LR_DEFAULTSIZE,
                            )
                            if h:
                                return h
                        except Exception:
                            pass
                try:
                    return user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
                except Exception:
                    return None

            icon_handle = load_icon()

            def remove_icon():
                if nid.hWnd:
                    try:
                        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
                    except Exception:
                        pass
                self._visible = False
                self._state_changed.set()

            def add_icon(hwnd):
                if self._visible:
                    self._state_changed.set()
                    return
                nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
                nid.hWnd = hwnd
                nid.uID = 1
                nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
                nid.uCallbackMessage = self.WM_TRAY
                nid.hIcon = icon_handle
                nid.szTip = "PortalAI — Zhandragon"
                self._visible = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
                self._state_changed.set()

            def show_menu(hwnd):
                menu = user32.CreatePopupMenu()
                if not menu:
                    return
                try:
                    items = (
                        (self.ID_RESTORE, "Restore PortalAI"),
                        (self.ID_CHAT, "Open Chat"),
                        (self.ID_NEW_CHAT, "New Chat"),
                        (None, None),
                        (self.ID_ACCOUNTS, "Accounts"),
                        (self.ID_RUNTIME, "Models"),
                        (self.ID_INSTALLED, "Packages"),
                        (self.ID_SETTINGS, "Settings"),
                        (self.ID_MAINTENANCE, "Maintenance"),
                        (self.ID_ACTIVITY, "Runtime"),
                        (self.ID_MISSIONS, "Persistence"),
                        (self.ID_HELP, "Documentation / Help"),
                        (None, None),
                        (self.ID_STARTUP, "Startup"),
                        (self.ID_SYSTEM_TEST, "System Test"),
                        (self.ID_REPORTS, "Open Maintenance Reports"),
                        (self.ID_THEME, "Toggle Light / Dark"),
                        (None, None),
                        (self.ID_STOP, "Stop all components"),
                        (self.ID_EXIT, "Exit PortalAI"),
                    )
                    for ident, title in items:
                        if ident is None:
                            user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                        else:
                            user32.AppendMenuW(menu, MF_STRING, ident, title)
                    pt = wintypes.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    user32.SetForegroundWindow(hwnd)
                    cmd = user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, hwnd, None)
                    action = {
                        self.ID_RESTORE: "restore",
                        self.ID_CHAT: "chat",
                        self.ID_NEW_CHAT: "new_chat",
                        self.ID_RUNTIME: "runtime",
                        self.ID_INSTALLED: "installed",
                        self.ID_SETTINGS: "settings",
                        self.ID_MAINTENANCE: "maintenance",
                        self.ID_ACCOUNTS: "accounts",
                        self.ID_ACTIVITY: "activity",
                        self.ID_MISSIONS: "missions",
                        self.ID_HELP: "help",
                        self.ID_STARTUP: "startup",
                        self.ID_SYSTEM_TEST: "system_test",
                        self.ID_REPORTS: "reports",
                        self.ID_THEME: "theme",
                        self.ID_STOP: "stop",
                        self.ID_EXIT: "exit",
                    }.get(cmd)
                    if action:
                        self.events.put(("tray_action", action))
                    user32.PostMessageW(hwnd, WM_NULL, 0, 0)
                finally:
                    user32.DestroyMenu(menu)

            @WNDPROC
            def wndproc(hwnd, msg, wparam, lparam):
                if msg == self.WM_SHOW_ICON:
                    add_icon(hwnd)
                    return 0
                if msg == self.WM_HIDE_ICON:
                    remove_icon()
                    return 0
                if msg == self.WM_CLOSE_TRAY:
                    remove_icon()
                    user32.DestroyWindow(hwnd)
                    return 0
                if msg == self.WM_TRAY:
                    # PORTABLEAI_TRAY_CLICK_ROUTING_v15_134E
                    event = int(lparam) & 0xFFFF
                    # A normal left click is deliberately boring: it only restores
                    # the Control Center. It never opens a menu.
                    if event == WM_LBUTTONUP:
                        self.events.put(("tray_action", "restore"))
                        return 0
                    # Right click asks the Tk/UI thread to draw the same themed
                    # borderless menu used inside the launcher. This avoids the
                    # unthemeable native TrackPopupMenu visual mismatch.
                    if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                        pt = wintypes.POINT()
                        if user32.GetCursorPos(ctypes.byref(pt)):
                            self.events.put(("tray_context", {"x": int(pt.x), "y": int(pt.y)}))
                        else:
                            self.events.put(("tray_context", None))
                        return 0
                    if event == WM_LBUTTONDBLCLK:
                        self.events.put(("tray_action", "restore"))
                        return 0
                if msg == WM_DESTROY:
                    remove_icon()
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            self._wndproc_ref = wndproc
            wc = WNDCLASSW()
            wc.lpfnWndProc = wndproc
            wc.hInstance = hinstance
            wc.lpszClassName = class_name
            atom = user32.RegisterClassW(ctypes.byref(wc))
            if not atom:
                self._ready.set()
                return

            hwnd = user32.CreateWindowExW(
                0, class_name, class_name, 0,
                0, 0, 0, 0,
                None, None, hinstance, None,
            )
            if not hwnd:
                self._ready.set()
                return
            self.hwnd = int(hwnd)
            self._ready.set()

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            self.hwnd = 0
            self._visible = False


    app = tk.Tk()
    from writer_jobs import WriterJobs
    gui_jobs = WriterJobs()
    account_gate = None
    sys.path.insert(0, str(root / "Agent"))
    from profile_paths import enabled as accounts_enabled, private_path
    from local_accounts import LocalAccounts

    # PORTABLEAI_BRAND_IDENTITY_v15_131
    # Approved PortableAI emblem assets. All PNG variants are pre-rendered so
    # the Control Center gains no Pillow/runtime dependency.
    brand_dir = root / "ControlCenter" / "Branding"

    def _brand_photo(filename: str):
        path = brand_dir / filename
        if not path.exists():
            return None
        try:
            return tk.PhotoImage(master=app, file=str(path))
        except Exception:
            return None

    brand_images = {
        "titlebar": _brand_photo("PortableAI_Titlebar_28.png"),
        "header": _brand_photo("PortableAI_Header_72.png"),
        "hero512": _brand_photo("PortableAI_Welcome_512.png"),
        "hero420": _brand_photo("PortableAI_Welcome_420.png"),
        "hero320": _brand_photo("PortableAI_Welcome_320.png"),
        "hero240": _brand_photo("PortableAI_Welcome_240.png"),
        "hero160": _brand_photo("PortableAI_Welcome_160.png"),
    }
    # Keep PhotoImage objects alive for the lifetime of the Tk interpreter.
    # PORTABLEAI_TAB_BRAND_ASSETS_v15_134D
    brand_images.update({
        "tabcorner176": _brand_photo("PortableAI_TabCorner_176.png"),
        "tabcorner128": _brand_photo("PortableAI_TabCorner_128.png"),
        "chatwm_light196": _brand_photo("PortableAI_ChatWatermark_Light_196.png"),
        "chatwm_light144": _brand_photo("PortableAI_ChatWatermark_Light_144.png"),
        "chatwm_dark196": _brand_photo("PortableAI_ChatWatermark_Dark_196.png"),
        "chatwm_dark144": _brand_photo("PortableAI_ChatWatermark_Dark_144.png"),
    })
    app._portableai_brand_images = brand_images

    # PORTABLEAI_TAB_BRAND_ASSET_SYNC_v15_135
    for _bk,_bf in (
        ("tabcorner176","PortableAI_TabCorner_176.png"),("tabcorner128","PortableAI_TabCorner_128.png"),
        ("chatwm_light196","PortableAI_ChatWatermark_Light_196.png"),("chatwm_light144","PortableAI_ChatWatermark_Light_144.png"),
        ("chatwm_dark196","PortableAI_ChatWatermark_Dark_196.png"),("chatwm_dark144","PortableAI_ChatWatermark_Dark_144.png"),
    ):
        if not brand_images.get(_bk): brand_images[_bk]=_brand_photo(_bf)
    app._portableai_brand_images = brand_images

    apply_root_typography(app)
    app.title("PortalAI Control Center")
    portable_icon_path = root / "ControlCenter" / "PortableAI.ico"
    if os.name == "nt" and portable_icon_path.exists():
        try:
            app.iconbitmap(default=str(portable_icon_path))
        except Exception:
            pass
    from window_icons import install as install_window_icons
    install_window_icons(app, portable_icon_path)
    app.configure(bg=COLORS["bg"])
    app.minsize(500, 400)
    app.resizable(True, True)
    sw, sh = app.winfo_screenwidth(), app.winfo_screenheight()
    w = min(1260, max(860, int(sw * 0.76)))
    h = min(820, max(620, int(sh * 0.76)))
    app.geometry(f"{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//2)}")
    use_custom_chrome = (os.name == "nt")
    if use_custom_chrome:
        try:
            app.overrideredirect(True)
        except Exception:
            use_custom_chrome = False

    window_shell = tk.Frame(
        app, bg=COLORS["shadow"],
        highlightthickness=0,
    )
    window_shell.pack(fill="both", expand=True, padx=4, pady=4)
    # PORTABLEAI_WINDOW_FILIGREE_v15_135
    window_ornament = ConnectedBorder(window_shell, COLORS, radius=21, outline_key="gold_mid", shine=True, filigree=True, erase_corners=False, inset=1)

    titlebar = tk.Frame(
        window_shell, bg=COLORS["panel3"], height=40,
        highlightthickness=0,
    )
    titlebar.pack(fill="x", padx=2, pady=(2, 0))
    # PORTABLEAI_TITLE_FILIGREE_v15_135
    title_filigree = install_title_filigree(window_shell, COLORS)
    titlebar.pack_propagate(False)
    titlebar_left = tk.Frame(titlebar, bg=COLORS["panel3"])
    titlebar_left.pack(side="left", fill="both", expand=True, padx=(10, 0))
    titlebar_right = tk.Frame(titlebar, bg=COLORS["panel3"])
    titlebar_right.pack(side="right", padx=(0, 6), pady=4)

    # PORTABLEAI_BRAND_IDENTITY_v15_131_TITLEBAR
    if brand_images.get("titlebar") is not None:
        titlebar_gem = tk.Label(
            titlebar_left, image=brand_images["titlebar"], bg=COLORS["panel3"],
            bd=0, highlightthickness=0, padx=0, pady=0,
        )
        titlebar_gem.pack(side="left", pady=5)
        titlebar_gem._portableai_brand_image = brand_images["titlebar"]
        titlebar_gem_items = None
    else:
        # Fail-safe fallback if branding assets are ever missing.
        titlebar_gem = tk.Canvas(titlebar_left, width=22, height=22, bg=COLORS["panel3"], highlightthickness=0, bd=0)
        titlebar_gem.pack(side="left", pady=0, anchor="center")
        titlebar_gem_items = {
            "outer": titlebar_gem.create_oval(2, 2, 20, 20, outline=COLORS["gold_mid"], width=2),
            "inner": titlebar_gem.create_oval(6, 6, 16, 16, outline=COLORS["accent"], width=2),
            "v": titlebar_gem.create_line(11, 1, 11, 21, fill=COLORS["gold_shine"], width=1),
            "h": titlebar_gem.create_line(1, 11, 21, 11, fill=COLORS["border"], width=1),
        }
    titlebar_text = tk.Label(
        titlebar_left, text=f"{display_caps('PortalAI')}  ·  {display_caps('Control Center')}",
        bg=COLORS["panel3"], fg=COLORS["text"],
        font=(portal_display_font(titlebar_left), 10, "bold"), anchor="w",
    )
    titlebar_text.pack(side="left", padx=(8, 0), fill="y")

    install_wordmark_label(titlebar_text, root, "banner", COLORS)
    chrome_buttons = {}
    def _chrome_button(parent, text, role="normal"):
        bg = COLORS["danger"] if role == "close" else COLORS["button"]
        fg = "#ffffff" if role == "close" else COLORS["text"]
        b = ElegantButton(
            parent, text=text, command=lambda: None,
            bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
            relief="flat", bd=0, padx=0, pady=0, width=4,
            font=("Segoe UI Variable Text", 10, "bold"),
            cursor="hand2", highlightthickness=1, highlightbackground=COLORS["border"],
        )
        b._portableai_role = role
        b.pack(side="left", padx=3, ipady=2)
        return b

    from donation_panel import DonationLink
    donate_link = DonationLink(titlebar_right, COLORS)
    donate_link.pack(side="left", padx=(0, 10), pady=(12, 0), anchor="center")

    chrome_buttons["minimize"] = _chrome_button(titlebar_right, "—")
    chrome_buttons["maximize"] = _chrome_button(titlebar_right, "▢")
    chrome_buttons["tray"] = _chrome_button(titlebar_right, "◫")
    chrome_buttons["close"] = _chrome_button(titlebar_right, "✕", role="close")

    drag_state = {"x": 0, "y": 0, "win_x": 0, "win_y": 0}
    window_state = {"maximized": False, "restore": app.geometry()}
    rounding_controller = None
    resize_state = {"active": False}

    def _remember_restore_geometry():
        if not window_state["maximized"]:
            try:
                window_state["restore"] = app.geometry()
            except Exception:
                pass

    def _begin_move(event):
        if window_state["maximized"]:
            return "break"
        drag_state["x"] = event.x_root
        drag_state["y"] = event.y_root
        drag_state["win_x"] = app.winfo_x()
        drag_state["win_y"] = app.winfo_y()
        return "break"

    def _do_move(event):
        if window_state["maximized"]:
            return "break"
        dx = event.x_root - drag_state["x"]
        dy = event.y_root - drag_state["y"]
        app.geometry(f"+{drag_state['win_x'] + dx}+{drag_state['win_y'] + dy}")
        return "break"

    def _bind_drag(widget):
        widget.bind("<ButtonPress-1>", _begin_move, add="+")
        widget.bind("<B1-Motion>", _do_move, add="+")

    for _drag_widget in (titlebar, titlebar_left, titlebar_text, titlebar_gem):
        _bind_drag(_drag_widget)

    def _toggle_maximize_custom(_event=None):
        try:
            if not window_state["maximized"]:
                _remember_restore_geometry()
                x, y, ww, hh = work_area_geometry(_custom_hwnd(), app)
                app.geometry(f"{ww}x{hh}+{x}+{y}")
                window_state["maximized"] = True
            else:
                app.geometry(window_state["restore"])
                window_state["maximized"] = False
            try:
                chrome_buttons["maximize"].configure(text=("❐" if window_state["maximized"] else "▢"))
            except Exception:
                pass
            try:
                if rounding_controller is not None:
                    app.after(20, rounding_controller.refresh)
            except Exception:
                pass
        except Exception:
            pass
        return "break"

    titlebar.bind("<Double-Button-1>", _toggle_maximize_custom, add="+")
    titlebar_text.bind("<Double-Button-1>", _toggle_maximize_custom, add="+")

    def _custom_hwnd():
        if os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes
            app.update_idletasks()
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            child = wintypes.HWND(int(app.winfo_id()))
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            return user32.GetParent(child) or child
        except Exception:
            return None

    def _ensure_custom_taskbar_style():
        """Give the borderless Tk wrapper a taskbar identity without adding a caption.

        Older builds called ensure_windows_chrome() on an overrideredirect window,
        which could manufacture tiny caption-only wrapper windows after minimize/
        restore cycles. Keep custom chrome custom: only adjust EXSTYLE here.
        """
        if not use_custom_chrome or os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = _custom_hwnd()
            if not hwnd:
                return
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            GWL_EXSTYLE = -20
            WS_EX_APPWINDOW = 0x00040000
            WS_EX_TOOLWINDOW = 0x00000080
            get_long = user32.GetWindowLongW
            set_long = user32.SetWindowLongW
            get_long.argtypes = [wintypes.HWND, ctypes.c_int]
            get_long.restype = ctypes.c_long
            set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            set_long.restype = ctypes.c_long
            exstyle = int(get_long(hwnd, GWL_EXSTYLE))
            set_long(hwnd, GWL_EXSTYLE, (exstyle | WS_EX_APPWINDOW) & ~WS_EX_TOOLWINDOW)
        except Exception:
            pass

    # PORTABLEAI_ROUNDED_WINDOW_v15_135
    rounding_controller = RoundedWindowController(app, _custom_hwnd, lambda: window_state["maximized"], radius=18)

    def _iconify_custom():
        try:
            if not use_custom_chrome:
                app.iconify()
                return True
            # Do not toggle overrideredirect(False/True). Tk can leave behind a
            # caption-only wrapper each time that transition races with iconify.
            # Minimize the existing native wrapper through its message pump.
            import ctypes
            hwnd = _custom_hwnd()
            if hwnd:
                _ensure_custom_taskbar_style()
                from ctypes import wintypes
                user32 = ctypes.WinDLL("user32", use_last_error=True)
                user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
                user32.PostMessageW.restype = wintypes.BOOL
                # Queue the normal Windows minimize command. Synchronous
                # ShowWindow re-enters Tk through the Explorer drop subclass
                # outside Tcl's event loop, aborting Python's thread state.
                # The queued message runs on Tk's own native message pump.
                if not user32.PostMessageW(hwnd, 0x0112, 0xF020, 0):  # WM_SYSCOMMAND / SC_MINIMIZE
                    raise ctypes.WinError(ctypes.get_last_error())
            else:
                raise RuntimeError('The PortalAI window is not ready to minimize.')
            return True
        except Exception as exc:
            # Keep the window reachable; never recurse between tray and taskbar
            # fallbacks if Explorer or the native window is unavailable.
            if getattr(app, '_portalai_main_ready', False):
                log(f'Could not minimize PortalAI: {exc}')
            return False

    def _make_resize_handler(direction):
        scheduled = {"after_id": None, "pending": None}

        def _apply_pending():
            scheduled["after_id"] = None
            pending = scheduled.get("pending")
            if not pending or not resize_state.get("active") or window_state["maximized"]:
                return
            ex, ey = pending
            dx = ex - resize_state["x"]
            dy = ey - resize_state["y"]
            x, y = resize_state["win_x"], resize_state["win_y"]
            w0, h0 = resize_state["w"], resize_state["h"]
            minw, minh = 500, 400
            new_x, new_y, new_w, new_h = x, y, w0, h0
            if "e" in direction:
                new_w = max(minw, w0 + dx)
            if "s" in direction:
                new_h = max(minh, h0 + dy)
            if "w" in direction:
                new_w = max(minw, w0 - dx)
                new_x = x + (w0 - new_w)
            if "n" in direction:
                new_h = max(minh, h0 - dy)
                new_y = y + (h0 - new_h)
            app.geometry(f"{int(new_w)}x{int(new_h)}+{int(new_x)}+{int(new_y)}")

        def _start(event):
            resize_state.update({
                "active": True,
                "dir": direction,
                "x": event.x_root,
                "y": event.y_root,
                "win_x": app.winfo_x(),
                "win_y": app.winfo_y(),
                "w": app.winfo_width(),
                "h": app.winfo_height(),
            })
            _remember_restore_geometry()
            return "break"

        def _drag(event):
            if not resize_state.get("active") or window_state["maximized"]:
                return "break"
            scheduled["pending"] = (event.x_root, event.y_root)
            if scheduled["after_id"] is None:
                # ~30 fps max. Coalesces high-frequency mouse motion events.
                scheduled["after_id"] = app.after(32, _apply_pending)
            return "break"

        def _stop(event):
            if scheduled["after_id"] is not None:
                try:
                    app.after_cancel(scheduled["after_id"])
                except Exception:
                    pass
                scheduled["after_id"] = None
            scheduled["pending"] = (event.x_root, event.y_root)
            _apply_pending()
            scheduled["pending"] = None
            resize_state["active"] = False
            callback = getattr(app, '_portalai_relayout', None)
            if callable(callback): callback(force=True)
            return "break"

        return _start, _drag, _stop

    _resize_cursor = {
        "n": "size_ns" if os.name == "nt" else "sb_v_double_arrow",
        "s": "size_ns" if os.name == "nt" else "sb_v_double_arrow",
        "w": "size_we" if os.name == "nt" else "sb_h_double_arrow",
        "e": "size_we" if os.name == "nt" else "sb_h_double_arrow",
        "nw": "size_nw_se" if os.name == "nt" else "top_left_corner",
        "se": "size_nw_se" if os.name == "nt" else "bottom_right_corner",
        "ne": "size_ne_sw" if os.name == "nt" else "top_right_corner",
        "sw": "size_ne_sw" if os.name == "nt" else "bottom_left_corner",
    }
    _resize_specs = {
        # Use native diagonal/edge resize cursors on Windows while retaining
        # portable Tk/X11 equivalents for development smoke tests.
        "n":  dict(relx=0.0, rely=0.0, relwidth=1.0, height=8, anchor="nw", cursor=_resize_cursor["n"]),
        "s":  dict(relx=0.0, rely=1.0, relwidth=1.0, height=8, anchor="sw", cursor=_resize_cursor["s"]),
        "w":  dict(relx=0.0, rely=0.0, relheight=1.0, width=8, anchor="nw", cursor=_resize_cursor["w"]),
        "e":  dict(relx=1.0, rely=0.0, relheight=1.0, width=8, anchor="ne", cursor=_resize_cursor["e"]),
        "nw": dict(relx=0.0, rely=0.0, width=10, height=10, anchor="nw", cursor=_resize_cursor["nw"]),
        "ne": dict(relx=1.0, rely=0.0, width=10, height=10, anchor="ne", cursor=_resize_cursor["ne"]),
        "sw": dict(relx=0.0, rely=1.0, width=10, height=10, anchor="sw", cursor=_resize_cursor["sw"]),
        "se": dict(relx=1.0, rely=1.0, width=10, height=10, anchor="se", cursor=_resize_cursor["se"]),
    }
    resize_grips = []
    for _dir, _place in _resize_specs.items():
        opts = dict(_place)
        cursor = opts.pop("cursor")
        grip = tk.Frame(window_shell, bg=COLORS["shadow"], cursor=cursor)
        grip.place(**opts)
        _s, _d, _u = _make_resize_handler(_dir)
        grip.bind("<ButtonPress-1>", _s, add="+")
        grip.bind("<B1-Motion>", _d, add="+")
        grip.bind("<ButtonRelease-1>", _u, add="+")
        resize_grips.append(grip)

    _grip_raise_pending = {"id": None}
    def _raise_resize_grips(_event=None):
        _grip_raise_pending["id"] = None
        for g in resize_grips:
            try: g.lift()
            except Exception: pass

    def _schedule_raise_resize_grips(_event=None):
        # Nested transcript cards cannot cover shell-level resize grips. Raising
        # all eight native windows whenever a card scrolls into view forces a
        # whole-window repaint on Windows.
        if (_event is not None and _event.widget not in (app, window_shell)
                and getattr(_event.widget, 'master', None) is not window_shell):
            return
        if _grip_raise_pending["id"] is None:
            try:
                _grip_raise_pending["id"] = app.after_idle(_raise_resize_grips)
            except Exception:
                pass

    # Content scrollbars/tabs are created after the grips. Keep the hit targets
    # above them so east-edge and diagonal corner resizing remain reachable.
    app.bind("<Map>", _schedule_raise_resize_grips, add="+")
    window_shell.bind("<Configure>", _schedule_raise_resize_grips, add="+")

    # v15.92: the main window is tabbed, so the old whole-window scroll canvas is
    # unnecessary. Each information-heavy tab owns its own scrollbar; the Chat tab
    # gets the full available viewport. This is what allows a much smaller window.
    outer = tk.Frame(window_shell, bg=COLORS["bg"])
    outer.pack(fill="both", expand=True, padx=2, pady=(0, 2))
    body = tk.Frame(outer, bg=COLORS["bg"])
    body.pack(fill="both", expand=True)
    canvas = None
    scroll = None

    # Build only the public, permanent launcher shell before authentication.
    # The same Tk and native wrapper keep their chrome/geometry through login.
    app._portalai_shell_ready = True
    app._portalai_login_host = body
    app._portalai_account_root = root
    app._portalai_main_ready = False
    app._portalai_chrome_widget = titlebar
    from public_welcome import build_public_welcome
    public_welcome = build_public_welcome(body, root, COLORS)
    app.update_idletasks()
    def _startup_close():
        dialogs = [d for d in getattr(app, '_portalai_account_dialogs', ()) if not d.closed]
        if dialogs: dialogs[-1].surface.on_close()
        elif account_gate is None or account_gate.session is None: app.destroy()
    app.protocol('WM_DELETE_WINDOW', _startup_close)
    chrome_buttons['close'].configure(command=lambda:app.tk.call(app.protocol('WM_DELETE_WINDOW')))
    chrome_buttons['minimize'].configure(command=_iconify_custom)
    chrome_buttons['maximize'].configure(command=_toggle_maximize_custom)
    # Pre-login has no private tray/status worker. Keep a reachable taskbar
    # minimize action on this chrome control until the authenticated tray exists.
    chrome_buttons['tray'].configure(command=_iconify_custom, state='normal')
    _ensure_custom_taskbar_style()
    # Windows delivers the borderless wrapper's first Configure/Map through
    # the event queue. Lay out this public-only page before freezing it for
    # login; update_idletasks alone can leave its child frames at 1x1.
    app.update()
    try:
        if not app.winfo_exists(): return 1
    except tk.TclError:
        return 1
    # Optional public input adapter also serves the real sign-in sheet. It does
    # not open profiles, start models, or change the account gate.
    from remote_desktop_input import install as install_remote_desktop_input
    try:
        remote_desktop_input = install_remote_desktop_input(app, root)
    except (OSError, ValueError, RuntimeError):
        # Optional remote control must not prevent normal local recovery/login.
        remote_desktop_input = None
    # Every installation must pass setup/login/recovery before private consumers.
    # Legacy files without a registry must never silently disable Accounts.
    from account_gate import GUIAccountGate
    if authenticated is not None and authenticated.geometry:app.geometry(authenticated.geometry)
    account_gate = GUIAccountGate(app, root, COLORS, authenticated=authenticated)
    if not account_gate.login():
        app.destroy()
        if single_instance_mutex is not None:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(single_instance_mutex))
        return 0  # Closing sign-in/setup is a normal unauthenticated exit.
    public_welcome.destroy()
    tray = WindowsTrayIcon(root, event_q)

    def label(parent, text="", size=10, fg=None, bold=False, **kw):
        family = portal_display_font(parent) if bold and size >= 11 else ui_font(parent)
        return tk.Label(
            parent, text=text, bg=parent.cget("bg"), fg=fg or COLORS["text"],
            font=(family, size, "bold" if bold else "normal"),
            anchor="w", **kw,
        )

    # v15.76: lightweight "soft frame" decoration.
    # The previous implementation created four Canvas widgets per rounded element
    # and redrew arcs on every <Configure>. With dozens of cards/rows that caused
    # resize lag and clipped/corrupted-looking corners. This version uses only
    # ordinary Tk widgets with relative placement; Tk moves/resizes them natively.
    soft_decorations = []

    def _decorate_soft_frame(widget, *, corner_size=14, outline_key="gold_mid", shine=True):
        # v15.135 replaces four disconnected glyph corners + line widgets with one
        # coherent Canvas border.  The canvas is lowered beneath child controls and
        # visually cuts away the Frame's square corners using the parent's surface.
        deco = ConnectedBorder(
            widget, COLORS, radius=corner_size, outline_key=outline_key,
            shine=shine, filigree=True, erase_corners=True,
        )
        soft_decorations.append(deco)
        return deco

    def _refresh_soft_decorations():
        for deco in list(soft_decorations):
            try:
                deco.apply_palette(COLORS)
            except Exception:
                pass

    def panel(parent, title_text, subtitle=None):
        shell = tk.Frame(parent, bg=COLORS["panel"], bd=0, highlightthickness=0)
        title_row = ResponsiveFlow(shell, bg=COLORS["panel"], hgap=11, vgap=4)
        title_row.pack(fill="x", padx=16, pady=(13, 5))
        title_row.add(label(title_row, title_text, 12, bold=True))
        if subtitle:
            subtitle_label=label(title_row, subtitle, 8, fg=COLORS["muted"], justify='left')
            title_row.add(subtitle_label);bind_responsive_wrap(subtitle_label,padding=8,minimum=120)
        # A restrained filigree separator now replaces the old stack of unrelated
        # top-edge frames.  The perimeter itself is one continuous rounded border.
        sep = install_separator(shell, COLORS, height=7)
        sep._portableai_ornate_separator = True
        _decorate_soft_frame(shell, corner_size=16, outline_key="gold_mid", shine=True)
        return shell

    readonly_scrollbars = []
    rounded_readouts = []
    from rounded_text import RoundedText
    def readonly_box(parent, height=5):
        box=RoundedText(parent,palette=COLORS,scrollbars=True,height=height,bg=COLORS['model_bg'],
                        fg=COLORS['text'],font=(mono_font(app),8),wrap='none',padx=3,pady=2,state='disabled')
        rounded_readouts.append(box)
        return box

    def compact_model_box(parent,width=38,height=3):
        # The service card already provides its rounded boundary. A plain,
        # selectable readout avoids nine nested frames and their vertical padding.
        return tk.Text(parent,width=width,height=height,bg=parent.cget('bg'),
                       fg=COLORS['accent2'],font=(mono_font(app),8),wrap='word',
                       padx=0,pady=0,bd=0,highlightthickness=0,state='disabled')

    def set_box_text(box, text):
        box.configure(state="normal")
        current = box.get("1.0", "end-1c")
        if current != text:
            box.delete("1.0", "end")
            box.insert("1.0", text)
        box.configure(state="disabled")

    # v15.92 moves branding/version/attribution off the persistent viewport and into Welcome.


    # ------------------------------------------------------------------
    # v15.92 compact tabbed Control Center
    # ------------------------------------------------------------------
    content = tk.Frame(body, bg=COLORS["bg"])
    content.pack(fill="both", expand=True, padx=8, pady=(4, 8))

    # Tabs stay as a single compact strip at the very top. Branding and attribution
    # live in Welcome so operational tabs spend almost the entire viewport on work.
    tabbar = tk.Frame(content, bg=COLORS["panel3"], highlightthickness=0)
    tabbar.pack(fill="x", pady=(0, 4))
    # PORTABLEAI_TABBAR_FILIGREE_v15_135
    tabbar_ornament = ConnectedBorder(tabbar, COLORS, radius=11, outline_key="gold_mid", shine=True, filigree=False)
    tabs_left = ResponsiveFlow(tabbar, bg=COLORS["panel3"], hgap=2, vgap=2)
    tabs_left.pack(side="left", fill="x", expand=True, padx=(5, 4), pady=5)
    tabs_right = tk.Frame(tabbar, bg=COLORS["panel3"])
    tabs_right.pack(side="right", padx=(4, 6), pady=5)

    tab_host = tk.Frame(content, bg=COLORS["bg"])
    app._portalai_account_host = tab_host
    tab_host.pack(fill="both", expand=True)

    tab_pages = {}
    tab_inners = {}
    tab_scroll_canvases = {}
    tab_buttons = {}
    selected_tab = {"key": "welcome"}

    def _make_tab_page(key, *, scrollable=True):
        page = tk.Frame(tab_host, bg=COLORS["bg"])
        tab_pages[key] = page
        if not scrollable:
            tab_inners[key] = page
            return page
        shell = tk.Frame(page, bg=COLORS["bg"])
        shell.pack(fill="both", expand=True)
        c = tk.Canvas(shell, bg=COLORS["bg"], highlightthickness=0, bd=0)
        sb = FiligreeScrollbar(shell, orient="vertical", command=c.yview, palette=COLORS, width=15)
        inner = tk.Frame(c, bg=COLORS["bg"])
        wid = c.create_window((0, 0), window=inner, anchor="nw")
        c.configure(yscrollcommand=sb.set)
        c.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(3, 0))
        from page_scroll import bind_page_scroll
        bind_page_scroll(c, inner, wid)
        tab_inners[key] = inner
        tab_scroll_canvases[key] = c
        return inner

    welcome_tab = _make_tab_page("welcome", scrollable=True)
    accounts_tab = _make_tab_page("accounts", scrollable=True)
    controls_tab = _make_tab_page("controls", scrollable=True)
    chat_tab = _make_tab_page("chat", scrollable=False)
    activity_tab = _make_tab_page("activity", scrollable=True)
    runtime_tab = _make_tab_page("runtime", scrollable=True)
    installed_tab = _make_tab_page("installed", scrollable=False)
    settings_tab = _make_tab_page("settings", scrollable=False)
    persistence_tab = _make_tab_page("persistence", scrollable=False)
    maintenance_tab = _make_tab_page("maintenance", scrollable=True)
    help_tab = _make_tab_page("help", scrollable=False)
    donation_tab = _make_tab_page("donation", scrollable=True)
    from donation_panel import DonationPanel, sponsor_button

    # PORTABLEAI_TAB_BRANDING_v15_134D
    # place() overlays never participate in pack/grid geometry, so these badges do
    # not change minimum sizes, scroll regions, or resize behavior.
    brand_corner_badges = []

    def _install_brand_corner_badge(page):
        badge = tk.Label(page, bg=COLORS["bg"], bd=0, highlightthickness=0, padx=0, pady=0)
        badge._portableai_brand_overlay = True
        badge._portableai_brand_image = None
        brand_corner_badges.append(badge)

        def _layout(_event=None):
            try:
                w=max(1,page.winfo_width()); h=max(1,page.winfo_height())
                if w < 520 or h < 330:
                    badge.place_forget(); return
                key = "tabcorner176" if w >= 860 and h >= 560 else "tabcorner128"
                img = brand_images.get(key)
                if img is None:
                    badge.place_forget(); return
                badge.configure(image=img, bg=COLORS["bg"])
                badge._portableai_brand_image = img
                margin = 24 if key == "tabcorner176" else 16
                badge.place(relx=1.0, rely=1.0, x=-margin, y=-margin, anchor="se")
                badge.lift()
            except Exception:
                pass

        page.bind("<Configure>", _layout, add="+")
        badge.bind("<MouseWheel>", _tab_mousewheel if "_tab_mousewheel" in locals() else (lambda _e: None), add="+")
        app.after_idle(_layout)
        return badge

    help_tab._portalai_page_watermark = True
    from page_watermark import PageWatermark
    page_watermark = PageWatermark(app,
        {key: tab_pages[key] for key in ('accounts','controls','persistence','activity','runtime','installed','settings','maintenance','help')},
        brand_images, lambda: theme_mode, lambda: selected_tab['key'])

    # Welcome owns the large identity board that used to consume space on every tab.
    welcome_shell = tk.Frame(welcome_tab, bg=COLORS["bg"])
    welcome_shell.pack(fill="both", expand=True, padx=18, pady=14)
    header = tk.Frame(welcome_shell, bg=COLORS["bg"])
    header.pack(fill="x", padx=12, pady=(18, 8))
    header_left = tk.Frame(header, bg=COLORS["bg"])
    header_left.pack(side="left", fill="x", expand=True)
    portal_welcome_wordmark = label(header_left, "Portal AI", 26, bold=True)
    install_wordmark_label(portal_welcome_wordmark, root, "welcome", COLORS)
    portal_welcome_wordmark.pack(fill="x")
    label(header_left, display_caps("Control Center"), 11, fg=COLORS["muted"]).pack(fill="x", pady=(0, 5))
    label(
        header_left,
        "Portal AI distribution designed and implemented by Zhandragon",
        10, fg=COLORS["accent"],
    ).pack(fill="x", pady=(3, 0))
    label(header_left, str(root), 8, fg=COLORS["muted"]).pack(fill="x", pady=(5, 0))

    deco = tk.Frame(header, bg=COLORS["bg"])
    deco.pack(side="right", anchor="ne", padx=(18, 0))
    # PORTABLEAI_BRAND_IDENTITY_v15_131_WELCOME_HEADER
    if brand_images.get("header") is not None:
        gem = tk.Label(
            deco, image=brand_images["header"], bg=COLORS["bg"],
            bd=0, highlightthickness=0, padx=0, pady=0,
        )
        gem.pack(anchor="e")
        gem._portableai_brand_image = brand_images["header"]
        gem_items = None
    else:
        gem = tk.Canvas(deco, width=170, height=56, bg=COLORS["bg"], highlightthickness=0, bd=0)
        gem.pack(anchor="e")
        gem_items = {
            "shadow_arc": gem.create_arc(12, 10, 142, 78, start=210, extent=120, style="arc", outline=COLORS["shadow"], width=4),
            "gold_arc": gem.create_arc(12, 8, 142, 76, start=210, extent=120, style="arc", outline=COLORS["border"], width=3),
            "shine_arc": gem.create_arc(14, 7, 140, 73, start=214, extent=112, style="arc", outline=COLORS["gold_shine"], width=1),
            "gem_outer": gem.create_oval(68, 12, 94, 38, outline=COLORS["gold_mid"], width=3),
            "gem_inner": gem.create_oval(73, 17, 89, 33, outline=COLORS["accent"], width=2),
            "ray_v": gem.create_line(81, 3, 81, 46, fill=COLORS["gold_shine"], width=2),
            "ray_h": gem.create_line(57, 25, 105, 25, fill=COLORS["border"], width=2),
        }
    version_lbl = label(deco, "Portal\u2009AI Control Center v15.138o", 9, fg=COLORS["muted"])
    version_lbl.pack(anchor="e", pady=(0, 3))

    welcome_note = tk.Frame(welcome_shell, bg=COLORS["panel"], highlightthickness=0)
    welcome_note.pack(fill="x", padx=12, pady=(16, 0))
    # PORTABLEAI_WELCOME_NOTE_BORDER_v15_135
    welcome_note_border = ConnectedBorder(welcome_note, COLORS, radius=17, outline_key="gold_mid", shine=True, filigree=True)
    # PORTALAI_WELCOME_NOTE_FILIGREE_v15_136
    label(welcome_note, display_caps("Welcome to Portal AI"), 13, bold=True).pack(fill="x", padx=16, pady=(14, 3))
    welcome_note_sep = install_separator(welcome_note, COLORS, height=8)
    label(
        welcome_note,
        "PortalAI Native Chat is the primary frontend. Use the tabs above for lifecycle controls, chat, live activity/GPU telemetry, runtime state, installed capabilities, and generalized maintenance.",
        9, fg=COLORS["muted"], wraplength=900, justify="left",
    ).pack(fill="x", padx=14, pady=(0, 12))

    welcome_sponsor_button = sponsor_button(welcome_note, COLORS)
    welcome_sponsor_button.pack(anchor="w", padx=14, pady=(0,12))

    # PORTABLEAI_BRAND_IDENTITY_v15_131_HERO
    # The Welcome tab deliberately gives the emblem the remaining vertical space.
    # Multiple pre-rendered sizes keep resizing sharp and dependency-free.
    brand_stage = tk.Frame(
        welcome_shell, bg=COLORS["bg"], highlightthickness=1,
        highlightbackground=COLORS["border"], bd=0,
    )
    brand_stage.pack(fill="both", expand=True, padx=12, pady=(12, 4))
    brand_feature = tk.Label(brand_stage, bg=COLORS["bg"], bd=0, highlightthickness=0)
    brand_feature.place(relx=0.5, rely=0.5, anchor="center")

    _brand_hero_choices = (
        (500, "hero512"),
        (405, "hero420"),
        (305, "hero320"),
        (225, "hero240"),
        (0, "hero160"),
    )
    _brand_hero_current = {"key": None}

    def _resize_welcome_brand(event=None):
        try:
            width = int(event.width if event is not None else brand_stage.winfo_width())
            height = int(event.height if event is not None else brand_stage.winfo_height())
            available = max(0, min(width - 24, height - 20))
            key = "hero160"
            for minimum, candidate in _brand_hero_choices:
                if available >= minimum and brand_images.get(candidate) is not None:
                    key = candidate
                    break
            image = brand_images.get(key)
            if image is None:
                image = next((brand_images.get(k) for _, k in reversed(_brand_hero_choices) if brand_images.get(k) is not None), None)
            if image is not None and _brand_hero_current.get("key") != key:
                brand_feature.configure(image=image)
                brand_feature._portableai_brand_image = image
                _brand_hero_current["key"] = key
        except Exception:
            pass

    brand_stage.bind("<Configure>", _resize_welcome_brand, add="+")
    app.after_idle(_resize_welcome_brand)

    # PORTABLEAI_WELCOME_ORNAMENT_v15_135
    try:
        brand_stage.configure(bg=COLORS["bg"], highlightthickness=0, bd=0)
        brand_feature.configure(bg=COLORS["bg"])
        welcome_stage_border = ConnectedBorder(brand_stage, COLORS, radius=20, outline_key="gold_mid", shine=True, filigree=True)
        welcome_ornament = WelcomeFiligree(brand_stage, COLORS)
        welcome_tagline = tk.Label(
            brand_stage, text="LOCAL  •  MODULAR  •  MULTIMODAL",
            bg=COLORS["bg"], fg=COLORS["gold_shine"],
            font=(ornate_heading_font(brand_stage), 11, "bold"), bd=0,
        )
        welcome_tagline.place(relx=0.5, rely=0.875, anchor="center")
        welcome_subtag = tk.Label(
            brand_stage,
            text="Native Intelligence  ·  Scientific Workbench  ·  Media Systems  ·  Dynamic GPU Leasing",
            bg=COLORS["bg"], fg=COLORS["muted"],
            font=(ui_font(brand_stage), 8, "normal"), bd=0,
        )
        welcome_subtag.place(relx=0.5, rely=0.92, anchor="center")
        # PORTALAI_WELCOME_ORNAMENT_RESPONSIVE_v15_137B
        def _layout_welcome_details(_event=None):
            try:
                w=max(1,int(brand_stage.winfo_width())); h=max(1,int(brand_stage.winfo_height()))
                # Prioritize an unobstructed emblem. Text is restored as vertical room appears.
                if h < 335 or w < 500:
                    welcome_tagline.place_forget(); welcome_subtag.place_forget()
                elif h < 405 or w < 690:
                    welcome_subtag.place_forget()
                    welcome_tagline.place(relx=0.5,rely=0.955,anchor="center")
                else:
                    welcome_tagline.place(relx=0.5,rely=0.885,anchor="center")
                    welcome_subtag.place(relx=0.5,rely=0.94,anchor="center")
                brand_feature.lift(); welcome_tagline.lift(); welcome_subtag.lift()
            except Exception: pass
        brand_stage.bind("<Configure>",_layout_welcome_details,add="+")
        app.after_idle(_layout_welcome_details)
    except Exception:
        welcome_stage_border = None; welcome_ornament = None
        welcome_tagline = None; welcome_subtag = None

    def _refresh_tab_buttons():
        for key, b in tab_buttons.items():
            active = key == selected_tab["key"]
            try:
                b.configure(
                    bg=(COLORS["accent"] if active else COLORS["button"]),
                    fg=("#ffffff" if active else COLORS["text"]),
                    activebackground=(COLORS["accent2"] if active else COLORS["button_hover"]),
                    activeforeground="#ffffff" if active else COLORS["text"],
                    highlightbackground=COLORS["border"],
                )
            except Exception:
                pass

    def show_tab(key):
        native_workflow=getattr(app,'_portalai_native_workflow',None)
        if native_workflow is not None and native_workflow.navigate(key):return
        if key not in tab_pages:
            return
        from internal_sheet import InternalSheet
        for sheet in list(tab_host.winfo_children()):
            if isinstance(sheet, InternalSheet): sheet.on_close()
        selected_tab["key"] = key
        for p in tab_pages.values():
            p.pack_forget()
        tab_pages[key].pack(fill="both", expand=True)
        _refresh_tab_buttons()
        if key=="persistence":persistence_page.select(persistence_page.selected or "missions")
        app.after_idle(page_watermark.refresh)
        if key in {"activity", "runtime", "installed"}:
            try:
                _ensure_status_worker()
            except Exception:
                pass
        try:
            # Navigation does not change every page's layout. Coalesce the
            # visible geometry change and retain unchanged grid/font layouts.
            relayout_main()
        except Exception:
            pass

    for key, title in (
        ("welcome", "Welcome"),
        ("accounts", "Accounts"),
        ("controls", "Controls"),
        ("chat", "Chat"),
        ("activity", "Runtime"),
        ("runtime", "Models"),
        ("installed", "Packages"),
        ("settings", "Settings"),
        ("persistence", "Persistence"),
        ("maintenance", "Maintenance"),
        ("help", "Help"),
    ):
        b = ElegantButton(
            tabs_left, text=display_caps(title), command=lambda k=key: show_tab(k),
            bg=COLORS["button"], fg=COLORS["text"],
            activebackground=COLORS["button_hover"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=7, pady=4,
            font=(portal_display_font(app), 8, "bold"), cursor="hand2",
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        tabs_left.add(b)
        tab_buttons[key] = b

    theme_toggle_btn = ElegantButton(
        tabs_right,
        text=(display_caps("Dark") if theme_mode == "light" else display_caps("Light")),
        command=lambda: toggle_theme(),
        bg=COLORS["button"], fg=COLORS["text"],
        activebackground=COLORS["button_hover"], activeforeground=COLORS["text"],
        relief="flat", bd=0, padx=7, pady=4,
        font=(portal_display_font(app), 8, "bold"), cursor="hand2",
        highlightthickness=1, highlightbackground=COLORS["border"],
    )
    theme_toggle_btn.pack(side="right")
    theme_toggle_btn.use_native_hover()

    from settings_page import SettingsPage, StorageReservesPage
    from mission_settings import show_mission_settings
    def current_account_session():
        return getattr(app, '_portalai_account_session', None)

    from persistence_page import PersistencePage
    persistence_page=PersistencePage(persistence_tab,root,COLORS,session=current_account_session,jobs=gui_jobs)
    persistence_page.pack(fill='both',expand=True)
    def open_account_missions():
        show_tab('persistence')

    settings_page = SettingsPage(settings_tab, root, COLORS,
        missions=open_account_missions, on_save=lambda: force_scan.set(), session=current_account_session)
    settings_page.pack(fill="both", expand=True, pady=(0, 10))
    documentation_panel = DocumentationPanel(help_tab, COLORS)
    donation_panel = DonationPanel(donation_tab, root, COLORS)

    # PORTALAI_HELP_DECOR_v15_136
    portal_help_decorator = decorate_help_page(help_tab, COLORS)
    app.after(250, lambda: (rebrand_widget_tree(help_tab, chat=False), upgrade_vertical_scrollbars(help_tab, COLORS)))

    def show_help_topic(topic="quick_start"):
        show_tab("help")
        documentation_panel.show_topic(topic)
        app.after_idle(lambda: (rebrand_widget_tree(help_tab, chat=False), portal_help_decorator.refresh(), upgrade_vertical_scrollbars(help_tab, COLORS)))

    app._portableai_show_help = show_help_topic

    show_tab("welcome")

    def _tab_mousewheel(event):
        # Let Text/Listbox widgets consume their own wheel input. Otherwise scroll
        # the currently visible informational tab. Chat manages its own scrolling.
        if selected_tab["key"] == "chat":
            return None
        try:
            cls = str(event.widget.winfo_class())
            if cls in ("Text", "Listbox", "TEntry", "Entry", "Spinbox"):
                return None
        except Exception:
            pass
        cv = tab_scroll_canvases.get(selected_tab["key"])
        if cv is None:
            return None
        delta = getattr(event, "delta", 0)
        if delta:
            steps = int(-delta / 120) or (-1 if delta > 0 else 1)
            cv.yview_scroll(steps * 3, "units")
            return "break"
        return None

    app.bind_all("<MouseWheel>", _tab_mousewheel, add="+")

    # Compatibility aliases for existing low-overhead relayout helpers.
    left_col = runtime_tab
    right_col = installed_tab

    # Embed the OpenGUI replacement directly into the Chat tab. Standalone launch
    # remains available through Launch_PortableChat.cmd for troubleshooting.
    native_chat_panel = None
    try:
        from native_chat import NativeChat
        native_chat_panel = NativeChat(root, parent=chat_tab, palette=COLORS)
        native_chat_panel.activity_callback = lambda value: event_q.put(('tool_activity', value))
    except Exception as exc:
        tk.Label(chat_tab, text=f"PortalAI Chat failed to initialize:\n{exc}",
                 bg=COLORS["bg"], fg=COLORS["bad"], justify="left",
                 font=("Cascadia Mono", 9)).pack(fill="both", expand=True, padx=16, pady=16)

    # PORTALAI_NATIVE_CHAT_FRONTEND_v15_136
    portal_chat_frontend = install_native_chat_frontend(
        app, chat_tab, native_chat_panel, COLORS, brand_images, lambda: theme_mode
    )


    # PORTABLEAI_CHAT_WATERMARK_v15_135
    # The watermark lives INSIDE the transcript's scroll-window Frame and is
    # lowered beneath message widgets.  That is important: drawing below the
    # Canvas window hides the emblem completely, while drawing above it obscures
    # text.  This placement keeps text/controls in the foreground and lets the
    # semi-transparent artwork remain visible through otherwise empty space.
    chat_brand_state = {"canvas": None, "window_item": None, "host": None, "label": None, "canvas_item": None}

    def _chat_widget_tree(widget):
        out=[]; stack=[widget]
        while stack:
            cur=stack.pop()
            try: children=list(cur.winfo_children())
            except Exception: children=[]
            out.extend(children); stack.extend(children)
        return out

    def _chat_watermark_canvas():
        candidates=[]
        # Prefer Canvas objects retained directly by NativeChat; then fall back
        # to geometry-based tree discovery so this survives internal renames.
        if native_chat_panel is not None:
            try:
                for _name,_value in vars(native_chat_panel).items():
                    if isinstance(_value, tk.Canvas):
                        candidates.append(_value)
            except Exception:
                pass
        for w in _chat_widget_tree(chat_tab):
            try:
                if isinstance(w, tk.Canvas) or str(w.winfo_class()) == "Canvas":
                    candidates.append(w)
            except Exception:
                pass
        scored=[]; seen=set()
        for cv in candidates:
            if id(cv) in seen: continue
            seen.add(id(cv))
            try:
                ww=max(1,int(cv.winfo_width())); hh=max(1,int(cv.winfo_height()))
                if ww < 280 or hh < 140: continue
                score=ww*hh
                try:
                    if str(cv.cget("yscrollcommand")).strip(): score*=1.35
                except Exception: pass
                try:
                    if cv.find_all(): score*=1.10
                except Exception: pass
                scored.append((score,cv))
            except Exception: pass
        return max(scored,default=(0,None),key=lambda x:x[0])[1]

    def _chat_canvas_host(cv):
        best=None
        try:
            for item in cv.find_all():
                try:
                    if cv.type(item) != "window": continue
                    path=str(cv.itemcget(item,"window") or "").strip()
                    if not path: continue
                    host=app.nametowidget(path)
                    ww=max(int(host.winfo_width()),int(host.winfo_reqwidth()),1)
                    hh=max(int(host.winfo_height()),int(host.winfo_reqheight()),1)
                    score=ww*hh
                    if best is None or score>best[0]: best=(score,item,host)
                except Exception: pass
        except Exception: pass
        return (best[1],best[2]) if best else (None,None)

    def _clear_chat_watermark():
        st=chat_brand_state
        try:
            if st.get("label") is not None: st["label"].destroy()
        except Exception: pass
        try:
            if st.get("canvas") is not None and st.get("canvas_item") is not None:
                st["canvas"].delete(st["canvas_item"])
        except Exception: pass
        st.update({"window_item":None,"host":None,"label":None,"canvas_item":None})

    def _chat_watermark_tick():
        try:
            if selected_tab.get("key") == "chat":
                cv=_chat_watermark_canvas()
                if cv is not chat_brand_state.get("canvas"):
                    _clear_chat_watermark(); chat_brand_state["canvas"]=cv
                if cv is not None:
                    ww=max(1,int(cv.winfo_width())); hh=max(1,int(cv.winfo_height()))
                    small=(ww < 760 or hh < 430)
                    mode="dark" if theme_mode == "dark" else "light"
                    key=f"chatwm_{mode}{144 if small else 196}"
                    img=brand_images.get(key) if isinstance(brand_images,dict) else None
                    if img is not None:
                        win_item,host=_chat_canvas_host(cv)
                        margin=24 if not small else 16
                        if host is not None and win_item is not None:
                            if host is not chat_brand_state.get("host"):
                                _clear_chat_watermark(); chat_brand_state["canvas"]=cv
                                chat_brand_state["host"]=host; chat_brand_state["window_item"]=win_item
                            lab=chat_brand_state.get("label")
                            if lab is None:
                                lab=tk.Label(host,image=img,bg=host.cget("bg"),bd=0,highlightthickness=0,padx=0,pady=0,takefocus=0)
                                chat_brand_state["label"]=lab
                            else:
                                lab.configure(image=img,bg=host.cget("bg"))
                            lab._portableai_brand_image=img
                            try:
                                wx,wy=(cv.coords(win_item)+[0,0])[:2]
                                px=cv.canvasx(max(1,ww-margin))-float(wx)
                                py=cv.canvasy(max(1,hh-margin))-float(wy)
                                lab.place(x=max(margin,px),y=max(margin,py),anchor="se")
                                lab.lower()
                            except Exception: pass
                        else:
                            # Rare fallback for a transcript drawn directly on Canvas.
                            item=chat_brand_state.get("canvas_item")
                            if item is None:
                                item=cv.create_image(0,0,image=img,anchor="se",tags=("portableai_chat_watermark",))
                                chat_brand_state["canvas_item"]=item
                            else: cv.itemconfigure(item,image=img,state="normal")
                            cv.coords(item,cv.canvasx(max(1,ww-margin)),cv.canvasy(max(1,hh-margin)))
            app.after(220,_chat_watermark_tick)
        except tk.TclError:
            return
        except Exception:
            try: app.after(500,_chat_watermark_tick)
            except Exception: pass

    # v15.136 watermark overlay supersedes the canvas-only v15.135 timer.

    # PORTALAI_GOLD_SCROLLBARS_v15_136
    app.after(650, lambda: (upgrade_vertical_scrollbars(help_tab, COLORS), upgrade_vertical_scrollbars(chat_tab, COLORS)))
    app.after(1600, lambda: (upgrade_vertical_scrollbars(help_tab, COLORS), upgrade_vertical_scrollbars(chat_tab, COLORS)))

    ctl = panel(controls_tab, "Controls", "Lifecycle and diagnostics")
    ctl.pack(fill="x", pady=(0, 10))
    control_hint = label(ctl, "Startup saves and applies your current chat settings, switching an idle model when needed. Finish active work first. Automatic fits available RAM/VRAM.",
                         9, fg=COLORS["muted"], wraplength=800, justify="left")
    control_hint.pack(fill="x", padx=12, pady=(0, 8))
    control_text_labels = [control_hint]
    control_policy = tk.StringVar(app, value=settings_page.startup_summary())
    control_loaded = tk.StringVar(app, value='Current chat: checking current server…')
    control_progress = tk.StringVar(app, value='')
    for value in (control_policy, control_loaded, control_progress):
        item = label(ctl, textvariable=value, size=9, fg=COLORS['muted'], wraplength=800, justify='left')
        item.pack(fill='x', padx=12, pady=(0, 4)); control_text_labels.append(item)
    def wrap_control_text(event):
        width = max(80, event.width - 28)
        for item in control_text_labels:
            if int(item.cget('wraplength')) != width:item.configure(wraplength=width)
    ctl.bind('<Configure>', wrap_control_text, add='+')
    settings_page.on_change = lambda: control_policy.set(settings_page.startup_summary())
    last_policy_edit = [time.monotonic()]
    def settings_saved():
        last_policy_edit[0] = time.monotonic()
        force_scan.set()
        if native_chat_panel is not None and getattr(native_chat_panel, 'effort', None):
            native_chat_panel.effort.sync_saved_choice()
    settings_page.on_save = settings_saved
    settings_page.chat_busy = lambda: bool(native_chat_panel and native_chat_panel.busy)
    if native_chat_panel is not None and getattr(native_chat_panel, 'effort', None):
        def effort_choice_saved():
            last_policy_edit[0] = time.monotonic()
            settings_page.sync_chat_choice()
            force_scan.set()
        native_chat_panel.effort.on_choice_saved = effort_choice_saved
    btnrow = tk.Frame(ctl, bg=COLORS["panel"])
    btnrow.pack(fill="x", padx=12, pady=(0, 12))
    buttons = []

    def control_button_style(kind):
        bg_key, hover_key = {
            "accent": ("accent", "accent2"),
            "warning": ("gold_mid", "gold_shine"),
            "danger": ("danger", "danger_hover"),
        }.get(kind, ("button", "button_hover"))
        fg = "#ffffff" if kind in ("accent", "danger") else "#202224" if kind == "warning" else COLORS["text"]
        return bg_key, hover_key, fg

    def button(text, cmd, *, kind="normal"):
        bg_key, hover_key, fg = control_button_style(kind)
        b = ElegantButton(
            btnrow, text=text, command=cmd, bg=COLORS[bg_key], fg=fg,
            activebackground=COLORS[hover_key], activeforeground=fg,
            relief="flat", bd=0, padx=14, pady=9,
            font=("Segoe UI Variable Text", 9, "bold"), cursor="hand2",
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        b._portableai_kind = kind
        b.use_native_hover()
        buttons.append(b)
        return b

    svc_panel = panel(
        runtime_tab,
        "Models / Services",
        "Server state, active work, and currently loaded model/component",
    )
    svc_panel.pack(fill="both", expand=True, pady=(0, 10))
    services = {}
    activities = {}
    runtime_model_boxes = {}
    service_cards_wrap = tk.Frame(svc_panel, bg=COLORS["panel"])
    service_cards_wrap.pack(fill="x", padx=10, pady=(0, 6))
    service_cards = []

    def status_block(parent, key, title, url=None, activity_rows=(), model_title="Loaded / detected"):
        block = tk.Frame(
            parent, bg=COLORS["card"], bd=0,
            highlightthickness=0,
        )
        top = tk.Frame(block, bg=COLORS["card"])
        top.pack(fill="x", padx=10, pady=(7, 1))
        name = label(top, title, 9, bold=True)
        name.pack(side="left")
        if url:
            name.configure(fg=COLORS["accent"], cursor="hand2")
            name.bind("<Button-1>", lambda _e, u=url: webbrowser.open(u))
        state = label(top, "CHECKING", 8, fg=COLORS["warn"], bold=True)
        state.pack(side="left", padx=(9, 7))
        services[key] = (state, None)
        detail = label(block, "", 8, fg=COLORS["muted"], width=1, wraplength=360, justify="left")
        detail.pack(fill="x", padx=10)
        def wrap_status(event, widget=detail):
            width=max(80,event.width-20)
            if int(widget.cget('wraplength'))!=width:widget.configure(wraplength=width)
        block.bind('<Configure>',wrap_status,add='+')
        services[key] = (state, detail)
        for activity_key, activity_title in activity_rows:
            sub = tk.Frame(block, bg=COLORS["card"])
            sub.pack(fill="x", padx=10)
            sub.columnconfigure(2,weight=1)
            label(sub, activity_title, 8, fg=COLORS["muted"], bold=True).grid(row=0,column=0,sticky='nw')
            astate = label(sub, "CHECKING", 8, fg=COLORS["warn"], bold=True)
            astate.grid(row=0,column=1,sticky='nw',padx=(8,7))
            adetail = label(sub, "", 8, fg=COLORS["muted"], width=1, wraplength=160, justify="left")
            adetail.grid(row=0,column=2,sticky='ew')
            def wrap_activity(event,widget=adetail):
                width=max(40,event.width-4)
                if int(widget.cget('wraplength'))!=width:widget.configure(wraplength=width)
            adetail.bind('<Configure>',wrap_activity,add='+')
            activities[activity_key] = (astate, adetail)
        model_wrap = tk.Frame(block, bg=COLORS["card"])
        model_wrap.pack(fill="x", padx=10, pady=(3, 7))
        label(model_wrap, model_title, 8, fg=COLORS["muted2"], bold=True).pack(fill="x")
        mbox = compact_model_box(model_wrap, width=32, height=2)
        mbox.pack(fill="x")
        runtime_model_boxes[key] = mbox
        _decorate_soft_frame(block, corner_size=12, outline_key="gold_mid", shine=False)
        service_cards.append(block)

    status_block(service_cards_wrap, "missions", "Persistent missions", model_title="Execution boundary")
    status_block(service_cards_wrap, "qwen", "Qwen / llama.cpp", _instance_url('qwen', ''),
                 activity_rows=(("agent", "Agent"), ("qwen", "Inference")), model_title="Chat model / residency")
    status_block(service_cards_wrap, "comfy", "ComfyUI", _instance_url('comfyui', ''),
                 activity_rows=(("comfy", "Activity"),), model_title="Loaded model(s)")
    status_block(service_cards_wrap, "ace", "ACE-Step", _instance_url('acestep', ''),
                 activity_rows=(("ace", "Activity"),), model_title="Loaded model(s)")
    status_block(service_cards_wrap, "tts", "Speech / Qwen + Piper",
                 activity_rows=(("tts", "Activity"),), model_title="Loaded model(s)")
    status_block(service_cards_wrap, "musetalk", "MuseTalk / Dialogue",
                 activity_rows=(("musetalk", "Activity"),), model_title="Loaded model(s)")
    status_block(service_cards_wrap, "mmaudio", "MMAudio / SFX",
                 activity_rows=(("mmaudio", "Activity"),), model_title="Loaded model(s)")
    status_block(service_cards_wrap, "science", "Science Engine",
                 activity_rows=(("science", "Activity"),), model_title="Compute policy")
    status_block(service_cards_wrap, "media", "Media previews", _instance_url('preview', ''),
                 activity_rows=(("media", "Activity"),), model_title="Component")
    if (root / "OpenGUI").exists():
        status_block(service_cards_wrap, "opengui", "Legacy OpenGUI", model_title="Component")
    label(
        svc_panel,
        "Low-overhead observability: local service state, foreground PortalAI commands, and host-managed model markers. Hidden model reasoning is never exposed.",
        8, fg=COLORS["muted"], wraplength=980, justify="left",
    ).pack(fill="x", padx=14, pady=(2, 12))

    diag_panel = panel(maintenance_tab, "Targeted Diagnostics", "Selected-component reports; full diagnosis and portability/media checks are separate")
    diag_panel.pack(fill="x", padx=0, pady=(4, 6))
    diag_row = ResponsiveFlow(diag_panel, bg=COLORS["panel"], hgap=6, vgap=6); diag_row.pack(fill="x", padx=12, pady=(0, 5))
    diag_component_var = tk.StringVar(value="Qwen")
    if str(root / 'Tools') not in sys.path:
        sys.path.insert(0, str(root / 'Tools'))
    from diagnostic_catalog import CHOICES as diag_choices, resolve as resolve_diagnostic, COVERAGE as diagnostic_coverage
    from diagnostic_selector import DiagnosticSelector
    diag_menu = DiagnosticSelector(diag_row,chooser_parent=tab_host,
                                textvariable=diag_component_var,values=diag_choices,
                                state='readonly',palette=COLORS,width=24)
    diag_row.add(diag_menu)
    diag_row.add(ElegantButton(diag_row, text="Run selected", command=lambda: show_or_run_component_diagnostic(),
              bg=COLORS["button"], fg=COLORS["text"], activebackground=COLORS["button_hover"],
              activeforeground=COLORS["text"], relief="flat", bd=0, padx=12, pady=6))
    diag_row.add(ElegantButton(diag_row, text="Full diagnosis", command=lambda: diagnose(),
              bg=COLORS["button"], fg=COLORS["text"], activebackground=COLORS["button_hover"],
              activeforeground=COLORS["text"], relief="flat", bd=0, padx=12, pady=6))
    diag_row.add(ElegantButton(diag_row, text="Fresh-machine readiness", command=lambda: show_or_run_fresh_machine_validator(),
              bg=COLORS["button"], fg=COLORS["text"], activebackground=COLORS["button_hover"],
              activeforeground=COLORS["text"], relief="flat", bd=0, padx=12, pady=6))
    diag_row.add(ElegantButton(diag_row, text="Verify media stack", command=lambda: show_or_run_media_stack_verify(),
              bg=COLORS["button"], fg=COLORS["text"], activebackground=COLORS["button_hover"],
              activeforeground=COLORS["text"], relief="flat", bd=0, padx=12, pady=6))
    diag_coverage_label=label(diag_panel, diagnostic_coverage, 8, fg=COLORS['muted'], wraplength=980,justify='left')
    diag_coverage_label.pack(fill='x', padx=14, pady=(0,6));bind_responsive_wrap(diag_coverage_label,padding=28,minimum=120)

    gpu_panel = panel(activity_tab, "CPU / Memory / GPU", "Host activity · five-minute rolling history · first reported GPU adapter")
    gpu_panel.pack(fill="x", pady=(0, 10))
    from activity_monitor import Sampler, ActivityCharts
    activity_sampler = Sampler()
    from runtime_activity import RuntimeActivity, format_processes
    runtime_activity = RuntimeActivity(root)
    activity_charts = ActivityCharts(gpu_panel, COLORS)
    activity_charts.pack(fill="x", padx=10, pady=(0, 6))
    gpu_lbl = label(gpu_panel, "GPU telemetry pending...", 9)
    gpu_lbl.pack(fill="x", padx=12, pady=(0, 5))
    tool_activity_label = label(gpu_panel, 'Chat tools: idle', 9, fg=COLORS['accent'])
    tool_activity_label.pack(fill='x', padx=12, pady=(3, 4))
    process_box = readonly_box(gpu_panel, height=7)
    process_box.border.simple=False;process_box.border.filigree=True
    process_box.pack(fill='x', padx=12, pady=(0, 6))
    label(gpu_panel, 'Concurrent owned processes: CPU % of host, resident RAM, busiest GPU engine %, dedicated/shared GPU memory. Shared allocations may be counted in several processes. n/a means unavailable; a resident process is not proof of active inference.', 8, fg=COLORS['muted'], wraplength=980, justify='left').pack(fill='x', padx=12, pady=(0, 8))
    label(
        gpu_panel, "Reported models / component stages (CPU or GPU)", 8,
        fg=COLORS["muted"], bold=True,
    ).pack(fill="x", padx=12, pady=(2, 4))
    gpu_models_box = readonly_box(gpu_panel, height=4)
    gpu_models_box.border.simple=False;gpu_models_box.border.filigree=True
    gpu_models_box.pack(fill="x", padx=12, pady=(0, 6))
    label(
        gpu_panel,
        "Read-only monitoring: CPU/RAM and WDDM about every 5 s; adapter summary every 15 s; package inventory every 2 min. Probes may extend intervals. Missing counters show unavailable.",
        8, fg=COLORS["muted"],
    ).pack(fill="x", padx=12, pady=(0, 12))

    maintenance_panel = panel(maintenance_tab, "Maintenance & Storage", "Inspect first; cleanup and destructive deletion remain explicit")
    maintenance_panel.pack(fill="x", padx=0, pady=(0, 6))
    from ui_extensions import ResponsiveGrid
    maintenance_groups={}
    for group in ('Checks and reports','Cleanup plans','Delete data'):
        label(maintenance_panel,group,9,bold=True).pack(fill='x',padx=16,pady=(3,3))
        grid=ResponsiveGrid(maintenance_panel,bg=COLORS['panel'],min_cell_width=220,max_columns=3,hgap=8,vgap=4)
        grid.pack(fill='x',padx=16,pady=(0,4));maintenance_groups[group]=grid
    maintenance_flow=maintenance_groups['Checks and reports']
    maintenance_buttons=[]

    def _maintenance_button(text, command, *, fg=None, kind='normal'):
        destructive=text.startswith('Delete ')
        grid=maintenance_groups['Delete data' if destructive else 'Cleanup plans' if 'Cleanup' in text else 'Checks and reports']
        kind='danger' if destructive else kind
        bg_key,hover_key,foreground=control_button_style(kind)
        b = ElegantButton(grid, text=text, command=command, bg=COLORS[bg_key],
                          fg=foreground, activebackground=COLORS[hover_key], activeforeground=foreground,
                          relief="flat", bd=0, padx=12, pady=5)
        b._portableai_kind=kind
        b.use_native_hover()
        maintenance_buttons.append(b)
        grid.add(b)
        return b

    _maintenance_button("Storage Audit", lambda: show_or_run_storage_audit(False))
    _maintenance_button("Deep Duplicate Scan", lambda: show_or_run_storage_audit(True))
    _maintenance_button("Safe Cleanup Plan", lambda: show_general_cleanup_panel(), kind='warning')
    _maintenance_button("Root-only Cleanup", lambda: run_root_hygiene_now(), kind='warning')
    _maintenance_button("Dependency Isolation Test", lambda: show_dependency_probe_panel())
    _maintenance_button("Reference Integrity", lambda: show_or_run_root_reference_audit())
    _maintenance_button("Maintenance Reports", lambda: open_maintenance_folder())
    _maintenance_button("Delete Web Cache", lambda: show_maintenance_delete_confirm("webcache"), fg=COLORS["warn"])
    _maintenance_button("Delete All Outputs", lambda: show_maintenance_delete_confirm("outputs"), fg=COLORS["bad"])
    _maintenance_button("Delete All Conversations + Memory", lambda: show_maintenance_delete_confirm("conversations"), fg=COLORS["bad"])
    maintenance_note=label(maintenance_panel,'Checks and plans do not delete data. Cleanup targets regenerable caches; Root-only Cleanup previews an archive. Deletion always requires confirmation. Reports retain Current + Previous.',8,fg=COLORS['muted'],justify='left')
    maintenance_note.pack(fill='x',padx=16,pady=(2,7));bind_responsive_wrap(maintenance_note,padding=32,minimum=120)

    storage_page = StorageReservesPage(maintenance_tab, root, COLORS, on_save=lambda: force_scan.set(),
                                       session=current_account_session)
    storage_page.pack(fill="x", padx=0, pady=(0,6))

    installed_panel = panel(installed_tab, "Packages", "Dynamic capability scan from current PortalAI files and command registry")
    installed_panel.pack(fill="both", expand=True, pady=(0, 10))
    from packages_page import PackagesView
    packages_view=PackagesView(installed_panel,COLORS)
    packages_view.pack(fill='both',expand=True,padx=12,pady=(0,12))
    from bundle_inventory import MODEL_LABELS, installed_rows as current_installed_rows
    installed_rows={}
    for key, title in (
        *(("model_" + key, value) for key, value in MODEL_LABELS.items()),
        ("backend_cuda", "CUDA chat backend"), ("backend_vulkan", "Vulkan chat backend"), ("backend_cpu", "CPU chat backend"),
        ("missions", "Persistent mission supervisor"), ("vmMode", "Offline VM mission shell"),
        ("piperCpu", "Piper CPU speech"), ("sd15Cpu", "SD1.5 CPU image fallback"),
        ("imageVulkan", "SD1.5 Vulkan image engine"), ("imageNativeCpu", "SD1.5 native CPU image engine"),
        ("amdTorch", "AMD ROCm media runtime"),
        ("qwenCore", "Qwen local multimodal core"),
        ("nativeChat", "Native Chat + persistent history"),
        ("contextMemory", "Context management + persistent memory"),
        ("liveTimers", "Live step / response timing"),
        ("voice", "Qwen3-TTS voices"),
        ("stt", "Speech-to-text / faster-whisper"),
        ("musetalk", "MuseTalk lip sync / dialogue"),
        ("dialogue", "Dialogue-video / video-dialogue"),
        ("sfx", "MMAudio sound effects / Foley"),
        ("videoSfx", "Video-conditioned synchronized SFX"),
        ("sfxInpaint", "Localized SFX inpainting / replacement"),
        ("fluxOfficial", "FLUX.2 Klein official"),
        ("fluxAlt", "FLUX.2 Klein alternative"),
        ("imageEdit", "Image generation/edit"),
        ("inpaint", "Image inpainting / masking"),
        ("video", "Wan image-to-video"),
        ("vace", "Wan VACE video editing"),
        ("videoRange", "Video range cut / VACE / regeneration"),
        ("videoUnderstand", "Video understanding / casual + forensic"),
        ("music", "ACE-Step music"),
        ("musicCpu", "MusicGen CPU instrumentals"),
        ("musicUnderstand", "Music / audio understanding"),
        ("mediaEdit", "Deterministic media editing"),
        ("audioInpaint", "Diffusive audio inpainting"),
        ("videoInpaint", "Diffusive video inpainting"),
        ("science", "Science Workbench"),
        ("scienceCore", "Science · math / stats / signal"),
        ("scienceCad", "Science · CAD / mesh"),
        ("scienceMech", "Science · mechanical"),
        ("scienceElectrical", "Science · electrical"),
        ("scienceChem", "Science · chemistry"),
        ("scienceGenomics", "Science · genomics / SBOL"),
        ("scienceProtein", "Science · protein / OpenMM"),
        ("sciencePhysics", "Science · physics"),
        ("scienceBiology", "Science · biology workbench"),
        ("scienceDesign", "Science · ProteinMPNN CPU design"),
        ("scienceCoupled", "Science · coupled physics"),
        ("scienceKicad", "Science · KiCad export"),
        ("scienceGpu", "Science · OpenCL / CUDA availability"),
        ("mediaPreview", "Local media preview / output return"),
        ("gpuHandoff", "Dynamic GPU / VRAM handoff"),
        ("diagnostics", "Diagnostics / storage / duplicate scan"),
        ("maintenance", "Cleanup / recovery / explicit data deletion"),
        ("webTools", "Web search / fetch / image tools"),
    ):
        installed_rows[key]=packages_view.add(key,title)
    diffusion_box=packages_view.diffusion_box;lora_box=packages_view.lora_box

    log_panel = panel(controls_tab, "Control Log", "Lifecycle, diagnosis, and controller events")
    log_panel.pack(fill="both", expand=True)
    log_box = readonly_box(log_panel,height=10)
    log_box.configure(wrap='word')
    log_box.pack(fill='both',expand=True,padx=12,pady=(0,12))

    def log(msg):
        stamp = time.strftime("%H:%M:%S")
        log_box.configure(state="normal")
        log_box.insert("end", f"[{stamp}] {msg}\n")
        if int(log_box.index('end-1c').split('.')[0]) > 1000: log_box.delete('1.0', '101.0')
        log_box.see("end")
        log_box.configure(state="disabled")

    def color_for(state):
        u = (state or "").upper()
        if any(x in u for x in ("READY", "IDLE", "INSTALLED")):
            return COLORS["good"]
        if "SUSPENDED" in u or "SLEEPING" in u:
            return COLORS["warn"]
        if "ROUTE MISSING" in u:
            return COLORS["warn"]
        if any(x in u for x in ("STOPPED", "OFFLINE", "MISSING", "ERROR", "STALLED")):
            return COLORS["bad"]
        if any(x in u for x in ("TOOL CALL", "QWEN INFERENCE", "PROCESSING", "QUEUED", "STARTING", "PORT OPEN")):
            return COLORS["accent2"]
        return COLORS["warn"]

    def set_pair(mapping, key, state, detail):
        if key not in mapping:
            return
        s, d = mapping[key]
        s.configure(text=state, fg=color_for(state))
        d.configure(text=detail)

    layout_state = {
        "button_cols": None,
        "service_cols": None,
        "installed_stacked": None,
        "after_id": None,
    }

    def relayout_buttons(force=False):
        width = max(btnrow.winfo_width(), ctl.winfo_width(), 1)
        # PORTALAI_RESPONSIVE_CONTROL_LAYOUT_HOOK_v15_138
        try:
            if portal_control_menu is not None and portal_control_menu.handle_layout(width):
                # Expanding back to the same column count must restore buttons
                # hidden by the narrow Controls menu.
                layout_state['button_cols'] = None
                return
        except (NameError, UnboundLocalError):
            pass
        cols = 1 if width < 360 else 2 if width < 560 else 3
        if not force and layout_state["button_cols"] == cols:
            return
        layout_state["button_cols"] = cols
        for child in buttons:
            child.grid_forget()
        for c in range(4):
            btnrow.grid_columnconfigure(c, weight=(1 if c < cols else 0), uniform=("btn" if c < cols else ""))
        for idx, child in enumerate(buttons):
            child.grid(row=idx // cols, column=idx % cols, sticky="ew", padx=4, pady=4)

    def relayout_service_cards(force=False):
        width = max(service_cards_wrap.winfo_width(), runtime_tab.winfo_width(), 1)
        cols = 1 if width < 520 else 2 if width < 900 else 3
        if not force and layout_state["service_cols"] == cols:
            return
        layout_state["service_cols"] = cols
        for c in range(4):
            service_cards_wrap.grid_columnconfigure(c, weight=0, uniform="")
        for c in range(cols):
            service_cards_wrap.grid_columnconfigure(c, weight=1, uniform="svc")
        for idx, block in enumerate(service_cards):
            block.grid_forget()
            block.grid(row=idx // cols, column=idx % cols, sticky="nsew", padx=4, pady=4)

    def relayout_installed_panel(force=False):
        packages_view.queue_layout()

    def _perform_relayout(force=False):
        layout_state["after_id"] = None
        width = max(content.winfo_width(), app.winfo_width(), 1)
        try:
            if width < 760:
                header.pack_configure(pady=(8, 4))
                gem.pack_forget()
            else:
                header.pack_configure(pady=(18, 8))
                if not gem.winfo_manager():
                    gem.pack(anchor="e")
        except Exception:
            pass
        relayout_buttons(force=force)
        relayout_service_cards(force=force)
        relayout_installed_panel(force=force)

    def relayout_main(_event=None, force=False):
        if force:
            if layout_state["after_id"] is not None:
                try: app.after_cancel(layout_state["after_id"])
                except Exception: pass
                layout_state["after_id"] = None
            _perform_relayout(force=True)
            return
        if layout_state["after_id"] is None:
            layout_state["after_id"] = app.after(45, _perform_relayout)

    app._portalai_relayout = relayout_main
    content.bind("<Configure>", relayout_main)
    # The scroll-page viewport can resize without the outer content frame
    # changing. Reflow Controls from its own geometry as well.
    ctl.bind('<Configure>', relayout_main, add='+')

    def _save_theme_preference():
        try:
            theme_pref_path.parent.mkdir(parents=True, exist_ok=True)
            from runtime_policy import atomic_json
            atomic_json(theme_pref_path, {"theme": theme_mode})
        except Exception:
            pass

    def _translate_theme_color(value, source, target):
        if not isinstance(value, str):
            return value
        low = value.lower()
        for key, old_value in source.items():
            if isinstance(old_value, str) and low == old_value.lower():
                return target.get(key, value)
        return value

    def _retheme_widget_tree(widget, source, target):
        options = (
            "background", "foreground", "activebackground", "activeforeground",
            "highlightbackground", "highlightcolor", "insertbackground",
            "selectbackground", "selectforeground", "troughcolor",
        )
        for option in options:
            try:
                current = widget.cget(option)
                translated = _translate_theme_color(current, source, target)
                if translated != current:
                    widget.configure(**{option: translated})
            except Exception:
                pass
        try:
            children = widget.winfo_children()
        except Exception:
            children = []
        for child in children:
            _retheme_widget_tree(child, source, target)

    def apply_theme(source, target):
        COLORS.clear()
        COLORS.update(target)
        _retheme_widget_tree(app, source, target)
        from account_presentation import refresh_account_theme
        refresh_account_theme(app, COLORS)
        from internal_sheet import InternalSheet
        for sheet in tab_host.winfo_children():
            if isinstance(sheet, InternalSheet): sheet.apply_palette(COLORS)

        # Branding images keep their approved artwork in both themes; only the
        # surrounding surfaces/borders follow the active palette.
        try:
            gem.configure(bg=COLORS["bg"])
            if isinstance(gem, tk.Canvas) and gem_items:
                gem.itemconfigure(gem_items["shadow_arc"], outline=COLORS["shadow"])
                gem.itemconfigure(gem_items["gold_arc"], outline=COLORS["border"])
                gem.itemconfigure(gem_items["shine_arc"], outline=COLORS["gold_shine"])
                gem.itemconfigure(gem_items["gem_outer"], outline=COLORS["gold_mid"])
                gem.itemconfigure(gem_items["gem_inner"], outline=COLORS["accent"])
                gem.itemconfigure(gem_items["ray_v"], fill=COLORS["gold_shine"])
                gem.itemconfigure(gem_items["ray_h"], fill=COLORS["border"])
            brand_stage.configure(bg=COLORS["bg"], highlightbackground=COLORS["border"])
            brand_feature.configure(bg=COLORS["bg"])
        except Exception:
            pass

        try:
            window_shell.configure(bg=COLORS["shadow"], highlightbackground=COLORS["gold_mid"])
            titlebar.configure(bg=COLORS["panel3"], highlightbackground=COLORS["gold_mid"])
            titlebar_left.configure(bg=COLORS["panel3"]); titlebar_right.configure(bg=COLORS["panel3"])
            titlebar_gem.configure(bg=COLORS["panel3"])
            if isinstance(titlebar_gem, tk.Canvas) and titlebar_gem_items:
                titlebar_gem.itemconfigure(titlebar_gem_items["outer"], outline=COLORS["gold_mid"])
                titlebar_gem.itemconfigure(titlebar_gem_items["inner"], outline=COLORS["accent"])
                titlebar_gem.itemconfigure(titlebar_gem_items["v"], fill=COLORS["gold_shine"])
                titlebar_gem.itemconfigure(titlebar_gem_items["h"], fill=COLORS["border"])
            titlebar_text.configure(bg=COLORS["panel3"], fg=COLORS["text"])
            donate_link.apply_palette(COLORS)
            for name, btn in chrome_buttons.items():
                role = getattr(btn, "_portableai_role", "normal")
                bg_key = "danger" if role == "close" else "button"
                fg = "#ffffff" if role == "close" else COLORS["text"]
                btn.configure(bg=COLORS[bg_key], fg=fg, activebackground=COLORS[bg_key], activeforeground=fg, highlightbackground=COLORS["border"])
        except Exception:
            pass

        try:
            scroll.configure(
                bg=COLORS["panel2"], activebackground=COLORS["button_hover"],
                troughcolor=COLORS["bg"], highlightbackground=COLORS["outline"],
            )
        except Exception:
            pass

        for b in buttons + maintenance_buttons:
            try:
                kind = getattr(b, "_portableai_kind", "normal")
                bg_key, hover_key, fg = control_button_style(kind)
                b.configure(
                    bg=COLORS[bg_key], fg=fg,
                    activebackground=COLORS[hover_key], activeforeground=fg,
                    highlightbackground=COLORS["border"],
                )
            except Exception:
                pass

        try:
            theme_toggle_btn.configure(
                text=(display_caps("Dark") if theme_mode == "light" else display_caps("Light")),
                bg=COLORS["button"], fg=COLORS["text"],
                activebackground=COLORS["button_hover"], activeforeground=COLORS["text"],
                highlightbackground=COLORS["border"],
            )
        except Exception:
            pass

        try:
            exit_menu.configure(
                bg=COLORS["panel"], fg=COLORS["text"],
                activebackground=COLORS["accent"], activeforeground=COLORS["text"],
                bd=1,
            )
        except Exception:
            pass

        _refresh_tab_buttons()
        try:
            if native_chat_panel is not None:
                native_chat_panel.apply_palette(COLORS)
        except Exception:
            pass
        try:
            documentation_panel.apply_palette(COLORS)
            donation_panel.apply_palette(COLORS)
            ui_context.apply_palette(COLORS)
        except Exception:
            pass
        try:
            settings_page.apply_palette(COLORS)
            storage_page.apply_palette(COLORS)
            persistence_page.apply_palette(COLORS)
            packages_view.apply_palette(COLORS)
            diag_menu.apply_palette(COLORS)
            if account_page is not None: account_page.apply_palette(COLORS)
            for field in rounded_readouts:
                if field.winfo_exists(): field.apply_palette(COLORS)
            activity_charts.apply_palette(COLORS)
        except Exception:
            pass
        _refresh_soft_decorations()
        for scrollbar in readonly_scrollbars:
            if scrollbar.winfo_exists(): scrollbar.apply_palette(COLORS)

        welcome_note_border.apply_palette(COLORS)
        welcome_note_sep._portableai_redraw()
        # v15.135 connected ornament/theme synchronization.
        try:
            window_ornament.apply_palette(COLORS)
            tabbar_ornament.apply_palette(COLORS)
            if rounding_controller is not None: rounding_controller.refresh()
            try:
                title_filigree.configure(bg=COLORS["panel3"])
                title_filigree._portableai_redraw()
            except Exception: pass
            try:
                if welcome_stage_border is not None: welcome_stage_border.apply_palette(COLORS)
                if welcome_ornament is not None: welcome_ornament.apply_palette(COLORS)
                if welcome_tagline is not None: welcome_tagline.configure(bg=COLORS["bg"],fg=COLORS["gold_shine"])
                if welcome_subtag is not None: welcome_subtag.configure(bg=COLORS["bg"],fg=COLORS["muted"])
            except Exception: pass
            for _cv_key,_cv in tab_scroll_canvases.items():
                try:
                    _parent=_cv.master
                    for _child in _parent.winfo_children():
                        if isinstance(_child,FiligreeScrollbar): _child.apply_palette(COLORS)
                except Exception: pass
            theme_native_scrollbars(app,COLORS)
            try:
                portal_help_decorator.apply_palette(COLORS)
            except Exception: pass
            try:
                apply_gold_scrollbar_palette(app, COLORS)
                upgrade_vertical_scrollbars(help_tab, COLORS)
                upgrade_vertical_scrollbars(chat_tab, COLORS)
            except Exception: pass
            try:
                portal_chat_frontend["overlay"].apply_palette(COLORS)
            except Exception: pass
            try:
                rebrand_widget_tree(help_tab, chat=False)
                rebrand_widget_tree(chat_tab, chat=True)
            except Exception: pass
        except Exception:
            pass
        # PORTABLEAI_TAB_BRAND_THEME_v15_134D
        try:
            for _badge in brand_corner_badges:
                _badge.configure(bg=COLORS["bg"])
            page_watermark.apply_palette(COLORS)
            portal_compact_mode._refresh_colors()
        except Exception:
            pass

        # Existing state labels may use semantic colors that were updated before
        # the recursive pass; refresh them from their current text state.
        try:
            for mapping in (services, activities, installed_rows):
                for _key, pair in mapping.items():
                    if not pair:
                        continue
                    state_widget = pair[0]
                    state_widget.configure(fg=color_for(state_widget.cget("text")))
        except Exception:
            pass

    def toggle_theme():
        nonlocal theme_mode
        old_mode = theme_mode
        theme_mode = "dark" if theme_mode == "light" else "light"
        apply_theme(THEMES[old_mode], THEMES[theme_mode])
        _save_theme_preference()
        try:
            log(f"Theme switched to {theme_mode} mode.")
        except Exception:
            pass

    # Busy-memory state mirrors old worker but lives in this one lightweight thread.
    busy_mem={k:{"since":None,"finger":"","change":time.time()} for k in ("qwen","comfy","ace","tts","musetalk","mmaudio")}
    last_gpu=0.0; gpu_cache=("GPU telemetry pending...",0.0)
    last_inventory=0.0; installed_cache=None
    observed_tool_pids={}
    last_agent_scan=0.0
    agent_cache=("IDLE","no Qwen inference or PortalAI tool call detected")
    last_media_probe=0.0
    media_cache=(("STOPPED",("localhost preview server; 8765-8780").replace('8765-8780', ''+str(_instance_port('preview')))),("OFFLINE","starts with PortalAI Startup"))
    last_opengui_probe=0.0
    opengui_cache=("STOPPED","Legacy OpenGUI not running")

    def observable_agent_state(qwen_activity, process_rows):
        workers = [row for row in process_rows if any(name in row['label'].lower()
            for name in ('tool', 'worker', 'proteinmpnn', 'ffmpeg', 'kicad', 'mafft', 'whisper', 'piper'))]
        if workers:
            return ('WORKERS', ' · '.join(f"{row['label']} (PID {row['pid']})" for row in workers[:8]))
        if qwen_activity[0] in ('PROCESSING','QUEUED','POSSIBLY STALLED'):
            return ('QWEN INFERENCE', qwen_activity[1])
        return ('IDLE', 'No current tool worker observed; short chat tools also report in the activity log.')

    def busy_state(key,busy,finger):
        m=busy_mem[key]; now=time.time()
        if not busy:
            m.update(since=None,finger=finger,change=now); return m
        if m["since"] is None:
            m.update(since=now,finger=finger,change=now); return m
        if m["finger"] != finger:
            m.update(finger=finger,change=now)
        return m

    def elapsed(t):
        if not t:return ""
        n=max(0,int(time.time()-t))
        if n>=3600:return f"{n//3600}h {(n%3600)//60}m"
        if n>=60:return f"{n//60}m {n%60}s"
        return f"{n}s"

    def gpu_state(data):
        if data.get('gpu') is None:
            return data.get('adapter', 'GPU counters unavailable'), 0.0
        summary = f"{data['adapter']} · {data['gpu']:.0f}% GPU"
        if data.get('vram_total'):
            summary += f" · {data['vram_used']:.1f}/{data['vram_total']:.1f} GiB VRAM"
        return summary, data['gpu']

    def qwen_state():
        h = qwen_health(cache_ttl=1.2)
        state = str(h.get("state") or "offline")
        model_name = str(h.get("model") or "Qwen")
        if state == "suspended":
            busy_state("qwen", False, "suspended")
            return (("SLEEPING", ("Server running on :8080 · weights unloaded to save memory").replace(':8080', ':'+str(_instance_port('qwen')))),
                    ("IDLE", "Reloads when chat needs it; idle sleep or a tool handoff"),
                    [f"{model_name} · sleeping (not resident)"])
        if not h.get("online"):
            busy_state("qwen", False, "offline")
            return (("STOPPED", ("llama.cpp; :8080").replace(':8080', ':'+str(_instance_port('qwen')))), ("OFFLINE", h.get("detail") or "server is not running"), [])
        models = [f"Qwen - {model_name}"] if model_name else []
        if not h.get("ready"):
            busy_state("qwen", False, "starting")
            return (("STARTING", h.get("detail") or ("server alive; model loading; :8080").replace(':8080', ':'+str(_instance_port('qwen')))), ("STARTING", "waiting for model readiness"), models)
        metrics = http_text(_instance_url('qwen', '/metrics'), .45)
        if not metrics:
            busy_state("qwen", False, "ready")
            return (("READY", (f"{model_name}; :8080").replace(':8080', ':'+str(_instance_port('qwen')))), ("IDLE", "ready; metrics endpoint unavailable"), models)
        processing = parse_prom_metric(metrics, "llamacpp:requests_processing") or 0
        deferred = parse_prom_metric(metrics, "llamacpp:requests_deferred") or 0
        prompt = parse_prom_metric(metrics, "llamacpp:prompt_tokens_total") or 0
        pred = parse_prom_metric(metrics, "llamacpp:tokens_predicted_total") or 0
        toksec = parse_prom_metric(metrics, "llamacpp:predicted_tokens_seconds")
        busy = processing > 0 or deferred > 0
        m = busy_state("qwen", busy, f"{processing}|{deferred}|{prompt}|{pred}")
        if not busy:
            act = ("IDLE", "no inference request active")
        elif processing > 0 and time.time() - m["change"] >= 90:
            act = ("POSSIBLY STALLED", f"busy {elapsed(m['since'])}; token counters unchanged for {int(time.time()-m['change'])}s")
        elif processing > 0:
            act = ("PROCESSING", f"active inference for {elapsed(m['since'])}" + (f"; {toksec:.1f} tok/s" if toksec and toksec > 0 else "") + f"; deferred={int(deferred)}")
        else:
            act = ("QUEUED", f"{int(deferred)} request(s) deferred")
        return (("READY", (f"{model_name}; :8080").replace(':8080', ':'+str(_instance_port('qwen')))), act, models)

    def comfy_state():
        if not port_open(_instance_port('comfyui')):
            busy_state("comfy",False,"offline"); return (("STOPPED",("on-demand; :8188").replace(':8188', ':'+str(_instance_port('comfyui')))),("OFFLINE","starts automatically when a media task needs it"))
        if http_text(_instance_url('comfyui', '/system_stats'),.7) is None:
            return (("PORT OPEN","ComfyUI port open; API unavailable"),("STARTING","status API is not responding"))
        info=http_json(_instance_url('comfyui', '/prompt'),.7) or {}
        try: remaining=int(info.get("exec_info",{}).get("queue_remaining",0))
        except Exception: remaining=0
        m=busy_state("comfy",remaining>0,str(remaining))
        if not remaining:return (("READY",("ComfyUI API; :8188").replace(':8188', ':'+str(_instance_port('comfyui')))),("IDLE","queue_remaining=0"))
        return (("READY",("ComfyUI API; :8188").replace(':8188', ':'+str(_instance_port('comfyui')))),("PROCESSING",f"queue_remaining={remaining}; active for {elapsed(m['since'])}"))

    def ace_state():
        if not port_open(_instance_port('acestep')):
            busy_state("ace",False,"offline"); return (("STOPPED",("on-demand; :8001").replace(':8001', ':'+str(_instance_port('acestep')))),("OFFLINE","starts automatically when a music task needs it"))
        if http_json(_instance_url('acestep', '/health'),.7) is None:
            return (("PORT OPEN","ACE-Step port open; API unavailable"),("STARTING","health endpoint is not responding"))
        stats=http_json(_instance_url('acestep', '/v1/stats'),.7)
        if not isinstance(stats,dict):return (("READY",("ACE-Step API; :8001").replace(':8001', ':'+str(_instance_port('acestep')))),("MONITORING UNAVAILABLE","/v1/stats did not respond"))
        jobs=((stats.get("data") or {}).get("jobs") or {}); data=stats.get("data") or {}
        def iv(k):
            try:return int(jobs.get(k,0))
            except:return 0
        running,queued,failed,succeeded=iv("running"),iv("queued"),iv("failed"),iv("succeeded")
        try:qsize=int(data.get("queue_size",0))
        except:qsize=0
        q=max(queued,qsize); m=busy_state("ace",running>0 or q>0,f"{running}|{q}|{failed}|{succeeded}")
        if not (running or q):act=("IDLE",f"running=0; queued=0; succeeded={succeeded}; failed={failed}")
        elif running:act=("PROCESSING",f"running={running}; queued={q}; active for {elapsed(m['since'])}")
        else:act=("QUEUED",f"{q} music job(s) waiting")
        return (("READY",("ACE-Step API; :8001").replace(':8001', ':'+str(_instance_port('acestep')))),act)



    def gpu_model_marker(process_rows):
        marker=runtime/"gpu_model_state.json"
        try:
            if not marker.exists(): return {}
            data=json.loads(marker.read_text(encoding="utf-8"))
            return data if isinstance(data,dict) and data.get('pid') in {row['pid'] for row in process_rows} else {}
        except Exception:
            return {}

    def _marker_matches(marker,*needles):
        service=str(marker.get("service") or "").strip().lower()
        stage=str(marker.get("stage") or marker.get("task") or "").strip().lower()
        hay=f"{service} {stage}"
        return any(n.lower() in hay for n in needles)

    def marker_models(marker):
        vals=marker.get("models") or []
        if isinstance(vals,str): vals=[vals]
        return [Path(str(v)).name if ("\\" in str(v) or "/" in str(v)) else str(v) for v in vals if str(v).strip()]

    def ondemand_state(component_installed,marker,*needles):
        active=bool(marker) and _marker_matches(marker,*needles)
        if active:
            stage=str(marker.get("stage") or marker.get("task") or "active")
            return (("READY","owned on-demand worker present"),("DECLARED STAGE",stage))
        if component_installed:
            return (("STOPPED","on-demand; starts automatically when needed"),("IDLE","no active job"))
        return (("NOT INSTALLED","component not detected"),("OFFLINE","runtime unavailable"))

    def science_state(process_rows):
        installed=(root/"Scientific"/"science_core.py").exists() and (root/"Agent"/"scientific_tool_bridge.py").exists()
        if not installed:
            return (("NOT INSTALLED","Science Workbench not detected"),("OFFLINE","runtime unavailable"))
        alive={row['pid'] for row in process_rows}
        active=[]
        for p in runtime.glob("science_activity_*.json"):
            try:
                d=json.loads(p.read_text(encoding="utf-8",errors="replace"));pid=int(d.get("pid") or 0)
                if pid in alive: active.append(d)
            except Exception: pass
        if active:
            d=active[-1];compute=str(d.get("compute") or "cpu").upper();op=str(d.get("operation") or "science")
            return (("ACTIVE",f"on-demand {compute} science workload"),("PROCESSING",op))
        return (("READY","on-demand CPU/RAM; no persistent science server"),("IDLE","CPU default; explicit OpenCL/CUDA uses the GPU lease and requires an installed plugin"))

    def installed_state():
        nonlocal last_inventory,installed_cache
        if installed_cache is not None and not force_scan.is_set() and time.time()-last_inventory<120:return installed_cache
        force_scan.clear(); r=root
        exists=lambda rel:(r/rel).exists()
        comps={}

        # Read command registry once per inventory refresh. This catches upgraded
        # feature installers without requiring the Control Center to know every
        # installer version number.
        ai_text=""
        try:
            ai_text=(r/"Agent"/"ai_tools.py").read_text(encoding="utf-8",errors="ignore")
        except Exception:
            pass
        def has_cmd(name):
            # Accept both one-line and multiline argparse declarations, e.g.
            #   p = sub.add_parser(
            #       "video-understand", aliases=[...]
            #   )
            pattern = r"add_parser\s*\(\s*['\"]" + re.escape(name) + r"['\"]"
            return re.search(pattern, ai_text, flags=re.IGNORECASE | re.DOTALL) is not None

        # v15.128e: capabilities added after the original Installed table.
        from bundle_inventory import inventory as inspect_bundle
        chat_inventory=inspect_bundle(root)
        qwen_server=any(chat_inventory["backends"].values())
        qwen_model=any(m["installed"] for m in chat_inventory["models"])
        comps["qwenCore"] = ("INSTALLED", "llama.cpp + local GGUF model stack") if qwen_server and qwen_model else (("PARTIAL", "server/model stack incomplete") if qwen_server or qwen_model else ("NOT INSTALLED", "local Qwen/llama.cpp stack not detected"))

        native_path = r / "ControlCenter" / "native_chat.py"
        native_ok = native_path.exists()
        try: native_text = native_path.read_text(encoding="utf-8", errors="ignore") if native_ok else ""
        except Exception: native_text = ""
        comps["nativeChat"] = ("INSTALLED", "native frontend + persistent local session history") if native_ok else ("NOT INSTALLED", "ControlCenter/native_chat.py not detected")
        memory_ok = exists("ControlCenter/persistent_memory.py")
        context_ok = native_ok and ("context_state" in native_text or "context budget" in native_text.lower())
        comps["contextMemory"] = ("INSTALLED", "rolling context + source-aware cross-session memory controls") if memory_ok and context_ok else (("PARTIAL", "context or persistent-memory layer incomplete") if memory_ok or context_ok else ("NOT INSTALLED", "context/memory layer not detected"))
        timer_ok = exists("ControlCenter/native_chat_timers_v15_128e.py") and "PORTABLEAI_NATIVE_CHAT_TIMER_LOADER_v15_128E" in native_text
        comps["liveTimers"] = ("INSTALLED", "live Qwen/tool-step timeline + total response timer") if timer_ok else ("NOT INSTALLED", "v15.128e live timer layer not detected")

        science_core=exists("Scientific/science_core.py") and exists("Agent/scientific_tool_bridge.py") and has_cmd("science")
        sp=r/"Runtime"/"ScientificPython"/"packages"
        def spkg(*names):
            return any((sp/n).exists() or any(sp.glob(n+"-*.dist-info")) or any(sp.glob(n.replace("-","_")+"-*.dist-info")) for n in names) if sp.exists() else False
        gmsh_ok=(sp/"gmsh.py").exists() and (any(sp.glob("gmsh*.dll")) or any(sp.rglob("gmsh*.dll")) or any(sp.rglob("gmsh.dll"))) if sp.exists() else False
        comps["science"]=("INSTALLED","deterministic foreground Science dispatcher; no persistent server") if science_core else ("NOT INSTALLED","Scientific/science_core.py + scientific_tool_bridge + science route required")
        comps["scienceCore"]=("INSTALLED","NumPy/SciPy/SymPy/Matplotlib; math, stats, signal; CPU/RAM on demand") if science_core and all(spkg(x) for x in ("numpy","scipy","sympy","matplotlib")) else ("PARTIAL","core scientific Python package set incomplete")
        comps["scienceCad"]=("INSTALLED","CadQuery + OCP + Gmsh; CAD model/blueprint/mesh inspection") if science_core and gmsh_ok and spkg("cadquery") and spkg("OCP","cadquery-ocp") else ("PARTIAL","CadQuery/OCP/Gmsh runtime incomplete")
        comps["scienceMech"]=("INSTALLED","beam, truss2d, rigid-body 2D simulation") if science_core and spkg("scipy") and spkg("pymunk") else ("PARTIAL","mechanical runtime incomplete")
        comps["scienceElectrical"]=("INSTALLED","DC/RC analysis + KiCad export") if science_core else ("NOT INSTALLED","Science core missing")
        comps["scienceChem"]=("INSTALLED","RDKit describe/render/conformer") if science_core and spkg("rdkit") else ("PARTIAL","RDKit not detected")
        comps["scienceGenomics"]=("INSTALLED","BioPython alignment/translation + SBOL circuit export") if science_core and spkg("Bio","biopython") and spkg("sbol3") else ("PARTIAL","BioPython/SBOL package set incomplete")
        comps["scienceProtein"]=("INSTALLED","PDB inspect/render + OpenMM minimization") if science_core and spkg("openmm") else ("PARTIAL","OpenMM not detected")
        comps["sciencePhysics"]=("INSTALLED","projectile, spring-mass, rigid-body 2D") if science_core and spkg("scipy") and spkg("pymunk") else ("PARTIAL","physics runtime incomplete")
        preview_ok = has_cmd("preview") or exists("Agent/media_preview_server.py") or exists("Services/media_preview_server.py")
        comps["mediaPreview"] = ("INSTALLED", "localhost output preview / return path") if preview_ok else ("NOT INSTALLED", "media preview route not detected")
        service_path = r / "Agent" / "service_manager.py"
        try: service_text = service_path.read_text(encoding="utf-8", errors="ignore") if service_path.exists() else ""
        except Exception: service_text = ""
        gpu_handoff = "qwen_gpu_handoff_begin" in service_text and "acquire_gpu_lease" in service_text
        comps["gpuHandoff"] = ("INSTALLED", "exclusive GPU lease + Qwen VRAM release/restore") if gpu_handoff else ("NOT INSTALLED", "GPU handoff/lease layer not detected")
        comps["scienceGpu"]=("INSTALLED","explicit OpenMM CUDA only; global GPU lease + Qwen handoff/restore; no persistent VRAM") if science_core and spkg("openmm") and "science_workload" in service_text and "openmm-cuda" in service_text else ("PARTIAL","Science CUDA lease path incomplete")
        diag_ok = exists("Tools/component_diagnostics.py") and exists("Tools/maintenance_storage.py")
        comps["diagnostics"] = ("INSTALLED", "component diagnosis + storage/deep-duplicate reporting") if diag_ok else (("PARTIAL", "diagnostic/report toolset incomplete") if exists("Tools/component_diagnostics.py") or exists("Tools/maintenance_storage.py") else ("NOT INSTALLED", "diagnostic/storage tools not detected"))
        maintenance_ok = exists("ControlCenter/maintenance_cleanup.py") and exists("Tools/storage_current.py")
        comps["maintenance"] = ("INSTALLED", "cleanup/recovery + webcache/output/conversation deletion controls") if maintenance_ok else (("PARTIAL", "maintenance/cleanup toolset incomplete") if exists("ControlCenter/maintenance_cleanup.py") else ("NOT INSTALLED", "maintenance cleanup layer not detected"))

        # Qwen3-TTS
        voice=[exists("Runtime/BootstrapPython/python.exe") and exists("Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts"),exists("Voice/Qwen3-TTS/models/Qwen3-TTS-12Hz-1.7B-VoiceDesign"),exists("Voice/Qwen3-TTS/models/Qwen3-TTS-12Hz-1.7B-Base")]
        comps["voice"]=("INSTALLED","local runtime + core voice models; one-shot") if all(voice) else (("PARTIAL","runtime/model incomplete") if any(voice) else ("NOT INSTALLED","Qwen3-TTS not detected"))

        # Speech-to-text / faster-whisper
        stt_code=exists("Agent/stt_bridge.py") and exists("Agent/stt_worker.py") and has_cmd("transcribe")
        stt_runtime=(r/"SpeechToText"/"python_packages").exists()
        stt_models=r/"SpeechToText"/"models"
        stt_model_cached=stt_models.exists() and any(stt_models.rglob("*"))
        if stt_code and stt_runtime:
            comps["stt"]=("INSTALLED", "faster-whisper; one-shot; model cached" if stt_model_cached else "faster-whisper; one-shot; model downloads on first use")
        elif stt_code or stt_runtime:
            comps["stt"]=("PARTIAL","STT code/runtime incomplete")
        else:
            comps["stt"]=("NOT INSTALLED","faster-whisper STT not detected")

        # MuseTalk / visible-dialogue pipeline
        muse_bridge=exists("Agent/musetalk_bridge.py")
        muse_runtime=any((r/x).exists() for x in ("Video/MuseTalk","MuseTalk","Video/MuseTalk-1.5","Generative/MuseTalk"))
        muse_cmd=has_cmd("lip-sync") and has_cmd("video-dialogue") and has_cmd("dialogue-video")
        if muse_bridge and (muse_runtime or muse_cmd):
            comps["musetalk"]=("INSTALLED","MuseTalk 1.5 bridge + dialogue/lip-sync routes; one-shot")
        elif muse_bridge or muse_cmd:
            comps["musetalk"]=("PARTIAL","MuseTalk bridge/routes detected; runtime path not confirmed")
        else:
            comps["musetalk"]=("NOT INSTALLED","MuseTalk dialogue pipeline not detected")

        # Explicit dialogue routes.
        dialogue_cmds = all(has_cmd(x) for x in ("dialogue-video", "video-dialogue", "lip-sync"))
        comps["dialogue"] = ("INSTALLED","atomic visible-dialogue + lip-sync routes") if dialogue_cmds else ("NOT INSTALLED","dialogue routes not detected")

        # MMAudio / SFX layer.
        # v15.72+: validate the real portable source + private runtime, not merely
        # the presence of the command/bridge. Current portable layout is
        # Services/MMAudio + Runtime/MMAudioPython/python.exe.
        sfx_bridge=exists("Agent/sfx_bridge.py")
        sfx_cmd=has_cmd("sfx"); video_sfx_cmd=has_cmd("video-sfx"); sfx_inpaint_cmd=has_cmd("sfx-inpaint")
        mmaudio_source_candidates=(
            "Services/MMAudio", "Engines/MMAudio", "External/MMAudio",
            "ThirdParty/MMAudio", "Tools/MMAudio", "MMAudio", "Agent/MMAudio",
        )
        mmaudio_python_candidates=(
            "Runtime/MMAudioPython/python.exe",
            "Runtime/MMAudioPython/Scripts/python.exe",
            "Runtime/MMAudio/python.exe",
            "Runtime/Python312_MMAudio/python.exe",
            "Agent/.runtime/mmaudio/python.exe",
            "Agent/.runtime/mmaudio/Scripts/python.exe",
        )
        mmaudio_source=next((x for x in mmaudio_source_candidates if exists(x + "/demo.py")), None)
        mmaudio_python=next((x for x in mmaudio_python_candidates if exists(x)), None)
        mmaudio_runtime=bool(mmaudio_source and mmaudio_python)
        if sfx_bridge and sfx_cmd and mmaudio_runtime:
            comps["sfx"]=("INSTALLED",f"MMAudio portable runtime; {mmaudio_source}; on-demand")
        elif sfx_bridge or sfx_cmd or mmaudio_source or mmaudio_python:
            missing=[]
            if not sfx_bridge: missing.append("bridge")
            if not sfx_cmd: missing.append("sfx command")
            if not mmaudio_source: missing.append("Services/MMAudio source")
            if not mmaudio_python: missing.append("Runtime/MMAudioPython")
            comps["sfx"]=("PARTIAL","missing: " + ", ".join(missing))
        else:
            comps["sfx"]=("NOT INSTALLED","MMAudio SFX layer not detected")
        comps["videoSfx"]=("INSTALLED","native video-conditioned synchronized Foley/SFX") if sfx_bridge and video_sfx_cmd and mmaudio_runtime else (("PARTIAL","video-sfx route/runtime incomplete") if sfx_bridge or video_sfx_cmd or mmaudio_runtime else ("NOT INSTALLED","video-sfx route not detected"))
        comps["sfxInpaint"]=("INSTALLED","localized semantic SFX repair/replacement on audio or video") if sfx_inpaint_cmd else ("NOT INSTALLED","sfx-inpaint route not detected")

        # FLUX image stack
        official=exists("Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/flux-2-klein-base-9b-fp8.safetensors")
        alt=exists("Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/flux-2-klein-base-9b-uncensored.safetensors")
        comps["fluxOfficial"]=("INSTALLED","9B FP8 checkpoint detected") if official else ("MISSING","official checkpoint not detected")
        comps["fluxAlt"]=("INSTALLED","alternative checkpoint detected") if alt else ("MISSING","alternative checkpoint not detected")
        wf=exists("Workflows/API/Flux2_Klein_9B_T2I_Official_FP8.json") and exists("Workflows/API/Flux2_Klein_9B_Image_Edit_Official_FP8.json")
        comps["imageEdit"]=("INSTALLED","generation + whole-image editing") if wf and official else ("PARTIAL","checkpoint/workflow incomplete")
        iwf=exists("Workflows/API/Flux2_Klein_9B_Inpaint_Official_FP8.json") and exists("Workflows/API/Flux2_Klein_9B_Inpaint_Uncensored.json")
        samdir=r/"Generative/ComfyUI_windows_portable/ComfyUI/models/sam2"; gdir=r/"Generative/ComfyUI_windows_portable/ComfyUI/models/grounding-dino"
        samplugin=exists("Generative/ComfyUI_windows_portable/ComfyUI/custom_nodes/ComfyUI-SAM2")
        inpaint=iwf and samplugin and samdir.exists() and any(samdir.iterdir()) and gdir.exists() and any(gdir.iterdir())
        comps["inpaint"]=("INSTALLED","FLUX inpaint + GroundingDINO/SAM2 masking") if inpaint else ("PARTIAL","workflow/plugin/model incomplete")

        # Wan I2V + VACE V2V
        wan=exists("Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors") and exists("Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors") and exists("Workflows/API/Wan2.2_14B_I2V_Official.json")
        comps["video"]=("INSTALLED","Wan 2.2 14B I2V; on-demand via ComfyUI") if wan else ("PARTIAL","Wan model/workflow incomplete")
        vace_model=exists("Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.1_vace_14B_fp16.safetensors")
        vace_workflow=exists("Workflows/API/Wan2.1_VACE_14B_V2V_API.json")
        vace_code=has_cmd("video-edit")
        if vace_model and vace_workflow and vace_code:
            comps["vace"]=("INSTALLED","Wan2.1 VACE 14B V2V; on-demand via ComfyUI")
        elif vace_model or vace_workflow or vace_code:
            comps["vace"]=("PARTIAL","VACE command/workflow/model stack incomplete")
        else:
            comps["vace"]=("NOT INSTALLED","VACE video-edit stack not detected")

        # General video understanding / comprehension
        vu_bridge=exists("Agent/video_understanding_bridge.py")
        vu_cmd=has_cmd("video-understand") or has_cmd("video-analyze")
        if vu_bridge and vu_cmd:
            comps["videoUnderstand"]=("INSTALLED","adaptive frame sampling + multimodal Qwen + optional STT; on-demand")
        elif vu_bridge or vu_cmd:
            comps["videoUnderstand"]=("PARTIAL","video-understanding bridge/command incomplete")
        else:
            comps["videoUnderstand"]=("NOT INSTALLED","video-understand route not detected")

        video_range_cmd=has_cmd("video-range-edit")
        comps["videoRange"] = (
            ("INSTALLED", "video-range-edit route detected")
            if video_range_cmd else
            ("ROUTE MISSING", "video-range-edit command is not registered in current Agent/ai_tools.py")
        )

        music_understand_bridge=exists("Agent/music_understanding_bridge.py")
        music_understand_cmd=has_cmd("music-understand")
        comps["musicUnderstand"]=("INSTALLED","audio/music feature analysis + focused questions") if music_understand_bridge and music_understand_cmd else (("PARTIAL","music-understanding bridge/route incomplete") if music_understand_bridge or music_understand_cmd else ("NOT INSTALLED","music-understand route not detected"))

        # ACE-Step
        ace=exists("Music/ACE-Step-1.5/acestep") and exists("Music/ACE-Step-1.5/checkpoints")
        comps["music"]=("INSTALLED","ACE-Step 1.5 local runtime; on-demand") if ace else ("PARTIAL","ACE-Step runtime/checkpoints incomplete")

        # Deterministic post-edit + experimental diffusion media inpainting
        media_bridge=exists("Agent/media_edit_bridge.py")
        det_cmds=all(has_cmd(x) for x in ("media-info","audio-edit","audio-mix","video-adjust"))
        comps["mediaEdit"]=("INSTALLED","FFmpeg post-edit stack: audio/video/mix/info") if media_bridge and det_cmds else (("PARTIAL","media editor bridge/commands incomplete") if media_bridge or det_cmds else ("NOT INSTALLED","deterministic media-edit tools not detected"))
        audio_inp=media_bridge and has_cmd("audio-inpaint")
        video_inp=media_bridge and has_cmd("video-inpaint")
        comps["audioInpaint"]=("INSTALLED","experimental spectrogram-domain diffusion; on-demand") if audio_inp else ("NOT INSTALLED","audio-inpaint route not detected")
        comps["videoInpaint"]=("INSTALLED","experimental masked framewise diffusion; on-demand") if video_inp else ("NOT INSTALLED","video-inpaint route not detected")

        # Web tool layer
        web=exists("Agent/web_tools.py")
        comps["webTools"]=("INSTALLED","search / fetch / research / real-image retrieval") if web else ("NOT INSTALLED","Agent/web_tools.py not detected")

        # Inventory panes remain model-file inventories, not feature lists.
        from bundle_inventory import media_model_files
        models,loras=media_model_files(r)
        comps.update(current_installed_rows(root))
        try:
            locks=json.loads((root/"Agent/.runtime/component_runtime_locks.json").read_text(encoding="utf-8"))
            if locks.get("components",{}).get("musetalk",{}).get("status")=="PROBE_FAILED":
                # This legacy cache has no freshness guarantee. It cannot
                # replace current file/route detection with a present failure.
                for key in ('musetalk', 'dialogue'):
                    if key in comps:
                        state, detail = comps[key]
                        comps[key] = (state, detail + '; historical cached MuseTalk probe failed; rerun diagnosis for current evidence')
        except (OSError,ValueError): pass
        installed_cache=(comps,models,loras); last_inventory=time.time(); return installed_cache

    def snapshot():
        activity_sample = activity_sampler.sample()
        process_rows, process_events = runtime_activity.processes()
        stages, stage_events = runtime_activity.lifecycle(process_rows)
        gpu_summary,gpu_util=gpu_state(activity_sample)
        qserver,qact,qmodels=qwen_state()
        cserver,cact=comfy_state()
        aserver,aact=ace_state()
        agentact=observable_agent_state(qact, process_rows)
        science_server,science_act=science_state(process_rows)
        nonlocal last_media_probe,media_cache,last_opengui_probe,opengui_cache
        now=time.time()
        if now-last_media_probe>=20.0:
            found_preview = None
            occupied_preview = None
            for preview_port in range(_instance_port('preview'), (_instance_port('preview')+1)):
                if not port_open(preview_port):
                    continue
                media_health=http_json(f"http://127.0.0.1:{preview_port}/__health__",.5)
                if isinstance(media_health,dict) and media_health.get("ok"):
                    found_preview = preview_port
                    break
                if occupied_preview is None:
                    occupied_preview = preview_port
            if found_preview is not None:
                media_cache=(("READY",f"Outputs preview server; :{found_preview}"),("IDLE","serves generated Outputs on demand"))
            elif occupied_preview is not None:
                media_cache=(("PORT OPEN",f"preview port :{occupied_preview} open; health unavailable"),("STARTING","waiting for preview health endpoint"))
            else:
                media_cache=(("STOPPED",("localhost preview server; 8765-8780").replace('8765-8780', ''+str(_instance_port('preview')))),("OFFLINE","starts with PortalAI Startup"))
            last_media_probe=now
        media,mact=media_cache
        if now-last_opengui_probe>=20.0:
            opath=runtime/"opengui_path.txt"; expected=None
            try:
                if opath.exists(): expected=Path(opath.read_text(encoding="utf-8").strip())
            except Exception: pass
            opengui_cache=("READY","Legacy OpenGUI process detected") if process_named("OpenGUI.exe",expected) else ("STOPPED","Legacy OpenGUI not running")
            last_opengui_probe=now
        op=opengui_cache
        comps,models,loras=installed_state()
        marker=gpu_model_marker(process_rows); active_models=marker_models(marker)
        tts_server,tts_act=ondemand_state(comps.get("voice",("NOT INSTALLED",""))[0] in ("INSTALLED","PARTIAL"),marker,"qwen3-tts","tts","voice")
        muse_server,muse_act=ondemand_state(comps.get("musetalk",("NOT INSTALLED",""))[0] in ("INSTALLED","PARTIAL"),marker,"musetalk","lip-sync","dialogue")
        if comps.get("musetalk", ("", ""))[1].startswith("Last interpreter probe failed"):
            muse_server=("CHECK RUNTIME","Last interpreter probe failed; run targeted diagnosis")
        mma_server,mma_act=ondemand_state(comps.get("sfx",("NOT INSTALLED",""))[0] in ("INSTALLED","PARTIAL"),marker,"mmaudio","sfx","foley")
        model_lines=list(qmodels)
        if marker:
            svc=str(marker.get("service") or "").strip()
            if svc and active_models: model_lines.extend([f"{svc} - {x}" for x in active_models])
        def active_for(*needles):
            return active_models if marker and _marker_matches(marker,*needles) else []
        from bundle_inventory import inventory as bundle_inventory
        from runtime_policy import load_effective_policy
        policy_sampled_at = time.monotonic()
        current_policy=bundle_inventory(root, policy=load_effective_policy(root))
        from effort_policy import load_preferences as load_effort_preferences
        saved_effort = load_effort_preferences(root)
        cfg=current_policy["policy"];budget=current_policy["storage"]
        from mission_runner import Missions, ACTIVE
        from mission_supervisor import read_policy
        mission_store=Missions(root)
        armed=[m["id"] for m in mission_store.list() if not m.get("parent") and m["status"] in ACTIVE and read_policy(mission_store,m["id"]).get("enabled")]
        if private_path(root, "Data/Missions/supervisor.stop").exists(): armed=[]
        runtime_models={
            "policy":[f"Selection: {cfg.get('selection')} / {cfg.get('backend')} / context ≤ {cfg.get('context_tokens')}",
                      f"Free {budget['free_bytes']/1024**3:.1f} GiB; output reserve {budget['output_reserve_bytes']/1024**3:.0f} GiB; floor {budget['minimum_free_bytes']/1024**3:.1f} GiB"],
            "missions":[f"Armed roots: {len(armed)}. Stop/Exit pauses missions; interrupted actions need review.",
                        "Full = host; Observe = capability restriction; VM = offline guest shell only."],
            "qwen":qmodels or ["No Qwen model currently reported loaded."],
            "comfy":active_for("comfy","flux","wan","vace") or ["No ComfyUI model currently reported loaded."],
            "ace":active_for("ace","music") or ["No ACE-Step model currently reported loaded."],
            "tts":active_for("qwen3-tts","tts","voice") or ["On-demand • no TTS model currently loaded."],
            "musetalk":active_for("musetalk","lip-sync","dialogue") or ["On-demand • no MuseTalk model currently loaded."],
            "mmaudio":active_for("mmaudio","sfx","foley") or ["On-demand • no MMAudio model currently loaded."],
            "science":["No persistent Science model • CPU/RAM on demand", "OpenMM CPU default; explicit OpenCL/CUDA requires installed plugin/device; leased handoff"],
            "media":["Output preview server • no ML model"],
                        "opengui":["Legacy OpenGUI fallback application"],
        }
        return {
            'process_text':format_processes(process_rows, activity_sample.get('gpu_processes'), activity_sample.get('process_counters'))+'\n\n'+'\n'.join(stages),
            'observed_events':process_events+stage_events,
            'settings_models':current_policy['models'],
            'settings_policy':current_policy['policy'], 'saved_effort':saved_effort,
            'policy_sampled_at':policy_sampled_at,
            'storage_budget':budget,
            "services":{"policy":("SAVED","Settings apply on next startup; loaded chat is shown separately"),"missions":("ARMED" if armed else "PAUSED","Persistent state on SSD; computer must remain on"),"qwen":qserver,"comfy":cserver,"ace":aserver,"tts":tts_server,"musetalk":muse_server,"mmaudio":mma_server,"science":science_server,"media":media,"opengui":op},
            "activity":{"agent":agentact,"qwen":qact,"comfy":cact,"ace":aact,"tts":tts_act,"musetalk":muse_act,"mmaudio":mma_act,"science":science_act,"media":mact},
            "telemetry":activity_sample,"runtime_models":runtime_models,"gpu":gpu_summary,"gpu_models":model_lines,
            "installed":comps,"models":models,"loras":loras,
        }

    def worker():
        # Lightweight always-on monitor. All probes/scans run off Tk's main thread.
        try:
            while not stop_worker.is_set():
                try:
                    event_q.put(("snapshot", snapshot()))
                except Exception as exc:
                    event_q.put(("log", f"Status monitor error: {type(exc).__name__}: {exc}"))
                stop_worker.wait(5.0)
        finally: activity_sampler.close()

    status_worker_started = False

    def _ensure_status_worker():
        nonlocal status_worker_started
        if status_worker_started or stop_worker.is_set():
            return
        status_worker_started = True
        gui_jobs.thread(target=worker, name="PortableAIStatus", daemon=True).start()

    
    from lifecycle_control import StartupGate, startup_result
    startup_gate = StartupGate()
    executable_repair = None

    def start_components():
        """Start or adopt the selected model through the native lifecycle helper."""
        script = root / "Launchers" / "Start_PortableAI_Native_v15_133.py"
        if os.name!='nt':script=root/'Agent/linux_lifecycle.py'
        stop_lock = getattr(stop_components, "_lock", None)
        if exit_in_progress or (stop_lock is not None and stop_lock.locked()):
            log("Wait for Stop to complete before Startup."); return
        if settings_page._busy:
            log('Startup is already applying the selected settings.'); return
        try:
            if not settings_page.commit_for_startup():
                detail = settings_page.status.get()
                control_progress.set(detail)
                log('Startup not started: ' + detail)
                show_tab('settings')
                return
        except Exception as exc:
            control_progress.set(f'Startup not started: {exc}'); log(control_progress.get()); return
        ticket = startup_gate.ticket()
        requested_at = time.time()
        py = Path(bootstrap_python(root))
        if not py.exists() or not script.exists():
            detail = f"Missing startup dependency:\n{py if not py.exists() else script}"
            log(detail)
            try: launcher_notice("PortalAI Startup", detail, kind="error")
            except Exception: pass
            return
        lock = getattr(start_components, "_lock", None)
        if lock is None:
            lock = threading.Lock(); start_components._lock = lock
        if not lock.acquire(blocking=False):
            log("PortalAI Startup is already running."); return
        settings_page.set_startup_busy(True)
        startup_button.configure(state='disabled')
        control_progress.set('Startup: applying ' + settings_page.startup_summary())
        try: set_pair(services, "qwen", "STARTING", "Qwen startup running in background")
        except Exception: pass
        log('Startup requested: ' + settings_page.startup_summary())
        def _launch():
            try:
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                child = startup_gate.launch(ticket, lambda: subprocess.Popen(
                    [str(py), str(script), *(['start'] if os.name!='nt' else []), '--requested-at', str(requested_at), "--root", str(root)], cwd=str(root),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace", creationflags=flags))
                try: stdout, stderr = child.communicate(timeout=440)
                except subprocess.TimeoutExpired:
                    child.kill(); child.communicate(); raise
                cp = subprocess.CompletedProcess(child.args, child.returncode, stdout, stderr)
                result = startup_result(root, cp, requested_at)
                result['ticket'] = ticket
                event_q.put(("startup_result", result))
            except subprocess.TimeoutExpired:
                event_q.put(("startup_result", {"ok":False,"ticket":ticket,"detail":"Startup timed out after 440 seconds. Check the Control Log and chat model log.","returncode":-1}))
            except Exception as exc:
                event_q.put(("startup_result", {"ok":False,"ticket":ticket,"detail":f"{type(exc).__name__}: {exc}","returncode":-1}))
            finally:
                try: lock.release()
                except Exception: pass
        gui_jobs.thread(target=_launch,name="PortableAINativeStart",daemon=True).start()

    def launch_legacy_openwebui():
        if account_gate is not None:
            launcher_notice("Legacy OpenWebUI", "Use Native Chat in account mode. Legacy frontend account isolation has not been verified.", kind="warn")
            return
        helper = root / "Tools" / "openwebui_legacy.py"
        py = root / "Runtime" / "BootstrapPython" / "pythonw.exe"
        if not helper.exists():
            launcher_notice("Legacy OpenWebUI", f"Legacy OpenWebUI helper is missing:\n{helper}", kind="error")
            return
        try:
            p=hidden_popen([str(py),str(helper),"--root",str(root),"start","--open"],cwd=root)
            log((f"Legacy OpenWebUI requested (helper PID {p.pid}) on http://127.0.0.1:3000; Qwen remains on :8080.").replace(':8080', ':'+str(_instance_port('qwen'))))
            set_pair(services,"openwebui","STARTING","starting local browser frontend on :3000")
        except Exception as exc:
            launcher_notice("Legacy OpenWebUI", f"Legacy OpenWebUI failed to start:\n{exc}", kind="error")
            log(f"Legacy OpenWebUI launcher failed: {exc}")

    def _stop_legacy_openwebui_quiet():
        helper = root / "Tools" / "openwebui_legacy.py"
        py = root / "Runtime" / "BootstrapPython" / "python.exe"
        if not helper.exists() or not py.exists():
            return
        try:
            hidden_run([str(py),str(helper),"--root",str(root),"stop"],timeout=12,cwd=root)
        except Exception as exc:
            log(f"Legacy OpenWebUI stop warning: {exc}")

    def launch_legacy_opengui():
        if account_gate is not None:
            launcher_notice("Legacy OpenGUI", "Use Native Chat in account mode. Legacy frontend account isolation has not been verified.", kind="warn")
            return
        launcher = root/"Launchers"/"Start_OpenGUI_Qwen.bat"
        if launcher.exists():
            try:
                p=hidden_popen(["cmd.exe","/d","/c",str(launcher)],cwd=root)
                log(f"Legacy OpenGUI requested (launcher PID {p.pid}). Native Chat remains the primary frontend.")
                return
            except Exception as exc:
                log(f"Legacy OpenGUI launcher failed: {exc}")
        candidates = [
            root/"OpenGUI"/"OpenGUI.exe",
            root/"OpenGUI"/"opengui.exe",
        ]
        try:
            ogdir = root/"OpenGUI"
            if ogdir.exists():
                candidates.extend(sorted(ogdir.rglob("OpenGUI*.exe")))
        except Exception:
            pass
        exe = next((x for x in candidates if x.exists() and "unins" not in x.name.lower() and "uninstall" not in x.name.lower()), None)
        if exe is None:
            launcher_notice("Legacy OpenGUI", "Legacy OpenGUI was not found.\n\nNative Chat is already available in the Chat tab.", kind="warn")
            return
        try:
            subprocess.Popen([str(exe)], cwd=str(exe.parent))
            log(f"Legacy OpenGUI opened: {exe}")
        except Exception as exc:
            launcher_notice("Legacy OpenGUI", f"Legacy OpenGUI failed to open:\n{exc}", kind="error")

    def _release_chat_audio_before_process_cleanup():
        try:
            if native_chat_panel is not None and hasattr(native_chat_panel, "release_audio_capture"):
                native_chat_panel.release_audio_capture()
                log("Chat microphone capture released cleanly before process cleanup.")
        except Exception as exc:
            log(f"Microphone release warning: {exc}")

    def stop_components():
        """Cancel chat, pause missions and stop owned workers."""
        startup_gate.cancel()
        control_progress.set('Stopping owned components; pending Startup is cancelled.')
        if native_chat_panel is not None:
            native_chat_panel.stop_generation()
            # Cancel metadata/seek callbacks before the helper stops processes;
            # a late duration result must never restart a stopped preview.
            native_chat_panel._stop_embedded_media()
        _release_chat_audio_before_process_cleanup()
        _stop_legacy_openwebui_quiet()
        script=root/"Launchers"/"Stop_PortableAI.py"; py=Path(bootstrap_python(root))
        if not script.exists() or not py.exists():
            detail=f"Missing stop dependency:\n{script if not script.exists() else py}"; log(detail); return
        lock=getattr(stop_components,"_lock",None)
        if lock is None: lock=threading.Lock(); stop_components._lock=lock
        if not lock.acquire(blocking=False): log("Stop all components is already running."); return
        log("Stopping all PortalAI-managed components, including active on-demand workers...")
        def _job():
            try:
                flags=getattr(subprocess,"CREATE_NO_WINDOW",0) if os.name=="nt" else 0
                cp=subprocess.run([str(py),str(script),"--root",str(root),"--include-opengui"],cwd=str(root),capture_output=True,text=True,errors="replace",timeout=120,creationflags=flags)
                detail=((cp.stdout or "")+("\n"+cp.stderr if cp.stderr else "")).strip()
                event_q.put(("stop_result",{"ok":cp.returncode==0,"detail":detail or f"Stop helper exited {cp.returncode}."}))
            except Exception as exc:event_q.put(("stop_result",{"ok":False,"detail":f"{type(exc).__name__}: {exc}"}))
            finally:
                try: lock.release()
                except Exception: pass
        gui_jobs.thread(target=_job,name="PortableAIStopAll",daemon=True).start()

    tray_hidden = False
    exit_in_progress = False
    shutdown_status = None


    # ------------------------------------------------------------------
    # Internal Control Center panels: PortableAI-owned reports/notices stay in
    # this launcher instead of creating unrelated desktop popup windows.
    # ------------------------------------------------------------------
    launcher_panel_state = {"overlay": None}

    def close_launcher_panel():
        overlay = launcher_panel_state.get("overlay")
        launcher_panel_state["overlay"] = None
        if overlay is not None:
            try: overlay.destroy()
            except Exception: pass

    def open_launcher_panel(title: str, *, width: float = 0.82, height: float = 0.82):
        close_launcher_panel()
        overlay = tk.Frame(tab_host, bg="#0B0E11", highlightthickness=0, bd=0)
        overlay._portalai_launcher_sheet=True
        overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        overlay.lift()
        launcher_panel_state["overlay"] = overlay
        card = tk.Frame(overlay, bg=COLORS["panel"], highlightthickness=0)
        _decorate_soft_frame(card,corner_size=18)
        card.place(relx=0.5, rely=0.5, anchor="center", relwidth=max(0.42, min(0.96, width)),
                   relheight=max(0.30, min(0.96, height)))
        head = tk.Frame(card, bg=COLORS["panel2"]); head.pack(fill="x",padx=13,pady=(13,0))
        label(head, title, 11, bold=True).pack(side="left", fill="x", expand=True, padx=12, pady=8)
        ElegantButton(head, text="✕", command=close_launcher_panel, bg=COLORS["panel2"], fg=COLORS["muted"],
                  activebackground=COLORS["bad"], activeforeground="#ffffff", relief="flat", bd=0,
                  padx=10, pady=6, cursor="hand2").pack(side="right", padx=4, pady=3)
        body_panel = tk.Frame(card, bg=COLORS["panel"]); body_panel.pack(fill="both", expand=True,padx=13,pady=(0,13))
        overlay.bind("<Escape>", lambda _e: close_launcher_panel())
        try: overlay.focus_set()
        except Exception: pass
        return body_panel

    def launcher_notice(title: str, text: str, *, kind: str = "error"):
        body_panel = open_launcher_panel(title, width=0.76, height=0.62)
        color = COLORS["bad"] if kind == "error" else COLORS["warn"] if kind == "warn" else COLORS["text"]
        viewer = RoundedText(body_panel,palette=COLORS,scrollbars=True,bg=COLORS["model_bg"], fg=color, insertbackground=COLORS["text"], font=(mono_font(app), 9), wrap="word", padx=4, pady=4)
        rounded_readouts.append(viewer)
        viewer.pack(fill="both", expand=True, padx=16, pady=(16, 8)); viewer.insert("1.0", str(text)); viewer.configure(state="disabled")
        def copy_all():
            try: app.clipboard_clear(); app.clipboard_append(str(text)); app.update_idletasks()
            except Exception: pass
        viewer.bind("<Control-a>", lambda e: (viewer.tag_add("sel","1.0","end-1c"),"break")[1])
        viewer.bind("<Control-c>", lambda e: None)
        row = tk.Frame(body_panel, bg=COLORS["bg"]); row.pack(fill="x", padx=16, pady=(0, 14))
        row.pack_configure(before=viewer.frame)
        ElegantButton(row, text="Copy to clipboard", command=copy_all, bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=14, pady=7).pack(side="left")
        ElegantButton(row, text="Close", command=close_launcher_panel, bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=16, pady=7).pack(side="right")

    def recovery_guard_factory(writing=False):
        from profile_paths import capture
        context=capture(root);ticket=startup_gate.ticket()
        def guard():
            if exit_in_progress or (account_gate is not None and account_gate.locked):
                raise PermissionError('Recovery cancelled because the account is closing or locked.')
            if capture(root)!=context or startup_gate.ticket()!=ticket:
                raise PermissionError('Recovery cancelled by Stop or a login change. Re-enable antivirus protection.')
            if writing and account_gate is not None and account_gate.session.role!='admin':
                raise PermissionError('Sign in as a PortalAI administrator to repair shared runtime files. Re-enable antivirus protection.')
        return guard

    def repair_executables():
        if executable_repair is not None:executable_repair.request(manual=True)

    sys.path.insert(0, str(root / "Tools"))
    from maintenance_reports import run_tool, saved_status
    maintenance_lock = threading.Lock()
    maintenance_reruns = {}
    maintenance_dir = private_path(root, "Data/Maintenance")
    MAX_INLINE_REPORT_CHARS = 220_000

    def _maintenance_report_path(report_key: str, previous: bool = False) -> Path:
        slot = "previous" if previous else "latest"
        return maintenance_dir / f"{report_key}_{slot}.txt"

    def _read_maintenance_report(report_key: str, previous: bool = False) -> tuple[str, Path | None]:
        p = _maintenance_report_path(report_key, previous)
        if not p.exists():
            return "", None
        try:
            return p.read_text(encoding="utf-8", errors="replace"), p
        except Exception as exc:
            return f"Could not read report: {exc}", p

    def _show_text_report(title: str, text: str, *, ok: bool = True, report_key: str | None = None, previous: bool = False):
        body_panel = open_launcher_panel(title, width=0.92, height=0.90)
        label(body_panel, "PREVIOUS" if previous else ("COMPLETE" if ok else "NEEDS ATTENTION"), 12,
              fg=COLORS["muted"] if previous else (COLORS["good"] if ok else COLORS["bad"]), bold=True).pack(fill="x", padx=14, pady=(12, 3))
        if report_key:
            path = _maintenance_report_path(report_key, previous)
            label(body_panel, str(path), 8, fg=COLORS["muted"], wraplength=900, justify="left").pack(fill="x", padx=14, pady=(0, 6))
        box = RoundedText(body_panel,palette=COLORS,scrollbars=True,bg=COLORS.get("model_bg", COLORS["panel"]), fg=COLORS["text"],
                           insertbackground=COLORS["text"], relief="flat", bd=0,
                           font=("Cascadia Mono", 9), wrap="word", padx=10, pady=10)
        box.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        rounded_readouts.append(box)
        full_text = text or "No report text returned."
        shown = full_text
        truncated = len(full_text) > MAX_INLINE_REPORT_CHARS
        if truncated:
            head = full_text[:170_000]
            tail = full_text[-35_000:]
            shown = head + "\n\n… [middle omitted from initial view; use Load full report] …\n\n" + tail
        box.insert("1.0", shown); box.configure(state="disabled")
        row = tk.Frame(body_panel, bg=COLORS["bg"]); row.pack(fill="x", padx=14, pady=(0, 12))
        row.pack_configure(before=box.frame)
        def copy_report():
            app.clipboard_clear();app.clipboard_append(full_text);app.update_idletasks()
        ElegantButton(row,text='Copy to clipboard',command=copy_report,bg=COLORS['button'],fg=COLORS['text'],
                      relief='flat',bd=0,padx=12,pady=7).pack(side='left',padx=(0,6))
        if truncated:
            def load_full():
                box.configure(state="normal"); box.delete("1.0", "end"); box.insert("1.0", full_text); box.configure(state="disabled")
            ElegantButton(row, text="Load full report", command=load_full, bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=12, pady=7).pack(side="left")
        if report_key:
            other_is_previous = not previous
            other = _maintenance_report_path(report_key, other_is_previous)
            if other.exists():
                ElegantButton(row, text="Current" if previous else "Previous",
                          command=lambda: _show_saved_report(report_key, title, previous=other_is_previous),
                          bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=12, pady=7).pack(side="left", padx=(6,0))
            rerun = maintenance_reruns.get(report_key)
            if rerun is not None:
                ElegantButton(row, text="Run again", command=lambda: (close_launcher_panel(), rerun()),
                          bg=COLORS["button"], fg=COLORS["accent"], relief="flat", bd=0, padx=12, pady=7).pack(side="left", padx=(6,0))
        ElegantButton(row, text="Reports folder", command=open_maintenance_folder, bg=COLORS["button"], fg=COLORS["muted"], relief="flat", bd=0, padx=12, pady=7).pack(side="right", padx=(6,0))
        ElegantButton(row, text="Close", command=close_launcher_panel, bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=16, pady=7).pack(side="right")

    def _show_saved_report(report_key, title, *, previous=False):
        text, path = _read_maintenance_report(report_key, previous)
        if path is None: return False
        status, timestamp = saved_status(root, report_key, previous)
        _show_text_report(title, f"Saved result: {status} · {timestamp}\n\n{text}",
                          ok=(status == "PASS"), report_key=report_key, previous=previous)
        return True

    def _run_maintenance_tool(script_name, args, event_name, title, timeout=900, report_key=None, rerun=None):
        if not maintenance_lock.acquire(blocking=False):
            launcher_notice(title, "A maintenance check is already running. Wait for its report before starting another.", kind="info")
            return
        key = report_key or Path(script_name).stem
        if rerun is not None: maintenance_reruns[key + "_run"] = rerun
        launcher_notice(title, "Running in the background… The result includes its timestamp and actual exit status. Reports keep Current + Previous.", kind="info")
        def job():
            try:
                payload = run_tool(root, script_name, list(args), key, title, timeout)
                event_q.put((event_name, payload))
            except Exception as exc:
                event_q.put((event_name, {"returncode":2,"text":str(exc),"title":title,"report_key":None}))
            finally: maintenance_lock.release()
        gui_jobs.thread(target=job, name="PortalAI-maintenance", daemon=True).start()

    def _component_diag_info():
        selected = resolve_diagnostic(diag_component_var.get())
        return selected['argument'], selected['label'], selected['report_key'], 'Component Diagnostic · ' + selected['label']

    def run_component_diagnostic():
        comp, label_name, key, title = _component_diag_info()
        rerun = lambda: run_component_diagnostic()
        _run_maintenance_tool("component_diagnostics.py", ["--component", comp], "diagnostic_complete", title, 900 if comp=='vision_integrity' else 180, report_key=key, rerun=rerun)

    def show_or_run_component_diagnostic():
        run_component_diagnostic()

    def run_media_stack_verify():
        _run_maintenance_tool(
            "media_stack_verify.py", [], "diagnostic_complete",
            "Media Stack Verification · installed media routes", 900,
            report_key="media_stack_verify", rerun=lambda: run_media_stack_verify(),
        )

    def show_or_run_media_stack_verify():
        run_media_stack_verify()

    def run_storage_audit(deep: bool = False):
        args = ["--deep"] if deep else []
        key = "deep_duplicate_scan" if deep else "storage_audit"
        title = "Deep Storage / Duplicate Audit" if deep else "Storage Audit"
        _run_maintenance_tool("maintenance_storage.py", args, "storage_report_complete", title, 3600 if deep else 1200, report_key=key, rerun=lambda: run_storage_audit(deep))

    def show_or_run_storage_audit(deep=False):
        run_storage_audit(deep)



    def _load_maintenance_json(keys: tuple[str, ...]) -> tuple[dict | None, Path | None]:
        candidates=[]
        for key in keys:
            p = maintenance_dir / f"{key}_latest.json"
            if p.exists():
                try: candidates.append((p.stat().st_mtime, p))
                except OSError: pass
        for _mtime, p in sorted(candidates, key=lambda x: x[0], reverse=True):
            try:
                return json.loads(p.read_text(encoding="utf-8", errors="replace")), p
            except Exception:
                continue
        return None, None

    def _human_bytes(n: int) -> str:
        units=("B","KB","MB","GB","TB"); x=float(max(0,int(n or 0)))
        for u in units:
            if x < 1024.0 or u == units[-1]:
                return f"{int(x)} B" if u == "B" else f"{x:.1f} {u}"
            x /= 1024.0
        return f"{int(n or 0)} B"

    def run_root_reference_audit():
        _run_maintenance_tool("reference_integrity.py", [], "storage_report_complete", "Reference Integrity", 1200, report_key="root_reference_audit", rerun=lambda: run_root_reference_audit())

    def show_or_run_root_reference_audit():
        run_root_reference_audit()

    def run_dependency_probe(suite: str = "full"):
        title = "Dependency Isolation Test · FULL" if suite == "full" else "Dependency Isolation Test · standard"
        _run_maintenance_tool("dependency_probe_current.py", ["--suite", suite], "storage_report_complete", title, 12000 if suite == "full" else 6500, report_key="dependency_probe", rerun=lambda: run_dependency_probe(suite))



    def show_dependency_probe_panel():
        body = open_launcher_panel("Dependency Isolation Test", width=0.84, height=0.62)
        label(body, "Offline runtime and import-origin checks", 13, fg=COLORS["accent"], bold=True).pack(fill="x", padx=16, pady=14)
        label(body, "Runs bundled interpreters in isolated processes with host Python paths removed and model downloads disabled. Standard checks GUI/account libraries/foundation/science; Full adds media, music understanding and isolated Radeon imports. No generation or automatic repair. Models and caches stay in place. This is not an OS sandbox or proof that any dependency can be deleted.",
              10, fg=COLORS["text"], wraplength=800, justify="left").pack(fill="x", padx=16, pady=12)
        row=tk.Frame(body,bg=COLORS["bg"]);row.pack(fill="x",padx=16,pady=14)
        for text, command in (("Run full check",lambda:run_dependency_probe("full")), ("Run standard check",lambda:run_dependency_probe("standard")),
                              ("View saved report",lambda:_show_saved_report("dependency_probe","Dependency Isolation Test"))):
            ElegantButton(row,text=text,command=command,bg=COLORS["button"],fg=COLORS["text"],relief="flat",padx=12,pady=7).pack(side="left",padx=4)

    def run_general_cleanup_plan():
        _run_maintenance_tool("maintenance_storage.py", ["--plan-safe"], "storage_report_complete", "Safe Cleanup Plan", 1800, report_key="general_cleanup_plan", rerun=lambda: run_general_cleanup_plan())

    def run_root_hygiene_now():
        body = open_launcher_panel("Root archive", width=0.82, height=0.65)
        from root_archive import plan
        candidates = plan(root)
        label(body, "Move verified historical root files into Maintenance/Archive. Nothing is deleted. Old installers must not be run from the archive.",9,wraplength=800,justify="left").pack(fill="x",padx=16,pady=12)
        viewer=RoundedText(body,palette=COLORS,scrollbars=True,bg=COLORS["panel"],fg=COLORS["text"],height=12)
        rounded_readouts.append(viewer)
        viewer.pack(fill="both",expand=True,padx=16,pady=8)
        viewer.insert("1.0","\n".join(p.name for p in candidates) or "Root archive is already up to date.");viewer.configure(state="disabled")
        ElegantButton(body,text='Copy to clipboard',command=lambda:(app.clipboard_clear(),app.clipboard_append(viewer.get('1.0','end-1c'))),
                      bg=COLORS['button'],fg=COLORS['text'],padx=12,pady=7).pack(before=viewer.frame,pady=6)
        if candidates:
            ElegantButton(body,text="Archive these files",command=lambda:_run_maintenance_tool("maintenance_storage.py",["--root-tidy","--apply"],"storage_report_complete","Root archive",600,report_key="root_hygiene_apply"),bg=COLORS["button"],fg=COLORS["text"],padx=12,pady=7).pack(pady=10)

    def show_or_run_root_hygiene():
        maintenance_reruns["root_hygiene_apply"] = lambda: run_root_hygiene_now()
        if not _show_saved_report("root_hygiene_apply", "Root Declutter"):
            run_root_hygiene_now()



    def show_general_cleanup_panel():
        body = open_launcher_panel("Safe Cleanup Plan", width=0.78, height=0.58)
        label(body, "Conservative current-generation cleanup", 13, fg=COLORS["accent"], bold=True).pack(fill="x", padx=16, pady=(14,4))
        label(body, "Only compiled Python cache files beneath first-party source are eligible. Files are rechecked immediately before cleanup. Models, runtimes, Science results, backups, missions, outputs, user data and duplicate groups are protected.", 9, fg=COLORS["text"], wraplength=900, justify="left").pack(fill="x", padx=16, pady=(0,10))
        row=tk.Frame(body,bg=COLORS["bg"]);row.pack(fill="x",padx=16,pady=(4,14))
        ElegantButton(row,text="Build / refresh plan",command=lambda:(close_launcher_panel(),run_general_cleanup_plan()),bg=COLORS["button"],fg=COLORS["text"],relief="flat",bd=0,padx=12,pady=7).pack(side="left")
        ElegantButton(row,text="Run safe cleanup",command=lambda:(close_launcher_panel(),_run_maintenance_tool("maintenance_storage.py",["--cleanup-safe"],"storage_report_complete","Safe Storage Cleanup",1800,report_key="storage_cleanup")),bg=COLORS["good"],fg="#ffffff",relief="flat",bd=0,padx=12,pady=7).pack(side="left",padx=6)
        ElegantButton(row,text="Close",command=close_launcher_panel,bg=COLORS["button"],fg=COLORS["text"],relief="flat",bd=0,padx=14,pady=7).pack(side="right")









    def run_fresh_machine_validator():
        _run_maintenance_tool("fresh_machine_validator.py", ["--run-system-test"], "diagnostic_complete", "Fresh-machine Validation Helper", 700,
                              report_key="fresh_machine_validation", rerun=lambda: run_fresh_machine_validator())

    def show_or_run_fresh_machine_validator():
        run_fresh_machine_validator()

    # PORTABLEAI_DATA_CLEANUP_UI_v15_125







    # PORTABLEAI_MAINTENANCE_EXECUTE_UI_v15_128A
    maintenance_delete_state = {"running": False}

    def _maintenance_human_bytes(value):
        x = float(max(0, int(value or 0)))
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if x < 1024.0 or unit == "TB":
                return f"{int(x)} B" if unit == "B" else f"{x:.1f} {unit}"
            x /= 1024.0
        return f"{int(value or 0)} B"

    def _maintenance_prepare_chat_wipe():
        if native_chat_panel is None:
            return True
        for name in ("prepare_for_full_conversation_wipe", "prepare_conversation_wipe"):
            fn = getattr(native_chat_panel, name, None)
            if callable(fn):
                return bool(fn())
        return True

    def _maintenance_finish_chat_wipe():
        if native_chat_panel is None:
            return
        for name in ("reset_after_full_conversation_wipe", "finish_conversation_wipe"):
            fn = getattr(native_chat_panel, name, None)
            if callable(fn):
                fn()
                return

    def _maintenance_execute_delete(kind, title):
        if maintenance_delete_state["running"]:
            launcher_notice(title, "Another maintenance deletion is already running.", kind="info")
            return
        if kind == "conversations":
            try:
                if not _maintenance_prepare_chat_wipe():
                    launcher_notice(title, "Stop the active chat, microphone/hands-free mode, or memory maintenance job before deleting conversations.", kind="error")
                    return
            except Exception as exc:
                launcher_notice(title, f"Could not prepare Native Chat for deletion:\n{exc}", kind="error")
                return

        close_launcher_panel()
        maintenance_delete_state["running"] = True
        log(f"{title}: explicit maintenance deletion started")

        def worker():
            try:
                result = execute_cleanup(root, kind)
            except Exception as exc:
                result = {"success": False, "kind": kind, "deleted_files": 0, "human_freed": "0 B", "errors": [f"{type(exc).__name__}: {exc}"]}

            def finish():
                maintenance_delete_state["running"] = False
                errors = list((result or {}).get("errors") or [])
                if kind == "conversations" and not errors:
                    try:
                        _maintenance_finish_chat_wipe()
                    except Exception as exc:
                        errors.append(f"Native Chat refresh: {exc}")
                msg = f"Deleted {(result or {}).get('deleted_files', 0):,} files; freed {(result or {}).get('human_freed', '0 B')}."
                if errors:
                    log(f"{title}: completed with warnings: " + "; ".join(str(x) for x in errors[:6]))
                    launcher_notice(title, msg + "\n\nSome items could not be removed:\n" + "\n".join(str(x) for x in errors[:8]), kind="error")
                else:
                    log(f"{title}: complete; {msg}")
                    launcher_notice(title, msg, kind="info")
            app.after(0, finish)

        gui_jobs.thread(target=worker, name=f"PortableAIMaintenanceDelete-{kind}", daemon=True).start()

    def show_maintenance_delete_confirm(kind):
        specs = {
            "webcache": (
                "Delete Web Cache",
                "Delete downloaded web/cache files now?",
                "Clears only allowlisted web-specific cache/download locations discovered under Cache, PortableCache, Outputs, Data, or Agent. Generic model/runtime caches are not recursively deleted.",
                "Delete now",
            ),
            "outputs": (
                "Delete All Outputs",
                "Delete ALL generated outputs now?",
                "Empties the current account’s Outputs folder, including generated/edited image, video, audio, transcript, preview, science-workbench output, and downloaded web output files. Models, tools, runtimes, source files, and Documentation are preserved.",
                "Delete outputs now",
            ),
            "conversations": (
                "Delete All Conversations + Memory",
                "Delete ALL saved conversations and learned conversation memory now?",
                "Clears saved sessions, chat-owned attachments/recordings/thumbnails/media cache, and Data\\Memory. Chat settings/custom instructions, master instructions, models, tools, runtimes, Outputs, and Documentation are preserved. A fresh blank chat is created afterward.",
                "Delete conversations now",
            ),
        }
        if kind not in specs:
            launcher_notice("Maintenance", f"Unknown delete action: {kind}", kind="error")
            return
        title, heading, description, action_text = specs[kind]
        try:
            info = preview_cleanup(root, kind)
        except Exception as exc:
            launcher_notice(title, f"Could not inspect cleanup targets:\n{exc}", kind="error")
            return

        body = open_launcher_panel(title, width=0.74, height=0.62)
        label(body, heading, 12, fg=COLORS["danger"], bold=True).pack(fill="x", padx=16, pady=(16, 6))
        label(body, description, 9, fg=COLORS["text"], wraplength=820, justify="left").pack(fill="x", padx=16, pady=(0, 10))
        label(body, f"Current preview: {int(info.get('files') or 0):,} files · {info.get('human_bytes') or _maintenance_human_bytes(info.get('bytes') or 0)}", 10, fg=COLORS["warn"], bold=True).pack(fill="x", padx=16, pady=(0, 8))

        targets = list(info.get("targets") or [])
        if targets:
            lines = []
            for row in targets[:8]:
                lines.append(f"• {row.get('path', '')}  ({int(row.get('files') or 0):,} files, {_maintenance_human_bytes(row.get('bytes') or 0)})")
            if len(targets) > 8:
                lines.append(f"• …and {len(targets) - 8} more allowlisted location(s)")
            label(body, "\n".join(lines), 8, fg=COLORS["muted"], wraplength=820, justify="left").pack(fill="x", padx=16, pady=(0, 10))

        if int(info.get("files") or 0) <= 0:
            label(body, "Nothing currently needs deletion in the allowlisted targets.", 9, fg=COLORS["good"]).pack(fill="x", padx=16, pady=(0, 12))
            row = tk.Frame(body, bg=COLORS["bg"]); row.pack(fill="x", padx=16, pady=(0, 16))
            ElegantButton(row, text="Close", command=close_launcher_panel, bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=14, pady=7).pack(side="right")
            return

        label(body, "This is an execution action, not a report. It starts only when you press the red button below.", 8, fg=COLORS["warn"], wraplength=820, justify="left").pack(fill="x", padx=16, pady=(0, 12))
        row = tk.Frame(body, bg=COLORS["bg"]); row.pack(fill="x", padx=16, pady=(0, 16))
        ElegantButton(row, text="Cancel", command=close_launcher_panel, bg=COLORS["button"], fg=COLORS["text"], relief="flat", bd=0, padx=14, pady=7).pack(side="right")
        ElegantButton(row, text=action_text, command=lambda: _maintenance_execute_delete(kind, title), bg=COLORS["danger"], fg="#ffffff", relief="flat", bd=0, padx=14, pady=7).pack(side="right", padx=8)

    def open_maintenance_folder():
        p = private_path(root, "Data/Maintenance")
        p.mkdir(parents=True, exist_ok=True)
        try:
            if os.name == "nt": os.startfile(str(p))
            else: webbrowser.open(p.as_uri())
        except Exception as exc:
            launcher_notice("Maintenance reports", f"Could not open report folder:\n{exc}\n\n{p}", kind="error")

    # PORTABLEAI_SYSTEM_TEST_v15_86
    system_test_state = {"running": False}



    def run_system_test():
        _run_maintenance_tool("system_test.py", [], "diagnostic_complete", "System Test", 600,
                              report_key="system_test", rerun=run_system_test)


    def diagnose():
        try: diag_component_var.set("All")
        except Exception: pass
        force_scan.set(); _ensure_status_worker(); log("Requested full component/lifecycle diagnosis.")
        try: show_or_run_component_diagnostic()
        except Exception as exc: launcher_notice("Full Component Diagnosis", f"Could not start full diagnosis:\n{exc}", kind="error")

    def minimize_to_tray():
        nonlocal tray_hidden
        if exit_in_progress or (account_gate is not None and account_gate.locked):
            restore_from_tray()
            return
        if tray_hidden:
            return
        if os.name != "nt" or not tray.show():
            # Fallback is a normal taskbar minimize; never make the window unreachable.
            if _iconify_custom():
                log("Tray icon could not be created; minimized to the taskbar instead.")
            return
        tray_hidden = True
        app.withdraw()
        log("PortalAI Control Center minimized to the Windows notification area.")

    def restore_from_tray():
        nonlocal tray_hidden
        if account_gate is not None and account_gate.locked:
            from account_presentation import lock_account_surfaces
            lock_account_surfaces(app, COLORS)
        tray_hidden = False
        app.deiconify()
        try:
            app.state("normal")
        except Exception:
            pass
        if use_custom_chrome:
            try: app.overrideredirect(True)
            except Exception: pass
            _ensure_custom_taskbar_style()
            _schedule_raise_resize_grips()
        else:
            ensure_windows_chrome(app)
        app.lift()
        try:
            app.focus_force()
        except Exception:
            pass

    def begin_exit_portableai():
        """Stop PortableAI-managed processes, then truly exit the controller.

        This is intentionally different from Stop all components: Exit waits for the
        stop helper and then removes the tray icon and destroys this GUI.
        """
        nonlocal exit_in_progress, shutdown_status
        if account_gate is not None and account_gate.locked and any(
                not dialog.closed and dialog.busy for dialog in getattr(app, '_portalai_account_dialogs', ())):
            # Logout/reset may already be sealing on its tracked lifecycle
            # worker. A second close must not start a competing seal/reset.
            restore_from_tray()
            return
        if exit_in_progress:
            restore_from_tray()
            if shutdown_status is not None: shutdown_status.show()
            return
        exit_in_progress = True
        try:
            startup_gate.cancel()
            if account_gate is not None:
                lock_account_application()
                from shutdown_ui import ShutdownStatus
                if shutdown_status is None:
                    shutdown_status = ShutdownStatus(app, COLORS, retry_account_shutdown)
                shutdown_status.begin()
            # Release microphone resources before process cleanup. Account mode
            # already does this inside chat.shutdown() with the writer gate shut.
            else:
                _release_chat_audio_before_process_cleanup()
                _stop_legacy_openwebui_quiet()
            log("Exit PortalAI requested; stopping all managed components before controller exit...")
        except Exception as exc:
            # A synchronous cleanup failure must take the same visible/retryable
            # path as a background failure; never strand exit_in_progress=True.
            event_q.put(("exit_complete", {"ok": False, "message": "Shutdown preparation failed: " + type(exc).__name__, "error_type":type(exc).__name__}))
            return

        def shutdown_worker():
            stop = root / "Launchers" / "Stop_PortableAI.py"
            result = "PortalAI shutdown helper completed."
            ok = True
            error_type = None
            try:
                if account_gate is not None:
                    account_gate.close()
                    event_q.put(("exit_complete", {"ok": True, "message": "Account workspace verified sealed; closing PortalAI."}))
                    return
                if not stop.exists():
                    raise FileNotFoundError(f"Missing shutdown helper: {stop}")
                cp = hidden_run(
                    [bootstrap_python(root, windowed=True), str(stop), "--root", str(root), "--include-opengui", "--quiet"],
                    timeout=90, cwd=root,
                )
                if cp.returncode != 0:
                    ok = False
                    detail = (cp.stderr or cp.stdout or "unknown shutdown error").strip()
                    result = f"PortalAI shutdown helper returned {cp.returncode}: {detail}"
            except Exception as exc:
                ok = False
                error_type = type(exc).__name__
                result = f"PortalAI shutdown helper failed: {exc}"
            event_q.put(("exit_complete", {"ok": ok, "message": result, "error_type":error_type}))

        try:
            threading.Thread(target=shutdown_worker, name="PortableAIExit", daemon=True).start()
        except RuntimeError as exc:
            event_q.put(("exit_complete", {"ok": False, "message": "Shutdown worker could not start: " + type(exc).__name__}))

    def retry_account_shutdown():
        nonlocal exit_in_progress
        exit_in_progress = False
        begin_exit_portableai()

    def lock_account_application():
        startup_gate.cancel()
        stop_worker.set()
        # Cover the window and close every writer gate before other cleanup.
        # The owned Stop helper handles legacy services off the Tk thread.
        account_gate.lock()
        _portableai_popup.close()
        close_native_chat_frontend(portal_chat_frontend)

    account_page = None
    if account_gate is not None:
        account_gate.bind_writers(gui_jobs, native_chat_panel)
        account_gate.on_shutdown_status = lambda message: event_q.put(('exit_status', message))
        def change_current_user():
            if exit_in_progress or account_gate.locked:return
            from account_switch import show_change_user
            show_change_user(app,account_gate,COLORS,lock_application=lock_account_application,
                on_ready=lambda ticket:event_q.put(('exit_complete',{'ok':True,'switch':ticket,'message':'Current account sealed; changing user.'})),
                exit_application=begin_exit_portableai)
        account_page = account_gate.page(accounts_tab, lock_application=lock_account_application,
                          change_user=change_current_user,
                          exit_application=lambda: event_q.put(("exit_complete", {"ok": True, "message": "Account workspace verified sealed; closing PortalAI."})))

    startup_button = button("Startup", start_components, kind="accent")
    if (root / "OpenGUI").exists():
        button("Legacy OpenGUI", launch_legacy_opengui)
    button("System Test", run_system_test)
    button("Full Component Diagnosis", diagnose)
    button("Minimize to tray", minimize_to_tray)
    button("Stop all components", stop_components, kind="warning")
    button("Exit PortalAI", begin_exit_portableai, kind="danger")

    def open_donation_page():
        if exit_in_progress or (account_gate is not None and account_gate.locked):
            return
        show_tab("donation")

    donate_link.configure(command=open_donation_page, state="normal")

    # PORTALAI_RESPONSIVE_COMPACT_v15_136E
    # PORTALAI_RESPONSIVE_CONTROL_MENU_v15_138
    portal_control_menu = install_responsive_controls(app, ctl, btnrow, buttons, COLORS)
    portal_compact_mode = install_compact_mode(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_tab, native_chat_panel, start_components, tabs_right, COLORS,
        titlebar=titlebar, toggle_theme=toggle_theme, theme_mode_getter=lambda: theme_mode,
        minimize_to_tray=minimize_to_tray, exit_all=begin_exit_portableai, root_dir=root,
    )
    portal_tab_scaler = install_dynamic_tab_scaler(
        app, list(tab_buttons.values()) + [theme_toggle_btn, portal_compact_mode.toggle_button]
    )
    portal_nav_layout = install_responsive_nav_layout(app, tabs_left, tabs_right)
    from remote_desktop_layout import install as install_remote_layout
    remote_layout = install_remote_layout(app, portal_compact_mode, show_tab, selected_tab,
        available=lambda: not exit_in_progress and (account_gate is None or not account_gate.locked))

    try:
        chrome_buttons["minimize"].configure(command=_iconify_custom)
        chrome_buttons["maximize"].configure(command=_toggle_maximize_custom)
        chrome_buttons["tray"].configure(command=minimize_to_tray, state='normal')
        chrome_buttons["close"].configure(command=begin_exit_portableai)
    except Exception:
        pass

    last_ui_state = {"services":{}, "activity":{}, "runtime_models":{}, "installed":{}, "gpu":None, "gpu_models":None, "models":None, "loras":None}

    def pump():
        nonlocal exit_in_progress, shutdown_status, next_account
        try:
            while True:
                kind,data=event_q.get_nowait()
                if account_gate is not None and account_gate.locked:
                    if kind in ('tray_action', 'tray_context'):
                        # Locked tray clicks reveal only the shutdown/recovery
                        # surface. Never dispatch chat, tools or settings here.
                        restore_from_tray()
                        if shutdown_status is not None: shutdown_status.show()
                        continue
                    if kind not in ('exit_complete', 'exit_status'):
                        continue
                if kind == 'exit_status':
                    if shutdown_status is not None: shutdown_status.update(data)
                    continue
                if kind=="log":
                    log(data); continue
                if kind == 'tool_activity':
                    phase, title = data.get('phase'), data.get('label', 'Tool')
                    if phase in ('started','returned','cancelled','idle'):
                        tool_activity_label.configure(text=f'Chat tools: {title} · {phase}')
                    message = f'{title} · {phase}'
                    if message != last_ui_state.get('tool_event'):
                        log(message); last_ui_state['tool_event'] = message
                    continue
                if kind=="stop_result":
                    control_progress.set('Stopped.' if data.get('ok') else 'Stop failed; check the Control Log.')
                    if bool(data.get("ok")):
                        control_loaded.set('Current chat: stopped.')
                        log("Stop all components completed. "+str(data.get("detail") or "")); force_scan.set()
                    else:
                        detail=str(data.get("detail") or "Stop failed."); log("Stop failed: "+detail); launcher_notice("Stop all components",detail,kind="error")
                    continue
                if kind=="startup_result":
                    settings_page.set_startup_busy(False)
                    startup_button.configure(state='normal')
                    if data.get('ticket') != startup_gate.ticket():
                        log('Startup result discarded after Stop/Exit.'); force_scan.set(); continue
                    control_progress.set(('Last Startup: ' if data.get('ok') else '') +
                                         str(data.get('detail') or 'Startup finished.'))
                    if bool(data.get("ok")):
                        model = data.get('model') or {}
                        name = model.get('label') or model.get('id') or 'Qwen'
                        context = f" · {model['context_tokens']} context tokens" if model.get('context_tokens') else ''
                        control_loaded.set('Current chat: ' + name + context)
                        log(str(data.get("detail") or "Native Startup complete: Qwen READY."))
                        force_scan.set()
                    else:
                        detail = str(data.get("detail") or "Native startup failed.")
                        log("Native Startup failed: " + detail)
                        launcher_notice("PortalAI Startup", detail, kind="error")
                        if executable_repair is not None:executable_repair.request(manual=True)
                        force_scan.set()
                    continue
                if kind=="system_test_complete":
                    system_test_state["running"] = False
                    report_ok = data.get('status') == 'PASS' if 'status' in data else data.get('returncode') == 0
                    log("System Test completed." if report_ok else "System Test completed with failures/warnings to review.")
                    _show_text_report("System Test", data.get("text", ""), ok=report_ok)
                    continue
                if kind in ("diagnostic_complete", "storage_report_complete"):
                    rc = int(data.get("returncode", 1))
                    report_ok = data.get('status') == 'PASS' if 'status' in data else rc == 0
                    report_key = data.get("report_key")
                    title = str(data.get("title") or "PortableAI Report")
                    shown = False
                    if report_key:
                        shown = _show_saved_report(str(report_key), title)
                    if not shown:
                        _show_text_report(title, str(data.get("text") or ""), ok=report_ok, report_key=str(report_key) if report_key else None)
                    log(f"{title} completed: {data.get('status', 'review report')}, exit code {rc}.")
                    if kind == "storage_report_complete":
                        force_scan.set()
                    continue
                # PORTABLEAI_TRAY_THEMED_MENU_PUMP_v15_134E
                if kind == "tray_context":
                    try:
                        if isinstance(data, dict):
                            px = int(data.get("x", app.winfo_pointerx()))
                            py = int(data.get("y", app.winfo_pointery()))
                        else:
                            px, py = int(app.winfo_pointerx()), int(app.winfo_pointery())
                        show_tray_context_menu(px, py)
                    except Exception as exc:
                        log(f"Tray context menu warning: {exc}")
                    continue
                if kind=="tray_action":
                    if data == "restore":
                        restore_from_tray()
                    elif data == "chat":
                        restore_from_tray(); show_tab("chat")
                    elif data == "new_chat":
                        restore_from_tray(); show_tab("chat")
                        if native_chat_panel is not None:
                            native_chat_panel.new_chat()
                    elif data == "runtime":
                        restore_from_tray(); show_tab("runtime")
                    elif data == "installed":
                        restore_from_tray(); show_tab("installed")
                    elif data in ('accounts', 'settings', 'maintenance', 'activity'):
                        restore_from_tray(); show_tab(data)
                    elif data == 'missions':
                        restore_from_tray(); open_account_missions()
                    elif data == "help":
                        restore_from_tray(); show_help_topic("quick_start")
                    elif data == "startup":
                        start_components()
                    elif data == "system_test":
                        run_system_test()
                    elif data == "reports":
                        open_maintenance_folder()
                    elif data == "theme":
                        toggle_theme()
                    elif data == "stop":
                        stop_components()
                    elif data == "exit":
                        begin_exit_portableai()
                    continue
                if kind=="exit_complete":
                    if account_gate is not None and not data.get("ok", False):
                        # Keep keys alive and private surfaces covered, but show
                        # the failure even when Exit began from a hidden tray.
                        exit_in_progress = False
                        if shutdown_status is not None: shutdown_status.failure(data.get("error_type"))
                        else:
                            from shutdown_ui import ShutdownStatus
                            # Logout normally owns its own visible sheet. A
                            # fallback queue failure still needs a retry surface.
                            shutdown_status = ShutdownStatus(app, COLORS, retry_account_shutdown)
                            shutdown_status.failure(data.get("error_type"))
                        continue
                    log(data.get("message", "PortalAI shutdown completed."))
                    if not data.get("ok", False):
                        # Exit is explicit: even if a worker already died or the helper
                        # reported an error, do not strand an unclosable controller.
                        log("Shutdown reported an error; the Control Center will still exit.")
                    stop_worker.set()
                    try:
                        if native_chat_panel is not None:
                            native_chat_panel.shutdown()
                        try:
                            close_native_chat_frontend(portal_chat_frontend)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    tray.close()
                    if shutdown_status is not None: shutdown_status.finish()
                    if data.get('switch') is not None:
                        next_account=data['switch']
                        if not isinstance(next_account,SwitchTicket):raise RuntimeError('Invalid account handoff')
                        next_account.instance_mutex=single_instance_mutex
                        next_account.geometry=app.geometry()
                    def destroy_window():
                        # No old Tk timer may resume in the next profile epoch.
                        from modal_guard import set_modal_surface
                        set_modal_surface(app,None)
                        for timer in app.tk.call('after','info'):
                            # Preserve each widget's command bookkeeping until
                            # its own destroy removes the registered callback.
                            try:app.tk.call('after','cancel',timer)
                            except tk.TclError:pass
                        app.destroy()
                    app.after(100, destroy_window)
                    return
                # Apply only actual changes. The old loop reconfigured dozens of
                # labels/Text widgets every monitor cycle even when nothing changed,
                # which made the launcher feel sluggish during chat streaming/resizing.
                for message in data.get('observed_events', []): log(message)
                # Policy I/O belongs to the monitor worker. A sample started
                # before a deliberate save cannot overwrite that newer UI choice.
                if data.get('policy_sampled_at', 0) >= last_policy_edit[0]:
                    settings_page.refresh_saved(data.get('settings_models'), policy=data['settings_policy'])
                    if native_chat_panel is not None and not native_chat_panel.busy:
                        native_chat_panel.effort.sync_saved_choice(
                            policy=data['settings_policy'], preferences=data['saved_effort'])
                if data.get('storage_budget'):
                    storage_page.refresh_budget(data['storage_budget'])
                native_exporter=getattr(app,'_portalai_native_exporter',None)
                if native_exporter is not None:
                    try:native_exporter.observe(data)
                    except (ValueError,TypeError,KeyError):native_exporter.invalidate()
                loaded = data.get('runtime_models', {}).get('qwen') or ['No model reported loaded.']
                control_loaded.set('Current chat: ' + ' · '.join(str(value) for value in loaded))
                process_text = data.get('process_text', '')
                if process_text != last_ui_state.get('process_text'):
                    set_box_text(process_box, process_text); last_ui_state['process_text'] = process_text
                for k,value in data["services"].items():
                    if last_ui_state["services"].get(k) != value:
                        previous = last_ui_state['services'].get(k)
                        if k in services and (previous is None or previous[0] != value[0]):
                            log(f'{k}: {value[0]} · {value[1]}')
                        set_pair(services,k,*value); last_ui_state["services"][k] = value
                for k,value in data["activity"].items():
                    if last_ui_state["activity"].get(k) != value:
                        set_pair(activities,k,*value); last_ui_state["activity"][k] = value
                for k,lines in data.get("runtime_models",{}).items():
                    frozen = tuple(lines) if isinstance(lines,(list,tuple)) else str(lines or "")
                    if k in runtime_model_boxes and last_ui_state["runtime_models"].get(k) != frozen:
                        model_text="\n".join(str(x) for x in lines if str(x).strip()) if isinstance(lines,(list,tuple)) else str(lines or "")
                        set_box_text(runtime_model_boxes[k],model_text or "No model/component reported.")
                        if k not in ('policy','missions'): log(f'{k} model/component: {model_text[:300]}')
                        last_ui_state["runtime_models"][k] = frozen
                if data.get('telemetry'): activity_charts.update_sample(data['telemetry'])
                if last_ui_state["gpu"] != data["gpu"]:
                    gpu_lbl.configure(text=data["gpu"]); last_ui_state["gpu"] = data["gpu"]
                gpu_models_value = tuple(data["gpu_models"])
                if last_ui_state["gpu_models"] != gpu_models_value:
                    set_box_text(gpu_models_box, "\n".join(data["gpu_models"]) if data["gpu_models"] else "No managed model is currently reported as resident.")
                    last_ui_state["gpu_models"] = gpu_models_value
                for k,value in data["installed"].items():
                    if last_ui_state["installed"].get(k) != value:
                        set_pair(installed_rows,k,*value); last_ui_state["installed"][k] = value
                        packages_view.queue_layout()
                models_value = tuple(data["models"]); loras_value = tuple(data["loras"])
                if last_ui_state["models"] != models_value:
                    set_box_text(diffusion_box, "\n".join(data["models"]) if data["models"] else "No diffusion model files detected."); last_ui_state["models"] = models_value
                if last_ui_state["loras"] != loras_value:
                    set_box_text(lora_box, "\n".join(data["loras"]) if data["loras"] else "No LoRA files detected."); last_ui_state["loras"] = loras_value
        except queue.Empty:pass
        except Exception:
            # A malformed status/UI event must not terminate the queue pump and
            # leave the notification icon permanently unresponsive.
            app.report_callback_exception(*sys.exc_info())
        app.after(500,pump)



    # Custom title bar on Windows: tray button minimizes; red X performs the
    # same managed stop-all-and-exit path as Exit PortableAI.
    app.after(200, lambda: (_ensure_custom_taskbar_style() if use_custom_chrome else ensure_windows_chrome(app)))
    app.after(220, _raise_resize_grips)
    app.after(600, _raise_resize_grips)
    # PORTABLEAI_FREEZE_WATCHDOG_v15_117
    _ui_heartbeat = {"last": time.monotonic(), "last_dump": 0.0}
    _freeze_log = (private_path(root, 'Logs/PortableAI_Freeze.log') if account_gate is not None
                   else root / "ControlCenter" / "PortableAI_Freeze.log")

    def _ui_beat():
        _ui_heartbeat["last"] = time.monotonic()
        try:
            app.after(250, _ui_beat)
        except Exception:
            pass

    def _freeze_watchdog():
        import faulthandler
        while not stop_worker.wait(1.0):
            lag = time.monotonic() - float(_ui_heartbeat.get("last", 0.0))
            now = time.monotonic()
            if lag < 3.0 or now - float(_ui_heartbeat.get("last_dump", 0.0)) < 12.0:
                continue
            _ui_heartbeat["last_dump"] = now
            try:
                _freeze_log.parent.mkdir(parents=True, exist_ok=True)
                with _freeze_log.open("a", encoding="utf-8", errors="replace") as fh:
                    fh.write(f"\n=== UI STALL {time.strftime('%Y-%m-%d %H:%M:%S')} | heartbeat lag {lag:.2f}s ===\n")
                    fh.flush()
                    faulthandler.dump_traceback(file=fh, all_threads=True)
                    fh.flush()
            except Exception:
                pass

    app.after(250, _ui_beat)
    gui_jobs.thread(target=_freeze_watchdog, name="PortableAIFreezeWatchdog", daemon=True).start()

    # PORTABLEAI_PERSISTENT_TRAY_v15_131B
    # Register the notification icon while the normal Control Center window is
    # visible too. Windows may still place it behind the system tray overflow
    # chevron according to the user's notification-area preferences.
    def _show_persistent_tray_icon():
        try:
            if not tray.show():
                log("Windows notification-area icon could not be registered; taskbar/window icon remains available.")
        except Exception as exc:
            log(f"Tray registration warning: {type(exc).__name__}: {exc}")

    app.after(350, _show_persistent_tray_icon)

    app.protocol("WM_DELETE_WINDOW", begin_exit_portableai)

    # PORTABLEAI_CONTEXT_MENU_SYNC_v15_134E
    # Unified themed context menus. This replaces the older generic ContextHelpManager
    # popup so launcher right-click and notification-area right-click share one visual
    # language and one current action/help registry.
    from themed_popup_menu import ThemedPopupMenu

    _portableai_popup = ThemedPopupMenu(app, lambda: COLORS)

    def _menu_item(label, command, tone="normal", enabled=True):
        def guarded_command():
            # Recheck at dispatch, not just menu construction: popup commands
            # run after_idle and may have been queued just before account lock.
            if exit_in_progress or (account_gate is not None and account_gate.locked):
                return
            if callable(command): return command()
        return {"label": label, "command": guarded_command if callable(command) else None, "tone": tone, "enabled": enabled}

    def _help_keys():
        from help_catalog import TOPICS
        return set(TOPICS)

    def _help_command(*topics):
        from help_catalog import canonical_topic
        choices = tuple(canonical_topic(str(x)) for x in topics if x)
        def _go():
            keys = _help_keys()
            chosen = None
            if keys:
                for topic in choices:
                    if topic in keys:
                        chosen = topic; break
            if chosen is None:
                chosen = choices[0] if choices else "quick_start"
            try:
                show_help_topic(chosen)
            except Exception:
                show_help_topic("quick_start")
        return _go

    from help_catalog import TOPICS as help_topics_catalog, TOPIC_ALIASES, action_topic
    _topic_title = {key:rec['title'] for key,rec in help_topics_catalog.items()}
    _topic_title.update({alias:_topic_title[key] for alias,key in TOPIC_ALIASES.items()})

    def _context_widget_text(widget):
        cur = widget
        for _ in range(7):
            if cur is None:
                break
            try:
                value = cur.cget("text")
                if value is not None and str(value).strip():
                    return str(value).strip()
            except Exception:
                pass
            if cur is app:
                break
            try:
                cur = cur.master
            except Exception:
                break
        return ""

    def _chat_callable(*names):
        if native_chat_panel is None:
            return None
        for name in names:
            try:
                fn = getattr(native_chat_panel, name, None)
            except Exception:
                fn = None
            if callable(fn):
                return fn
        return None

    def _chat_item(label, names, tone="normal"):
        fn = _chat_callable(*names)
        return _menu_item(label, fn, tone=tone, enabled=fn is not None) if fn is not None else None

    def _select_component_diagnostic(name):
        def _run():
            try:
                options = tuple(str(x) for x in diag_choices)
                target = next((x for x in options if x.casefold() == str(name).casefold()), None)
                if target is None:
                    target = next((x for x in options if str(name).casefold() in x.casefold()), None)
                if target is None:
                    target = "All" if "All" in options else options[0]
                diag_component_var.set(target)
                show_or_run_component_diagnostic()
            except Exception:
                diagnose()
        return _run

    def _component_from_text(text):
        t = text.casefold()
        table = (
            (("vision asset checksums", "vision checksums"), "Vision Asset Checksums", "vision_integrity"),
            (("small vision", "2b vision", "4b vision", "qwen3-vl"), "Small Vision (2B / 4B)", "small_vision"),
            (("home assistant", "projection"), "Home Assistant / Projection", "home_assistant"),
            (("portable recovery", "ha recovery", "recover_portalai_login"), "Portable Recovery", "recovery"),
            (("runtime repair", "repair_account_runtime", "portable pip"), "Runtime Repair", "runtime_repair"),
            (("musicgen", "cpu music"), "MusicGen CPU", "musicgen"),
            (("demucs",), "Offline Demucs", "demucs"),
            (("music understanding", "moss", "clap"), "Music Understanding", "demucs"),
            (("ffmpeg", "ffprobe"), "FFmpeg / Media Tools", "ffmpeg"),
            (("native flux", "klein"), "Native FLUX", "native_image"),
            (("native image", "sd1.5", "sd 1.5", "dreamshaper"), "Native Image", "native_image"),
            (("offline vm", "secure vm", "qemu", "whpx"), "Offline VM", "vm"),
            (("radeon", "rocm"), "Radeon Adapters", "radeon"),
            (("science", "engineering", "openmm", "genome", "chemistry"), "Science", "science"),
            (("qwen3-tts", "tts"), "Qwen3-TTS", "qwen3_tts"),
            (("musetalk", "dialogue"), "MuseTalk", "musetalk"),
            (("mmaudio", "sfx", "foley"), "MMAudio", "mmaudio"),
            (("ace-step", "ace step", "music"), "ACE-Step", "acestep"),
            (("comfyui", "flux", "wan", "vace", "inpaint"), "ComfyUI", "comfyui"),
            (("speech-to-text", "stt", "whisper"), "STT", "component_diagnostics"),
            (("media preview", "preview"), "Media Preview", "component_diagnostics"),
            (("qwen", "llama.cpp", "llama"), "Qwen", "qwen"),
        )
        for needles, component, topic in table:
            if any(n in t for n in needles):
                return component, topic
        return None, None

    def _context_topic(text, tab):
        t = text.casefold()
        matched = action_topic(text)
        if matched:return matched
        checks = (
            (("storage audit",), "storage"),
            (("duplicate",), "duplicate"),
            (("general cleanup",), "cleanup"),
            (("root declutter", "root hygiene"), "declutter"),
            (("dependency",), "dependency"),
            (("reference audit",), "reference"),
            (("fresh-machine", "fresh machine", "run diagnostic", "component diagnosis", "system test", "verify media"), "component_diagnostics"),
            (("branch",), "branch"),
            (("edit last",), "edit_last"),
            (("history",), "history"),
            (("memory", "recall", "contribute"), "persistent_memory"),
            (("validate chat", "tool trace"), "chat_toolbar"),
            (("minimize", "tray"), "tray"),
        )
        for needles, topic in checks:
            if any(n in t for n in needles):
                return topic
        _comp, topic = _component_from_text(t)
        if topic:
            return topic
        return {
            "welcome": "quick_start", "accounts": "accounts", "controls": "controls", "chat": "chat",
            "activity": "activity", "runtime": "runtime", "installed": "installed", "settings": "settings",
            "maintenance": "maintenance", "persistence": "persistence", "help": "quick_start",
        }.get(tab, "quick_start")

    def _text_edit_items(widget):
        try:
            cls = str(widget.winfo_class())
        except Exception:
            return []
        if cls not in {"Text", "Entry", "TEntry", "Spinbox"}:
            return []

        def copy():
            try: widget.event_generate("<<Copy>>")
            except Exception: pass
        def cut():
            try: widget.event_generate("<<Cut>>")
            except Exception: pass
        def paste():
            try: widget.event_generate("<<Paste>>")
            except Exception: pass
        def select_all():
            try:
                if cls == "Text":
                    widget.tag_add("sel", "1.0", "end-1c"); widget.mark_set("insert", "1.0")
                else:
                    widget.selection_range(0, "end"); widget.icursor("end")
            except Exception:
                pass
        writable = True
        try:
            writable = str(widget.cget("state")) not in {"disabled", "readonly"}
        except Exception:
            pass
        items = [_menu_item("Copy", copy), _menu_item("Select all", select_all)]
        if writable:
            items += [_menu_item("Cut", cut), _menu_item("Paste", paste)]
        return items

    def _launcher_menu_items():
        return [
            _menu_item("Open Chat", lambda: show_tab("chat"), tone="accent"),
            _menu_item("Accounts", lambda: show_tab("accounts")),
            _menu_item("Controls", lambda: show_tab("controls")),
            _menu_item("Runtime", lambda: show_tab("activity")),
            _menu_item("Models", lambda: show_tab("runtime")),
            _menu_item("Packages", lambda: show_tab("installed")),
            _menu_item("Settings", lambda: show_tab("settings")),
            _menu_item("Maintenance", lambda: show_tab("maintenance")),
            _menu_item("Persistence", open_account_missions),
            _menu_item("Documentation / Help", _help_command("quick_start")),
            None,
            _menu_item("Startup", start_components),
            _menu_item("System Test", run_system_test),
            _menu_item("Full Component Diagnosis", diagnose),
            _menu_item("Repair missing executables", repair_executables),
            _menu_item("Open Maintenance Reports", open_maintenance_folder),
            None,
            _menu_item("Switch to " + ("Dark" if theme_mode == "light" else "Light") + " mode", toggle_theme),
            _menu_item("Minimize to tray", minimize_to_tray),
            _menu_item("Stop all components", stop_components, tone="danger"),
            _menu_item("Exit PortalAI", begin_exit_portableai, tone="danger"),
        ]

    def _context_items(widget, text, tab):
        t = text.casefold()
        topic = _context_topic(text, tab)
        items = _text_edit_items(widget)
        if items:
            items.append(None)

        # Specific controls and subfunctions first.
        if "startup" in t:
            items += [_menu_item("Startup", start_components, tone="accent"), _menu_item("System Test", run_system_test)]
        elif "system test" in t:
            items += [_menu_item("Run System Test", run_system_test, tone="accent"), _menu_item("Full Component Diagnosis", diagnose)]
        elif "full component" in t or "component diagnosis" in t or "full diagnosis" in t:
            items += [_menu_item("Run Full Component Diagnosis", diagnose, tone="accent"), _menu_item("System Test", run_system_test)]
        elif "stop all" in t:
            items += [_menu_item("Stop all components", stop_components, tone="danger")]
        elif "minimize" in t:
            items += [_menu_item("Minimize to tray", minimize_to_tray)]
        elif "exit portableai" in t or "exit portalai" in t:
            items += [_menu_item("Exit PortalAI", begin_exit_portableai, tone="danger")]
        elif "fresh-machine" in t or "fresh machine" in t:
            items += [_menu_item("Run fresh-machine readiness", show_or_run_fresh_machine_validator, tone="accent")]
        elif "verify media" in t:
            items += [_menu_item("Verify media stack", show_or_run_media_stack_verify, tone="accent")]
        elif t.strip() in ("run diagnostic", "run selected") or "targeted diagnostic" in t:
            items += [_menu_item("Run selected component diagnostic", show_or_run_component_diagnostic, tone="accent")]
        elif "storage audit" in t:
            items += [_menu_item("Run Storage Audit", lambda: show_or_run_storage_audit(False), tone="accent"), _menu_item("Open reports", open_maintenance_folder)]
        elif "duplicate" in t:
            items += [_menu_item("Run Deep Duplicate Scan", lambda: show_or_run_storage_audit(True), tone="accent"), _menu_item("Open reports", open_maintenance_folder)]
        elif "general cleanup" in t or "safe cleanup" in t:
            items += [_menu_item("Open Safe Cleanup Plan", show_general_cleanup_panel, tone="accent")]
        elif "root declutter" in t or "root-only cleanup" in t:
            items += [_menu_item("Open Root-only Cleanup", run_root_hygiene_now, tone="accent")]
        elif "dependency" in t:
            items += [_menu_item("Open Dependency Isolation Test", show_dependency_probe_panel, tone="accent")]
        elif "reference audit" in t or "reference integrity" in t:
            items += [_menu_item("Run Reference Integrity", show_or_run_root_reference_audit, tone="accent")]
        elif "open reports" in t or "maintenance reports" in t:
            items += [_menu_item("Open Maintenance Reports", open_maintenance_folder)]
        elif "delete web cache" in t:
            items += [_menu_item("Delete Web Cache…", lambda: show_maintenance_delete_confirm("webcache"), tone="danger")]
        elif "delete all outputs" in t:
            items += [_menu_item("Delete All Outputs…", lambda: show_maintenance_delete_confirm("outputs"), tone="danger")]
        elif "delete all conversations" in t:
            items += [_menu_item("Delete Conversations + Memory…", lambda: show_maintenance_delete_confirm("conversations"), tone="danger")]

        # Native Chat commands belong to the Chat page.
        if native_chat_panel is not None and tab == "chat":
            if "+ new" in t or t.strip() == "new":
                for x in (
                    _chat_item("New chat", ("new_chat",), "accent"),
                    _chat_item("New isolated chat", ("new_isolated_chat",)),
                ):
                    if x: items.append(x)
            elif "history" in t:
                x=_chat_item("Toggle History", ("toggle_history",)); items += [x] if x else []
            elif "branch" in t:
                x=_chat_item("Branch conversation…", ("open_branch_panel",)); items += [x] if x else []
            elif "edit last" in t:
                x=_chat_item("Edit last user message…", ("edit_last_user",)); items += [x] if x else []
            elif "memory" in t:
                x=_chat_item("Open memory settings", ("open_memory_panel",)); items += [x] if x else []
            elif "settings" in t or "preferences" in t:
                x=_chat_item("Chat Preferences", ("open_settings_panel", "open_settings", "show_settings")); items += [x] if x else []
            elif "instructions" in t:
                x=_chat_item("Open instructions", ("open_instructions_panel", "open_instructions", "show_instructions")); items += [x] if x else []
            elif "rename" in t:
                x=_chat_item("Rename conversation…", ("rename_chat", "rename_current_chat", "open_rename_panel")); items += [x] if x else []
            elif t.strip() == "delete" or "delete chat" in t:
                x=_chat_item("Delete conversation…", ("delete_chat", "delete_current_chat"), "danger"); items += [x] if x else []
            elif "copy" in t:
                x=_chat_item("Copy conversation", ("copy_chat", "copy_conversation", "copy_current_chat")); items += [x] if x else []
            elif "export" in t:
                x=_chat_item("Export conversation…", ("export_chat", "export_conversation", "export_current_chat")); items += [x] if x else []
            elif "tool trace" in t:
                x=_chat_item("Toggle tool trace", ("toggle_tool_trace", "toggle_trace")); items += [x] if x else []
            elif "validate chat" in t:
                x=_chat_item("Validate chat state", ("validate_chat_state", "validate_state", "validate"), "accent"); items += [x] if x else []
            elif "recall" in t:
                x=_chat_item("Toggle Recall", ("toggle_recall", "toggle_memory_recall")); items += [x] if x else []
            elif "contribute" in t:
                x=_chat_item("Toggle memory contribution", ("toggle_contribute", "toggle_memory_contribution")); items += [x] if x else []

        component, comp_topic = _component_from_text(t)
        if component and (tab in {"runtime", "installed"} or "diagnostic" in t):
            items += [_menu_item(f"Diagnose {component}", _select_component_diagnostic(component), tone="accent")]
            topic = comp_topic or topic

        # Context-level defaults fill the gaps on blank panel areas.
        if not [x for x in items if isinstance(x, dict) and x.get("command")]:
            if tab == "controls":
                from model_settings import show_model_settings
                items += [_menu_item("Model and hardware…", lambda: show_tab("settings"))]
                from mission_settings import show_mission_settings
                items += [_menu_item("Persistence", open_account_missions)]
                items += [_menu_item("Repair missing executables", repair_executables)]
                items += [_menu_item("Startup", start_components), _menu_item("System Test", run_system_test), _menu_item("Full Component Diagnosis", diagnose)]
            elif tab == "runtime":
                items += [_menu_item("Refresh models and services", lambda: force_scan.set()), _menu_item("Run selected component diagnostic", show_or_run_component_diagnostic)]
            elif tab == "activity":
                items += [_menu_item("Refresh Runtime", lambda: force_scan.set()), _menu_item("Open Models", lambda: show_tab("runtime"))]
            elif tab == "installed":
                items += [_menu_item("Packages", lambda:packages_view.select("packages")), _menu_item("Weights & LoRAs", lambda:packages_view.select("weights")), _menu_item("Refresh package inventory", lambda: force_scan.set()), _menu_item("Maintenance", lambda: show_tab("maintenance"))]
            elif tab == "settings":
                items += [_menu_item("Check chat hardware fit", settings_page.probe), _menu_item("Save chat settings", settings_page.save), _menu_item("Check media hardware fit", lambda:settings_page.probe("media")), _menu_item("Save media settings", lambda:settings_page.save("media")), _menu_item("Persistence", open_account_missions)]
            elif tab == "persistence":
                items += [_menu_item("Missions", lambda:persistence_page.select("missions")), _menu_item("Schedules", lambda:persistence_page.select("schedules"))]
            elif tab == "maintenance":
                items += [_menu_item("Run selected diagnostic", show_or_run_component_diagnostic),
                          _menu_item("Repair missing executables", repair_executables),
                          _menu_item("Full Component Diagnosis", diagnose),
                          _menu_item("Fresh-machine readiness", show_or_run_fresh_machine_validator),
                          _menu_item("Verify media stack", show_or_run_media_stack_verify), None,
                          _menu_item("Dependency Isolation Test", show_dependency_probe_panel),
                          _menu_item("Reference Integrity", show_or_run_root_reference_audit),
                          _menu_item("Storage Audit", lambda: show_or_run_storage_audit(False)),
                          _menu_item("Maintenance Reports", open_maintenance_folder)]
            elif tab == "chat" and native_chat_panel is not None:
                items += [_menu_item("New chat", native_chat_panel.new_chat, tone="accent")]
                h = _chat_callable("toggle_history")
                if h: items.append(_menu_item("Toggle History", h))
                m = _chat_callable("open_memory_panel")
                if m: items.append(_menu_item("Memory", m))
            elif tab == "help":
                items += [_menu_item("Quick start", _help_command("quick_start")),
                          _menu_item("Browse all Help topics", lambda:(documentation_panel.category_var.set("All topics"), documentation_panel.search_var.set("")))]
            else:
                items += [_menu_item("Open Chat", lambda: show_tab("chat")), _menu_item("Models", lambda: show_tab("runtime"))]

        # Every contextual menu ends with an explicit relevant help link and an
        # escape hatch to the complete launcher menu.
        items += [None]
        items += [_menu_item("Help: " + _topic_title.get(topic, topic.replace("_", " ").title()), _help_command(topic, tab, "quick_start"), tone="accent")]
        items += [_menu_item("PortalAI menu…", lambda: _show_full_launcher_menu(app.winfo_pointerx(), app.winfo_pointery()), tone="muted")]
        return items, topic

    def _show_full_launcher_menu(x, y):
        if exit_in_progress or (account_gate is not None and account_gate.locked):
            return
        _portableai_popup.show(int(x), int(y), _launcher_menu_items(), title="PortalAI Control Center")

    def _show_launcher_context(event):
        if exit_in_progress or (account_gate is not None and account_gate.locked):
            return 'break'
        try:
            widget = event.widget
            text = _context_widget_text(widget)
            tab = selected_tab.get("key", "quick_start")
            items, topic = _context_items(widget, text, tab)
            title = text if text else _topic_title.get(_context_topic(text, tab), "PortalAI")
            _portableai_popup.show(int(event.x_root), int(event.y_root), items, title=title)
            return "break"
        except Exception as exc:
            try: log(f"Context menu warning: {exc}")
            except Exception: pass
            return None

    def show_tray_context_menu(x, y):
        if exit_in_progress or (account_gate is not None and account_gate.locked):
            restore_from_tray()
            return
        def _open_tab(key):
            return lambda: (restore_from_tray(), show_tab(key))
        def _open_help():
            restore_from_tray(); show_help_topic("quick_start")
        def _new_chat():
            restore_from_tray(); show_tab("chat")
            if native_chat_panel is not None:
                native_chat_panel.new_chat()
        items = [
            _menu_item("Open Control Center", restore_from_tray, tone="accent"),
            _menu_item("Open Chat", _open_tab("chat")),
            _menu_item("New Chat", _new_chat),
            None,
            _menu_item("Accounts", _open_tab("accounts")),
            _menu_item("Controls", _open_tab("controls")),
            _menu_item("Runtime", _open_tab("activity")),
            _menu_item("Models", _open_tab("runtime")),
            _menu_item("Packages", _open_tab("installed")),
            _menu_item("Settings", _open_tab("settings")),
            _menu_item("Maintenance", _open_tab("maintenance")),
            _menu_item("Persistence", lambda: (restore_from_tray(), open_account_missions())),
            _menu_item("Documentation / Help", _open_help),
            None,
            _menu_item("Startup", start_components),
            _menu_item("System Test", run_system_test),
            _menu_item("Full Component Diagnosis", diagnose),
            _menu_item("Open Maintenance Reports", open_maintenance_folder),
            _menu_item("Switch to " + ("Dark" if theme_mode == "light" else "Light") + " mode", toggle_theme),
            None,
            _menu_item("Stop all components", stop_components, tone="danger"),
            _menu_item("Exit PortalAI", begin_exit_portableai, tone="danger"),
        ]
        _portableai_popup.show(int(x), int(y), items, title="PortalAI")

    class _PortableAIContextFacade:
        def install(self):
            # bind_all gives child widgets the same launcher-owned menu. Returning
            # "break" prevents an additional plain Tk/native menu from opening.
            app.bind_all("<Button-3>", _show_launcher_context, add="+")
        def apply_palette(self, _palette):
            _portableai_popup.apply_palette(_palette)

    ui_context = _PortableAIContextFacade()
    ui_context.install()
    app.bind("<Control-Shift-q>", lambda _e: begin_exit_portableai())

    # v15.117: initial widgets already use the selected palette; skip recursive repaint.
    app.after(50, lambda: relayout_main(force=True))
    # v15.117: automatic root hygiene deferred; use maintenance controls when desired.
    # Finish layout behind the retained sign-in panel; revealing the interface
    # neither replaces nor remaps the native launcher window.
    relayout_main(force=True)
    app.update_idletasks()
    app._portalai_main_ready = True
    if account_gate is not None: account_gate.application_ready()
    try:
        from native_ui_state import install as install_native_ui_state
        install_native_ui_state(app, root, account_gate, native_chat_panel, settings_page)
        from native_workflow_launcher import configure as configure_native_workflows
        configure_native_workflows(app, locals())
    except (OSError,ValueError,RuntimeError,PermissionError):
        log('Native read-only state unavailable; ordinary local/projection UI remains available.')
        workflow=getattr(app,'_portalai_native_workflow',None)
        if workflow is not None:
            workflow.complete=False
            workflow.adapter.publish_endpoint()
    log("PortalAI ready. Models shows service state; Packages lists assets; Settings holds model and media policy; Persistence manages missions and schedules. Maintenance holds diagnostics and storage. Runtime observes owned workers; Control Log reports new handoffs.")
    if getattr(app, '_portalai_account_warning', False):
        launcher_notice('Account recovery copy', 'Your login succeeded, but the encrypted recovery copy could not be repaired. Keep your current password and repair the recovery copy before relying on registry recovery.', kind='warn')
    _ensure_status_worker()
    from executable_recovery_ui import RecoveryUI
    executable_repair=RecoveryUI(app,root,jobs=gui_jobs,colors=lambda:COLORS,
        open_panel=open_launcher_panel,close_panel=close_launcher_panel,
        can_show=lambda:not exit_in_progress and not launcher_panel_state.get('overlay') and
            (account_gate is None or not account_gate.locked),
        guard_factory=recovery_guard_factory,log=log)
    def _resume_armed_missions():
        if account_gate is not None and account_gate.session.role != 'admin':
            return
        try:
            sys.path.insert(0, str(root / "Agent"))
            from mission_supervisor import ensure_running
            ensure_running(root)
        except Exception as exc:
            log(f"Mission supervisor: {exc}")
    gui_jobs.thread(target=_resume_armed_missions, name="PortalAIMissionStartup", daemon=True).start()
    pump(); app.mainloop()
    if next_account is not None:return next_account
    if single_instance_mutex is not None:
        import ctypes
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(single_instance_mutex))
    return 0


def run_application():
    from account_switch import SwitchTicket
    result=main()
    while isinstance(result,SwitchTicket):
        result=main(authenticated=result)
    return result

if __name__ == "__main__":
    raise SystemExit(run_application())
