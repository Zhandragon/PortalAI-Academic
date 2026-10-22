from __future__ import annotations

import os
import tkinter as tk
from typing import Callable, Iterable, Any

try:
    from portal_frontend_v15136 import portal_display_font, portal_body_font, display_caps
except Exception:
    def portal_display_font(_w): return "Segoe UI Semibold"
    def portal_body_font(_w): return "Segoe UI"
    def display_caps(x): return str(x).upper()

MARKER = "PORTALAI_ROUNDED_CONTEXT_MENUS_v15_136B"


def _diamond(canvas, cx, cy, size, fill, outline=None):
    return canvas.create_polygon(cx,cy-size,cx+size,cy,cx,cy+size,cx-size,cy,
                                 fill=fill,outline=outline or fill)


class ThemedPopupMenu:
    """Rounded decorative popup used by both launcher and notification-area tray.

    This intentionally avoids Windows' native TrackPopupMenu so the launcher and
    tray can share the same gold/cyan visual identity.  Items are dictionaries:
      label, command, tone=(normal|accent|danger|muted), enabled=True
    Use None or {separator: True} for a separator.
    """

    def __init__(self, root: tk.Misc, palette_getter: Callable[[], dict[str, str]]):
        self.root = root
        self.palette_getter = palette_getter
        self.window: tk.Toplevel | None = None
        self._rounded_after = None
        self._root_bindings = []
        self._dismiss_after = None
        self._timers = set()

    def close(self) -> None:
        for timer in self._timers:
            try: self.root.after_cancel(timer)
            except tk.TclError: pass
        self._timers.clear()
        if self._dismiss_after is not None:
            try: self.root.after_cancel(self._dismiss_after)
            except tk.TclError: pass
            self._dismiss_after = None
        win = self.window
        self.window = None
        # Never use a modal Tk grab for a context menu.  Remove only the temporary
        # root bindings installed by this menu so the rest of PortalAI keeps all
        # of its normal bindings.
        for seq, funcid in list(self._root_bindings):
            try: self.root.unbind(seq, funcid)
            except Exception: pass
        self._root_bindings.clear()
        if win is not None:
            try: win.destroy()
            except Exception: pass

    def apply_palette(self, _palette=None) -> None:
        self.close()

    def _later(self, delay, callback):
        timer = None
        def run():
            self._timers.discard(timer); callback()
        timer = self.root.after(delay, run); self._timers.add(timer)

    def _run(self, command) -> None:
        self.close()
        if callable(command):
            try: self.root.after_idle(command)
            except Exception: command()

    def _round_window(self, win, radius=18):
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            hwnd = int(win.winfo_id())
            w=max(20,int(win.winfo_width())); h=max(20,int(win.winfo_height()))
            user32=ctypes.WinDLL("user32",use_last_error=True)
            gdi32=ctypes.WinDLL("gdi32",use_last_error=True)
            gdi32.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6
            gdi32.CreateRoundRectRgn.restype=wintypes.HANDLE
            user32.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HANDLE,wintypes.BOOL]
            user32.SetWindowRgn.restype=ctypes.c_int
            gdi32.DeleteObject.argtypes=[wintypes.HANDLE]
            gdi32.DeleteObject.restype=wintypes.BOOL
            region=gdi32.CreateRoundRectRgn(0,0,w+1,h+1,radius*2,radius*2)
            if region:
                ok=user32.SetWindowRgn(wintypes.HWND(hwnd),region,True)
                if not ok:gdi32.DeleteObject(region)
            # Keep it out of Alt-Tab while retaining topmost popup behavior.
            GWL_EXSTYLE=-20; WS_EX_TOOLWINDOW=0x80
            get_style=user32.GetWindowLongPtrW if hasattr(user32,"GetWindowLongPtrW") else user32.GetWindowLongW
            set_style=user32.SetWindowLongPtrW if hasattr(user32,"SetWindowLongPtrW") else user32.SetWindowLongW
            style=int(get_style(hwnd,GWL_EXSTYLE));set_style(hwnd,GWL_EXSTYLE,style|WS_EX_TOOLWINDOW)
        except Exception:
            pass

    def show(self, x: int, y: int, items: Iterable[Any], *, title: str = "PortalAI") -> None:
        self.close()
        palette = dict(self.palette_getter() or {})
        bg = palette.get("panel", "#F8F3EA")
        panel2 = palette.get("panel2", "#E9E0D2")
        panel3 = palette.get("panel3", "#DED1BC")
        text = palette.get("text", "#202224")
        muted = palette.get("muted", "#625E59")
        accent = palette.get("accent", "#3E91A2")
        bad = palette.get("bad", "#A9514C")
        hover = palette.get("button_hover", "#D9CBB3")
        border = palette.get("border", "#7B5A22")
        outline = palette.get("outline", "#343638")
        gold = palette.get("gold_mid", border)
        shine = palette.get("gold_shine", "#D9BE78")

        win = tk.Toplevel(self.root)
        self.window = win
        win.withdraw(); win.overrideredirect(True)
        try: win.attributes("-topmost", True)
        except Exception: pass
        win.configure(bg=outline)

        # Connected shell: two contiguous gold outlines with corner clipping supplied
        # by SetWindowRgn after geometry is final.
        shell = tk.Frame(win,bg=bg,highlightthickness=2,highlightbackground=gold,bd=0)
        shell.pack(fill="both",expand=True,padx=1,pady=1)
        inner = tk.Frame(shell,bg=bg,highlightthickness=1,highlightbackground=shine,bd=0)
        inner.pack(fill="both",expand=True,padx=3,pady=3)

        if title:
            head=tk.Frame(inner,bg=panel3)
            head.pack(fill="x",padx=2,pady=(2,0))
            # small gold filigree bar above the title
            flourish=tk.Canvas(head,height=7,bg=panel3,bd=0,highlightthickness=0,takefocus=0)
            flourish.pack(fill="x",padx=8,pady=(4,0))
            def draw_head(_e=None):
                try:
                    w=max(80,int(flourish.winfo_width()));cy=3;cx=w/2
                    flourish.delete("all")
                    flourish.create_line(0,cy,cx-22,cy,fill=gold,width=1)
                    flourish.create_line(cx+22,cy,w,cy,fill=gold,width=1)
                    _diamond(flourish,cx,cy,4,shine,gold)
                    flourish.create_oval(cx-1,cy-1,cx+1,cy+1,fill=accent,outline=accent)
                except Exception:pass
            flourish.bind("<Configure>",draw_head,add="+")
            tk.Label(head,text=display_caps(title),bg=panel3,fg=text,
                     font=(portal_display_font(head),9,"bold"),anchor="w",padx=11,pady=6).pack(fill="x")

        body=tk.Frame(inner,bg=bg);body.pack(fill="both",expand=True,padx=4,pady=4)
        usable=0
        for item in items:
            if item is None or (isinstance(item,dict) and item.get("separator")):
                sep=tk.Canvas(body,height=8,bg=bg,bd=0,highlightthickness=0,takefocus=0)
                sep.pack(fill="x",padx=7,pady=1)
                def draw_sep(_e=None,c=sep):
                    try:
                        w=max(50,int(c.winfo_width()));cy=4;cx=w/2
                        c.delete("all");c.create_line(0,cy,cx-10,cy,fill=border,width=1);c.create_line(cx+10,cy,w,cy,fill=border,width=1)
                        _diamond(c,cx,cy,3,shine,gold)
                    except Exception:pass
                sep.bind("<Configure>",draw_sep,add="+")
                continue
            if not isinstance(item,dict):continue
            label=str(item.get("label") or "").strip()
            if not label:continue
            usable+=1;command=item.get("command");enabled=bool(item.get("enabled",True)) and callable(command)
            tone=str(item.get("tone") or "normal")
            fg=text
            if tone=="accent":fg=accent
            elif tone=="danger":fg=bad
            elif tone=="muted" or not enabled:fg=muted
            row=tk.Label(body,text=label,bg=bg,fg=fg,anchor="w",justify="left",
                         font=(portal_body_font(body),9,"bold" if tone in {"accent","danger"} else "normal"),
                         padx=13,pady=7,cursor="hand2" if enabled else "arrow")
            row.pack(fill="x",padx=2)
            if enabled:
                row.bind("<Enter>",lambda _e,w=row:w.configure(bg=hover))
                row.bind("<Leave>",lambda _e,w=row:w.configure(bg=bg))
                row.bind("<ButtonRelease-1>",lambda _e,cmd=command:self._run(cmd))

        if usable==0:
            tk.Label(body,text="No actions available",bg=bg,fg=muted,
                     font=(portal_body_font(body),9),anchor="w",padx=12,pady=8).pack(fill="x")

        # restrained footer filigree keeps tray menu visually tied to the main shell
        foot=tk.Canvas(inner,height=9,bg=bg,bd=0,highlightthickness=0,takefocus=0)
        foot.pack(fill="x",padx=10,pady=(0,4))
        def draw_foot(_e=None):
            try:
                w=max(80,int(foot.winfo_width()));cy=4;cx=w/2
                foot.delete("all");foot.create_line(w*.18,cy,cx-12,cy,fill=gold,width=1);foot.create_line(cx+12,cy,w*.82,cy,fill=gold,width=1)
                _diamond(foot,cx,cy,3,shine,gold)
            except Exception:pass
        foot.bind("<Configure>",draw_foot,add="+")

        win.update_idletasks()
        reqw=max(246,int(win.winfo_reqwidth()));reqh=max(48,int(win.winfo_reqheight()))
        sw=int(win.winfo_screenwidth());sh=int(win.winfo_screenheight());px=int(x);py=int(y)
        if px+reqw>sw-8:px=max(8,sw-reqw-8)
        if py+reqh>sh-48:py=max(8,py-reqh)
        win.geometry(f"{reqw}x{reqh}+{px}+{py}")
        win.deiconify();win.lift();win.update_idletasks();self._round_window(win,18)
        # Context menus must never modal-lock the Control Center.  In particular,
        # grab_set() prevented clicks outside the menu from reaching the GUI.
        try: win.focus_force()
        except Exception: pass
        win.bind("<Escape>",lambda _e:self.close())
        win.bind("<Button-3>",lambda _e:self.close())

        def outside_press(event):
            if self.window is not win:
                return None
            try:
                if event.widget.winfo_toplevel() is win:
                    return None
            except Exception:
                pass
            # Close on ButtonPress, then let the same click continue to the target
            # control.  No "break" is returned, so the GUI operates immediately.
            self.close()
            return None

        for seq in ("<ButtonPress-1>", "<ButtonPress-3>"):
            try:
                fid=self.root.bind(seq,outside_press,add="+")
                if fid:self._root_bindings.append((seq,fid))
            except Exception:pass

        def arm_focus_close():
            try:
                if self.window is win:
                    win.bind("<FocusOut>",lambda _e:self._later(80,lambda:self._close_if_unfocused(win)))
            except Exception:pass
        self._later(100,arm_focus_close)
        self._watch_outside(win)

    def _watch_outside(self, win):
        """A hidden launcher cannot receive Tk clicks on another application.

        Observe native foreground/pointer state only while the menu is open.
        No global input hook, modal grab, or background watcher remains on close.
        """
        if os.name != 'nt': return
        try:
            import ctypes
            from ctypes import wintypes
            api = ctypes.WinDLL('user32', use_last_error=True)
            api.GetForegroundWindow.restype = wintypes.HWND
            api.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            api.GetAncestor.restype = wintypes.HWND
            api.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
            api.GetAsyncKeyState.argtypes = [ctypes.c_int]
            api.GetAsyncKeyState.restype = ctypes.c_short
            api.SetForegroundWindow.argtypes = [wintypes.HWND]
            hwnd = api.GetAncestor(wintypes.HWND(win.winfo_id()), 2)
            api.SetForegroundWindow(hwnd)
        except (OSError, AttributeError, tk.TclError): return
        previous = [bool(api.GetAsyncKeyState(key)&0x8000) for key in (1,2,4)]
        original_foreground = api.GetForegroundWindow()
        activated = [original_foreground == hwnd]
        api.GetAsyncKeyState(0x1B)  # Discard an Escape press before this menu.
        def poll():
            self._dismiss_after = None
            if self.window is not win: return
            try:
                foreground = api.GetForegroundWindow()
                if foreground == hwnd: activated[0] = True
                if foreground != hwnd and (activated[0] or foreground != original_foreground):
                    self.close(); return
                point = wintypes.POINT(); api.GetCursorPos(ctypes.byref(point))
                inside = (win.winfo_rootx() <= point.x < win.winfo_rootx()+win.winfo_width() and
                          win.winfo_rooty() <= point.y < win.winfo_rooty()+win.winfo_height())
                states = [api.GetAsyncKeyState(key) for key in (1,2,4)]
                current = [bool(value&0x8000) for value in states]
                if (api.GetAsyncKeyState(0x1B)&0x8001 or
                    (not inside and any((new and not old) or (value&1) for new,old,value in zip(current,previous,states)))):
                    self.close(); return
                previous[:] = current
                self._dismiss_after = self.root.after(75, poll)
            except tk.TclError: self.close()
        self._dismiss_after = self.root.after(150, poll)

    def _close_if_unfocused(self, expected=None) -> None:
        win=self.window
        if expected is not None and win is not expected:return
        if win is None:return
        try:
            focus=win.focus_get()
            if focus is None or not str(focus).startswith(str(win)):self.close()
        except Exception:self.close()
