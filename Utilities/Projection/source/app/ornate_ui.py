from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont

_HEADING_CACHE = {}


def heading_font(widget) -> str:
    """Pick an elegant Windows-bundled serif without introducing a font dependency."""
    try:
        key = str(widget.tk)
    except Exception:
        key = "default"
    cached = _HEADING_CACHE.get(key)
    if cached:
        return cached
    preferred = (
        "Palatino Linotype",
        "Constantia",
        "Georgia",
        "Cambria",
        "Times New Roman",
    )
    try:
        families = {str(x).casefold(): str(x) for x in tkfont.families(widget)}
        for name in preferred:
            hit = families.get(name.casefold())
            if hit:
                _HEADING_CACHE[key] = hit
                return hit
    except Exception:
        pass
    _HEADING_CACHE[key] = "Georgia"
    return "Georgia"


def nav_font(widget) -> str:
    return heading_font(widget)


def _rounded_outline(canvas, x1, y1, x2, y2, radius, *, color, width=1, tag="ornate"):
    r = max(2, min(int(radius), int((x2 - x1) / 2), int((y2 - y1) / 2)))
    # Four straight segments and four true quarter-circle arcs.  Unlike the old
    # Unicode corner glyphs these physically meet at the same coordinates.
    canvas.create_line(x1 + r, y1, x2 - r, y1, fill=color, width=width, tags=tag)
    canvas.create_line(x1 + r, y2, x2 - r, y2, fill=color, width=width, tags=tag)
    canvas.create_line(x1, y1 + r, x1, y2 - r, fill=color, width=width, tags=tag)
    canvas.create_line(x2, y1 + r, x2, y2 - r, fill=color, width=width, tags=tag)
    canvas.create_arc(x1, y1, x1 + 2*r, y1 + 2*r, start=90, extent=90,
                      style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x2 - 2*r, y1, x2, y1 + 2*r, start=0, extent=90,
                      style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x1, y2 - 2*r, x1 + 2*r, y2, start=180, extent=90,
                      style="arc", outline=color, width=width, tags=tag)
    canvas.create_arc(x2 - 2*r, y2 - 2*r, x2, y2, start=270, extent=90,
                      style="arc", outline=color, width=width, tags=tag)


def _diamond(canvas, cx, cy, size, *, fill, outline=None, tag="ornate"):
    pts = (cx, cy-size, cx+size, cy, cx, cy+size, cx-size, cy)
    return canvas.create_polygon(*pts, fill=fill, outline=outline or fill, tags=tag)


class ConnectedBorder:
    """One connected, anti-disjoint visual border for Tk Frame-like widgets.

    The border is a single low-overhead Canvas lowered underneath the widget's
    children.  Corner cut-outs are painted with the parent's background so a
    rectangular Tk Frame visually becomes a coherent rounded card.
    """
    def __init__(self, widget, palette, *, radius=14, outline_key="gold_mid",
                 shine=True, filigree=True, erase_corners=True, inset=1, simple=False):
        self.widget = widget
        self.palette = palette
        self.radius = int(radius)
        self.outline_key = outline_key
        self.shine = bool(shine)
        self.filigree = bool(filigree)
        self.erase_corners = bool(erase_corners)
        self.inset = int(inset)
        self.simple = bool(simple)
        self._after = None
        self._last_size = (-1, -1)
        self._last_paint = None
        self.canvas = tk.Canvas(widget, bd=0, highlightthickness=0, takefocus=0)
        self.canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        try:
            self.canvas.tk.call("lower", self.canvas._w)
        except Exception:
            pass
        widget.bind("<Configure>", self._schedule, add="+")
        self.apply_palette(palette)
        try:
            widget.after_idle(self.redraw)
        except Exception:
            pass

    def _schedule(self, _event=None):
        if self._after is None:
            try:
                self._after = self.widget.after_idle(self.redraw)
            except Exception:
                self._after = None

    def apply_palette(self, palette=None):
        if palette is not None:
            self.palette = palette
        try:
            self.canvas.configure(bg=self.widget.cget("bg"))
        except Exception:
            pass
        self._last_size = (-1, -1)
        self._last_paint = None
        self._schedule()

    def redraw(self):
        self._after = None
        try:
            w = max(2, int(self.widget.winfo_width()))
            h = max(2, int(self.widget.winfo_height()))
        except Exception:
            return
        p = self.palette
        try:
            bg = self.widget.cget("bg")
            parent_bg = self.widget.master.cget("bg")
        except Exception:
            bg = p.get("panel", "#222")
            parent_bg = p.get("bg", bg)
        # Canvas item fills are independent of widget background options. A
        # same-size palette/surface change must repaint the corner masks too.
        paint = (bg, parent_bg, p.get(self.outline_key), p.get('gold_mid'),
                 p.get('gold_shine'), p.get('shadow'), self.simple, self.shine, self.filigree)
        if (w, h) == self._last_size and paint == self._last_paint and self.canvas.find_withtag("ornate"):
            return
        self._last_size = (w, h)
        self._last_paint = paint
        self.canvas.delete("ornate")
        self.canvas.configure(bg=bg)
        r = max(7, min(self.radius, max(7, min(w, h)//3)))
        if self.simple: r = min(getattr(self, 'simple_radius', 5), max(3, min(w,h)//3))
        if self.erase_corners and w > r*2 and h > r*2:
            # Cover the Frame's square corner pixels before painting the connected arc.
            cut = r + 2
            for rect, circle, start in (
                ((0, 0, cut, cut), (0, 0, cut*2, cut*2), 90),
                ((w-cut, 0, w, cut), (w-cut*2, 0, w, cut*2), 0),
                ((0, h-cut, cut, h), (0, h-cut*2, cut*2, h), 180),
                ((w-cut, h-cut, w, h), (w-cut*2, h-cut*2, w, h), 270),
            ):
                self.canvas.create_rectangle(*rect, fill=parent_bg,
                                             outline=parent_bg, tags=("ornate", "ornate-corner-mask"))
                # Refill the quarter-circle interior. Painting only a square
                # parent-colored cutout leaves a square notch inside the card.
                self.canvas.create_arc(*circle, start=start, extent=90,
                                       style='pieslice', fill=bg, outline='', width=0,
                                       tags=("ornate", "ornate-corner-fill"))
        outline = p.get(self.outline_key, p.get("gold_mid", "#A87D32"))
        shadow = p.get("shadow", "#111")
        shine = p.get("gold_shine", "#D9BE78")
        i = self.inset
        if self.simple and w > 2*r+4 and h > 2*r+4:
            from elegant_native_ui import blend
            _rounded_outline(self.canvas, i, i, w-i-1, h-i-1, r,
                             color=blend(outline, bg, .45), width=1, tag='ornate')
        elif w > 2*r+4 and h > 2*r+4:
            _rounded_outline(self.canvas, i+1, i+2, w-i-2, h-i-2, r,
                             color=shadow, width=3, tag="ornate")
            _rounded_outline(self.canvas, i, i, w-i-1, h-i-1, r,
                             color=outline, width=2, tag="ornate")
            if self.shine and w > 40 and h > 20:
                _rounded_outline(self.canvas, i+3, i+3, w-i-4, h-i-4, max(5, r-3),
                                 color=shine, width=1, tag="ornate")
        if self.filigree and not self.simple and w >= 210:
            cx = w / 2.0
            y = max(4, i + 1)
            # restrained top-center flourish; enough character without visual noise
            self.canvas.create_line(cx-58, y+1, cx-20, y+1, cx-10, y+5,
                                    fill=outline, width=1, smooth=True, tags="ornate")
            self.canvas.create_line(cx+58, y+1, cx+20, y+1, cx+10, y+5,
                                    fill=outline, width=1, smooth=True, tags="ornate")
            _diamond(self.canvas, cx, y+2, 4, fill=shine, outline=outline)
        try:
            self.canvas.tk.call("lower", self.canvas._w)
        except Exception:
            pass


class FiligreeScrollbar(tk.Canvas):
    """Compact Canvas scrollbar styled to match the PortableAI gold/cyan palette."""
    def __init__(self, master, *, command, palette, orient="vertical", width=15, **kw):
        if orient != "vertical":
            raise NotImplementedError("PortableAI FiligreeScrollbar currently supports vertical scrollbars")
        super().__init__(master, width=width, bd=0, highlightthickness=0, takefocus=0, **kw)
        self.command = command
        self.palette = palette
        self.first = 0.0
        self.last = 1.0
        self._drag_offset = None
        self._thumb = (0, 0)
        self._last_draw = None
        self.bind("<Configure>", lambda _e: self._draw(), add="+")
        self.bind("<Button-1>", self._press, add="+")
        self.bind("<B1-Motion>", self._drag, add="+")
        self.bind("<ButtonRelease-1>", self._release, add="+")
        self.apply_palette(palette)

    def apply_palette(self, palette=None):
        if palette is not None:
            self.palette = palette
        self.configure(bg=self.palette.get("bg", "#111"))
        self._draw()

    def set(self, first, last):
        try:
            self.first = max(0.0, min(1.0, float(first)))
            self.last = max(self.first, min(1.0, float(last)))
        except Exception:
            self.first, self.last = 0.0, 1.0
        if self.last - self.first >= 1.0:
            self._drag_offset = None
        self._draw()

    def _geometry(self):
        h = max(1, int(self.winfo_height()))
        top, bottom = 14, max(15, h-14)
        span = max(1, bottom-top)
        visible = max(0.04, min(1.0, self.last-self.first))
        thumb_h = min(span, max(28, int(span*visible)))
        travel = max(1, span-thumb_h)
        y1 = top + int(travel*self.first/max(1e-9, 1.0-visible)) if visible < 0.9999 else top
        y1 = max(top, min(bottom-thumb_h, y1))
        return h, top, bottom, y1, y1+thumb_h, visible

    def _draw(self):
        try:
            w = max(8, int(self.winfo_width()))
            h, top, bottom, y1, y2, visible = self._geometry()
        except Exception:
            return
        p = self.palette
        signature = (w, h, top, bottom, y1, y2, tuple(sorted(p.items())))
        if signature == self._last_draw: return
        self._last_draw = signature
        self.delete("all")
        bg = p.get("bg", "#111")
        track = p.get("panel3", bg)
        gold = p.get("gold_mid", "#A87D32")
        shine = p.get("gold_shine", "#D9BE78")
        accent = p.get("accent", "#3E91A2")
        self.configure(bg=bg)
        cx = w/2
        self.create_line(cx, top, cx, bottom, fill=gold, width=2)
        self.create_line(cx+2, top+1, cx+2, bottom-1, fill=track, width=max(3, w-7))
        self.create_rectangle(3, y1, w-4, y2, fill=gold, outline=shine, width=1)
        self.create_line(5, y1+2, w-6, y1+2, fill=shine, width=1)
        self.create_line(5, y2-2, w-6, y2-2, fill=accent, width=1)
        # Engraved vines and a central jewel remain legible on a narrow thumb.
        if y2-y1 > 32:
            cy = (y1+y2)/2
            for sign in (-1, 1):
                self.create_line(cx, cy+sign*12, cx-3, cy+sign*8, cx+3, cy+sign*5,
                                 cx, cy+sign*3, smooth=True, fill=shine, width=1, tags='filigree')
            _diamond(self, cx, cy, 2.5, fill=shine, outline=accent, tag='filigree')
        _diamond(self, cx, 7, 3, fill=shine, outline=gold, tag="all")
        _diamond(self, cx, h-7, 3, fill=shine, outline=gold, tag="all")
        self._thumb = (y1, y2)

    def _press(self, event):
        if self.last - self.first >= 1.0:
            return "break"
        h, top, bottom, y1, y2, visible = self._geometry()
        if event.y < top:
            self.command("scroll", -3, "units")
            return "break"
        if event.y > bottom:
            self.command("scroll", 3, "units")
            return "break"
        if y1 <= event.y <= y2:
            self._drag_offset = event.y - y1
            return "break"
        span = max(1, bottom-top)
        target = (event.y-top)/span - visible/2.0
        self.command("moveto", max(0.0, min(1.0-visible, target)))
        return "break"

    def _drag(self, event):
        if self._drag_offset is None:
            return "break"
        h, top, bottom, y1, y2, visible = self._geometry()
        thumb_h = y2-y1
        travel = max(1, (bottom-top)-thumb_h)
        new_y = event.y-self._drag_offset
        frac = (new_y-top)/travel
        self.command("moveto", max(0.0, min(1.0-visible, frac*(1.0-visible))))
        return "break"

    def _release(self, _event):
        self._drag_offset = None
        return "break"


def install_separator(parent, palette, *, height=8):
    c = tk.Canvas(parent, height=height, bg=parent.cget("bg"), bd=0,
                  highlightthickness=0, takefocus=0)
    c.pack(fill="x", padx=12, pady=(0, 4))
    def draw(_e=None):
        try:
            w=max(20,int(c.winfo_width())); h=max(6,int(c.winfo_height())); cy=h/2
            c.delete("all")
            g=palette.get("gold_mid", "#A87D32"); s=palette.get("gold_shine", "#D9BE78"); a=palette.get("accent", "#3E91A2")
            cx=w/2
            c.create_line(4,cy,cx-18,cy,fill=g,width=1)
            c.create_line(cx+18,cy,w-4,cy,fill=g,width=1)
            c.create_line(12,cy-1,cx-36,cy-1,fill=s,width=1)
            c.create_line(cx+36,cy-1,w-12,cy-1,fill=s,width=1)
            _diamond(c,cx,cy,4,fill=s,outline=g)
            c.create_oval(cx-1,cy-1,cx+1,cy+1,fill=a,outline=a)
        except Exception:
            pass
    c._portableai_redraw = draw
    c._portableai_palette = palette
    c.bind("<Configure>", draw, add="+")
    c.after_idle(draw)
    return c


def install_title_filigree(parent, palette):
    c = tk.Canvas(parent, height=7, bg=palette.get("panel3", parent.cget("bg")),
                  bd=0, highlightthickness=0, takefocus=0)
    c.pack(fill="x", padx=6, pady=(0, 1))
    def draw(_e=None):
        try:
            w=max(20,int(c.winfo_width())); cy=3
            c.configure(bg=palette.get("panel3", parent.cget("bg")))
            c.delete("all")
            g=palette.get("gold_mid", "#A87D32"); s=palette.get("gold_shine", "#D9BE78"); a=palette.get("accent", "#3E91A2")
            cx=w/2
            c.create_line(0,cy,cx-48,cy,fill=g,width=1)
            c.create_line(cx+48,cy,w,cy,fill=g,width=1)
            c.create_line(cx-48,cy,cx-22,cy,cx-12,cy+2,fill=s,width=1,smooth=True)
            c.create_line(cx+48,cy,cx+22,cy,cx+12,cy+2,fill=s,width=1,smooth=True)
            _diamond(c,cx,cy,4,fill=s,outline=g)
            c.create_oval(cx-1,cy-1,cx+1,cy+1,fill=a,outline=a)
        except Exception:
            pass
    c._portableai_redraw=draw
    c.bind("<Configure>",draw,add="+")
    c.after_idle(draw)
    return c


class WelcomeFiligree:
    def __init__(self, stage, palette):
        self.stage=stage; self.palette=palette; self._after=None
        self.canvas=tk.Canvas(stage,bd=0,highlightthickness=0,takefocus=0)
        self.canvas.place(x=0,y=0,relwidth=1.0,relheight=1.0)
        try:self.canvas.tk.call("lower", self.canvas._w)
        except Exception:pass
        stage.bind("<Configure>",self._schedule,add="+")
        self.apply_palette(palette)
    def _schedule(self,_e=None):
        if self._after is None:
            try:self._after=self.stage.after_idle(self.redraw)
            except Exception:self._after=None
    def apply_palette(self,palette=None):
        if palette is not None:self.palette=palette
        try:self.canvas.configure(bg=self.stage.cget("bg"))
        except Exception:pass
        self._schedule()
    def redraw(self):
        self._after=None
        try:w=max(10,int(self.stage.winfo_width()));h=max(10,int(self.stage.winfo_height()))
        except Exception:return
        p=self.palette; self.canvas.delete("all")
        try:self.canvas.configure(bg=self.stage.cget("bg"))
        except Exception:pass
        g=p.get("gold_mid","#A87D32");s=p.get("gold_shine","#D9BE78");a=p.get("accent","#3E91A2");m=p.get("muted2",g)
        cx=w/2; cy=h*0.48; base=min(w,h)
        r=max(70,min(base*0.34,260))
        for extra,color,width,start,extent in (
            (34,g,1,205,130),(52,s,1,218,104),(70,m,1,230,80),
        ):
            rr=r+extra
            self.canvas.create_arc(cx-rr,cy-rr,cx+rr,cy+rr,start=start,extent=extent,style="arc",outline=color,width=width)
            self.canvas.create_arc(cx-rr,cy-rr,cx+rr,cy+rr,start=start+180,extent=extent,style="arc",outline=color,width=width)
        # Cyan orbital accents echo the emblem without turning the whole page neon.
        rr=r+22
        self.canvas.create_arc(cx-rr,cy-rr,cx+rr,cy+rr,start=318,extent=34,style="arc",outline=a,width=2)
        self.canvas.create_arc(cx-rr,cy-rr,cx+rr,cy+rr,start=138,extent=34,style="arc",outline=a,width=2)
        # Corner filigree strokes.
        pad=26
        for sx,sy in ((1,1),(-1,1),(1,-1),(-1,-1)):
            x=pad if sx>0 else w-pad; y=pad if sy>0 else h-pad
            pts=(x, y, x+sx*32, y, x+sx*46, y+sy*14, x+sx*58, y+sy*14)
            self.canvas.create_line(*pts,fill=g,width=1,smooth=True)
            _diamond(self.canvas,x+sx*4,y+sy*4,3,fill=s,outline=g)
        # Bottom ceremonial rule.
        by=h-38
        if by>cy+30:
            self.canvas.create_line(w*0.18,by,cx-16,by,fill=g,width=1)
            self.canvas.create_line(cx+16,by,w*0.82,by,fill=g,width=1)
            _diamond(self.canvas,cx,by,5,fill=s,outline=g)
        try:self.canvas.tk.call("lower", self.canvas._w)
        except Exception:pass


class RoundedWindowController:
    """Clip a borderless Tk window to a rounded Win32 region while restored.

    Maximized state clears the custom region so normal square fullscreen/work-area
    behavior is preserved.  This is intentionally a visual shell feature only.
    """
    def __init__(self, app, hwnd_getter, maximized_getter, *, radius=18):
        self.app=app; self.hwnd_getter=hwnd_getter; self.maximized_getter=maximized_getter
        self.radius=int(radius); self._after=None; self._last_shape=None
        if os.name=="nt":
            app.bind("<Configure>",self._schedule,add="+")
            app.bind("<Map>",self._schedule,add="+")
            try:app.after(250,self.refresh)
            except Exception:pass
    def _schedule(self,_e=None):
        if os.name!="nt":return
        # A toplevel bind also receives descendant events. Scrolling embedded
        # chat cards must not rebuild the native region of the entire window.
        if _e is not None and _e.widget is not self.app:return
        if self._after is not None:
            try:self.app.after_cancel(self._after)
            except Exception:pass
        try:self._after=self.app.after(35,self.refresh)
        except Exception:self._after=None
    def refresh(self):
        self._after=None
        if os.name!="nt":return
        try:
            import ctypes
            from ctypes import wintypes
            hwnd=self.hwnd_getter()
            if not hwnd:return
            maximized=bool(self.maximized_getter())
            w=max(20,int(self.app.winfo_width()));h=max(20,int(self.app.winfo_height()))
            shape=(getattr(hwnd,'value',hwnd),w,h,maximized,self.radius)
            if shape==self._last_shape:return
            user32=ctypes.WinDLL("user32",use_last_error=True)
            gdi32=ctypes.WinDLL("gdi32",use_last_error=True)
            user32.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HANDLE,wintypes.BOOL]
            user32.SetWindowRgn.restype=ctypes.c_int
            if maximized:
                if user32.SetWindowRgn(wintypes.HWND(hwnd),None,True):self._last_shape=shape
                self._set_dwm(hwnd,False)
                return
            gdi32.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6
            gdi32.CreateRoundRectRgn.restype=wintypes.HANDLE
            user32.SetWindowRgn.argtypes=[wintypes.HWND,wintypes.HANDLE,wintypes.BOOL]
            user32.SetWindowRgn.restype=ctypes.c_int
            gdi32.DeleteObject.argtypes=[wintypes.HANDLE]
            gdi32.DeleteObject.restype=wintypes.BOOL
            region=gdi32.CreateRoundRectRgn(0,0,w+1,h+1,self.radius*2,self.radius*2)
            if region:
                # Ownership of region transfers to the window on success.
                ok=user32.SetWindowRgn(wintypes.HWND(hwnd),region,True)
                if not ok:
                    gdi32.DeleteObject(region)
                else:self._last_shape=shape
            self._set_dwm(hwnd,True)
        except Exception:
            pass
    def _set_dwm(self,hwnd,rounded):
        try:
            import ctypes
            from ctypes import wintypes
            dwm=ctypes.WinDLL("dwmapi",use_last_error=True)
            attr=33 # DWMWA_WINDOW_CORNER_PREFERENCE
            value=ctypes.c_int(2 if rounded else 1) # ROUND / DO_NOT_ROUND
            dwm.DwmSetWindowAttribute(wintypes.HWND(hwnd),attr,ctypes.byref(value),ctypes.sizeof(value))
        except Exception:
            pass


def work_area_geometry(hwnd, fallback_widget=None):
    """Return monitor work-area geometry x,y,w,h; excludes the taskbar."""
    if os.name=="nt" and hwnd:
        try:
            import ctypes
            from ctypes import wintypes
            user32=ctypes.WinDLL("user32",use_last_error=True)
            class MONITORINFO(ctypes.Structure):
                _fields_=[("cbSize",wintypes.DWORD),("rcMonitor",wintypes.RECT),("rcWork",wintypes.RECT),("dwFlags",wintypes.DWORD)]
            user32.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD]
            user32.MonitorFromWindow.restype=wintypes.HANDLE
            user32.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MONITORINFO)]
            user32.GetMonitorInfoW.restype=wintypes.BOOL
            mon=user32.MonitorFromWindow(wintypes.HWND(hwnd),2) # MONITOR_DEFAULTTONEAREST
            mi=MONITORINFO();mi.cbSize=ctypes.sizeof(mi)
            if mon and user32.GetMonitorInfoW(mon,ctypes.byref(mi)):
                r=mi.rcWork
                return int(r.left),int(r.top),int(r.right-r.left),int(r.bottom-r.top)
        except Exception:
            pass
    if fallback_widget is not None:
        return 0,0,int(fallback_widget.winfo_screenwidth()),int(fallback_widget.winfo_screenheight())
    return 0,0,1280,720


def theme_native_scrollbars(root_widget, palette):
    """Best-effort styling for legacy/native Tk scrollbars inside complex panels."""
    stack=[root_widget]
    while stack:
        w=stack.pop()
        try: stack.extend(w.winfo_children())
        except Exception: pass
        try:
            if str(w.winfo_class()) in ("Scrollbar","TScrollbar"):
                w.configure(bg=palette.get("gold_mid"),
                            activebackground=palette.get("gold_shine"),
                            troughcolor=palette.get("panel2"),
                            relief="flat",bd=0,highlightthickness=0)
        except Exception:
            pass
