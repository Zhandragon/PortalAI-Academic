# PORTALAI_VISUAL_STABILITY_v15_136C
from __future__ import annotations

import os
import re
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
try:
    from tkinter import ttk
except Exception:  # pragma: no cover
    ttk = None

from ornate_ui import ConnectedBorder, FiligreeScrollbar
from elegant_native_ui import ElegantButton

MARKER = "PORTALAI_FRONTEND_v15_136"
HOTFIX_MARKER = "PORTALAI_FRONTEND_NATIVE_TYPOGRAPHY_v15_136D"
UX_MARKER = "PORTALAI_RESPONSIVE_COMPACT_v15_136E"
PORTALAI_WORDMARK_COMPACT_v15_137 = True
PORTAL_THIN = "Portal\u2009AI"
PORTAL_THIN_UPPER = "PORTAL\u2009AI"
_FONT_CACHE: dict[tuple[str, str], str] = {}


def _families(widget):
    try:
        return {str(x).casefold(): str(x) for x in tkfont.families(widget)}
    except Exception:
        return {}


def portal_display_font(widget) -> str:
    """Ornate but readable display face from normal Windows-installed fonts.

    v15.136b used Bahnschrift plus Unicode small-cap glyphs.  The glyph fallback
    made full-height capitals and small capitals visibly different weights.  v15.136c
    renders true mixed-size capitals itself, so the face can be chosen for elegance
    rather than Unicode small-cap coverage.
    """
    key = (str(getattr(widget, "tk", "default")), "display")
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    families = _families(widget)
    for name in (
        "Copperplate Gothic Bold",
        "Copperplate Gothic Light",
        "Perpetua Titling MT",
        "Constantia",
        "Palatino Linotype",
        "Georgia",
        "Cambria",
        "Aptos Display",
        "Segoe UI Semibold",
    ):
        hit = families.get(name.casefold())
        if hit:
            _FONT_CACHE[key] = hit
            return hit
    _FONT_CACHE[key] = "Georgia"
    return _FONT_CACHE[key]


def portal_body_font(widget) -> str:
    key = (str(getattr(widget, "tk", "default")), "body")
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    families = _families(widget)
    for name in ("Aptos", "Segoe UI Variable Text", "Segoe UI", "Calibri"):
        hit = families.get(name.casefold())
        if hit:
            _FONT_CACHE[key] = hit
            return hit
    _FONT_CACHE[key] = "Segoe UI"
    return _FONT_CACHE[key]


# ---------------------------------------------------------------------------
# Stable native small-caps typography.
#
# v15.136c simulated small caps by placing a Canvas over each button/label and
# drawing every glyph separately.  That looked correct in still frames, but Tk and
# the Windows compositor can repaint the native widget underneath independently,
# causing the overlay text to blink or disappear.  v15.136d removes ALL text
# overlays.  It uses the actual widget text and a real display face instead.
#
# Copperplate Gothic Bold is preferred because its lowercase glyphs are designed as
# smaller capitals, giving the requested "large initial caps + small caps" look in
# one font, one widget, one paint pass.  If unavailable, the fallback remains an
# ornate, readable mixed-case face rather than synthesizing glyphs.
# ---------------------------------------------------------------------------

def display_caps(text: str) -> str:
    """Preserve source capitalization; the selected display font supplies the look."""
    return str(text or "")


_SMALLCAP_BUTTON_WORDS = {
    "Welcome", "Accounts", "Controls", "Chat", "Runtime", "Models", "Packages", "Settings", "Maintenance", "Help",
    "Dark", "Light",
}
_SMALLCAP_LABEL_WORDS = {
    "PortalAI", "Control Center", "PortalAI  ·  Control Center",
    "PortalAI · Control Center", "Welcome to PortalAI",
}


def _widget_font_size(widget, default=10):
    try:
        f = tkfont.Font(master=widget, font=widget.cget("font"))
        n = abs(int(f.cget("size") or default))
        return max(7, n)
    except Exception:
        return int(default)


class NativeSmallCapsController:
    """Apply the decorative face directly to native widgets; never draw overlays."""
    def __init__(self, app, palette):
        self.app = app
        self.palette = palette
        self.alive = True
        self._styled: dict[int, tuple[str, str, int]] = {}
        self.scan()
        # A slow discovery pass catches widgets created after startup. Existing
        # widgets are not reconfigured unless their visible text actually changes.
        self._schedule()

    def _source_for(self, w):
        try:
            txt = str(w.cget("text") or "")
        except Exception:
            return None
        # Dynamic navigation sizing owns its own font and must not be overwritten
        # by the slow decorative-font discovery pass.
        if getattr(w, "_portalai_dynamic_nav", False):
            return None
        cls = str(w.winfo_class())
        norm = txt.replace("\u2009", "").replace("\u202f", "")
        if cls in {"Button", "TButton"} and (txt in _SMALLCAP_BUTTON_WORDS or norm.title() in _SMALLCAP_BUTTON_WORDS):
            return txt
        label_norm = norm.replace("  ·  ", " · ")
        if cls == "Label" and (txt in _SMALLCAP_LABEL_WORDS or label_norm in _SMALLCAP_LABEL_WORDS or label_norm.casefold() in {x.casefold() for x in _SMALLCAP_LABEL_WORDS}):
            return txt
        return None

    def _style_widget(self, w, src):
        cls = str(w.winfo_class())
        family = portal_display_font(w)
        size = _widget_font_size(w, 10)
        low = src.casefold()
        if cls in {"Button", "TButton"}:
            size = max(8, min(size, 10))
        elif low == "portalai" and size >= 18:
            size = max(size, 25)
        elif "portalai" in low and "control center" in low:
            size = max(9, min(size, 11))
        elif low == "control center":
            size = max(9, min(size, 11))
        elif "welcome to portalai" in low:
            size = max(11, min(size, 14))
        key = (src, family, size)
        if self._styled.get(id(w)) == key:
            return
        try:
            w.configure(font=(family, size, "bold"))
            self._styled[id(w)] = key
        except Exception:
            pass

    def scan(self):
        for w in _walk(self.app):
            try:
                src = self._source_for(w)
            except Exception:
                src = None
            if src:
                self._style_widget(w, src)

    def _schedule(self):
        if not self.alive:
            return
        try:
            self.app.after(2200, self._tick)
        except Exception:
            pass

    def _tick(self):
        if not self.alive:
            return
        try:
            self.scan()
        finally:
            self._schedule()

    def apply_palette(self, palette):
        self.palette = palette
        # Fonts do not depend on palette; intentionally no repaint/reconfigure.

    def close(self):
        self.alive = False


def install_true_smallcaps_ui(app, palette):
    current = getattr(app, "_portalai_smallcaps_controller", None)
    if isinstance(current, NativeSmallCapsController):
        current.apply_palette(palette)
        current.scan()
        return current
    # Stop the old overlay controller if v15.136c was loaded in this interpreter.
    if current is not None:
        try:
            current.close()
        except Exception:
            pass
        try:
            for ov in list(getattr(current, "overlays", []) or []):
                canvas = getattr(ov, "canvas", None)
                if canvas is not None:
                    canvas.destroy()
        except Exception:
            pass
    ctl = NativeSmallCapsController(app, palette)
    try:
        app._portalai_smallcaps_controller = ctl
    except Exception:
        pass
    return ctl

def frontend_brand_text(text: str, *, chat=False) -> str:
    """Change only visible brand language. Filesystem/runtime identifiers stay intact."""
    s = str(text or "")
    # Never rewrite literal filesystem paths.
    if re.search(r"[A-Za-z]:[\\/]", s):
        return s
    s = s.replace("PortableAI", "PortalAI")
    # Frontend brand typography uses a THIN SPACE between Portal and AI.  It is
    # visually a single brand word, but prevents Copperplate's L/A side bearings
    # from appearing to collide at small sizes.  Internal identifiers are untouched.
    s = s.replace("PORTALAI", PORTAL_THIN_UPPER).replace("PortalAI", PORTAL_THIN)
    if chat:
        # Only visible identity phrases; do not rewrite technical component names.
        if s.strip() == "Qwen":
            s = s.replace("Qwen", "Nice")
        elif re.match(r"^\s*Qwen\s*[•·]|^\s*Qwen\s*$", s):
            s = re.sub(r"^(\s*)Qwen", r"\1Nice", s, count=1)
        elif s.startswith("Qwen ") and not any(x in s.lower() for x in ("llama", "model", "server", "gguf")):
            s = "Nice " + s[5:]
    return s


def _walk(root):
    stack = [root]
    seen = set()
    while stack:
        w = stack.pop()
        if id(w) in seen:
            continue
        seen.add(id(w))
        yield w
        try:
            stack.extend(w.winfo_children())
        except Exception:
            pass


def rebrand_widget_tree(root, *, chat=False) -> None:
    """Best-effort visible-label branding without touching files, commands, or model IDs."""
    for w in _walk(root):
        try:
            txt = w.cget("text")
        except Exception:
            txt = None
        if txt is not None:
            try:
                new = frontend_brand_text(str(txt), chat=chat)
                if new != str(txt):
                    w.configure(text=new)
            except Exception:
                pass

        # Documentation listboxes are safe to brand PortableAI -> PortalAI.
        try:
            if str(w.winfo_class()) == "Listbox":
                n = int(w.size())
                for i in range(n):
                    old = str(w.get(i))
                    new = frontend_brand_text(old, chat=False)
                    if new != old:
                        w.delete(i); w.insert(i, new)
        except Exception:
            pass

        # In help text, rewrite app branding and only the conversational Qwen phrase.
        # Replace ranges in place so DocumentationPanel heading/body tags survive.
        try:
            if str(w.winfo_class()) == "Text" and not chat:
                state = str(w.cget("state"))
                if state == "disabled": w.configure(state="normal")
                for needle, replacement in (("PortableAI", "PortalAI"), ("Chat: use Qwen", "Chat: use Nice")):
                    start = "1.0"
                    while True:
                        idx = w.search(needle, start, stopindex="end")
                        if not idx: break
                        end = f"{idx}+{len(needle)}c"
                        tags = tuple(w.tag_names(idx))
                        w.delete(idx, end)
                        w.insert(idx, replacement, tags)
                        start = f"{idx}+{len(replacement)}c"
                if state == "disabled": w.configure(state="disabled")
        except Exception:
            pass


def style_display_labels(root, palette, *, include_buttons=False) -> None:
    family = portal_display_font(root)
    for w in _walk(root):
        try:
            cls = str(w.winfo_class())
        except Exception:
            continue
        try:
            text = str(w.cget("text") or "")
        except Exception:
            text = ""
        if not text:
            continue
        try:
            if cls in {"Button", "TButton"} and include_buttons:
                w.configure(font=(family, 9, "bold"))
            elif cls == "Label":
                old = str(w.cget("font") or "")
                if any(k in text.casefold() for k in (
                    "portalai", "documentation & help", "quick start", "runtime status",
                    "installed components", "gpu / vram", "controls"
                )):
                    size = 11 if len(text) < 32 else 9
                    w.configure(font=(family, size, "bold"))
        except Exception:
            pass


class HelpPageDecorator:
    """Documentation decoration with one inset connected border and blended emblem.

    v15.136 drew an outer border plus borders around several child frames.  On the
    non-scrollable Help page those canvases reached the clipping edge, producing the
    visibly cut/doubled right and bottom lines.  v15.136c+ keeps a single inset outer
    border and lets the Listbox/Text controls provide their own inner gold outline.
    """
    def __init__(self, help_root, palette):
        self.help_root=help_root; self.palette=palette; self.borders=[]; self.emblem=None; self.emblem_target=None
        try:
            self.outer=ConnectedBorder(help_root,palette,radius=18,outline_key="gold_mid",shine=True,filigree=True,erase_corners=False,inset=6)
            self.borders.append(self.outer)
        except Exception:self.outer=None
        try:install_true_smallcaps_ui(help_root.winfo_toplevel(),palette)
        except Exception:pass
        help_root.after(180,self.refresh)

    def _largest_text(self):
        best=None
        for w in _walk(self.help_root):
            try:
                if str(w.winfo_class())!="Text":continue
                ww=max(1,int(w.winfo_width()));hh=max(1,int(w.winfo_height()))
                if ww<280 or hh<160:continue
                score=ww*hh
                if best is None or score>best[0]:best=(score,w)
            except Exception:pass
        return best[1] if best else None

    def _place_emblem(self):
        if getattr(self.help_root, '_portalai_page_watermark', False): return
        target=self._largest_text()
        if target is None:return
        # Hide the old page-root badge.  Its label background matched help_root rather
        # than the document Text background, which produced the rectangular patch.
        for w in _walk(self.help_root):
            if getattr(w,"_portableai_brand_overlay",False):
                try:w.place_forget()
                except Exception:pass
        if self.emblem is None or self.emblem_target is not target:
            try:
                if self.emblem is not None:self.emblem.destroy()
            except Exception:pass
            self.emblem_target=target
            try:
                self.emblem=tk.Label(target,bd=0,highlightthickness=0,padx=0,pady=0,takefocus=0)
                self.emblem._portalai_help_emblem=True
            except Exception:
                self.emblem=None;return
        app=self.help_root.winfo_toplevel();imgs=getattr(app,"_portableai_brand_images",{}) or {}
        try:
            ww=max(1,int(target.winfo_width()));hh=max(1,int(target.winfo_height()))
            key="tabcorner176" if ww>=760 and hh>=500 else "tabcorner128"
            img=imgs.get(key)
            if img is None:
                self.emblem.place_forget();return
            bg=str(target.cget("bg"))
            self.emblem.configure(image=img,bg=bg)
            self.emblem._portalai_brand_image=img
            margin=22 if key=="tabcorner176" else 16
            self.emblem.place(relx=1.0,rely=1.0,x=-margin,y=-margin,anchor="se")
            self.emblem.lift()
        except Exception:pass

    def refresh(self):
        p=self.palette;family=portal_display_font(self.help_root);body=portal_body_font(self.help_root)
        for w in _walk(self.help_root):
            try:cls=str(w.winfo_class())
            except Exception:continue
            try:
                if cls=="Listbox":
                    w.configure(bg=p.get("panel","#fff"),fg=p.get("text","#222"),selectbackground=p.get("accent","#369"),selectforeground="#ffffff",highlightthickness=1,highlightbackground=p.get("gold_mid",p.get("border","#997")),relief="flat",bd=0,font=(body,9),activestyle="none")
                elif cls=="Text":
                    w.configure(bg=p.get("panel","#fff"),fg=p.get("text","#222"),insertbackground=p.get("text","#222"),highlightthickness=1,highlightbackground=p.get("gold_mid",p.get("border","#997")),relief="flat",bd=0,padx=14,pady=12,font=(body,10))
                elif cls=="Label":
                    txt=str(w.cget("text") or "")
                    if txt and ("Documentation" in txt or "quick start" in txt.lower()):
                        w.configure(font=(family,13 if "Documentation" in txt else 12,"bold"),fg=p.get("text"))
            except Exception:pass
        rebrand_widget_tree(self.help_root,chat=False)
        self._place_emblem()

    def apply_palette(self,palette):
        self.palette=palette
        for b in list(self.borders):
            try:b.apply_palette(palette)
            except Exception:pass
        try:install_true_smallcaps_ui(self.help_root.winfo_toplevel(),palette).apply_palette(palette)
        except Exception:pass
        self.refresh()


def decorate_help_page(help_root,palette):
    return HelpPageDecorator(help_root,palette)


def decorate_welcome_note(note, palette):
    try:
        return ConnectedBorder(note, palette, radius=17, outline_key="gold_mid", shine=True, filigree=True)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# True golden scrollbars: replace native Tk/ttk vertical bars with the canvas
# filigree implementation so Windows theme engines cannot repaint them gray.
# ---------------------------------------------------------------------------

def _widget_scroll_targets(parent, old_scroll):
    out = []
    old_path = str(old_scroll)
    for w in _walk(parent):
        if w is old_scroll:
            continue
        try:
            ycmd = str(w.cget("yscrollcommand") or "")
            if old_path in ycmd:
                out.append(w)
        except Exception:
            pass
    return out


def _geometry_snapshot(w):
    try:
        mgr = str(w.winfo_manager())
    except Exception:
        return "", {}
    try:
        if mgr == "pack": return mgr, dict(w.pack_info())
        if mgr == "grid": return mgr, dict(w.grid_info())
        if mgr == "place": return mgr, dict(w.place_info())
    except Exception:
        pass
    return mgr, {}


def _restore_geometry(new, mgr, info):
    info = dict(info or {})
    info.pop("in", None)
    try:
        if mgr == "grid":
            allowed = {"row","column","rowspan","columnspan","sticky","padx","pady","ipadx","ipady"}
            new.grid(**{k:v for k,v in info.items() if k in allowed})
        elif mgr == "place":
            allowed = {"x","y","relx","rely","width","height","relwidth","relheight","anchor","bordermode"}
            new.place(**{k:v for k,v in info.items() if k in allowed})
        else:
            allowed = {"side","fill","expand","padx","pady","ipadx","ipady","anchor"}
            opts={k:v for k,v in info.items() if k in allowed}
            if not opts:
                opts={"side":"right","fill":"y"}
            new.pack(**opts)
    except Exception:
        try: new.pack(side="right", fill="y")
        except Exception: pass


def upgrade_vertical_scrollbars(root_widget, palette, *, include_descendants=True):
    created = getattr(root_widget, "_portalai_gold_scrollbars", None)
    if created is None:
        created = []
        try: root_widget._portalai_gold_scrollbars = created
        except Exception: pass
    nodes = list(_walk(root_widget)) if include_descendants else list(root_widget.winfo_children())
    for old in nodes:
        if getattr(old, "_portalai_replaced_scrollbar", False):
            continue
        try:
            cls = str(old.winfo_class())
            if cls not in {"Scrollbar", "TScrollbar"}:
                continue
            orient = str(old.cget("orient") or "vertical").lower()
            if "vertical" not in orient:
                continue
            cmd = str(old.cget("command") or "").strip()
            if not cmd:
                continue
        except Exception:
            continue
        parent = old.master
        mgr, info = _geometry_snapshot(old)
        if not mgr:
            continue  # Hidden originals must not reappear as duplicate bars.
        targets = _widget_scroll_targets(parent, old)
        def call_scroll(*args, _cmd=cmd, _tk=old.tk):
            try: return _tk.call(_cmd, *args)
            except Exception: return None
        try:
            new = FiligreeScrollbar(parent, command=call_scroll, palette=palette, orient="vertical", width=15)
            for target in targets:
                try: target.configure(yscrollcommand=new.set)
                except Exception: pass
            if mgr == "grid": old.grid_remove()
            elif mgr == "place": old.place_forget()
            else: old.pack_forget()
            old._portalai_replaced_scrollbar = True
            new._portalai_original_scrollbar = old
            _restore_geometry(new, mgr, info)
            created.append(new)
        except Exception:
            continue
    return created


def apply_gold_scrollbar_palette(root_widget, palette):
    for sb in list(getattr(root_widget, "_portalai_gold_scrollbars", []) or []):
        try: sb.apply_palette(palette)
        except Exception: pass


# ---------------------------------------------------------------------------
# Chat identity + always-visible faded watermark, including Text-based chat UIs.
# Uses a click-through helper window on Windows so transcript text remains readable.
# ---------------------------------------------------------------------------

class ChatWatermarkOverlay:
    """Stable click-through watermark with event-driven geometry.

    v15.136/b called geometry(), deiconify(), lift() and Win32 style mutation every
    250 ms.  Desktop composition of a layered transparent Toplevel can visibly blink
    when it is repeatedly raised/repositioned.  This version keeps one sticky target,
    only changes geometry when the target actually moves/resizes, and raises the
    overlay only when first shown.
    """
    def __init__(self,app,chat_root,brand_images,mode_getter,palette_getter):
        self.app=app;self.chat_root=chat_root;self.brand_images=brand_images
        self.mode_getter=mode_getter;self.palette_getter=palette_getter
        self.win=None;self.label=None;self.target=None;self._last_key=None;self._last_geom=None
        self._transparent_key="#010203";self._shown=False;self._bound_target=None
        self._build();self.app.after(120,self._refresh)

    def _build(self):
        try:
            win=tk.Toplevel(self.app);win.withdraw();win.overrideredirect(True);win.configure(bg=self._transparent_key)
            try:win.attributes("-transparentcolor",self._transparent_key)
            except Exception:pass
            try:win.attributes("-alpha",0.20)
            except Exception:pass
            try:win.transient(self.app)
            except Exception:pass
            lab=tk.Label(win,bg=self._transparent_key,bd=0,highlightthickness=0,padx=0,pady=0,takefocus=0)
            lab.pack(fill="both",expand=True);self.win,self.label=win,lab
            win.update_idletasks();self._make_clickthrough()
        except Exception:self.win=None;self.label=None

    def _make_clickthrough(self):
        if os.name!="nt" or self.win is None:return
        try:
            import ctypes
            user32=ctypes.WinDLL("user32",use_last_error=True);hwnd=int(self.win.winfo_id())
            GWL_EXSTYLE=-20;WS_EX_TRANSPARENT=0x20;WS_EX_TOOLWINDOW=0x80;WS_EX_NOACTIVATE=0x08000000
            get_style=user32.GetWindowLongPtrW if hasattr(user32,"GetWindowLongPtrW") else user32.GetWindowLongW
            set_style=user32.SetWindowLongPtrW if hasattr(user32,"SetWindowLongPtrW") else user32.SetWindowLongW
            style=int(get_style(hwnd,GWL_EXSTYLE));set_style(hwnd,GWL_EXSTYLE,style|WS_EX_TRANSPARENT|WS_EX_TOOLWINDOW|WS_EX_NOACTIVATE)
        except Exception:pass

    def _target_valid(self,w):
        try:
            return bool(w and w.winfo_exists() and w.winfo_ismapped() and int(w.winfo_width())>=340 and int(w.winfo_height())>=180)
        except Exception:return False

    def _find_target(self):
        # Keep the original transcript target once found.  Re-selecting the "largest"
        # Text/Canvas every timer tick could alternate between equal-size candidates.
        if self._target_valid(self.target):return self.target
        best=None
        for w in _walk(self.chat_root):
            try:
                cls=str(w.winfo_class())
                if cls not in {"Text","Canvas"}:continue
                ww=max(1,int(w.winfo_width()));hh=max(1,int(w.winfo_height()))
                if ww<340 or hh<180:continue
                score=ww*hh*(1.25 if cls=="Text" else 1.0)
                try:
                    if str(w.cget("yscrollcommand") or "").strip():score*=1.2
                except Exception:pass
                if best is None or score>best[0]:best=(score,w)
            except Exception:pass
        self.target=best[1] if best else None
        if self.target is not self._bound_target and self.target is not None:
            self._bound_target=self.target
            try:self.target.bind("<Configure>",lambda _e:self._refresh(force_geometry=True),add="+")
            except Exception:pass
            try:self.target.bind("<Map>",lambda _e:self._refresh(force_geometry=True),add="+")
            except Exception:pass
        return self.target

    def _hide(self):
        if self.win is not None and self._shown:
            try:self.win.withdraw()
            except Exception:pass
        self._shown=False;self._last_geom=None

    def _refresh(self,_event=None,force_geometry=False):
        try:
            target=self._find_target()
            if target is None or self.win is None or self.label is None or not self.chat_root.winfo_ismapped() or not self.app.winfo_viewable():
                self._hide();self.app.after(650,self._refresh);return
            ww=max(1,int(target.winfo_width()));hh=max(1,int(target.winfo_height()))
            from page_watermark import watermark_size
            size=watermark_size(ww,hh)
            if not size:
                self._hide();self.app.after(650,self._refresh);return
            mode="dark" if str(self.mode_getter()).lower()=="dark" else "light";key=f"chatwm_{mode}{size}"
            img=(self.brand_images or {}).get(key)
            if img is None:
                self._hide();self.app.after(800,self._refresh);return
            if key!=self._last_key:
                self.label.configure(image=img);self.label._portalai_image=img;self._last_key=key
                try:self.win.attributes("-alpha",0.22 if mode=="dark" else 0.18)
                except Exception:pass
            margin=22;x=int(target.winfo_rootx()+max(0,ww-size-margin));y=int(target.winfo_rooty()+max(0,hh-size-margin))
            geom=(size,x,y)
            if force_geometry or geom!=self._last_geom:
                self.win.geometry(f"{size}x{size}+{x}+{y}");self._last_geom=geom
            if not self._shown:
                self.win.deiconify();self.win.lift();self._make_clickthrough();self._shown=True
            # Poll only for visibility/theme; no lift/reposition when nothing changed.
            self.app.after(650,self._refresh)
        except tk.TclError:return
        except Exception:
            try:self.app.after(1000,self._refresh)
            except Exception:pass

    def apply_palette(self,_palette=None):
        self._last_key=None
        try:self._refresh(force_geometry=True)
        except Exception:pass

    def close(self):
        try:
            if self.win is not None:self.win.destroy()
        except Exception:pass
        self.win=None


def _rename_chat_role_tags(widget):
    # Only tagged role/name ranges are changed; user message content is untouched.
    if str(widget.winfo_class()) != "Text":
        return
    try:
        tags = tuple(widget.tag_names())
    except Exception:
        return
    for tag in tags:
        low=str(tag).casefold()
        if not any(k in low for k in ("assistant","speaker","author","role","name")):
            continue
        try:ranges=widget.tag_ranges(tag)
        except Exception:continue
        for i in range(0,len(ranges),2):
            try:
                a,b=ranges[i],ranges[i+1]
                old=widget.get(a,b)
                if old.strip()=="Qwen":
                    state=str(widget.cget("state"))
                    if state=="disabled":widget.configure(state="normal")
                    widget.delete(a,b);widget.insert(a,"Nice",tag)
                    if state=="disabled":widget.configure(state="disabled")
            except Exception:pass



def _nice_visible_text(value: str) -> str:
    """Normalize only user-facing chat identity text; technical Qwen labels elsewhere remain."""
    text = str(value or "")
    # Chat header/status/role labels are the only things pinned here.
    if re.match(r"^\s*Qwen(?=\s|$|[•·:—-])", text):
        return re.sub(r"^(\s*)Qwen", r"\1Nice", text, count=1)
    return text


def _pin_label_identity(widget) -> None:
    """Prevent NativeChat refreshes from writing Qwen back into visible status labels.

    Supports both direct widget.configure(text=...) updates and Tk textvariables.  The
    conversion therefore happens synchronously at the write, eliminating the visible
    Qwen/Nice flash instead of correcting it on a later polling tick.
    """
    if getattr(widget, "_portalai_nice_identity_pinned", False):
        return
    try:
        cls = str(widget.winfo_class())
    except Exception:
        return
    if cls not in {"Label", "Button", "TLabel", "TButton"}:
        return
    try:
        current = str(widget.cget("text") or "")
    except Exception:
        current = ""
    try:
        tv_name = str(widget.cget("textvariable") or "")
    except Exception:
        tv_name = ""
    # Only pin widgets that already look like the chat identity/status surface.
    if not (re.match(r"^\s*(Qwen|Nice)(?=\s|$|[•·:—-])", current) or tv_name):
        return

    # Direct .configure/.config writes.
    try:
        original_configure = widget.configure
        def portal_configure(cnf=None, **kw):
            if isinstance(cnf, dict) and "text" in cnf:
                cnf = dict(cnf); cnf["text"] = _nice_visible_text(cnf["text"])
            if "text" in kw:
                kw["text"] = _nice_visible_text(kw["text"])
            return original_configure(cnf, **kw) if cnf is not None else original_configure(**kw)
        widget.configure = portal_configure
        widget.config = portal_configure
    except Exception:
        pass

    # Synchronous trace for StringVar-backed labels.
    if tv_name:
        try:
            var = tk.StringVar(master=widget, name=tv_name)
            guard = {"busy": False}
            def normalize_var(*_args):
                if guard["busy"]: return
                try:
                    old = str(var.get() or ""); new = _nice_visible_text(old)
                    if new != old:
                        guard["busy"] = True
                        var.set(new)
                finally:
                    guard["busy"] = False
            trace_id = var.trace_add("write", normalize_var)
            widget._portalai_nice_var = var
            widget._portalai_nice_trace = trace_id
            normalize_var()
        except Exception:
            pass

    try:
        if current:
            widget.configure(text=_nice_visible_text(current))
    except Exception:
        pass
    widget._portalai_nice_identity_pinned = True


def _chat_action(native_chat_panel, *names):
    for name in names:
        fn = getattr(native_chat_panel, name, None)
        if callable(fn):
            return fn
    return None


def _install_themed_chat_context(widget, app, native_chat_panel, menu, palette) -> None:
    """Replace NativeChat's plain/native transcript menu with PortalAI's rounded menu."""
    if getattr(widget, "_portalai_themed_chat_context", False):
        return
    try:
        cls = str(widget.winfo_class())
        ww=max(1,int(widget.winfo_width())); hh=max(1,int(widget.winfo_height()))
    except Exception:
        return
    if cls not in {"Text", "Canvas"} or ww < 280 or hh < 120:
        return

    def copy_selection():
        try:
            if cls == "Text":
                value = widget.get("sel.first", "sel.last")
            else:
                value = ""
            if value:
                app.clipboard_clear(); app.clipboard_append(value)
        except Exception:
            pass

    def select_all():
        try:
            if cls == "Text":
                widget.tag_add("sel", "1.0", "end-1c"); widget.mark_set("insert", "1.0"); widget.see("insert")
        except Exception:
            pass

    def show_menu(event):
        items=[]
        if cls == "Text":
            try:
                has_sel = bool(widget.tag_ranges("sel"))
            except Exception:
                has_sel=False
            items += [
                {"label":"Copy selection", "command":copy_selection, "enabled":has_sel},
                {"label":"Select all", "command":select_all},
                None,
            ]
        candidates = [
            ("New chat", ("new_chat",)),
            ("New isolated chat", ("new_isolated_chat",)),
            ("Branch conversation…", ("open_branch_panel","branch_conversation")),
            ("Edit last user message…", ("edit_last_user","edit_last")),
            ("History", ("toggle_history","open_history")),
            ("Memory", ("open_memory_panel","open_memory_settings")),
            ("Chat Preferences", ("open_settings_panel","open_settings")),
            ("Instructions", ("open_instructions_panel","open_instructions")),
            ("Validate chat state", ("validate_chat_state","validate_state","validate")),
        ]
        for label,names in candidates:
            fn=_chat_action(native_chat_panel,*names)
            if fn is not None:
                items.append({"label":label,"command":fn})
        menu.show(int(event.x_root),int(event.y_root),items,title="PortalAI · Chat")
        return "break"

    # Replace, rather than add to, any old Tk/native transcript context menu.
    try:
        widget.bind("<Button-3>", show_menu)
        widget._portalai_themed_chat_context = True
    except Exception:
        pass

def install_native_chat_frontend(app, chat_root, native_chat_panel, palette, brand_images, mode_getter):
    state={"alive":True}
    overlay=ChatWatermarkOverlay(app,chat_root,brand_images,mode_getter,lambda:palette)
    try:
        from themed_popup_menu import ThemedPopupMenu
        chat_menu = ThemedPopupMenu(app, lambda: palette)
    except Exception:
        chat_menu = None

    def tick():
        if not state.get("alive"):return
        try:
            rebrand_widget_tree(chat_root,chat=True)
            for w in _walk(chat_root):
                try:_rename_chat_role_tags(w)
                except Exception:pass
                try:_pin_label_identity(w)
                except Exception:pass
                if chat_menu is not None:
                    try:_install_themed_chat_context(w,app,native_chat_panel,chat_menu,palette)
                    except Exception:pass
            upgrade_vertical_scrollbars(chat_root,palette)
            app.after(300,tick)
        except tk.TclError:return
        except Exception:
            try:app.after(750,tick)
            except Exception:pass
    app.after(50,tick)
    return {"overlay":overlay,"state":state,"chat_menu":chat_menu}


def close_native_chat_frontend(handle):
    if not isinstance(handle,dict):return
    handle.get("state",{})["alive"]=False
    try:handle.get("overlay").close()
    except Exception:pass
    try:handle.get("chat_menu").close()
    except Exception:pass



# ---------------------------------------------------------------------------
# v15.137: image wordmarks.  They use ordinary Tk PhotoImage assets so there is no
# repaint/timer overlay and no dependency on Pillow on the destination machine.
# ---------------------------------------------------------------------------

def _branding_path(root_dir, filename):
    try:
        return Path(root_dir).resolve() / "ControlCenter" / "Branding" / filename
    except Exception:
        return Path(str(root_dir)) / "ControlCenter" / "Branding" / filename


def install_wordmark_label(widget, root_dir, kind, palette=None):
    """Configure an existing Label as the PortalAI image wordmark.

    kind='welcome' uses the large title; kind='banner' uses the narrow top-bar asset.
    Falls back to stable native text if the asset is unavailable.
    """
    palette = palette or {}
    filename = "PortalAI_Wordmark_Welcome.png" if str(kind).lower()=="welcome" else "PortalAI_Wordmark_Banner.png"
    fallback = PORTAL_THIN_UPPER if str(kind).lower()=="welcome" else f"{PORTAL_THIN_UPPER}  ·  CONTROL CENTER"
    try:
        img = tk.PhotoImage(file=str(_branding_path(root_dir, filename)))
        widget.configure(image=img, text="", compound="center", bd=0, highlightthickness=0)
        widget._portalai_wordmark_image = img
        return widget
    except Exception:
        try:
            size = 26 if str(kind).lower()=="welcome" else 10
            widget.configure(text=fallback, image="", font=(portal_display_font(widget), size, "bold"),
                             fg=palette.get("text", "#202224"))
        except Exception:
            pass
        return widget


# ---------------------------------------------------------------------------
# v15.136e: responsive navigation typography + compact chat mode.
# ---------------------------------------------------------------------------

class DynamicTabFontController:
    """Resize navigation text only when the outer window crosses width bands.

    This is event-driven (Configure + debounce), not a timer, so it does not create
    a repaint loop.  Normal desktop widths gain ~2 pt over the original 8 pt tabs;
    very wide windows gain up to 4 pt, while side-by-side narrow windows stay small.
    """
    def __init__(self, app, buttons, family_getter=portal_display_font):
        self.app=app; self.buttons=[]; self.family_getter=family_getter
        self._after=None; self._size=None; self._last_width=0
        for b in list(buttons or []): self.register(b)
        try: app.bind("<Configure>", self._on_configure, add="+")
        except Exception: pass
        self._schedule(1)

    def register(self, button):
        if button is None or button in self.buttons:return
        self.buttons.append(button)
        try:button._portalai_dynamic_nav=True
        except Exception:pass
        self._schedule(1)

    @staticmethod
    def _size_for_width(width):
        width=int(width or 0)
        if width < 900:return 8
        if width < 1150:return 9
        if width < 1400:return 10
        if width < 1700:return 11
        return 12

    def _on_configure(self,event=None):
        # Ignore child Configure storms; only the toplevel dimensions matter.
        try:
            if event is not None and event.widget is not self.app:return
        except Exception:pass
        self._schedule(70)

    def _schedule(self,delay=70):
        try:
            if self._after is not None:self.app.after_cancel(self._after)
        except Exception:pass
        try:self._after=self.app.after(delay,self.refresh)
        except Exception:self._after=None

    def refresh(self):
        self._after=None
        try:w=int(self.app.winfo_width())
        except Exception:return
        size=self._size_for_width(w)
        if size==self._size and abs(w-self._last_width)<40:return
        self._size=size;self._last_width=w
        dead=[]
        for b in list(self.buttons):
            try:
                if not b.winfo_exists():dead.append(b);continue
                b.configure(font=(self.family_getter(b),size,"bold"))
            except Exception:pass
        for b in dead:
            try:self.buttons.remove(b)
            except ValueError:pass


def install_dynamic_tab_scaler(app, buttons):
    old=getattr(app,"_portalai_dynamic_tab_scaler",None)
    if isinstance(old,DynamicTabFontController):
        for b in list(buttons or []):old.register(b)
        old.refresh();return old
    ctl=DynamicTabFontController(app,buttons)
    try:app._portalai_dynamic_tab_scaler=ctl
    except Exception:pass
    return ctl


def _mgr_snapshot(widget):
    try:mgr=str(widget.winfo_manager())
    except Exception:return None
    try:
        if mgr=="pack": info=dict(widget.pack_info())
        elif mgr=="grid": info=dict(widget.grid_info())
        elif mgr=="place": info=dict(widget.place_info())
        else:return None
    except Exception:return None
    parent=widget.master
    next_widget=None
    if mgr=="pack":
        try:
            slaves=list(parent.pack_slaves());i=slaves.index(widget)
            if i+1<len(slaves):next_widget=slaves[i+1]
        except Exception:pass
    return (mgr,info,next_widget)


def _hide_with_snapshot(widget):
    snap=_mgr_snapshot(widget)
    if snap is None:return None
    mgr,info,next_widget=snap
    try:
        if mgr=="pack":widget.pack_forget()
        elif mgr=="grid":widget.grid_remove()
        elif mgr=="place":widget.place_forget()
    except Exception:return None
    return (widget,mgr,info,next_widget)


def _restore_snapshot(snap):
    if not snap:return
    w,mgr,info,next_widget=snap
    try:
        if not w.winfo_exists():return
    except Exception:return
    info=dict(info or {});info.pop("in",None)
    try:
        if mgr=="pack":
            allowed={"side","fill","expand","padx","pady","ipadx","ipady","anchor"}
            opts={k:v for k,v in info.items() if k in allowed}
            if next_widget is not None:
                try:
                    if next_widget.winfo_exists() and str(next_widget.winfo_manager())=="pack":opts["before"]=next_widget
                except Exception:pass
            w.pack(**opts)
        elif mgr=="grid":
            # grid_remove preserves the original grid configuration.
            w.grid()
        elif mgr=="place":
            allowed={"x","y","relx","rely","width","height","relwidth","relheight","anchor","bordermode"}
            w.place(**{k:v for k,v in info.items() if k in allowed})
    except Exception:pass


def _button_text(widget):
    try:
        if str(widget.winfo_class()) not in {"Button","TButton","Menubutton"}:return ""
        return str(widget.cget("text") or "").strip()
    except Exception:return ""


def _find_button(root,*names):
    wanted={str(x).strip().casefold() for x in names}
    for w in _walk(root):
        t=_button_text(w)
        if t.casefold() in wanted:return w
    return None


def _call_first(obj,names):
    if obj is None:return False
    for name in names:
        fn=getattr(obj,name,None)
        if callable(fn):
            try:fn();return True
            except Exception:return False
    return False


class CompactModeController:
    """Toolbar-style Compact Mode with the existing live NativeChat session.

    Collapsed mode is deliberately closer to the old Google Desktop search bar than
    to a miniature copy of the full Control Center: one thin action toolbar plus the
    existing composer.  The transcript is hidden until EXPAND CHAT is requested.
    The NativeChat object is never recreated, so draft text, current session, voice
    state and an in-progress response remain owned by the same frontend instance.
    """
    def __init__(self,app,content,tabbar,tab_host,tab_pages,selected_tab,show_tab,
                 chat_root,native_chat_panel,start_components,tabs_right,palette,
                 *,titlebar=None,toggle_theme=None,theme_mode_getter=None,
                 minimize_to_tray=None,exit_all=None,root_dir=None):
        self.app=app;self.content=content;self.tabbar=tabbar;self.tab_host=tab_host
        self.tab_pages=tab_pages;self.selected_tab=selected_tab;self.show_tab=show_tab
        self.chat_root=chat_root;self.native_chat_panel=native_chat_panel
        self.start_components=start_components;self.tabs_right=tabs_right;self.palette=palette
        self.titlebar=titlebar;self.toggle_theme=toggle_theme;self.theme_mode_getter=theme_mode_getter
        self.minimize_to_tray=minimize_to_tray;self.exit_all=exit_all;self.root_dir=root_dir
        self.active=False;self.expanded=False;self._hidden=[];self._transcript_snap=None
        self._history_was_visible=False;self._prev_tab="chat";self._prev_geometry=None
        self._compact_bar=None;self._compact_buttons=[];self._drag=None;self._icon_image=None
        self.toggle_button=self._make_toggle_button()

    def _colors(self):return self.palette

    def _mk_button(self,parent,text,command,accent=False,danger=False,width=None,image=None):
        p=self._colors()
        if danger:
            bg=p.get("danger","#7C403E");hover=p.get("danger_hover","#66312F");fg="#ffffff"
        elif accent:
            bg=p.get("accent","#3E91A2");hover=p.get("accent2",p.get("button_hover",bg));fg="#ffffff"
        else:
            bg=p.get("button",p.get("panel"));hover=p.get("button_hover",bg);fg=p.get("text","#111")
        kw=dict(text=text,command=command,bg=bg,fg=fg,activebackground=hover,activeforeground=fg,
                relief="flat",bd=0,padx=7,pady=3,cursor="hand2",highlightthickness=1,
                highlightbackground=p.get("border",p.get("gold_mid","#a77b22")),
                font=(portal_display_font(parent),8,"bold"))
        if image is not None:
            kw.update(image=image,compound="center",padx=3,pady=2)
        b=ElegantButton(parent,**kw)
        if width is not None:
            try:b.configure(width=width)
            except Exception:pass
        try:
            b.bind("<Enter>",lambda _e,w=b,c=hover:w.configure(bg=c),add="+")
            b.bind("<Leave>",lambda _e,w=b,c=bg:w.configure(bg=c),add="+")
        except Exception:pass
        self._compact_buttons.append((b,accent,danger))
        return b

    def _make_toggle_button(self):
        b=self._mk_button(self.tabs_right,"COMPACT",self.toggle)
        b.pack(side="right",padx=(0,5))
        try:b._portalai_dynamic_nav=True
        except Exception:pass
        return b

    def _history_visible(self):
        for w in _walk(self.chat_root):
            try:
                if str(w.winfo_class())=="Listbox" and w.winfo_ismapped() and int(w.winfo_width())>=90:return True
            except Exception:pass
        return False

    def _button(self,*names):
        return _find_button(self.chat_root,*names)

    def _button_action(self,*names):
        btn=self._button(*names)
        if btn is not None:
            def invoke():
                try:btn.invoke();return
                except Exception:pass
                try:btn.event_generate("<Button-1>");btn.event_generate("<ButtonRelease-1>")
                except Exception:pass
            return invoke
        return lambda:None

    def _hide_unique(self,widget):
        if widget is None:return
        for row in self._hidden:
            if row and row[0] is widget:return
        snap=_hide_with_snapshot(widget)
        if snap:self._hidden.append(snap)

    def _largest_transcript_widget(self):
        best=None
        for w in _walk(self.chat_root):
            try:
                cls=str(w.winfo_class())
                if cls not in {"Canvas","Text"}:continue
                ww=int(w.winfo_width());hh=int(w.winfo_height())
                if ww<280 or hh<130:continue
                score=ww*hh
                if best is None or score>best[0]:best=(score,w)
            except Exception:pass
        return best[1] if best else None

    def _collapse_transcript(self):
        if self._transcript_snap:return
        w=self._largest_transcript_widget()
        if w is None:return
        target=w.master
        # Never hide the complete Chat tab merely because the canvas is a direct child.
        if target is self.chat_root:target=w
        snap=_hide_with_snapshot(target)
        if snap:self._transcript_snap=snap

    def _expand_transcript(self):
        if self._transcript_snap:
            _restore_snapshot(self._transcript_snap);self._transcript_snap=None

    def _hide_full_chat_chrome(self):
        # Hide the full-size action toolbar, status/header row, attachment-management
        # row and bottom full-size controls.  The message composer itself remains.
        for names in (("Edit last","Edit Last"),("Hands-free","Hands free"),("Attach",),("History",)):
            b=self._button(*names)
            if b is not None:
                self._hide_unique(b.master)
        hold=self._button("Hold")
        if hold is not None:self._hide_unique(hold)

    def _load_icon(self):
        if self._icon_image is not None:return self._icon_image
        try:
            p=_branding_path(self.root_dir,"PortalAI_Compact_Icon.png")
            self._icon_image=tk.PhotoImage(file=str(p));return self._icon_image
        except Exception:return None

    def _set_theme(self,want):
        try:cur=str(self.theme_mode_getter() if callable(self.theme_mode_getter) else "").lower()
        except Exception:cur=""
        want=str(want).lower()
        if cur and cur==want:return
        if callable(self.toggle_theme):
            try:self.toggle_theme()
            except Exception:return
            try:self.app.after(80,self._refresh_colors)
            except Exception:pass

    def _refresh_colors(self):
        p=self._colors()
        try:self._compact_bar.configure(bg=p.get("panel3",p.get("panel")),highlightbackground=p.get("gold_mid",p.get("border")))
        except Exception:pass
        for b,accent,danger in list(self._compact_buttons):
            try:
                if danger:bg=p.get("danger");fg="#fff"
                elif accent:bg=p.get("accent");fg="#fff"
                else:bg=p.get("button");fg=p.get("text")
                b.configure(bg=bg,fg=fg,highlightbackground=p.get("border",p.get("gold_mid")))
            except Exception:pass

    def _drag_start(self,e):
        try:self._drag=(e.x_root,e.y_root,self.app.winfo_x(),self.app.winfo_y())
        except Exception:self._drag=None

    def _drag_move(self,e):
        if not self._drag:return
        try:
            sx,sy,ox,oy=self._drag
            self.app.geometry(f"+{ox+e.x_root-sx}+{oy+e.y_root-sy}")
        except Exception:pass

    def _attach_spot(self,parent):
        p=self._colors()
        spot=tk.Label(parent,text="DROP FILES / ATTACH",bg=p.get("panel2",p.get("panel")),fg=p.get("muted",p.get("text")),
                      bd=0,highlightthickness=1,highlightbackground=p.get("gold_mid",p.get("border")),
                      padx=12,pady=4,cursor="hand2",font=(portal_body_font(parent),8,"bold"))
        spot.bind("<Button-1>",lambda _e:self._button_action("Attach")(),add="+")
        return spot

    def _build_bar(self):
        if self._compact_bar is not None:
            try:
                if self._compact_bar.winfo_exists():return
            except Exception:pass
        p=self._colors();self._compact_buttons=[]
        bar=tk.Frame(self.content,bg=p.get("panel3",p.get("panel")),highlightthickness=1,
                     highlightbackground=p.get("gold_mid",p.get("border")))
        row=tk.Frame(bar,bg=p.get("panel3",p.get("panel")));row.pack(fill="x",padx=4,pady=(3,2))
        icon=self._load_icon()
        if icon is not None:
            self._mk_button(row,"",self.minimize_to_tray or (lambda:None),image=icon).pack(side="left",padx=(2,5))
        else:
            self._mk_button(row,"TRAY",self.minimize_to_tray or (lambda:None)).pack(side="left",padx=(2,4))
        identity=tk.Label(row,text="PortalAI",bg=p.get("panel3",p.get("panel")),fg=p.get("text"),
                          font=(portal_display_font(row),9,"bold"),padx=3)
        identity.pack(side="left",padx=(0,5))
        for w in (bar,row,identity):
            try:w.bind("<ButtonPress-1>",self._drag_start,add="+");w.bind("<B1-Motion>",self._drag_move,add="+")
            except Exception:pass

        self._mk_button(row,"STARTUP",self.start_components,accent=True).pack(side="left",padx=2)
        self._mk_button(row,"EDIT",self._button_action("Edit last","Edit Last")).pack(side="left",padx=2)
        self._mk_button(row,"BRANCH",self._button_action("Branch")).pack(side="left",padx=2)
        self._mk_button(row,"HF",self._button_action("Hands-free","Hands free")).pack(side="left",padx=2)
        self._mk_button(row,"MIC",self._button_action("Mic")).pack(side="left",padx=2)
        self._mk_button(row,"STOP",self._button_action("Stop"),danger=True).pack(side="left",padx=2)
        self._mk_button(row,"SEND",self._button_action("Send"),accent=True).pack(side="left",padx=2)
        self._mk_button(row,"EXPAND CHAT",self.toggle_chat).pack(side="left",padx=(6,2))

        self._mk_button(row,"FULL UI",self.exit).pack(side="right",padx=(2,3))
        self._mk_button(row,"DARK",lambda:self._set_theme("dark")).pack(side="right",padx=2)
        self._mk_button(row,"LIGHT",lambda:self._set_theme("light")).pack(side="right",padx=2)
        self._mk_button(row,"×",self.exit_all or self.app.destroy,danger=True).pack(side="right",padx=(4,2))

        lower=tk.Frame(bar,bg=p.get("panel3",p.get("panel")));lower.pack(fill="x",padx=5,pady=(0,3))
        self._attach_spot(lower).pack(side="left",fill="x",expand=True,padx=(0,4))
        self._mk_button(lower,"ATTACH",self._button_action("Attach")).pack(side="right")
        self._compact_bar=bar

    def _collapsed_geometry(self):
        try:sw=int(self.app.winfo_screenwidth())
        except Exception:sw=1200
        width=max(760,min(1120,sw-40));return width,150

    def _expanded_geometry(self):
        try:sw=int(self.app.winfo_screenwidth());sh=int(self.app.winfo_screenheight())
        except Exception:sw,sh=1200,800
        width=max(760,min(1120,sw-40));height=max(480,min(680,sh-90));return width,height

    def _set_size(self,expanded=False):
        try:
            w,h=self._expanded_geometry() if expanded else self._collapsed_geometry()
            self.app.geometry(f"{w}x{h}+{self.app.winfo_x()}+{self.app.winfo_y()}")
        except Exception:pass

    def enter(self):
        if self.active:return
        self.active=True;self.expanded=False;self._prev_tab=str(self.selected_tab.get("key") or "chat")
        try:self._prev_geometry=self.app.geometry()
        except Exception:self._prev_geometry=None
        self.show_tab("chat")
        self._history_was_visible=self._history_visible()
        if self._history_was_visible:_call_first(self.native_chat_panel,("toggle_history",))
        self._hidden=[]
        self._hide_full_chat_chrome();self._collapse_transcript();self._build_bar()
        if self.titlebar is not None:self._hide_unique(self.titlebar)
        self._hide_unique(self.tabbar)
        try:self._compact_bar.pack(fill="x",before=self.tab_host,pady=(0,2))
        except Exception:
            try:self._compact_bar.pack(fill="x",pady=(0,2))
            except Exception:pass
        self._set_size(False)

    def toggle_chat(self):
        if not self.active:return
        self.expanded=not self.expanded
        if self.expanded:self._expand_transcript()
        else:self._collapse_transcript()
        # Update only the compact expand button's text if it is still present.
        for b,_accent,_danger in list(self._compact_buttons):
            try:
                if str(b.cget("text")).strip().upper() in {"EXPAND CHAT","COLLAPSE CHAT"}:
                    b.configure(text="COLLAPSE CHAT" if self.expanded else "EXPAND CHAT")
            except Exception:pass
        self._set_size(self.expanded)

    def exit(self):
        if not self.active:return
        self._expand_transcript()
        try:
            if self._compact_bar is not None:self._compact_bar.pack_forget()
        except Exception:pass
        for snap in reversed(self._hidden):_restore_snapshot(snap)
        self._hidden=[]
        if self._history_was_visible and not self._history_visible():_call_first(self.native_chat_panel,("toggle_history",))
        self.active=False;self.expanded=False
        if self._prev_tab in self.tab_pages:self.show_tab(self._prev_tab)
        try:
            if self._prev_geometry and str(self.app.state())=="normal":self.app.geometry(self._prev_geometry)
        except Exception:pass

    def toggle(self):
        if self.active:self.exit()
        else:self.enter()


def install_compact_mode(app,content,tabbar,tab_host,tab_pages,selected_tab,show_tab,
                         chat_root,native_chat_panel,start_components,tabs_right,palette,**kwargs):
    old=getattr(app,"_portalai_compact_controller",None)
    if isinstance(old,CompactModeController):return old
    ctl=CompactModeController(app,content,tabbar,tab_host,tab_pages,selected_tab,show_tab,
                              chat_root,native_chat_panel,start_components,tabs_right,palette,**kwargs)
    try:app._portalai_compact_controller=ctl
    except Exception:pass
    return ctl

# ===========================================================================
# PORTALAI_LAYOUT_STABILITY_v15_138
# Responsive narrow-window navigation, compact composer, welcome hero restore,
# and Help-page de-duplication/border hardening. Later definitions intentionally
# override v15.136/137 implementations while preserving all earlier capabilities.
# ===========================================================================
PORTALAI_LAYOUT_STABILITY_v15_138 = True


def _safe_invoke(widget):
    if widget is None:
        return False
    try:
        widget.invoke(); return True
    except Exception:
        pass
    try:
        widget.event_generate("<Button-1>"); widget.event_generate("<ButtonRelease-1>"); return True
    except Exception:
        return False


def _palette_from_widget(widget):
    def get(name, fallback):
        try:
            v = str(widget.cget(name) or "")
            return v or fallback
        except Exception:
            return fallback
    bg = get("bg", "#E6DCCB")
    fg = get("fg", "#202224")
    border = get("highlightbackground", "#A87D32")
    return {
        "bg": get("bg", "#EEE7DC"), "panel": bg, "panel2": bg, "panel3": bg,
        "button": bg, "button_hover": get("activebackground", bg),
        "text": fg, "muted": fg, "accent": "#3E91A2", "accent2": "#1F6F82",
        "border": border, "gold_mid": border, "gold_shine": "#D9BE78",
        "danger": "#7C403E", "danger_hover": "#66312F",
    }


class _PortalDropdown:
    """Small themed dropdown wrapper using the existing rounded popup when available."""
    def __init__(self, app, palette_getter):
        self.app = app; self.palette_getter = palette_getter; self.popup = None
        try:
            from themed_popup_menu import ThemedPopupMenu
            self.popup = ThemedPopupMenu(app, palette_getter)
        except Exception:
            self.popup = None

    def show_for(self, widget, items, title="PortalAI"):
        try:
            x = int(widget.winfo_rootx())
            y = int(widget.winfo_rooty() + widget.winfo_height() + 3)
        except Exception:
            x = y = 0
        if self.popup is not None:
            try:
                self.popup.show(x, y, items, title=title); return
            except Exception:
                pass
        # Conservative fallback if the custom menu module is unavailable.
        try:
            p = self.palette_getter() or {}
            menu = tk.Menu(self.app, tearoff=False,
                           bg=p.get("panel", "#F8F3EA"), fg=p.get("text", "#202224"),
                           activebackground=p.get("button_hover", "#D9CBB3"),
                           activeforeground=p.get("text", "#202224"),
                           bd=1, relief="solid")
            for item in items:
                if item is None:
                    menu.add_separator(); continue
                menu.add_command(label=item.get("label", ""), command=item.get("command"),
                                 state=("normal" if item.get("enabled", True) else "disabled"))
            menu.tk_popup(x, y)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Welcome hero: deterministic pack layout, never overlays the tagline on icon.
# ---------------------------------------------------------------------------
class WelcomeFeatureController:
    def __init__(self, shell, root_dir, palette):
        self.shell = shell; self.root_dir = root_dir; self.palette = palette
        self.frame = None; self.icon_label = None; self.tag1 = None; self.tag2 = None
        self.access_note = None
        self.images = {}; self._last_size = None; self._after = None
        self._remove_stale_features(); self._build()

    def _remove_stale_features(self):
        # Remove only prior welcome hero/decor blocks, not the header or Welcome note.
        for child in list(self.shell.winfo_children()):
            if getattr(child, "_portalai_welcome_feature", False):
                try: child.destroy()
                except Exception: pass
                continue
            texts = []
            try:
                for w in _walk(child):
                    try:
                        t = str(w.cget("text") or "")
                        if t: texts.append(t)
                    except Exception: pass
            except Exception:
                pass
            blob = " ".join(texts)
            if "LOCAL" in blob and "MODULAR" in blob and ("Native Intelligence" in blob or "Scientific Workbench" in blob):
                try: child.destroy()
                except Exception: pass

    def _load(self, size):
        if size in self.images: return self.images[size]
        try:
            p = _branding_path(self.root_dir, f"PortalAI_Emblem_{size}.png")
            img = tk.PhotoImage(file=str(p)); self.images[size] = img; return img
        except Exception:
            return None

    def _build(self):
        p = self.palette
        f = tk.Frame(self.shell, bg=p.get("bg"), bd=0, highlightthickness=0)
        f._portalai_welcome_feature = True
        # It comes after header + Welcome note and owns all remaining vertical room.
        f.pack(fill="both", expand=True, padx=12, pady=(10, 8))
        tagbox = tk.Frame(f, bg=p.get("bg")); tagbox.pack(side="bottom", fill="x", pady=(2, 6))
        self.tag1 = tk.Label(tagbox, text="LOCAL  •  MODULAR  •  MULTIMODAL",
                             bg=p.get("bg"), fg=p.get("gold_shine", p.get("gold_mid")),
                             font=(portal_display_font(tagbox), 11, "bold"), anchor="center")
        self.tag1.pack(fill="x")
        self.tag2 = tk.Label(tagbox,
                             text="Native Intelligence  ·  Scientific Workbench  ·  Media Systems  ·  Dynamic GPU Leasing",
                             bg=p.get("bg"), fg=p.get("muted", p.get("text")),
                             font=(portal_body_font(tagbox), 8), anchor="center")
        self.tag2.pack(fill="x", pady=(2, 0))
        # Academic distribution: access to the separate unrestricted repository is by request.
        self.access_note = tk.Label(tagbox,
                             text='The unrestricted version of PortalAI is currently private to prevent misuse. To request access to the abliterated/uncensored PortalAI distribution repository, please contact genesislung@gmail.com',
                             bg=p.get("bg"), fg=p.get("muted", p.get("text")),
                             font=(portal_body_font(tagbox), 8), anchor="center",
                             justify="center", wraplength=560)
        self.access_note.pack(fill="x", padx=8, pady=(8, 0))
        self.icon_label = tk.Label(f, bg=p.get("bg"), bd=0, highlightthickness=0, padx=0, pady=0)
        self.icon_label.pack(side="top", fill="both", expand=True)
        self.frame = f
        try: f.bind("<Configure>", self._on_configure, add="+")
        except Exception: pass
        try: f.after(50, self.refresh)
        except Exception: pass

    def _on_configure(self, _event=None):
        if self._after is not None:
            try: self.frame.after_cancel(self._after)
            except Exception: pass
        try: self._after = self.frame.after(60, self.refresh)
        except Exception: self._after = None

    def refresh(self):
        self._after = None
        if self.frame is None: return
        p = self.palette
        try:
            h = max(1, int(self.frame.winfo_height())); w = max(1, int(self.frame.winfo_width()))
        except Exception:
            return
        # Reserve the wrapped notice and taglines before sizing the emblem.
        self.access_note.configure(wraplength=max(160, w - 16))
        text_height = (self.tag1.winfo_reqheight() + self.tag2.winfo_reqheight() +
                       self.access_note.winfo_reqheight() + 22)
        avail = max(80, min(w - 24, h - text_height))
        if avail >= 320: size = 320
        elif avail >= 240: size = 240
        elif avail >= 180: size = 180
        elif avail >= 128: size = 128
        else: size = 96
        if size != self._last_size:
            img = self._load(size)
            if img is not None:
                try: self.icon_label.configure(image=img); self.icon_label._portalai_image = img
                except Exception: pass
            self._last_size = size
        try:
            for wgt in (self.frame, self.icon_label, self.tag1.master, self.tag1, self.tag2, self.access_note):
                wgt.configure(bg=p.get("bg"))
            self.tag1.configure(fg=p.get("gold_shine", p.get("gold_mid")))
            self.tag2.configure(fg=p.get("muted", p.get("text")))
            self.access_note.configure(fg=p.get("muted", p.get("text")))
            # Only the second line yields at truly tiny heights; primary tagline remains.
            if h < 118:
                self.tag2.pack_forget()
            elif not self.tag2.winfo_manager():
                self.tag2.pack(fill="x", pady=(2, 0), before=self.access_note)
        except Exception:
            pass

    def apply_palette(self, palette):
        self.palette = palette; self.refresh()


def install_welcome_feature(shell, root_dir, palette):
    old = getattr(shell, "_portalai_welcome_feature_controller", None)
    if isinstance(old, WelcomeFeatureController):
        old.palette = palette; old.refresh(); return old
    ctl = WelcomeFeatureController(shell, root_dir, palette)
    try: shell._portalai_welcome_feature_controller = ctl
    except Exception: pass
    return ctl


# Override the wordmark installer: vertically center the top banner and automatically
# restore the lower welcome hero when the large Welcome wordmark is installed.
def install_wordmark_label(widget, root_dir, kind, palette=None):
    palette = palette or {}
    kind = str(kind).lower()
    filename = "PortalAI_Wordmark_Welcome.png" if kind == "welcome" else "PortalAI_Wordmark_Banner.png"
    fallback = PORTAL_THIN_UPPER if kind == "welcome" else f"{PORTAL_THIN_UPPER}  ·  CONTROL CENTER"
    try:
        img = tk.PhotoImage(file=str(_branding_path(root_dir, filename)))
        widget.configure(image=img, text="", compound="center", bd=0, highlightthickness=0,
                         anchor="center" if kind == "banner" else "w")
        widget._portalai_wordmark_image = img
        if kind == "banner":
            # The old fill='y' pack made the image appear top-heavy in the 40px titlebar.
            try: widget.pack_configure(fill="none", pady=(4, 4), anchor="center")
            except Exception: pass
        else:
            try:
                shell = widget.master.master.master  # label -> header_left -> header -> welcome_shell
                widget.after(80, lambda s=shell: install_welcome_feature(s, root_dir, palette))
            except Exception:
                pass
        return widget
    except Exception:
        try:
            size = 26 if kind == "welcome" else 10
            widget.configure(text=fallback, image="", font=(portal_display_font(widget), size, "bold"),
                             fg=palette.get("text", "#202224"))
            if kind == "banner":
                try: widget.pack_configure(fill="none", pady=(4, 4), anchor="center")
                except Exception: pass
        except Exception:
            pass
        return widget


# ---------------------------------------------------------------------------
# Help page: singleton decorator, one transparent emblem, larger inset border.
# ---------------------------------------------------------------------------
class HelpPageDecorator:
    def __init__(self, help_root, palette):
        self.help_root = help_root; self.palette = palette; self.emblem = None; self._img = None
        self._purge_stale_emblems()
        try:
            self.outer = ConnectedBorder(help_root, palette, radius=16, outline_key="gold_mid",
                                         shine=True, filigree=True, erase_corners=False, inset=13)
        except Exception:
            self.outer = None
        try: install_true_smallcaps_ui(help_root.winfo_toplevel(), palette)
        except Exception: pass
        help_root.after(180, self.refresh)

    def _purge_stale_emblems(self):
        for w in list(_walk(self.help_root)):
            if w is self.help_root: continue
            if (getattr(w, "_portalai_help_emblem", False) or
                getattr(w, "_portableai_brand_overlay", False) or
                getattr(w, "_portalai_brand_overlay", False) or
                getattr(w, "_portalai_brand_image", False)):
                try: w.destroy()
                except Exception: pass

    def _largest_text(self):
        best = None
        for w in _walk(self.help_root):
            try:
                if str(w.winfo_class()) != "Text": continue
                ww = max(1, int(w.winfo_width())); hh = max(1, int(w.winfo_height()))
                if ww < 260 or hh < 150: continue
                score = ww * hh
                if best is None or score > best[0]: best = (score, w)
            except Exception: pass
        return best[1] if best else None

    def _place_emblem(self):
        if getattr(self.help_root, '_portalai_page_watermark', False): return
        target = self._largest_text()
        if target is None: return
        # Destroy every stale instance first; previous builds could leave two decorators alive.
        for w in list(_walk(self.help_root)):
            if w is self.emblem: continue
            if (getattr(w, "_portalai_help_emblem", False) or
                getattr(w, "_portableai_brand_overlay", False) or
                getattr(w, "_portalai_brand_overlay", False) or
                getattr(w, "_portalai_brand_image", False)):
                try: w.destroy()
                except Exception: pass
        if self.emblem is None:
            try:
                self.emblem = tk.Label(target, bd=0, highlightthickness=0, padx=0, pady=0, takefocus=0)
                self.emblem._portalai_help_emblem = True
            except Exception:
                self.emblem = None; return
        try:
            ww = max(1, int(target.winfo_width())); hh = max(1, int(target.winfo_height()))
            size = 160 if ww >= 760 and hh >= 430 else 128
            p = Path(__file__).resolve().parent / "Branding" / f"PortalAI_Emblem_{size}.png"
            key = (str(p), size)
            if getattr(self, "_img_key", None) != key:
                self._img = tk.PhotoImage(file=str(p)); self._img_key = key
            self.emblem.configure(image=self._img, bg=str(target.cget("bg")))
            self.emblem._portalai_image = self._img
            margin = 24 if size == 160 else 18
            self.emblem.place(relx=1.0, rely=1.0, x=-margin, y=-margin, anchor="se")
            self.emblem.lift()
        except Exception:
            try: self.emblem.place_forget()
            except Exception: pass

    def refresh(self):
        p = self.palette; family = portal_display_font(self.help_root); body = portal_body_font(self.help_root)
        for w in _walk(self.help_root):
            try: cls = str(w.winfo_class())
            except Exception: continue
            try:
                if cls == "Listbox":
                    w.configure(bg=p.get("panel", "#fff"), fg=p.get("text", "#222"),
                                selectbackground=p.get("accent", "#369"), selectforeground="#ffffff",
                                highlightthickness=0 if getattr(w,"_portalai_rounded_container",False) else 1, highlightbackground=p.get("gold_mid", p.get("border", "#997")),
                                relief="flat", bd=0, font=(body, 9), activestyle="none")
                elif cls == "Text":
                    w.configure(bg=p.get("panel", "#fff"), fg=p.get("text", "#222"),
                                insertbackground=p.get("text", "#222"), highlightthickness=0 if getattr(w,"_portalai_rounded_container",False) else 1,
                                highlightbackground=p.get("gold_mid", p.get("border", "#997")),
                                relief="flat", bd=0, padx=14, pady=12, font=(body, 10))
                elif cls == "Label":
                    txt = str(w.cget("text") or "")
                    if txt and ("Documentation" in txt or "quick start" in txt.lower()):
                        w.configure(font=(family, 13 if "Documentation" in txt else 12, "bold"), fg=p.get("text"))
            except Exception: pass
        rebrand_widget_tree(self.help_root, chat=False)
        self._place_emblem()

    def apply_palette(self, palette):
        self.palette = palette
        try:
            if self.outer is not None: self.outer.apply_palette(palette)
        except Exception: pass
        try: install_true_smallcaps_ui(self.help_root.winfo_toplevel(), palette).apply_palette(palette)
        except Exception: pass
        self.refresh()


def decorate_help_page(help_root, palette):
    old = getattr(help_root, "_portalai_help_decorator", None)
    if isinstance(old, HelpPageDecorator):
        old.apply_palette(palette); return old
    # Clean any stale labels before constructing the singleton.
    for w in list(_walk(help_root)):
        if w is help_root: continue
        if (getattr(w, "_portalai_help_emblem", False) or
            getattr(w, "_portableai_brand_overlay", False) or
            getattr(w, "_portalai_brand_overlay", False) or
            getattr(w, "_portalai_brand_image", False)):
            try: w.destroy()
            except Exception: pass
    ctl = HelpPageDecorator(help_root, palette)
    try: help_root._portalai_help_decorator = ctl
    except Exception: pass
    return ctl


# ---------------------------------------------------------------------------
# Responsive full-UI navigation: normal tabs when roomy; two dropdowns when narrow.
# ---------------------------------------------------------------------------
class DynamicTabFontController:
    def __init__(self, app, buttons, family_getter=portal_display_font):
        self.app = app; self.buttons = []; self.family_getter = family_getter
        self._after = None; self._size = None; self._mobile = False
        self._left_snap = None; self._right_snap = None; self._mobile_frame = None
        self._sections_btn = None; self._tools_btn = None; self._menu = None
        for b in list(buttons or []): self.register(b)
        try: app.bind("<Configure>", self._on_configure, add="+")
        except Exception: pass
        self._schedule(1)

    def register(self, button):
        if button is None or button in self.buttons: return
        self.buttons.append(button)
        try: button._portalai_dynamic_nav = True
        except Exception: pass

    def _on_configure(self, event=None):
        try:
            if event is not None and event.widget is not self.app: return
        except Exception: pass
        self._schedule(70)

    def _schedule(self, delay=70):
        try:
            if self._after is not None: self.app.after_cancel(self._after)
        except Exception: pass
        try: self._after = self.app.after(delay, self.refresh)
        except Exception: self._after = None

    @staticmethod
    def _size_for_width(width):
        if width < 900: return 8
        if width < 1150: return 9
        if width < 1400: return 10
        if width < 1700: return 11
        return 12

    def _groups(self):
        tabs = []; tools = []
        for b in self.buttons:
            try: text = str(b.cget("text") or "").strip().upper()
            except Exception: continue
            if text in {"DARK", "LIGHT", "COMPACT"}: tools.append(b)
            else: tabs.append(b)
        return tabs, tools

    def _build_mobile(self):
        tabs, tools = self._groups()
        if not tabs: return
        left = tabs[0].master
        right = tools[0].master if tools else None
        tabbar = getattr(left, "master", None)
        if tabbar is None: return
        if self._mobile_frame is None:
            p = _palette_from_widget(tabs[0])
            frame = tk.Frame(tabbar, bg=p.get("panel3", p.get("panel")))
            self._mobile_frame = frame
            self._menu = _PortalDropdown(self.app, lambda: _palette_from_widget(tabs[0]))
            def mk(text, cmd):
                b = ElegantButton(frame, text=text, command=cmd, bg=p.get("button"), fg=p.get("text"),
                                  activebackground=p.get("button_hover"), activeforeground=p.get("text"),
                                  relief="flat", bd=0, padx=12, pady=4,
                                  font=(portal_display_font(frame), 8, "bold"), cursor="hand2",
                                  highlightthickness=1, highlightbackground=p.get("border"))
                return b
            self._sections_btn = mk("SECTIONS ▾", self._show_sections)
            self._tools_btn = mk("TOOLS ▾", self._show_tools)
            self._sections_btn.pack(side="left", fill="x", expand=True, padx=(4,2), pady=4)
            self._tools_btn.pack(side="right", padx=(2,4), pady=4)
        if self._left_snap is None: self._left_snap = _hide_with_snapshot(left)
        if right is not None and self._right_snap is None: self._right_snap = _hide_with_snapshot(right)
        if not self._mobile_frame.winfo_manager(): self._mobile_frame.pack(fill="x", expand=True)
        self._mobile = True

    def _show_sections(self):
        tabs, _ = self._groups()
        items = []
        for b in tabs:
            try: label = str(b.cget("text") or "")
            except Exception: label = ""
            items.append({"label": label, "command": lambda w=b: _safe_invoke(w)})
        if self._menu: self._menu.show_for(self._sections_btn, items, "PortalAI · Sections")

    def _show_tools(self):
        _, tools = self._groups()
        items = []
        for b in tools:
            try: label = str(b.cget("text") or "")
            except Exception: label = ""
            items.append({"label": label, "command": lambda w=b: _safe_invoke(w)})
        if self._menu: self._menu.show_for(self._tools_btn, items, "PortalAI · View")

    def _restore_mobile(self):
        if self._mobile_frame is not None:
            try: self._mobile_frame.pack_forget()
            except Exception: pass
        if self._left_snap is not None:
            _restore_snapshot(self._left_snap); self._left_snap = None
        if self._right_snap is not None:
            _restore_snapshot(self._right_snap); self._right_snap = None
        self._mobile = False

    def refresh(self):
        self._after = None
        try: width = int(self.app.winfo_width())
        except Exception: return
        if width < 760:
            self._build_mobile(); return
        if self._mobile: self._restore_mobile()
        size = self._size_for_width(width)
        if size == self._size: return
        self._size = size
        for b in list(self.buttons):
            try:
                if b.winfo_exists(): b.configure(font=(self.family_getter(b), size, "bold"))
            except Exception: pass


def install_dynamic_tab_scaler(app, buttons):
    old = getattr(app, "_portalai_dynamic_tab_scaler", None)
    if isinstance(old, DynamicTabFontController):
        for b in list(buttons or []): old.register(b)
        old.refresh(); return old
    ctl = DynamicTabFontController(app, buttons)
    try: app._portalai_dynamic_tab_scaler = ctl
    except Exception: pass
    return ctl


# ---------------------------------------------------------------------------
# Full Controls panel: one ACTIONS dropdown below narrow-width threshold.
# ---------------------------------------------------------------------------
class ResponsiveControlMenuController:
    def __init__(self, app, ctl, btnrow, buttons, palette):
        self.app = app; self.ctl = ctl; self.btnrow = btnrow; self.buttons = list(buttons); self.palette = palette
        self.menu_button = None; self.menu = _PortalDropdown(app, lambda: self.palette); self.compact = False

    def _ensure_button(self):
        if self.menu_button is not None:
            try:
                if self.menu_button.winfo_exists(): return self.menu_button
            except Exception: pass
        p = self.palette
        b = ElegantButton(self.btnrow, text="CONTROL ACTIONS ▾", command=self.show_menu,
                          bg=p.get("button"), fg=p.get("text"),
                          activebackground=p.get("button_hover"), activeforeground=p.get("text"),
                          relief="flat", bd=0, padx=14, pady=7,
                          font=(portal_display_font(self.btnrow), 9, "bold"), cursor="hand2",
                          highlightthickness=1, highlightbackground=p.get("border", p.get("gold_mid")))
        self.menu_button = b; return b

    def show_menu(self):
        items = []
        for b in self.buttons:
            try: label = str(b.cget("text") or "")
            except Exception: label = ""
            items.append({"label": label, "command": lambda w=b: _safe_invoke(w)})
        self.menu.show_for(self._ensure_button(), items, "PortalAI · Controls")

    def handle_layout(self, width):
        narrow = int(width or 0) < 610
        if narrow:
            for b in self.buttons:
                try: b.grid_forget()
                except Exception:
                    try: b.pack_forget()
                    except Exception: pass
            mb = self._ensure_button()
            if str(mb.winfo_manager()) != "grid":
                try:
                    for c in range(4): self.btnrow.grid_columnconfigure(c, weight=(1 if c == 0 else 0), uniform=("btn" if c == 0 else ""))
                    mb.grid(row=0, column=0, sticky="ew", padx=4, pady=4)
                except Exception: pass
            self.compact = True; return True
        if self.compact:
            try: self.menu_button.grid_forget()
            except Exception: pass
            self.compact = False
        return False


def install_responsive_controls(app, ctl, btnrow, buttons, palette):
    old = getattr(app, "_portalai_control_menu", None)
    if isinstance(old, ResponsiveControlMenuController):
        old.palette = palette; old.buttons = list(buttons); return old
    ctlr = ResponsiveControlMenuController(app, ctl, btnrow, buttons, palette)
    try: app._portalai_control_menu = ctlr
    except Exception: pass
    return ctlr


# ---------------------------------------------------------------------------
# Compact Mode v15.138: true toolbar + proxy composer; transcript is a toggle.
# ---------------------------------------------------------------------------
class CompactModeController:
    def __init__(self,app,content,tabbar,tab_host,tab_pages,selected_tab,show_tab,
                 chat_root,native_chat_panel,start_components,tabs_right,palette,
                 *,titlebar=None,toggle_theme=None,theme_mode_getter=None,
                 minimize_to_tray=None,exit_all=None,root_dir=None):
        self.app=app;self.content=content;self.tabbar=tabbar;self.tab_host=tab_host
        self.tab_pages=tab_pages;self.selected_tab=selected_tab;self.show_tab=show_tab
        self.chat_root=chat_root;self.native_chat_panel=native_chat_panel
        self.start_components=start_components;self.tabs_right=tabs_right;self.palette=palette
        self.titlebar=titlebar;self.toggle_theme=toggle_theme;self.theme_mode_getter=theme_mode_getter
        self.minimize_to_tray=minimize_to_tray;self.exit_all=exit_all;self.root_dir=root_dir
        self.active=False;self.expanded=False;self._hidden=[];self._tabhost_snap=None
        self._history_was_visible=False;self._prev_tab="chat";self._prev_geometry=None
        self._compact_bar=None;self._composer_row=None;self._entry_var=None;self._source_input=None
        self._compact_buttons=[];self._drag=None;self._icon_image=None;self._layout_after=None
        self._chat_menu=None;self._view_menu=None;self._theme_button=None;self._expand_button=None
        self._left_direct=[];self._chat_dropdown_button=None;self._view_dropdown_button=None
        self.toggle_button=self._make_toggle_button()

    def _colors(self): return self.palette

    def _mk_button(self,parent,text,command,accent=False,danger=False,width=None,image=None):
        p=self._colors()
        if danger: bg=p.get("danger","#7C403E");hover=p.get("danger_hover","#66312F");fg="#ffffff"
        elif accent: bg=p.get("accent","#3E91A2");hover=p.get("accent2",p.get("button_hover",bg));fg="#ffffff"
        else: bg=p.get("button",p.get("panel"));hover=p.get("button_hover",bg);fg=p.get("text","#111")
        kw=dict(text=text,command=command,bg=bg,fg=fg,activebackground=hover,activeforeground=fg,
                relief="flat",bd=0,padx=6,pady=2,cursor="hand2",highlightthickness=1,
                highlightbackground=p.get("border",p.get("gold_mid","#a77b22")),
                font=(portal_display_font(parent),8,"bold"))
        if image is not None: kw.update(image=image,compound="center",padx=2,pady=1)
        b=ElegantButton(parent,**kw)
        if width is not None:
            try:b.configure(width=width)
            except Exception:pass
        try:
            b.bind("<Enter>",lambda _e,w=b,c=hover:w.configure(bg=c),add="+")
            b.bind("<Leave>",lambda _e,w=b,c=bg:w.configure(bg=c),add="+")
        except Exception:pass
        self._compact_buttons.append((b,accent,danger)); return b

    def _make_toggle_button(self):
        b=self._mk_button(self.tabs_right,"COMPACT",self.toggle);b.pack(side="right",padx=(0,5))
        try:b._portalai_dynamic_nav=True
        except Exception:pass
        return b

    def _button(self,*names): return _find_button(self.chat_root,*names)
    def _button_action(self,*names):
        btn=self._button(*names)
        return (lambda w=btn:_safe_invoke(w)) if btn is not None else (lambda:None)

    def _history_visible(self):
        for w in _walk(self.chat_root):
            try:
                if str(w.winfo_class())=="Listbox" and w.winfo_ismapped() and int(w.winfo_width())>=90:return True
            except Exception:pass
        return False

    def _hide_unique(self,widget):
        if widget is None:return
        for snap in self._hidden:
            if snap and snap[0] is widget:return
        snap=_hide_with_snapshot(widget)
        if snap:self._hidden.append(snap)

    def _load_icon(self):
        if self._icon_image is not None:return self._icon_image
        try:self._icon_image=tk.PhotoImage(file=str(_branding_path(self.root_dir,"PortalAI_Compact_Icon.png")))
        except Exception:self._icon_image=None
        return self._icon_image

    def _find_source_input(self):
        if self._source_input is not None:
            try:
                if self._source_input.winfo_exists():return self._source_input
            except Exception:pass
        best=None
        for w in _walk(self.chat_root):
            try:
                cls=str(w.winfo_class())
                if cls not in {"Entry","TEntry","Text"}:continue
                state=str(w.cget("state") or "normal")
                if state=="disabled":continue
                ww=max(1,int(w.winfo_width()));hh=max(1,int(w.winfo_height()))
                if ww<160:continue
                if cls=="Text" and hh>150:continue
                score=(5000 if cls in {"Entry","TEntry"} else 1000)+int(w.winfo_rooty())+ww-hh*2
                if best is None or score>best[0]:best=(score,w)
            except Exception:pass
        self._source_input=best[1] if best else None
        return self._source_input

    def _read_source(self):
        w=self._find_source_input()
        if w is None:return ""
        try:
            if str(w.winfo_class())=="Text":return str(w.get("1.0","end-1c"))
            return str(w.get())
        except Exception:return ""

    def _write_source(self,text):
        w=self._find_source_input()
        if w is None:return False
        try:
            if str(w.winfo_class())=="Text":
                w.delete("1.0","end");w.insert("1.0",text)
            else:
                w.delete(0,"end");w.insert(0,text)
            try:w.event_generate("<KeyRelease>")
            except Exception:pass
            return True
        except Exception:return False

    def _send_compact(self):
        text=str(self._entry_var.get() if self._entry_var is not None else "")
        if text.strip():self._write_source(text)
        if self._button_action("Send")():
            pass
        else:
            _call_first(self.native_chat_panel,("submit_message","send_message","on_send"))
        try:self.app.after(80,lambda:self._entry_var.set(""))
        except Exception:pass

    def _sync_entry_from_source(self):
        if self._entry_var is None:return
        try:
            if not str(self._entry_var.get() or "").strip():self._entry_var.set(self._read_source())
        except Exception:pass

    def _hide_full_chat_chrome(self):
        # Hide full-size toolbars and the native composer/control rows. Compact mode
        # uses its own composer while preserving the same NativeChat session underneath.
        for names in (("Edit last","Edit Last"),("History",),("Hands-free","Hands free"),("Attach",),("Hold",),("Send",)):
            b=self._button(*names)
            if b is not None:self._hide_unique(b.master)
        src=self._find_source_input()
        if src is not None:self._hide_unique(src.master)

    def _drag_start(self,e):
        try:self._drag=(e.x_root,e.y_root,self.app.winfo_x(),self.app.winfo_y())
        except Exception:self._drag=None
    def _drag_move(self,e):
        if not self._drag:return
        try:
            sx,sy,ox,oy=self._drag;self.app.geometry(f"+{ox+e.x_root-sx}+{oy+e.y_root-sy}")
        except Exception:pass

    def _theme_label(self):
        try:cur=str(self.theme_mode_getter() if callable(self.theme_mode_getter) else "light").lower()
        except Exception:cur="light"
        return "LIGHT" if cur=="dark" else "DARK"

    def _toggle_theme(self):
        if callable(self.toggle_theme):
            try:self.toggle_theme()
            except Exception:return
        try:self.app.after(80,self._refresh_colors)
        except Exception:pass

    def _show_chat_menu(self):
        items=[
            {"label":"Edit last", "command":self._button_action("Edit last","Edit Last")},
            {"label":"Branch", "command":self._button_action("Branch")},
            {"label":"Hands-free", "command":self._button_action("Hands-free","Hands free")},
            {"label":"Mic", "command":self._button_action("Mic")},
            {"label":"Attach", "command":self._button_action("Attach")},
        ]
        if self._chat_menu:self._chat_menu.show_for(self._chat_dropdown_button,items,"PortalAI · Chat")

    def _show_view_menu(self):
        items=[
            {"label":self._theme_label()+" MODE", "command":self._toggle_theme},
            {"label":"COLLAPSE CHAT" if self.expanded else "EXPAND CHAT", "command":self.toggle_chat},
            {"label":"FULL UI", "command":self.exit},
            {"label":"MINIMIZE TO TRAY", "command":self.minimize_to_tray or (lambda:None)},
        ]
        if self._view_menu:self._view_menu.show_for(self._view_dropdown_button,items,"PortalAI · View")

    def _attach_spot(self,parent):
        p=self._colors()
        b=ElegantButton(parent,text="ATTACH",command=self._button_action("Attach"),
                        bg=p.get("button"),fg=p.get("text"),activebackground=p.get("button_hover"),activeforeground=p.get("text"),
                        relief="flat",bd=0,padx=7,pady=2,cursor="hand2",highlightthickness=1,
                        highlightbackground=p.get("gold_mid",p.get("border")),font=(portal_display_font(parent),8,"bold"))
        return b

    def _build_bar(self):
        if self._compact_bar is not None:
            try:
                if self._compact_bar.winfo_exists():return
            except Exception:pass
        p=self._colors();self._compact_buttons=[]
        bar=tk.Frame(self.content,bg=p.get("panel3",p.get("panel")),highlightthickness=1,
                     highlightbackground=p.get("gold_mid",p.get("border")))
        row=tk.Frame(bar,bg=p.get("panel3",p.get("panel")));row.pack(fill="x",padx=4,pady=(3,2))
        left=tk.Frame(row,bg=p.get("panel3",p.get("panel")));left.pack(side="left",fill="x",expand=True)
        right=tk.Frame(row,bg=p.get("panel3",p.get("panel")));right.pack(side="right")
        icon=self._load_icon()
        iconbtn=self._mk_button(left,"",self.minimize_to_tray or (lambda:None),image=icon,width=3) if icon is not None else self._mk_button(left,"TRAY",self.minimize_to_tray or (lambda:None))
        iconbtn.pack(side="left",padx=(2,4))
        identity=tk.Label(left,text="PortalAI",bg=p.get("panel3",p.get("panel")),fg=p.get("text"),font=(portal_display_font(left),9,"bold"),padx=3)
        identity.pack(side="left",padx=(0,5))
        for w in (bar,row,left,identity):
            try:w.bind("<ButtonPress-1>",self._drag_start,add="+");w.bind("<B1-Motion>",self._drag_move,add="+")
            except Exception:pass

        startup=self._mk_button(left,"STARTUP",self.start_components,accent=True);startup.pack(side="left",padx=2)
        stop=self._mk_button(left,"STOP",self._button_action("Stop"),danger=True);stop.pack(side="left",padx=2)
        send=self._mk_button(left,"SEND",self._send_compact,accent=True);send.pack(side="left",padx=2)
        self._left_direct=[startup,stop,send]
        self._chat_menu=_PortalDropdown(self.app,lambda:self.palette);self._view_menu=_PortalDropdown(self.app,lambda:self.palette)
        self._chat_dropdown_button=self._mk_button(left,"CHAT ▾",self._show_chat_menu);self._chat_dropdown_button.pack(side="left",padx=(4,2))

        # Pack left-to-right inside a right cluster, guaranteeing X is physically far-right.
        self._theme_button=self._mk_button(right,self._theme_label(),self._toggle_theme)
        self._expand_button=self._mk_button(right,"EXPAND CHAT",self.toggle_chat)
        full=self._mk_button(right,"FULL UI",self.exit)
        tray=self._mk_button(right,"",self.minimize_to_tray or (lambda:None),image=icon,width=3) if icon is not None else self._mk_button(right,"TRAY",self.minimize_to_tray or (lambda:None))
        close=self._mk_button(right,"×",self.exit_all or self.app.destroy,danger=True,width=3)
        self._view_dropdown_button=self._mk_button(right,"VIEW ▾",self._show_view_menu)
        self._right_direct=[self._theme_button,self._expand_button,full,tray]
        for b in self._right_direct:b.pack(side="left",padx=2)
        close.pack(side="left",padx=(3,2))

        # One-line proxy composer: always visible in collapsed mode and remains the
        # single composer in expanded Compact Mode while the native composer is hidden.
        comp=tk.Frame(bar,bg=p.get("panel3",p.get("panel")));comp.pack(fill="x",padx=5,pady=(0,4))
        attach=self._attach_spot(comp);attach.pack(side="left",padx=(0,4))
        self._entry_var=tk.StringVar(master=self.app,value=self._read_source())
        entry=tk.Entry(comp,textvariable=self._entry_var,bg=p.get("panel",p.get("bg")),fg=p.get("text"),
                       insertbackground=p.get("text"),relief="flat",bd=0,highlightthickness=1,
                       highlightbackground=p.get("gold_mid",p.get("border")),highlightcolor=p.get("accent"),
                       font=(portal_body_font(comp),10))
        entry.pack(side="left",fill="x",expand=True,ipady=5)
        entry.bind("<Return>",lambda _e:(self._send_compact(),"break")[1])
        self._composer_row=comp;self._compact_bar=bar;self._compact_entry_widget=entry;self._close_button=close
        try:self.app.bind("<Configure>",self._compact_configure,add="+")
        except Exception:pass

    def _compact_configure(self,event=None):
        if not self.active:return
        try:
            if event is not None and event.widget is not self.app:return
        except Exception:pass
        if self._layout_after is not None:
            try:self.app.after_cancel(self._layout_after)
            except Exception:pass
        try:self._layout_after=self.app.after(60,self._layout_toolbar)
        except Exception:self._layout_after=None

    def _layout_toolbar(self):
        self._layout_after=None
        if not self.active or self._compact_bar is None:return
        try:w=int(self.app.winfo_width())
        except Exception:w=760
        narrow=w<900
        # CHAT menu remains the compact interaction bucket. On wider compact windows
        # expose its actions directly; on narrow ones they collapse into CHAT ▾.
        extra_names=[("EDIT",("Edit last","Edit Last")),("BRANCH",("Branch",)),("HF",("Hands-free","Hands free")),("MIC",("Mic",))]
        if not hasattr(self,"_extra_direct"):self._extra_direct=[]
        left=self._chat_dropdown_button.master
        if narrow:
            for b in list(self._extra_direct):
                try:b.pack_forget()
                except Exception:pass
            if not self._chat_dropdown_button.winfo_manager():self._chat_dropdown_button.pack(side="left",padx=(4,2))
            for b in self._right_direct:
                try:b.pack_forget()
                except Exception:pass
            if not self._view_dropdown_button.winfo_manager():self._view_dropdown_button.pack(side="left",padx=(2,2),before=self._close_button)
        else:
            try:self._chat_dropdown_button.pack_forget()
            except Exception:pass
            if not self._extra_direct:
                for text,names in extra_names:
                    b=self._mk_button(left,text,self._button_action(*names));self._extra_direct.append(b)
            for b in self._extra_direct:
                if not b.winfo_manager():b.pack(side="left",padx=2)
            try:self._view_dropdown_button.pack_forget()
            except Exception:pass
            for b in self._right_direct:
                if not b.winfo_manager():b.pack(side="left",padx=2,before=self._close_button)
        self._refresh_colors()

    def _refresh_colors(self):
        p=self._colors()
        try:
            self._compact_bar.configure(bg=p.get("panel3",p.get("panel")),highlightbackground=p.get("gold_mid",p.get("border")))
            self._composer_row.configure(bg=p.get("panel3",p.get("panel")))
            self._compact_entry_widget.configure(bg=p.get("panel",p.get("bg")),fg=p.get("text"),insertbackground=p.get("text"),
                                                 highlightbackground=p.get("gold_mid",p.get("border")),highlightcolor=p.get("accent"))
            if self._theme_button is not None:self._theme_button.configure(text=self._theme_label())
            if self._expand_button is not None:self._expand_button.configure(text="COLLAPSE CHAT" if self.expanded else "EXPAND CHAT")
        except Exception:pass
        for b,accent,danger in list(self._compact_buttons):
            try:
                if danger:bg=p.get("danger");fg="#fff"
                elif accent:bg=p.get("accent");fg="#fff"
                else:bg=p.get("button");fg=p.get("text")
                b.configure(bg=bg,fg=fg,activebackground=(p.get("danger_hover") if danger else p.get("accent2") if accent else p.get("button_hover")),
                            activeforeground=fg,highlightbackground=p.get("border",p.get("gold_mid")))
            except Exception:pass

    def _collapsed_geometry(self):
        try:sw=int(self.app.winfo_screenwidth())
        except Exception:sw=1200
        return max(620,min(860,sw-40)), 92
    def _expanded_geometry(self):
        try:sw=int(self.app.winfo_screenwidth());sh=int(self.app.winfo_screenheight())
        except Exception:sw,sh=1200,800
        return max(760,min(1120,sw-40)), max(480,min(680,sh-90))
    def _set_size(self,expanded=False):
        try:
            w,h=self._expanded_geometry() if expanded else self._collapsed_geometry()
            self.app.geometry(f"{w}x{h}+{self.app.winfo_x()}+{self.app.winfo_y()}")
            # Prevent the packed content from retaining the old tall requested size.
            self.app.update_idletasks()
        except Exception:pass

    def _hide_tab_host(self):
        if self._tabhost_snap is None:self._tabhost_snap=_hide_with_snapshot(self.tab_host)
    def _show_tab_host(self):
        if self._tabhost_snap is not None:
            _restore_snapshot(self._tabhost_snap);self._tabhost_snap=None

    def enter(self):
        if self.active:return
        self.active=True;self.expanded=False;self._prev_tab=str(self.selected_tab.get("key") or "chat")
        try:self._prev_geometry=self.app.geometry()
        except Exception:self._prev_geometry=None
        self.show_tab("chat");self._source_input=self._find_source_input();self._history_was_visible=self._history_visible()
        if self._history_was_visible:_call_first(self.native_chat_panel,("toggle_history",))
        self._hidden=[];self._hide_full_chat_chrome();self._build_bar();self._sync_entry_from_source()
        if self.titlebar is not None:self._hide_unique(self.titlebar)
        self._hide_unique(self.tabbar);self._hide_tab_host()
        try:self._compact_bar.pack(fill="x",before=self.tab_host,pady=0)
        except Exception:
            try:self._compact_bar.pack(fill="x",pady=0)
            except Exception:pass
        self._set_size(False);self._layout_toolbar()

    def toggle_chat(self):
        if not self.active:return
        self.expanded=not self.expanded
        if self.expanded:self._show_tab_host()
        else:self._hide_tab_host()
        if self._expand_button is not None:
            try:self._expand_button.configure(text="COLLAPSE CHAT" if self.expanded else "EXPAND CHAT")
            except Exception:pass
        self._set_size(self.expanded);self._layout_toolbar()

    def exit(self):
        if not self.active:return
        # Preserve a compact-mode draft in the real composer before restoring full UI.
        try:
            draft=str(self._entry_var.get() or "") if self._entry_var is not None else ""
            if draft:self._write_source(draft)
        except Exception:pass
        self._show_tab_host()
        try:
            if self._compact_bar is not None:self._compact_bar.pack_forget()
        except Exception:pass
        for snap in reversed(self._hidden):_restore_snapshot(snap)
        self._hidden=[]
        if self._history_was_visible and not self._history_visible():_call_first(self.native_chat_panel,("toggle_history",))
        self.active=False;self.expanded=False
        if self._prev_tab in self.tab_pages:self.show_tab(self._prev_tab)
        try:
            if self._prev_geometry and str(self.app.state())=="normal":self.app.geometry(self._prev_geometry)
        except Exception:pass

    def toggle(self):
        if self.active:self.exit()
        else:self.enter()


def install_compact_mode(app,content,tabbar,tab_host,tab_pages,selected_tab,show_tab,
                         chat_root,native_chat_panel,start_components,tabs_right,palette,**kwargs):
    old=getattr(app,"_portalai_compact_controller",None)
    if isinstance(old,CompactModeController):return old
    ctl=CompactModeController(app,content,tabbar,tab_host,tab_pages,selected_tab,show_tab,
                              chat_root,native_chat_panel,start_components,tabs_right,palette,**kwargs)
    try:app._portalai_compact_controller=ctl
    except Exception:pass
    return ctl

# ===========================================================================
# PORTALAI_V15_138A_STARTUP_COMPAT
# v15.137b permanently added install_responsive_nav_layout to PortableAI_GUI.py.
# v15.138 replaced this helper from an older branch and accidentally removed that
# exported name, causing an ImportError before the Control Center window appeared.
# v15.138's final DynamicTabFontController already owns narrow-window navigation,
# so this compatibility entry point delegates to that controller instead of
# reintroducing the older pack/unpack controller (which would conflict with it).
# ===========================================================================
PORTALAI_V15_138A_STARTUP_COMPAT = True
PORTALAI_COMPACT_RESPONSIVE_v15_137B = True


def install_responsive_nav_layout(app, tabs_left, tabs_right):
    """Backward-compatible v15.137b API retained for cumulative GUI builds.

    v15.138 moved responsive navigation into the final DynamicTabFontController.
    Return/delegate to that live controller when present.  The tabs arguments are
    retained only for API compatibility with the already-patched GUI.
    """
    ctl = getattr(app, "_portalai_dynamic_tab_scaler", None)
    if ctl is not None:
        try:
            ctl.refresh()
        except Exception:
            pass
        return ctl

    # Extremely defensive fallback for an unusual call-order: do not rearrange
    # widgets with the obsolete v15.137b controller.  A tiny inert adapter avoids
    # import/startup failure until install_dynamic_tab_scaler is created.
    class _ResponsiveNavCompat:
        def refresh(self):
            live = getattr(app, "_portalai_dynamic_tab_scaler", None)
            if live is not None:
                try:
                    live.refresh()
                except Exception:
                    pass
            return live
    compat = _ResponsiveNavCompat()
    try:
        app._portalai_responsive_nav_layout = compat
    except Exception:
        pass
    return compat


def _normalize_button_label(value):
    """Normalize decorative Native Chat button labels for robust Compact actions."""
    s = str(value or "").strip().casefold()
    s = re.sub(r"^[^a-z0-9+]+", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _find_button(root, *names):
    """v15.137b-compatible lookup: tolerate glyph prefixes and short state suffixes."""
    wanted = {_normalize_button_label(x) for x in names}
    for w in _walk(root):
        t = _button_text(w)
        n = _normalize_button_label(t)
        if n in wanted:
            return w
        if any(n.startswith(x + " ") for x in wanted if x):
            return w
    return None


# ===========================================================================
# PORTALAI_VISUAL_POLISH_v15_138B
# Cumulative post-v15.138 visual/layout fixes:
#   * viewport-driven Welcome emblem sizing
#   * visible rounded filigree Help border
#   * exact navigation font family sharing for COMPACT + compact toolbar
#   * immediate compact-button hover release
#   * vertically centered top-banner brand and compact brand cluster
#   * truly short Compact collapsed window (temporarily lowers Tk minsize)
# Runtime card gold is patched in PortableAI_GUI.py by the v15.138b installer.
# ===========================================================================
PORTALAI_VISUAL_POLISH_v15_138B = True


def _portalai_font_parts(widget, fallback_size=9):
    """Return a stable (family, size, weight) tuple from an existing native widget."""
    try:
        f = tkfont.Font(master=widget, font=widget.cget("font"))
        family = str(f.actual("family") or portal_display_font(widget))
        size = abs(int(f.actual("size") or fallback_size))
        weight = str(f.actual("weight") or "bold")
        return family, max(7, size), ("bold" if weight.lower() == "bold" else "normal")
    except Exception:
        return portal_display_font(widget), int(fallback_size), "bold"


def _portalai_reference_nav(app):
    """Find one of the established full-UI tab buttons to use as the typography source."""
    preferred = ("WELCOME", "CONTROLS", "CHAT", "ACTIVITY/GPU", "ACTIVITY / GPU", "RUNTIME", "INSTALLED", "HELP")
    found = {}
    for w in _walk(app):
        try:
            if str(w.winfo_class()) not in {"Button", "TButton"}:
                continue
            txt = str(w.cget("text") or "").strip().upper()
            if txt in preferred:
                found.setdefault(txt, w)
        except Exception:
            pass
    for name in preferred:
        if name in found:
            return found[name]
    return None


def _portalai_compact_font(app, size=8):
    ref = _portalai_reference_nav(app)
    if ref is not None:
        family, _old_size, weight = _portalai_font_parts(ref, size)
        return (family, int(size), weight)
    return (portal_display_font(app), int(size), "bold")


# ---------------------------------------------------------------------------
# 1) Welcome emblem: size from the actual visible viewport, not the requested
# height of the inner scroll-frame.  A scrollable Welcome page otherwise keeps
# a tiny requested height and permanently selects the 96/128 px emblem.
# ---------------------------------------------------------------------------
_WelcomeFeatureController_v15_138A = WelcomeFeatureController


class WelcomeFeatureController(_WelcomeFeatureController_v15_138A):
    def __init__(self, shell, root_dir, palette):
        self._viewport_after = None
        super().__init__(shell, root_dir, palette)
        try:
            shell.bind("<Configure>", self._viewport_changed, add="+")
        except Exception:
            pass
        try:
            shell.winfo_toplevel().bind("<Configure>", self._viewport_changed, add="+")
        except Exception:
            pass
        try:
            self.frame.after(90, self.refresh)
        except Exception:
            pass

    def _viewport_changed(self, event=None):
        try:
            if not self.shell.winfo_exists() or not self.frame.winfo_exists():
                return
            if event is not None and event.widget not in (self.shell, self.shell.winfo_toplevel()):
                return
        except Exception:
            pass
        if self._viewport_after is not None:
            try:
                self.frame.after_cancel(self._viewport_after)
            except Exception:
                pass
        try:
            self._viewport_after = self.frame.after(45, self.refresh)
        except Exception:
            self._viewport_after = None

    def _visible_extent(self):
        app = self.shell.winfo_toplevel()
        try:
            width = max(int(self.shell.winfo_width()), int(self.frame.winfo_width()), 1)
        except Exception:
            width = 640
        try:
            app_bottom = int(app.winfo_rooty()) + int(app.winfo_height())
            frame_top = int(self.frame.winfo_rooty())
            viewport = self.shell.master
            while viewport is not None and not isinstance(viewport, tk.Canvas):
                viewport = getattr(viewport, 'master', None)
            if viewport is not None:
                # The page ends above the outer window chrome. Undo its scroll
                # offset so moving the page cannot grow the hero's requested size.
                app_bottom = int(viewport.winfo_rooty()) + int(viewport.winfo_height())
                frame_top += int(viewport.canvasy(0))
            # Reserve the hero's 8-pixel and shell's 14-pixel bottom padding.
            height = max(135, app_bottom - frame_top - 22)
        except Exception:
            try:
                height = max(135, int(app.winfo_height()) - 300)
            except Exception:
                height = 240
        return width, height

    def refresh(self):
        self._after = None
        self._viewport_after = None
        if self.frame is None:
            return
        # A public pre-login welcome can be replaced after authentication.
        # A queued resize must not operate on that destroyed surface.
        try:
            if not self.frame.winfo_exists() or not self.shell.winfo_exists():return
        except tk.TclError:
            return
        p = self.palette
        width, visible_h = self._visible_extent()

        # In a scrollable tab, pack(expand=True) follows the inner frame's requested
        # height rather than the Canvas viewport.  Give the hero the viewport height
        # explicitly so its center and image scale actually track window resizing.
        try:
            self.frame.configure(height=visible_h)
            self.frame.pack_propagate(False)
        except Exception:
            pass

        self.access_note.configure(wraplength=max(160, width - 16))
        reserve = (self.tag1.winfo_reqheight() + self.tag2.winfo_reqheight() +
                   self.access_note.winfo_reqheight() + 22)
        avail = max(80, min(width - 28, visible_h - reserve))
        if avail >= 320:
            size = 320
        elif avail >= 240:
            size = 240
        elif avail >= 180:
            size = 180
        elif avail >= 160:
            size = 160
        elif avail >= 128:
            size = 128
        else:
            size = 96

        if size != self._last_size:
            img = self._load(size)
            if img is not None:
                try:
                    self.icon_label.configure(image=img)
                    self.icon_label._portalai_image = img
                except Exception:
                    pass
            self._last_size = size

        try:
            for wgt in (self.frame, self.icon_label, self.tag1.master, self.tag1, self.tag2, self.access_note):
                wgt.configure(bg=p.get("bg"))
            self.tag1.configure(fg=p.get("gold_shine", p.get("gold_mid")))
            self.tag2.configure(fg=p.get("muted", p.get("text")))
            self.access_note.configure(fg=p.get("muted", p.get("text")))
            if visible_h < 150:
                self.tag2.pack_forget()
            elif not self.tag2.winfo_manager():
                self.tag2.pack(fill="x", pady=(2, 0), before=self.access_note)
        except Exception:
            pass


def install_welcome_feature(shell, root_dir, palette):
    old = getattr(shell, "_portalai_welcome_feature_controller", None)
    if isinstance(old, WelcomeFeatureController):
        old.palette = palette
        old.refresh()
        return old
    if old is not None:
        try:
            old.frame.destroy()
        except Exception:
            pass
    ctl = WelcomeFeatureController(shell, root_dir, palette)
    try:
        shell._portalai_welcome_feature_controller = ctl
    except Exception:
        pass
    return ctl


# ---------------------------------------------------------------------------
# 2) Help: restore the rounded filigree perimeter.  v15.138 moved the connected
# border to inset=13; because ConnectedBorder is intentionally lowered beneath
# child widgets, the DocumentationPanel then painted over almost all of it.
# The earlier visible-safe inset was 6 px.
# ---------------------------------------------------------------------------
_HelpPageDecorator_v15_138A = HelpPageDecorator


class HelpPageDecorator(_HelpPageDecorator_v15_138A):
    def __init__(self, help_root, palette):
        self.help_root = help_root
        self.palette = palette
        self.emblem = None
        self._img = None
        self._purge_stale_emblems()
        try:
            self.outer = ConnectedBorder(
                help_root, palette, radius=18, outline_key="gold_mid",
                shine=True, filigree=True, erase_corners=True, inset=1,
            )
        except Exception:
            self.outer = None
        try:
            install_true_smallcaps_ui(help_root.winfo_toplevel(), palette)
        except Exception:
            pass
        try:
            help_root.after(120, self.refresh)
        except Exception:
            pass


def decorate_help_page(help_root, palette):
    old = getattr(help_root, "_portalai_help_decorator", None)
    if isinstance(old, HelpPageDecorator):
        old.apply_palette(palette)
        return old
    # Destroy only known old Help decorators/emblems.  Documentation widgets stay put.
    if old is not None:
        try:
            canvas = getattr(getattr(old, "outer", None), "canvas", None)
            if canvas is not None:
                canvas.destroy()
        except Exception:
            pass
    for w in list(_walk(help_root)):
        if w is help_root:
            continue
        if (getattr(w, "_portalai_help_emblem", False) or
                getattr(w, "_portableai_brand_overlay", False) or
                getattr(w, "_portalai_brand_overlay", False) or
                getattr(w, "_portalai_brand_image", False)):
            try:
                w.destroy()
            except Exception:
                pass
    ctl = HelpPageDecorator(help_root, palette)
    try:
        help_root._portalai_help_decorator = ctl
    except Exception:
        pass
    return ctl


# ---------------------------------------------------------------------------
# 5 + 6) Wordmark: restore v15.137b's responsive pre-rendered sizes and force the
# banner's parent to fill the complete titlebar height.  Pack then centers both
# the icon sibling and wordmark vertically instead of preserving their old top bias.
# ---------------------------------------------------------------------------
def install_wordmark_label(widget, root_dir, kind, palette=None):
    palette = palette or {}
    kind = str(kind).lower()
    specs = (
        [(420, "PortalAI_Wordmark_Welcome.png"),
         (320, "PortalAI_Wordmark_Welcome_320.png"),
         (240, "PortalAI_Wordmark_Welcome_240.png"),
         (180, "PortalAI_Wordmark_Welcome_180.png")]
        if kind == "welcome" else
        [(120, "PortalAI_Wordmark_Banner.png"),
         (96, "PortalAI_Wordmark_Banner_96.png"),
         (72, "PortalAI_Wordmark_Banner_72.png")]
    )
    cache = {}
    for width, filename in specs:
        try:
            cache[width] = tk.PhotoImage(file=str(_branding_path(root_dir, filename)))
        except Exception:
            pass

    fallback = PORTAL_THIN_UPPER if kind == "welcome" else f"{PORTAL_THIN_UPPER}  ·  CONTROL CENTER"
    if not cache:
        try:
            size = 26 if kind == "welcome" else 10
            widget.configure(text=fallback, image="", font=(portal_display_font(widget), size, "bold"),
                             fg=palette.get("text", "#202224"))
        except Exception:
            pass
        return widget

    widget._portalai_wordmark_images = cache
    state = {"width": None}

    def choose(parent_width):
        parent_width = max(1, int(parent_width or 1))
        if kind == "welcome":
            budget = max(150, parent_width - 26)
            for width in (420, 320, 240, 180):
                if width in cache and width <= budget:
                    return width
            return min(cache)
        if parent_width >= 260 and 120 in cache:
            return 120
        if parent_width >= 205 and 96 in cache:
            return 96
        if 72 in cache:
            return 72
        return min(cache)

    def center_banner_parent():
        if kind != "banner":
            return
        parent = widget.master
        try:
            if str(parent.winfo_manager()) == "pack":
                parent.pack_configure(fill="both", expand=True)
        except Exception:
            pass
        try:
            widget.pack_configure(fill="none", pady=(0, 3), ipady=0, anchor="s")
        except Exception:
            pass
        # The icon/gem is a sibling in the same left titlebar cluster. Removing its
        # historic 8 px top/bottom pad lets pack center it in exactly the same cavity.
        try:
            for sibling in parent.winfo_children():
                if sibling is widget or str(sibling.winfo_manager()) != "pack":
                    continue
                cls = str(sibling.winfo_class())
                if cls in {"Canvas", "Label"}:
                    sibling.pack_configure(pady=(0, 3), ipady=0, anchor="s")
        except Exception:
            pass

    def apply(_event=None):
        try:
            parent = widget.master
            avail = int(parent.winfo_width())
            width = choose(avail)
            if state["width"] != width:
                img = cache[width]
                widget.configure(image=img, text="", compound="center", bd=0, highlightthickness=0,
                                 anchor=("center" if kind == "banner" else "w"))
                widget._portalai_wordmark_image = img
                state["width"] = width
            center_banner_parent()
            if kind == "welcome":
                try:
                    shell = widget.master.master.master
                    widget.after(60, lambda s=shell: install_welcome_feature(s, root_dir, palette))
                except Exception:
                    pass
        except Exception:
            pass

    try:
        widget.master.bind("<Configure>", apply, add="+")
        widget.after_idle(apply)
    except Exception:
        apply()
    return widget


# ---------------------------------------------------------------------------
# 5) Full-UI COMPACT typography: after the normal tab scaler runs, copy the exact
# font specification from an established navigation tab to utility buttons.  This
# eliminates the separate helper-selected face that made COMPACT look unrelated.
# ---------------------------------------------------------------------------
_DynamicTabFontController_v15_138A = DynamicTabFontController


class DynamicTabFontController(_DynamicTabFontController_v15_138A):
    def refresh(self):
        super().refresh()
        if getattr(self, "_mobile", False):
            return
        ref = _portalai_reference_nav(self.app)
        if ref is None:
            return
        try:
            ref_font = ref.cget("font")
        except Exception:
            return
        for b in list(self.buttons):
            try:
                txt = str(b.cget("text") or "").strip().upper()
                if txt in {"COMPACT", "DARK", "LIGHT"}:
                    b.configure(font=ref_font)
            except Exception:
                pass


def install_dynamic_tab_scaler(app, buttons):
    old = getattr(app, "_portalai_dynamic_tab_scaler", None)
    if isinstance(old, DynamicTabFontController):
        for b in list(buttons or []):
            old.register(b)
        old.refresh()
        return old
    ctl = DynamicTabFontController(app, buttons)
    try:
        app._portalai_dynamic_tab_scaler = ctl
    except Exception:
        pass
    return ctl


# ---------------------------------------------------------------------------
# 4 + 5 + 6 + 7) Compact Mode:
#   * all buttons use the same family/weight as the full navigation
#   * leave-state is corrected immediately and repeatedly for ~0.4 s, defeating
#     stale delayed ElegantButton hover callbacks without a polling loop
#   * brand icon/text sit in one fixed-height centered cluster
#   * collapsed mode temporarily lowers the root minsize and sizes itself from the
#     actual compact toolbar requested height (the old 400 px minsize caused the gap)
# ---------------------------------------------------------------------------
_CompactModeController_v15_138A = CompactModeController


class CompactModeController(_CompactModeController_v15_138A):
    def __init__(self, *args, **kwargs):
        self._prev_minsize_138b = None
        super().__init__(*args, **kwargs)

    @staticmethod
    def _pointer_inside(widget):
        try:
            px, py = widget.winfo_pointerxy()
            x = int(widget.winfo_rootx()); y = int(widget.winfo_rooty())
            return x <= px < x + int(widget.winfo_width()) and y <= py < y + int(widget.winfo_height())
        except Exception:
            return False

    def _settle_normal(self, widget, repeats=20):
        """Keep correcting stale hover animation only while the pointer is outside."""
        try:
            if not widget.winfo_exists() or self._pointer_inside(widget):
                return
            normal = getattr(widget, "_portalai_normal_bg", None)
            if normal:
                widget.configure(bg=normal)
        except Exception:
            return
        if repeats > 0:
            try:
                widget.after(20, lambda w=widget, n=repeats-1: self._settle_normal(w, n))
            except Exception:
                pass

    def _bind_fast_hover(self, button, normal, hover):
        button._portalai_normal_bg = normal
        button._portalai_hover_bg = hover

        def entered(_event=None, w=button):
            try:
                w.configure(bg=getattr(w, "_portalai_hover_bg", hover))
            except Exception:
                pass

        def left(_event=None, w=button):
            self._settle_normal(w, 20)

        try:
            button.bind("<Enter>", entered, add="+")
            button.bind("<Leave>", left, add="+")
        except Exception:
            pass

    def _mk_button(self, parent, text, command, accent=False, danger=False, width=None, image=None):
        p = self._colors()
        if danger:
            bg = p.get("danger", "#7C403E"); hover = p.get("danger_hover", "#66312F"); fg = "#ffffff"
        elif accent:
            bg = p.get("accent", "#3E91A2"); hover = p.get("accent2", p.get("button_hover", bg)); fg = "#ffffff"
        else:
            bg = p.get("button", p.get("panel")); hover = p.get("button_hover", bg); fg = p.get("text", "#111")
        kw = dict(
            text=text, command=command, bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg,
            relief="flat", bd=0, padx=6, pady=2, cursor="hand2",
            highlightthickness=1,
            highlightbackground=p.get("border", p.get("gold_mid", "#a77b22")),
            font=_portalai_compact_font(self.app, 8),
        )
        if image is not None:
            kw.update(image=image, compound="center", padx=2, pady=1)
        b = ElegantButton(parent, **kw)
        try:
            b._portalai_dynamic_nav = True
        except Exception:
            pass
        if width is not None:
            try:
                b.configure(width=width)
            except Exception:
                pass
        self._bind_fast_hover(b, bg, hover)
        self._compact_buttons.append((b, accent, danger))
        return b

    def _attach_spot(self, parent):
        return self._mk_button(parent, "ATTACH", self._button_action("Attach"))

    def _build_bar(self):
        if self._compact_bar is not None:
            try:
                if self._compact_bar.winfo_exists():
                    return
            except Exception:
                pass
        p = self._colors(); self._compact_buttons = []
        bar = tk.Frame(
            self.content, bg=p.get("panel3", p.get("panel")),
            highlightthickness=1, highlightbackground=p.get("gold_mid", p.get("border")),
        )
        row = tk.Frame(bar, bg=p.get("panel3", p.get("panel")))
        row.pack(fill="x", padx=4, pady=(2, 1))
        left = tk.Frame(row, bg=p.get("panel3", p.get("panel")))
        left.pack(side="left", fill="x", expand=True)
        right = tk.Frame(row, bg=p.get("panel3", p.get("panel")))
        right.pack(side="right")

        # A dedicated fixed-height branding cavity makes the icon and text share the
        # same vertical center rather than relying on two unrelated widget baselines.
        brandbox = tk.Frame(left, bg=p.get("panel3", p.get("panel")), width=126, height=32)
        brandbox.pack(side="left", fill="y", padx=(2, 4))
        brandbox.pack_propagate(False)
        icon = self._load_icon()
        brand_icon = tk.Label(brandbox, bg=p.get("panel3", p.get("panel")), bd=0,
                              highlightthickness=0, padx=0, pady=0)
        if icon is not None:
            brand_icon.configure(image=icon); brand_icon._portalai_image = icon
        else:
            brand_icon.configure(text="◉", fg=p.get("accent"))
        brand_icon.pack(side="left", padx=(2, 5), anchor="center")
        identity = tk.Label(
            brandbox, text="PortalAI", bg=p.get("panel3", p.get("panel")), fg=p.get("text"),
            font=_portalai_compact_font(self.app, 8), padx=0, pady=0, anchor="center",
        )
        identity.pack(side="left", anchor="center")
        for w in (bar, row, left, brandbox, brand_icon, identity):
            try:
                w.bind("<ButtonPress-1>", self._drag_start, add="+")
                w.bind("<B1-Motion>", self._drag_move, add="+")
            except Exception:
                pass

        startup = self._mk_button(left, "STARTUP", self.start_components, accent=True); startup.pack(side="left", padx=2)
        stop = self._mk_button(left, "STOP", self._button_action("Stop"), danger=True); stop.pack(side="left", padx=2)
        send = self._mk_button(left, "SEND", self._send_compact, accent=True); send.pack(side="left", padx=2)
        self._left_direct = [startup, stop, send]
        self._chat_menu = _PortalDropdown(self.app, lambda: self.palette)
        self._view_menu = _PortalDropdown(self.app, lambda: self.palette)
        self._chat_dropdown_button = self._mk_button(left, "CHAT ▾", self._show_chat_menu)
        self._chat_dropdown_button.pack(side="left", padx=(4, 2))

        self._theme_button = self._mk_button(right, self._theme_label(), self._toggle_theme)
        self._expand_button = self._mk_button(right, "EXPAND CHAT", self.toggle_chat)
        full = self._mk_button(right, "FULL UI", self.exit)
        tray = (self._mk_button(right, "", self.minimize_to_tray or (lambda: None), image=icon, width=3)
                if icon is not None else self._mk_button(right, "TRAY", self.minimize_to_tray or (lambda: None)))
        close = self._mk_button(right, "×", self.exit_all or self.app.destroy, danger=True, width=3)
        self._view_dropdown_button = self._mk_button(right, "VIEW ▾", self._show_view_menu)
        self._right_direct = [self._theme_button, self._expand_button, full, tray]
        for b in self._right_direct:
            b.pack(side="left", padx=2)
        close.pack(side="left", padx=(3, 2))

        comp = tk.Frame(bar, bg=p.get("panel3", p.get("panel")))
        comp.pack(fill="x", padx=5, pady=(0, 2))
        attach = self._attach_spot(comp); attach.pack(side="left", padx=(0, 4))
        self._entry_var = tk.StringVar(master=self.app, value=self._read_source())
        entry = tk.Entry(
            comp, textvariable=self._entry_var,
            bg=p.get("panel", p.get("bg")), fg=p.get("text"), insertbackground=p.get("text"),
            relief="flat", bd=0, highlightthickness=1,
            highlightbackground=p.get("gold_mid", p.get("border")), highlightcolor=p.get("accent"),
            font=(portal_body_font(comp), 10),
        )
        entry.pack(side="left", fill="x", expand=True, ipady=3)
        entry.bind("<Return>", lambda _e: (self._send_compact(), "break")[1])
        self._composer_row = comp; self._compact_bar = bar; self._compact_entry_widget = entry; self._close_button = close
        try:
            self.app.bind("<Configure>", self._compact_configure, add="+")
        except Exception:
            pass

    def _refresh_colors(self):
        super()._refresh_colors()
        p = self._colors()
        for b, accent, danger in list(self._compact_buttons):
            try:
                if danger:
                    normal = p.get("danger", "#7C403E"); hover = p.get("danger_hover", "#66312F")
                elif accent:
                    normal = p.get("accent", "#3E91A2"); hover = p.get("accent2", p.get("button_hover", normal))
                else:
                    normal = p.get("button", p.get("panel")); hover = p.get("button_hover", normal)
                b._portalai_normal_bg = normal; b._portalai_hover_bg = hover
                b.configure(font=_portalai_compact_font(self.app, 8))
                if not self._pointer_inside(b):
                    b.configure(bg=normal)
            except Exception:
                pass

    def _collapsed_geometry(self):
        try:
            sw = int(self.app.winfo_screenwidth())
        except Exception:
            sw = 1200
        width = max(620, min(860, sw - 40))
        try:
            self.app.update_idletasks()
            bar_h = max(1, int(self._compact_bar.winfo_reqheight())) if self._compact_bar is not None else 70
            top = max(0, int(self._compact_bar.winfo_rooty()) - int(self.app.winfo_rooty())) if self._compact_bar is not None else 8
            height = max(78, min(132, top + bar_h + 10))
        except Exception:
            height = 96
        return width, height

    def _set_size(self, expanded=False):
        try:
            self.app.update_idletasks()
            w, h = self._expanded_geometry() if expanded else self._collapsed_geometry()
            self.app.geometry(f"{w}x{h}+{self.app.winfo_x()}+{self.app.winfo_y()}")
            self.app.update_idletasks()
        except Exception:
            pass

    def enter(self):
        if self.active:
            return
        try:
            self._prev_minsize_138b = tuple(self.app.minsize())
            # The full Control Center historically uses a ~400px minimum height.
            # Compact collapsed mode cannot become a toolbar until that constraint is
            # temporarily lowered.  Width remains guarded by _collapsed_geometry().
            self.app.minsize(420, 1)
        except Exception:
            self._prev_minsize_138b = None
        super().enter()
        try:
            self.app.after_idle(lambda: self._set_size(False))
        except Exception:
            pass

    def exit(self):
        if not self.active:
            return
        super().exit()
        if self._prev_minsize_138b:
            try:
                self.app.minsize(int(self._prev_minsize_138b[0]), int(self._prev_minsize_138b[1]))
            except Exception:
                pass
        self._prev_minsize_138b = None


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        return old
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_UI_RESPONSIVENESS_v15_138C
# Final polish after v15.138b:
#   * lower-align full-UI titlebar brand toward the bottom gold rule
#   * true mixed-case/small-cap labels for Compact controls
#   * remove callback storms and repeated widget-tree scans from Compact hover/layout
#   * cache navigation typography lookup
#   * reduce chat-frontend background polling from several full tree passes every 300 ms
#   * avoid redundant synchronous update_idletasks() calls during mode changes
# ===========================================================================
PORTALAI_UI_RESPONSIVENESS_v15_138C = True


def _portalai_reference_nav(app):
    """Return and cache the established full-UI navigation typography source.

    v15.138b rescanned the complete widget tree every time a Compact button wanted
    its font.  Compact color/layout refreshes touch many buttons, so that became an
    avoidable O(buttons * widgets) hot path.  The navigation widget itself is stable
    for the lifetime of the Control Center, so cache the live widget reference.
    """
    cached = getattr(app, "_portalai_reference_nav_widget_138c", None)
    if cached is not None:
        try:
            if cached.winfo_exists():
                return cached
        except Exception:
            pass
    preferred = ("WELCOME", "CONTROLS", "CHAT", "ACTIVITY/GPU", "ACTIVITY / GPU", "RUNTIME", "INSTALLED", "HELP")
    found = {}
    for w in _walk(app):
        try:
            if str(w.winfo_class()) not in {"Button", "TButton"}:
                continue
            txt = str(w.cget("text") or "").strip().upper()
            if txt in preferred:
                found.setdefault(txt, w)
        except Exception:
            pass
    for name in preferred:
        if name in found:
            try:
                app._portalai_reference_nav_widget_138c = found[name]
            except Exception:
                pass
            return found[name]
    return None


def _portalai_compact_font(app, size=8):
    """Compact display font with cached family/weight and an explicit compact size."""
    cache = getattr(app, "_portalai_compact_font_cache_138c", None)
    if not isinstance(cache, dict):
        cache = {}
        try:
            app._portalai_compact_font_cache_138c = cache
        except Exception:
            pass
    key = int(size)
    if key in cache:
        return cache[key]
    ref = _portalai_reference_nav(app)
    if ref is not None:
        family, _old_size, weight = _portalai_font_parts(ref, size)
        value = (family, key, weight)
    else:
        value = (portal_display_font(app), key, "bold")
    cache[key] = value
    return value


# Full navigation: do not repaint utility-button fonts when the reference font did
# not actually change.  The base responsive scaler still owns real width changes.
_DynamicTabFontController_v15_138B = DynamicTabFontController


class DynamicTabFontController(_DynamicTabFontController_v15_138B):
    def __init__(self, *args, **kwargs):
        self._portalai_utility_font_key_138c = None
        super().__init__(*args, **kwargs)

    def refresh(self):
        super().refresh()
        if getattr(self, "_mobile", False):
            return
        ref = _portalai_reference_nav(self.app)
        if ref is None:
            return
        try:
            ref_font = ref.cget("font")
            font_key = str(ref_font)
        except Exception:
            return
        if font_key == self._portalai_utility_font_key_138c:
            return
        self._portalai_utility_font_key_138c = font_key
        for b in list(self.buttons):
            try:
                txt = str(b.cget("text") or "").strip().upper()
                if txt in {"COMPACT", "DARK", "LIGHT"} and str(b.cget("font")) != font_key:
                    b.configure(font=ref_font)
            except Exception:
                pass


def install_dynamic_tab_scaler(app, buttons):
    old = getattr(app, "_portalai_dynamic_tab_scaler", None)
    if isinstance(old, DynamicTabFontController):
        for b in list(buttons or []):
            old.register(b)
        old.refresh()
        return old
    ctl = DynamicTabFontController(app, buttons)
    try:
        app._portalai_dynamic_tab_scaler = ctl
    except Exception:
        pass
    return ctl


# Mixed-case source strings are intentional.  Copperplate Gothic's lowercase glyphs
# render as the small-cap forms used by the rest of PortalAI, whereas feeding it an
# all-uppercase string makes every glyph full-height.
def _portalai_pretty_compact_text(text):
    raw = str(text or "")
    mapping = {
        "COMPACT": "Compact",
        "STARTUP": "Startup",
        "STOP": "Stop",
        "SEND": "Send",
        "CHAT ▾": "Chat ▾",
        "VIEW ▾": "View ▾",
        "ATTACH": "Attach",
        "DARK": "Dark",
        "LIGHT": "Light",
        "EXPAND CHAT": "Expand chat",
        "COLLAPSE CHAT": "Collapse chat",
        "FULL UI": "Full UI",
        "TRAY": "Tray",
        "EDIT": "Edit",
        "BRANCH": "Branch",
        "MIC": "Mic",
        "TOOLS ▾": "Tools ▾",
        "SECTIONS ▾": "Sections ▾",
    }
    return mapping.get(raw.strip().upper(), raw)


_CompactModeController_v15_138B = CompactModeController


class CompactModeController(_CompactModeController_v15_138B):
    def __init__(self, *args, **kwargs):
        self._layout_narrow_138c = None
        self._collapsed_height_138c = None
        super().__init__(*args, **kwargs)

    def _mk_button(self, parent, text, command, accent=False, danger=False, width=None, image=None):
        # Let v15.138b retain its rounded ElegantButton construction and palette;
        # only normalize the visible source capitalization before the widget exists.
        return super()._mk_button(
            parent, _portalai_pretty_compact_text(text), command,
            accent=accent, danger=danger, width=width, image=image,
        )

    def _theme_label(self):
        try:
            cur = str(self.theme_mode_getter() if callable(self.theme_mode_getter) else "light").lower()
        except Exception:
            cur = "light"
        return "Light" if cur == "dark" else "Dark"

    def _bind_fast_hover(self, button, normal, hover):
        """Replace ElegantButton's delayed hover handlers instead of fighting them.

        v15.138b appended new handlers and then scheduled 20 corrective callbacks on
        every <Leave>.  Rapid pointer movement could queue hundreds of callbacks and
        make clicks/mode switches feel sticky.  Replacing only the instance-level
        Enter/Leave bindings preserves the button command and rounded drawing while
        making hover state one immediate paint plus one idle confirmation.
        """
        button._portalai_normal_bg = normal
        button._portalai_hover_bg = hover

        def reset_if_outside(w=button):
            try:
                if w.winfo_exists() and not self._pointer_inside(w):
                    w.configure(bg=getattr(w, "_portalai_normal_bg", normal))
            except Exception:
                pass

        def entered(_event=None, w=button):
            try:
                w.configure(bg=getattr(w, "_portalai_hover_bg", hover))
            except Exception:
                pass

        def left(_event=None, w=button):
            try:
                w.configure(bg=getattr(w, "_portalai_normal_bg", normal))
                # One idle correction catches a class-level repaint without creating
                # a timer storm.  No repeated polling/correction loop remains.
                w.after_idle(lambda: reset_if_outside(w))
            except Exception:
                pass

        try:
            # Deliberately replace previous instance hover bindings (no add='+').
            button.bind("<Enter>", entered)
            button.bind("<Leave>", left)
        except Exception:
            pass

    def _normalize_button_labels(self):
        for b, _accent, _danger in list(getattr(self, "_compact_buttons", []) or []):
            try:
                old = str(b.cget("text") or "")
                new = _portalai_pretty_compact_text(old)
                if new != old:
                    b.configure(text=new)
            except Exception:
                pass

    def _show_view_menu(self):
        items = [
            {"label": self._theme_label() + " mode", "command": self._toggle_theme},
            {"label": "Collapse chat" if self.expanded else "Expand chat", "command": self.toggle_chat},
            {"label": "Full UI", "command": self.exit},
            {"label": "Minimize to tray", "command": self.minimize_to_tray or (lambda: None)},
        ]
        if self._view_menu:
            self._view_menu.show_for(self._view_dropdown_button, items, "PortalAI · View")

    def _layout_toolbar(self):
        self._layout_after = None
        if not self.active or self._compact_bar is None:
            return
        try:
            width = int(self.app.winfo_width())
        except Exception:
            width = 760
        narrow = width < 900

        # Root Configure fires repeatedly during geometry negotiation and dragging.
        # If the layout bucket did not cross the 900px threshold, there is nothing
        # to repack/recolor.  This removes a major mode-switch/resizing hot path.
        if self._layout_narrow_138c is narrow:
            return
        self._layout_narrow_138c = narrow

        extra_names = [
            ("Edit", ("Edit last", "Edit Last")),
            ("Branch", ("Branch",)),
            ("HF", ("Hands-free", "Hands free")),
            ("Mic", ("Mic",)),
        ]
        if not hasattr(self, "_extra_direct"):
            self._extra_direct = []
        left = self._chat_dropdown_button.master
        if narrow:
            for b in list(self._extra_direct):
                try:
                    b.pack_forget()
                except Exception:
                    pass
            if not self._chat_dropdown_button.winfo_manager():
                self._chat_dropdown_button.pack(side="left", padx=(4, 2))
            for b in self._right_direct:
                try:
                    b.pack_forget()
                except Exception:
                    pass
            if not self._view_dropdown_button.winfo_manager():
                self._view_dropdown_button.pack(side="left", padx=(2, 2), before=self._close_button)
        else:
            try:
                self._chat_dropdown_button.pack_forget()
            except Exception:
                pass
            if not self._extra_direct:
                for text, names in extra_names:
                    b = self._mk_button(left, text, self._button_action(*names))
                    self._extra_direct.append(b)
            for b in self._extra_direct:
                if not b.winfo_manager():
                    b.pack(side="left", padx=2)
            try:
                self._view_dropdown_button.pack_forget()
            except Exception:
                pass
            for b in self._right_direct:
                if not b.winfo_manager():
                    b.pack(side="left", padx=2, before=self._close_button)
        self._refresh_colors()
        self._normalize_button_labels()

    def _refresh_colors(self):
        super()._refresh_colors()
        self._normalize_button_labels()

    def toggle_chat(self):
        super().toggle_chat()
        self._normalize_button_labels()

    def _collapsed_geometry(self):
        try:
            sw = int(self.app.winfo_screenwidth())
        except Exception:
            sw = 1200
        width = max(620, min(860, sw - 40))
        if self._collapsed_height_138c is None:
            try:
                bar_h = max(1, int(self._compact_bar.winfo_reqheight())) if self._compact_bar is not None else 70
                top = max(0, int(self._compact_bar.winfo_y())) if self._compact_bar is not None else 0
                self._collapsed_height_138c = max(78, min(132, top + bar_h + 8))
            except Exception:
                self._collapsed_height_138c = 96
        return width, int(self._collapsed_height_138c)

    def _set_size(self, expanded=False):
        try:
            if not expanded and self._collapsed_height_138c is None and self._compact_bar is not None:
                # One geometry flush is enough to establish the toolbar's requested
                # height. v15.138b forced the whole root idle queue twice per switch.
                self._compact_bar.update_idletasks()
            w, h = self._expanded_geometry() if expanded else self._collapsed_geometry()
            self.app.geometry(f"{w}x{h}+{self.app.winfo_x()}+{self.app.winfo_y()}")
        except Exception:
            pass

    def enter(self):
        if self.active:
            return
        self._layout_narrow_138c = None
        try:
            self._prev_minsize_138b = tuple(self.app.minsize())
            self.app.minsize(420, 1)
        except Exception:
            self._prev_minsize_138b = None
        # Bypass v15.138b's extra after_idle second sizing pass. The original
        # v15.138 Compact enter path already calls self._set_size() once.
        _CompactModeController_v15_138A.enter(self)
        self._normalize_button_labels()

    def exit(self):
        if not self.active:
            return
        _CompactModeController_v15_138A.exit(self)
        if self._prev_minsize_138b:
            try:
                self.app.minsize(int(self._prev_minsize_138b[0]), int(self._prev_minsize_138b[1]))
            except Exception:
                pass
        self._prev_minsize_138b = None


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        return old
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
    except Exception:
        pass
    return ctl


# ---------------------------------------------------------------------------
# Chat frontend idle cost.
# v15.138b inherited a 300 ms loop that performed rebrand_widget_tree(), another
# complete _walk(), and a scrollbar-upgrade walk every tick. That is unnecessary
# once label identity/context bindings are pinned. Keep the same functionality but
# consolidate to one pass at 1 s, with scrollbar discovery every fourth pass.
# ---------------------------------------------------------------------------
def install_native_chat_frontend(app, chat_root, native_chat_panel, palette, brand_images, mode_getter):
    state = {"alive": True, "ticks": 0}
    overlay = ChatWatermarkOverlay(app, chat_root, brand_images, mode_getter, lambda: palette)
    try:
        from themed_popup_menu import ThemedPopupMenu
        chat_menu = ThemedPopupMenu(app, lambda: palette)
    except Exception:
        chat_menu = None

    def tick():
        if not state.get("alive"):
            return
        try:
            for w in _walk(chat_root):
                # Lightweight visible-label rebrand in the same traversal.
                try:
                    txt = w.cget("text")
                except Exception:
                    txt = None
                if txt is not None:
                    try:
                        new = frontend_brand_text(str(txt), chat=True)
                        if new != str(txt):
                            w.configure(text=new)
                    except Exception:
                        pass
                try:
                    _rename_chat_role_tags(w)
                except Exception:
                    pass
                try:
                    _pin_label_identity(w)
                except Exception:
                    pass
                if chat_menu is not None:
                    try:
                        _install_themed_chat_context(w, app, native_chat_panel, chat_menu, palette)
                    except Exception:
                        pass

            state["ticks"] = int(state.get("ticks", 0)) + 1
            if state["ticks"] == 1 or state["ticks"] % 4 == 0:
                try:
                    upgrade_vertical_scrollbars(chat_root, palette)
                except Exception:
                    pass
            app.after(1000, tick)
        except tk.TclError:
            return
        except Exception:
            try:
                app.after(1500, tick)
            except Exception:
                pass

    app.after(50, tick)
    return {"overlay": overlay, "state": state, "chat_menu": chat_menu}


# ===========================================================================
# PORTALAI_WELCOME_BRIGHTNESS_ALIGNMENT_v15_138D
# Final branding polish after v15.138c:
#   * large Welcome hero uses a dedicated brighter asset set only on Welcome
#   * full-UI banner wordmark assets keep their existing layout API but use
#     corrected internal vertical alignment (assets supplied by installer)
# Nothing here changes chat watermarks, Help emblems, compact icon, runtime logic,
# model startup, GPU leasing, or component behavior.
# ===========================================================================
PORTALAI_WELCOME_BRIGHTNESS_ALIGNMENT_v15_138D = True


_WelcomeFeatureController_v15_138C = WelcomeFeatureController


class WelcomeFeatureController(_WelcomeFeatureController_v15_138C):
    """Welcome hero that prefers the v15.138d bright-only emblem assets.

    Keep brightness policy local to the Welcome page.  Other emblem uses remain on
    their established assets so this visual correction cannot alter Help, chat,
    compact mode, tray/chrome identity, or theme behavior.
    """

    def _load(self, size):
        if size in self.images:
            return self.images[size]
        # v15.138d supplies all sizes used by the responsive Welcome controller.
        try:
            p = _branding_path(self.root_dir, f"PortalAI_Emblem_Bright_{int(size)}.png")
            if p.exists():
                img = tk.PhotoImage(file=str(p))
                self.images[size] = img
                return img
        except Exception:
            pass
        # Safe fallback preserves startup even if a single bright asset is missing.
        return super()._load(size)


def install_welcome_feature(shell, root_dir, palette):
    old = getattr(shell, "_portalai_welcome_feature_controller", None)
    if isinstance(old, WelcomeFeatureController):
        old.palette = palette
        old.refresh()
        return old
    if old is not None:
        try:
            old.frame.destroy()
        except Exception:
            pass
    ctl = WelcomeFeatureController(shell, root_dir, palette)
    try:
        shell._portalai_welcome_feature_controller = ctl
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_HERO_CONTEXT_ATTACH_FIX_v15_138E
# Fixes after v15.138d:
#   * Welcome hero now uses the actual bright reference-derived asset set rather
#     than the darker/cutout derivative set from the existing emblem pipeline.
#   * Full-UI titlebar wordmark is nudged slightly lower without re-moving the icon.
#   * Compact Attach button is normalized/centered.
#   * Right-click on the chat composer/Entry widgets gets a sane themed edit menu
#     instead of the odd native "PY_VAR*" menu.
# ===========================================================================
PORTALAI_HERO_CONTEXT_ATTACH_FIX_v15_138E = True


# 1) Correct Welcome hero asset routing.
_WelcomeFeatureController_v15_138D = WelcomeFeatureController

class WelcomeFeatureController(_WelcomeFeatureController_v15_138D):
    def _load(self, size):
        if size in self.images:
            return self.images[size]
        for stem in ("PortalAI_Emblem_HeroBright_", "PortalAI_Emblem_Bright_", "PortalAI_Emblem_"):
            try:
                p = _branding_path(self.root_dir, f"{stem}{int(size)}.png")
                if p.exists():
                    img = tk.PhotoImage(file=str(p))
                    self.images[size] = img
                    return img
            except Exception:
                pass
        return super()._load(size)


def install_welcome_feature(shell, root_dir, palette):
    old = getattr(shell, "_portalai_welcome_feature_controller", None)
    if isinstance(old, WelcomeFeatureController):
        old.palette = palette
        old.refresh()
        return old
    if old is not None:
        try:
            old.frame.destroy()
        except Exception:
            pass
    ctl = WelcomeFeatureController(shell, root_dir, palette)
    try:
        shell._portalai_welcome_feature_controller = ctl
    except Exception:
        pass
    return ctl


# 2) Nudge only the banner/wordmark lower; leave the icon where the user already liked it.
_install_wordmark_label_v15_138D = install_wordmark_label

def install_wordmark_label(widget, root_dir, kind, palette=None):
    widget = _install_wordmark_label_v15_138D(widget, root_dir, kind, palette)
    if str(kind).lower() == "banner":
        def _nudge(_event=None):
            try:
                widget.pack_configure(fill="none", pady=(5, 0), ipady=0, anchor="s")
            except Exception:
                pass
        try:
            widget.master.bind("<Configure>", _nudge, add="+")
            widget.after_idle(_nudge)
        except Exception:
            _nudge()
    return widget


# 3) Sane themed right-click menus for transcript text/canvas plus Entry widgets.
def _install_themed_chat_context(widget, app, native_chat_panel, menu, palette) -> None:
    if getattr(widget, "_portalai_themed_chat_context_138e", False):
        return
    try:
        cls = str(widget.winfo_class())
        ww = max(1, int(widget.winfo_width())); hh = max(1, int(widget.winfo_height()))
    except Exception:
        return
    allowed = {"Text", "Canvas", "Entry", "TEntry"}
    if cls not in allowed:
        return
    if cls in {"Text", "Canvas"} and (ww < 280 or hh < 80):
        return
    if cls in {"Entry", "TEntry"} and (ww < 70 or hh < 12):
        return

    def _clipboard_get():
        try:
            return app.clipboard_get()
        except Exception:
            return ""

    def _text_has_sel():
        try:
            return bool(widget.tag_ranges("sel"))
        except Exception:
            return False

    def _entry_has_sel():
        try:
            return bool(widget.selection_present())
        except Exception:
            try:
                widget.index("sel.first")
                return True
            except Exception:
                return False

    def copy_selection():
        try:
            if cls == "Text":
                value = widget.get("sel.first", "sel.last") if _text_has_sel() else ""
            elif cls in {"Entry", "TEntry"}:
                value = widget.selection_get() if _entry_has_sel() else ""
            else:
                value = ""
            if value:
                app.clipboard_clear(); app.clipboard_append(value)
        except Exception:
            pass

    def cut_selection():
        try:
            if cls in {"Entry", "TEntry"} and _entry_has_sel():
                value = widget.selection_get()
                if value:
                    app.clipboard_clear(); app.clipboard_append(value)
                widget.delete("sel.first", "sel.last")
        except Exception:
            pass

    def paste_clipboard():
        try:
            value = _clipboard_get()
            if cls in {"Entry", "TEntry"}:
                try:
                    if _entry_has_sel():
                        widget.delete("sel.first", "sel.last")
                except Exception:
                    pass
                widget.insert("insert", value)
            elif cls == "Text":
                widget.insert("insert", value)
        except Exception:
            pass

    def select_all():
        try:
            if cls == "Text":
                widget.tag_add("sel", "1.0", "end-1c"); widget.mark_set("insert", "1.0"); widget.see("insert")
            elif cls in {"Entry", "TEntry"}:
                widget.selection_range(0, "end"); widget.icursor("end")
        except Exception:
            pass

    def _show_with_fallback(x_root, y_root, items, title):
        if menu is not None and hasattr(menu, "show"):
            try:
                menu.show(int(x_root), int(y_root), items, title=title)
                return
            except Exception:
                pass
        m = tk.Menu(app, tearoff=False,
                    bg=palette.get("panel", palette.get("bg", "#f5f2ea")),
                    fg=palette.get("text", "#111"),
                    activebackground=palette.get("accent", "#3E91A2"),
                    activeforeground="#ffffff")
        try:
            if title:
                m.add_command(label=title, state="disabled")
                m.add_separator()
        except Exception:
            pass
        for item in items:
            if item is None:
                m.add_separator(); continue
            kw = {"label": item.get("label", "")}
            if item.get("command") is not None:
                kw["command"] = item["command"]
            if item.get("enabled") is False:
                kw["state"] = "disabled"
            m.add_command(**kw)
        try:
            m.tk_popup(int(x_root), int(y_root))
        finally:
            try:
                m.grab_release()
            except Exception:
                pass

    def show_menu(event):
        items = []
        title = "PortalAI · Chat"
        if cls in {"Entry", "TEntry"}:
            has_sel = _entry_has_sel()
            items += [
                {"label": "Cut", "command": cut_selection, "enabled": has_sel},
                {"label": "Copy", "command": copy_selection, "enabled": has_sel},
                {"label": "Paste", "command": paste_clipboard},
                None,
                {"label": "Select all", "command": select_all},
            ]
            title = "PortalAI · Edit"
        elif cls == "Text":
            has_sel = _text_has_sel()
            items += [
                {"label": "Copy selection", "command": copy_selection, "enabled": has_sel},
                {"label": "Select all", "command": select_all},
                None,
            ]
        # Transcript canvas/text can still expose chat actions; editor fields stay clean.
        if cls not in {"Entry", "TEntry"}:
            candidates = [
                ("New chat", ("new_chat",)),
                ("New isolated chat", ("new_isolated_chat",)),
                ("Branch conversation…", ("open_branch_panel", "branch_conversation")),
                ("Edit last user message…", ("edit_last_user", "edit_last")),
                ("History", ("toggle_history", "open_history")),
                ("Memory", ("open_memory_panel", "open_memory_settings")),
                ("Chat Preferences", ("open_settings_panel", "open_settings")),
                ("Instructions", ("open_instructions_panel", "open_instructions")),
            ]
            for label, names in candidates:
                fn = _chat_action(native_chat_panel, *names)
                if fn is not None:
                    items.append({"label": label, "command": fn})
        _show_with_fallback(event.x_root, event.y_root, items, title)
        return "break"

    try:
        widget.bind("<Button-3>", show_menu)
        widget.bind("<Control-Button-1>", show_menu)
        widget._portalai_themed_chat_context_138e = True
    except Exception:
        pass


def install_native_chat_frontend(app, chat_root, native_chat_panel, palette, brand_images, mode_getter):
    state = {"alive": True, "ticks": 0}
    overlay = ChatWatermarkOverlay(app, chat_root, brand_images, mode_getter, lambda: palette)
    try:
        from themed_popup_menu import ThemedPopupMenu
        chat_menu = ThemedPopupMenu(app, lambda: palette)
    except Exception:
        chat_menu = None

    def tick():
        if not state.get("alive"):
            return
        try:
            for w in _walk(chat_root):
                try:
                    txt = w.cget("text")
                except Exception:
                    txt = None
                if txt is not None:
                    try:
                        new = frontend_brand_text(str(txt), chat=True)
                        if new != str(txt):
                            w.configure(text=new)
                    except Exception:
                        pass
                try:
                    _rename_chat_role_tags(w)
                except Exception:
                    pass
                try:
                    _pin_label_identity(w)
                except Exception:
                    pass
                try:
                    _install_themed_chat_context(w, app, native_chat_panel, chat_menu, palette)
                except Exception:
                    pass
            state["ticks"] = int(state.get("ticks", 0)) + 1
            if state["ticks"] == 1 or state["ticks"] % 4 == 0:
                try:
                    upgrade_vertical_scrollbars(chat_root, palette)
                except Exception:
                    pass
            app.after(1000, tick)
        except tk.TclError:
            return
        except Exception:
            try:
                app.after(1500, tick)
            except Exception:
                pass

    app.after(50, tick)
    return {"overlay": overlay, "state": state, "chat_menu": chat_menu}


# 4) Compact Attach button normalization + direct Entry context binding.
_CompactModeController_v15_138D = CompactModeController

class CompactModeController(_CompactModeController_v15_138D):
    def _attach_spot(self, parent):
        b = super()._attach_spot(parent)
        try:
            b.configure(text="Attach", font=_portalai_compact_font(self.app, 8), padx=8, pady=2, anchor="center", width=9)
        except Exception:
            pass
        try:
            self._attach_button_138e = b
        except Exception:
            pass
        return b

    def _build_bar(self):
        pre = getattr(self, "_compact_bar", None)
        super()._build_bar()
        try:
            b = getattr(self, "_attach_button_138e", None)
            if b is not None:
                b.configure(text="Attach", font=_portalai_compact_font(self.app, 8), padx=8, pady=2, anchor="center", width=9)
        except Exception:
            pass
        entry = getattr(self, "_compact_entry_widget", None)
        if entry is not None:
            try:
                from themed_popup_menu import ThemedPopupMenu
                entry_menu = getattr(self, "_portalai_entry_menu_138e", None)
                if entry_menu is None:
                    entry_menu = ThemedPopupMenu(self.app, lambda: self.palette)
                    self._portalai_entry_menu_138e = entry_menu
            except Exception:
                entry_menu = None
            try:
                _install_themed_chat_context(entry, self.app, self.native_chat_panel, entry_menu, self.palette)
            except Exception:
                pass


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old._refresh_colors(); return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_HERO_ALPHA_HOVER_ATTACH_v15_138F
# Final polish after v15.138e:
#   * use a padded, genuinely transparent Welcome hero asset family;
#   * lower only the small titlebar icon ~2 px to align with the wordmark;
#   * build compact Attach exactly like the other compact buttons (no late width hack);
#   * stop ElegantButton's delayed class hover handlers at the widget binding stage.
# ===========================================================================
PORTALAI_HERO_ALPHA_HOVER_ATTACH_v15_138F = True


# 1) Corrected Welcome hero. These files have real alpha and generous transparent
# padding, so no screenshot rectangle flashes during theme changes and no edge can
# be clipped when the responsive controller selects a size.
_WelcomeFeatureController_v15_138E = WelcomeFeatureController

class WelcomeFeatureController(_WelcomeFeatureController_v15_138E):
    def _load(self, size):
        if size in self.images:
            return self.images[size]
        try:
            p = _branding_path(self.root_dir, f"PortalAI_Emblem_HeroClean_{int(size)}.png")
            if p.exists():
                img = tk.PhotoImage(file=str(p))
                self.images[size] = img
                return img
        except Exception:
            pass
        return super()._load(size)


def install_welcome_feature(shell, root_dir, palette):
    old = getattr(shell, "_portalai_welcome_feature_controller", None)
    if isinstance(old, WelcomeFeatureController):
        old.palette = palette
        old.refresh()
        return old
    if old is not None:
        try:
            old.frame.destroy()
        except Exception:
            pass
    ctl = WelcomeFeatureController(shell, root_dir, palette)
    try:
        shell._portalai_welcome_feature_controller = ctl
    except Exception:
        pass
    return ctl


# 2) Keep the wordmark exactly where v15.138e put it, but lower the icon sibling
# by about two pixels. Earlier code gave icon siblings bottom padding, which pushes
# their visible artwork upward inside the brand cavity.
_install_wordmark_label_v15_138E = install_wordmark_label

def install_wordmark_label(widget, root_dir, kind, palette=None):
    widget = _install_wordmark_label_v15_138E(widget, root_dir, kind, palette)
    if str(kind).lower() != "banner":
        return widget

    def _lower_icon_only(_event=None):
        try:
            parent = widget.master
            for sibling in parent.winfo_children():
                if sibling is widget or str(sibling.winfo_manager()) != "pack":
                    continue
                cls = str(sibling.winfo_class())
                image_name = ""
                try:
                    image_name = str(sibling.cget("image") or "")
                except Exception:
                    pass
                # The small brand icon is a Label/Canvas sibling with image content.
                if image_name or cls == "Canvas":
                    try:
                        sibling.pack_configure(pady=(2, 0), ipady=0, anchor="s")
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    try:
        widget.master.bind("<Configure>", _lower_icon_only, add="+")
        widget.after_idle(_lower_icon_only)
        widget.after(40, _lower_icon_only)
    except Exception:
        _lower_icon_only()
    return widget


# 3/4) Compact button creation and immediate hover. Returning "break" from the
# widget-level Enter/Leave binding prevents ElegantButton's class binding from
# scheduling a later animation that repaints the stale hover color.
_CompactModeController_v15_138E = CompactModeController

class CompactModeController(_CompactModeController_v15_138E):
    def _bind_fast_hover(self, button, normal, hover):
        button._portalai_normal_bg = normal
        button._portalai_hover_bg = hover

        def entered(_event=None, w=button):
            try:
                w.configure(bg=getattr(w, "_portalai_hover_bg", hover))
            except Exception:
                pass
            return "break"

        def left(_event=None, w=button):
            try:
                w.configure(bg=getattr(w, "_portalai_normal_bg", normal))
            except Exception:
                pass
            return "break"

        try:
            button.bind("<Enter>", entered)
            button.bind("<Leave>", left)
            button._portalai_fast_hover_138f = True
        except Exception:
            pass

    def _attach_spot(self, parent):
        # Do not configure width/padding after ElegantButton has built its internal
        # rounded geometry. Create Attach through the exact same path as its peers.
        return self._mk_button(parent, "Attach", self._button_action("Attach"))


def _portalai_accelerate_elegant_hover(root):
    """Native ttk hover uses current theme colors, never a cached background."""
    for widget in _walk(root):
        if isinstance(widget, ElegantButton): widget.use_native_hover()



_install_native_chat_frontend_v15_138E = install_native_chat_frontend

def install_native_chat_frontend(app, chat_root, native_chat_panel, palette, brand_images, mode_getter):
    out = _install_native_chat_frontend_v15_138E(
        app, chat_root, native_chat_panel, palette, brand_images, mode_getter
    )
    # A few bounded discovery passes catch controls created during startup/lazy tab
    # construction. This is not a permanent scan loop.
    for delay in (0, 250, 1000, 2500):
        try:
            app.after(delay, lambda a=app: _portalai_accelerate_elegant_hover(a))
        except Exception:
            pass
    return out


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old._refresh_colors()
        try:
            app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
        except Exception:
            pass
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_COMPACT_LAYOUT_BRAND_NUDGE_v15_138G
# Compact-mode geometry polish after v15.138f:
#   * give Attach a fixed pixel cavity so ElegantButton cannot collapse it;
#   * size expanded compact mode to the actual wide-toolbar requirement;
#   * fall back to Chat/View overflow menus when the physical screen is too narrow;
#   * preserve every existing command, theme action, tray action, and chat behavior.
# The full-UI upper-right version/brand text vertical nudge is patched in
# PortableAI_GUI.py by the v15.138g installer.
# ===========================================================================
PORTALAI_COMPACT_LAYOUT_BRAND_NUDGE_v15_138G = True


_CompactModeController_v15_138F = CompactModeController


class CompactModeController(_CompactModeController_v15_138F):
    _ATTACH_WIDTH_PX_138G = 118
    _ATTACH_HEIGHT_PX_138G = 31

    def _attach_spot(self, parent):
        """Return a fixed-size cavity containing the real compact Attach button.

        ElegantButton computes its rounded geometry during construction.  Letting the
        second composer row squeeze that widget directly made the button look vertically
        compressed even though its text/font were correct.  A non-propagating pixel
        cavity gives it the same visual height as the first-row controls without using
        Tk's character-based ``width=`` option.
        """
        p = self._colors()
        holder = tk.Frame(
            parent,
            bg=p.get("panel3", p.get("panel")),
            width=self._ATTACH_WIDTH_PX_138G,
            height=self._ATTACH_HEIGHT_PX_138G,
            bd=0,
            highlightthickness=0,
        )
        holder.pack_propagate(False)
        button = self._mk_button(holder, "Attach", self._button_action("Attach"))
        button.pack(fill="both", expand=True)
        self._attach_holder_138g = holder
        self._attach_button_138g = button
        return holder

    def _ensure_extra_direct_138g(self):
        if not hasattr(self, "_extra_direct"):
            self._extra_direct = []
        if self._extra_direct:
            return
        left = self._chat_dropdown_button.master
        for text, names in [
            ("Edit", ("Edit last", "Edit Last")),
            ("Branch", ("Branch",)),
            ("HF", ("Hands-free", "Hands free")),
            ("Mic", ("Mic",)),
        ]:
            self._extra_direct.append(self._mk_button(left, text, self._button_action(*names)))

    def _wide_required_width_138g(self):
        """Estimate the real toolbar width without packing hidden controls.

        This replaces the old fixed 900 px breakpoint.  At ~1120 px the toolbar was
        classified as 'wide' even though Edit/Branch/HF/Mic plus the View-side actions
        physically could not fit, so the final controls simply disappeared off-window.
        """
        try:
            self._ensure_extra_direct_138g()
            left = self._chat_dropdown_button.master
            right = self._close_button.master

            # Wide layout does not use the Chat/View overflow buttons.
            left_skip = {self._chat_dropdown_button}
            right_skip = {self._view_dropdown_button}

            left_px = 0
            for child in left.winfo_children():
                if child in left_skip:
                    continue
                try:
                    left_px += max(1, int(child.winfo_reqwidth())) + 4
                except Exception:
                    pass

            right_px = 0
            for child in right.winfo_children():
                if child in right_skip:
                    continue
                try:
                    right_px += max(1, int(child.winfo_reqwidth())) + 4
                except Exception:
                    pass

            # Outer frame padding + a safety margin for native/Tk scaling differences.
            return max(1420, left_px + right_px + 56)
        except Exception:
            return 1420

    def _expanded_geometry(self):
        try:
            sw = int(self.app.winfo_screenwidth())
            sh = int(self.app.winfo_screenheight())
        except Exception:
            sw, sh = 1200, 800

        required = int(self._wide_required_width_138g())
        available = max(760, sw - 40)
        # If the monitor has room, expand enough to show every direct control.
        # If not, _layout_toolbar() intentionally selects the overflow-menu layout.
        width = min(available, required)
        height = max(480, min(680, sh - 90))
        return width, height

    def _layout_toolbar(self):
        self._layout_after = None
        if not self.active or self._compact_bar is None:
            return
        try:
            width = int(self.app.winfo_width())
        except Exception:
            width = 760

        required = int(self._wide_required_width_138g())
        narrow = width < required
        if self._layout_narrow_138c is narrow:
            return
        self._layout_narrow_138c = narrow

        self._ensure_extra_direct_138g()

        if narrow:
            for b in list(self._extra_direct):
                try:
                    b.pack_forget()
                except Exception:
                    pass
            if not self._chat_dropdown_button.winfo_manager():
                self._chat_dropdown_button.pack(side="left", padx=(4, 2))
            for b in self._right_direct:
                try:
                    b.pack_forget()
                except Exception:
                    pass
            if not self._view_dropdown_button.winfo_manager():
                self._view_dropdown_button.pack(side="left", padx=(2, 2), before=self._close_button)
        else:
            try:
                self._chat_dropdown_button.pack_forget()
            except Exception:
                pass
            for b in self._extra_direct:
                if not b.winfo_manager():
                    b.pack(side="left", padx=2)
            try:
                self._view_dropdown_button.pack_forget()
            except Exception:
                pass
            for b in self._right_direct:
                if not b.winfo_manager():
                    b.pack(side="left", padx=2, before=self._close_button)

        self._refresh_colors()
        self._normalize_button_labels()

    def _refresh_colors(self):
        super()._refresh_colors()
        try:
            p = self._colors()
            holder = getattr(self, "_attach_holder_138g", None)
            if holder is not None and holder.winfo_exists():
                holder.configure(bg=p.get("panel3", p.get("panel")))
        except Exception:
            pass


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_COMPACT_EXPANDED_REFLOW_BRANDTEXT_v15_138H
# Final compact-expanded reflow after v15.138g:
#   * cap expanded width below the native-chat ultra-wide breakpoint that caused
#     the transcript/history layout to sink to the bottom with a huge blank area;
#   * keep History directly accessible in expanded Compact Mode;
#   * keep the end-of-row lifecycle controls accessible without clipping by using
#     the View overflow for theme/full-UI while retaining Collapse/Tray/Close;
#   * raise only the upper-left full-UI PortalAI wordmark by ~2 px (~1.5 pt @96dpi).
# Existing collapsed-mode height, Attach cavity, hover acceleration, hero alpha,
# startup routing, model/tool behavior, and theme behavior remain unchanged.
# ===========================================================================
PORTALAI_COMPACT_EXPANDED_REFLOW_BRANDTEXT_v15_138H = True


# Upper-left full-UI banner wordmark: v15.138e intentionally moved it down to
# pady=(5,0).  The icon is now correctly aligned after v15.138f, so bring only the
# wordmark back up by ~2 px.  Bind after the older callback so this wins on future
# Configure events as well as the initial layout.
_install_wordmark_label_v15_138G = install_wordmark_label

def install_wordmark_label(widget, root_dir, kind, palette=None):
    widget = _install_wordmark_label_v15_138G(widget, root_dir, kind, palette)
    if str(kind).lower() != "banner":
        return widget

    def _raise_wordmark_138h(_event=None):
        try:
            widget.pack_configure(fill="none", pady=(3, 0), ipady=0, anchor="s")
        except Exception:
            pass

    try:
        widget.master.bind("<Configure>", _raise_wordmark_138h, add="+")
        widget.after_idle(_raise_wordmark_138h)
        widget.after(50, _raise_wordmark_138h)
    except Exception:
        _raise_wordmark_138h()
    return widget


_CompactModeController_v15_138G = CompactModeController

class CompactModeController(_CompactModeController_v15_138G):
    """Compact Mode reflow that avoids the ultra-wide Native Chat layout path."""

    _EXPANDED_WIDTH_CAP_138H = 1200

    def __init__(self, *args, **kwargs):
        self._history_direct_138h = None
        self._layout_signature_138h = None
        super().__init__(*args, **kwargs)

    def _expanded_geometry(self):
        # v15.138g widened expanded Compact Mode to ~1420+ px so every direct
        # toolbar button could fit.  On the actual Native Chat frontend that width
        # crosses a wide-layout path where the transcript/history content becomes
        # bottom-biased, creating the giant blank area visible in the screenshot.
        # Keep the known-good compact-chat width band and use overflow where needed.
        try:
            sw = int(self.app.winfo_screenwidth())
            sh = int(self.app.winfo_screenheight())
        except Exception:
            sw, sh = 1200, 800
        width = max(860, min(self._EXPANDED_WIDTH_CAP_138H, sw - 40))
        height = max(480, min(680, sh - 90))
        return width, height

    def _ensure_history_direct_138h(self):
        b = self._history_direct_138h
        try:
            if b is not None and b.winfo_exists():
                return b
        except Exception:
            pass
        left = self._chat_dropdown_button.master
        b = self._mk_button(left, "History", self._button_action("History"))
        self._history_direct_138h = b
        return b

    def _show_chat_menu(self):
        # Keep History available even when the direct button is hidden in collapsed
        # Compact Mode.  This also gives narrow monitors a no-clipping fallback.
        items = [
            {"label": "History", "command": self._button_action("History")},
            {"label": "Edit last", "command": self._button_action("Edit last", "Edit Last")},
            {"label": "Branch", "command": self._button_action("Branch")},
            {"label": "Hands-free", "command": self._button_action("Hands-free", "Hands free")},
            {"label": "Mic", "command": self._button_action("Mic")},
            {"label": "Attach", "command": self._button_action("Attach")},
        ]
        if self._chat_menu:
            self._chat_menu.show_for(self._chat_dropdown_button, items, "PortalAI · Chat")

    def _layout_toolbar(self):
        self._layout_after = None
        if not self.active or self._compact_bar is None:
            return

        # Avoid repeatedly repacking the same widgets on Configure storms.
        signature = (bool(self.expanded),)
        if self._layout_signature_138h == signature:
            return
        self._layout_signature_138h = signature

        self._ensure_extra_direct_138g()
        history = self._ensure_history_direct_138h()

        # The four optional direct chat-action buttons were what forced v15.138g
        # into the ultra-wide window. Keep them in the Chat menu instead.
        for b in list(getattr(self, "_extra_direct", []) or []):
            try:
                b.pack_forget()
            except Exception:
                pass

        if self.expanded:
            # Left: core actions + a real History button + Chat overflow.
            if not history.winfo_manager():
                history.pack(side="left", padx=(4, 2))
            if not self._chat_dropdown_button.winfo_manager():
                self._chat_dropdown_button.pack(side="left", padx=(2, 2))

            # Right: keep the controls most useful while expanded visible.  Theme
            # and Full UI remain in View so this fits the 1200-px known-good band.
            for b in self._right_direct:
                try:
                    b.pack_forget()
                except Exception:
                    pass
            for b in (self._expand_button,):
                try:
                    if b is not None and not b.winfo_manager():
                        b.pack(side="left", padx=2, before=self._close_button)
                except Exception:
                    pass
            # Tray is the last member of _right_direct in the current cumulative UI.
            try:
                tray = self._right_direct[-1] if self._right_direct else None
                if tray is not None and not tray.winfo_manager():
                    tray.pack(side="left", padx=2, before=self._close_button)
            except Exception:
                pass
            if not self._view_dropdown_button.winfo_manager():
                self._view_dropdown_button.pack(side="left", padx=(2, 2), before=self._close_button)
        else:
            # Collapsed Compact Mode stays minimal exactly as before.
            try:
                history.pack_forget()
            except Exception:
                pass
            if not self._chat_dropdown_button.winfo_manager():
                self._chat_dropdown_button.pack(side="left", padx=(4, 2))
            for b in self._right_direct:
                try:
                    b.pack_forget()
                except Exception:
                    pass
            if not self._view_dropdown_button.winfo_manager():
                self._view_dropdown_button.pack(side="left", padx=(2, 2), before=self._close_button)

        self._refresh_colors()
        self._normalize_button_labels()

    def _set_size(self, expanded=False):
        super()._set_size(expanded)
        if expanded:
            # The width change is what moves Native Chat back into its compact
            # responsive path.  Re-assert the chat tab after the geometry settles so
            # Tk recalculates the transcript/history layout at the final width.
            def _settle():
                try:
                    self.show_tab("chat")
                    self.tab_host.event_generate("<Configure>")
                    self.chat_root.event_generate("<Configure>")
                except Exception:
                    pass
            try:
                self.app.after(70, _settle)
                self.app.after(180, _settle)
            except Exception:
                pass

    def toggle_chat(self):
        # Reset the layout signature when crossing collapsed/expanded state so the
        # toolbar is repacked exactly once for the new mode.
        self._layout_signature_138h = None
        return super().toggle_chat()

    def enter(self):
        self._layout_signature_138h = None
        return super().enter()

    def exit(self):
        self._layout_signature_138h = None
        return super().exit()


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            try:
                old.exit()
            except Exception:
                pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl

# ===========================================================================
# PORTALAI_COMPACT_DENSE_BRAND_FIX_v15_138I
# Compact polish after v15.138h:
#   * align the Attach control to the compact brand/composer row instead of
#     leaving the fixed holder at the parent's raw left edge;
#   * replace the plain "PortalAI" compact identity Label with the same image
#     wordmark family used by the full UI;
#   * remove the expanded-mode stretch gap by using a genuinely compact height
#     and then trimming any residual blank band after Native Chat settles.
# ===========================================================================
PORTALAI_COMPACT_DENSE_BRAND_FIX_v15_138I = True


_CompactModeController_v15_138H = CompactModeController


class CompactModeController(_CompactModeController_v15_138H):
    _EXPANDED_HEIGHT_MIN_138I = 340
    _EXPANDED_HEIGHT_MAX_138I = 420

    def __init__(self, *args, **kwargs):
        self._compact_wordmark_image_138i = None
        self._compact_identity_label_138i = None
        self._trim_passes_138i = 0
        super().__init__(*args, **kwargs)

    def _load_compact_wordmark_138i(self):
        if self._compact_wordmark_image_138i is not None:
            return self._compact_wordmark_image_138i
        try:
            p = _branding_path(self.root_dir, "PortalAI_Compact_Wordmark_72.png")
            if p.exists():
                self._compact_wordmark_image_138i = tk.PhotoImage(file=str(p))
        except Exception:
            self._compact_wordmark_image_138i = None
        return self._compact_wordmark_image_138i

    def _find_compact_identity_138i(self):
        old = self._compact_identity_label_138i
        try:
            if old is not None and old.winfo_exists():
                return old
        except Exception:
            pass
        bar = getattr(self, "_compact_bar", None)
        if bar is None:
            return None
        for w in _walk(bar):
            try:
                if str(w.winfo_class()) not in {"Label", "TLabel"}:
                    continue
                if str(w.cget("text") or "").replace("\u2009", "").replace(" ", "").lower() == "portalai":
                    self._compact_identity_label_138i = w
                    return w
            except Exception:
                pass
        return None

    def _apply_compact_wordmark_138i(self):
        identity = self._find_compact_identity_138i()
        img = self._load_compact_wordmark_138i()
        if identity is None or img is None:
            return
        try:
            identity.configure(
                image=img, text="", compound="center",
                padx=0, pady=0, bd=0, highlightthickness=0,
            )
            identity._portalai_compact_wordmark_138i = img
        except Exception:
            pass

    def _align_attach_138i(self):
        """Pixel-align Attach with the brand cavity and the composer Entry.

        v15.138g fixed the button's compression with a non-propagating holder, but
        the holder remained packed at x=0 of the composer row.  The brand cavity in
        row one has its own left inset, so Attach appeared visibly shifted left.
        Derive the inset from the actual widgets instead of hard-coding DPI pixels.
        """
        holder = getattr(self, "_attach_holder_138g", None)
        entry = getattr(self, "_compact_entry_widget", None)
        identity = self._find_compact_identity_138i()
        if holder is None or entry is None:
            return
        try:
            if not holder.winfo_exists() or not entry.winfo_exists():
                return
            self.app.update_idletasks()
            comp = holder.master
            brandbox = identity.master if identity is not None else None

            left_pad = 4
            if brandbox is not None and brandbox.winfo_exists():
                left_pad = max(0, min(16, int(brandbox.winfo_rootx()) - int(comp.winfo_rootx())))

            entry_h = max(26, int(entry.winfo_height()), int(entry.winfo_reqheight()))
            holder.configure(width=self._ATTACH_WIDTH_PX_138G, height=entry_h)
            holder.pack_propagate(False)
            holder.pack_configure(side="left", padx=(left_pad, 4), pady=0)

            button = getattr(self, "_attach_button_138g", None)
            if button is not None and button.winfo_exists():
                button.pack_configure(fill="both", expand=True, padx=0, pady=0)
        except Exception:
            pass

    def _build_bar(self):
        super()._build_bar()
        # Apply after Tk has negotiated the two compact rows; a second short pass
        # catches Windows DPI rounding without introducing any recurring polling.
        try:
            self.app.after_idle(self._apply_compact_wordmark_138i)
            self.app.after_idle(self._align_attach_138i)
            self.app.after(60, self._apply_compact_wordmark_138i)
            self.app.after(60, self._align_attach_138i)
        except Exception:
            self._apply_compact_wordmark_138i()
            self._align_attach_138i()

    def _expanded_geometry(self):
        width, _old_height = super()._expanded_geometry()
        try:
            sh = int(self.app.winfo_screenheight())
        except Exception:
            sh = 800
        # Expanded Compact Mode should expose chat, not recreate a full-height app.
        # The previous 480-px minimum left Native Chat's stretch row with ~80 px of
        # dead air above the transcript on common 125% Windows scaling.
        height = max(
            self._EXPANDED_HEIGHT_MIN_138I,
            min(self._EXPANDED_HEIGHT_MAX_138I, sh - 160),
        )
        return width, height

    def _compact_visible_content_top_138i(self):
        """Find the first real mapped chat/content widget below the compact bar."""
        try:
            bar_bottom = int(self._compact_bar.winfo_rooty()) + int(self._compact_bar.winfo_height())
        except Exception:
            return None, None
        candidates = []
        for w in _walk(self.chat_root):
            try:
                if not w.winfo_ismapped():
                    continue
                cls = str(w.winfo_class())
                if cls in {"Frame", "TFrame", "Scrollbar", "TScrollbar"}:
                    continue
                ww = int(w.winfo_width()); hh = int(w.winfo_height())
                if ww < 60 or hh < 10:
                    continue
                y = int(w.winfo_rooty())
                if y < bar_bottom + 2:
                    continue
                if cls in {"Label", "TLabel", "Button", "TButton", "Menubutton"}:
                    try:
                        if not str(w.cget("text") or "").strip():
                            continue
                    except Exception:
                        continue
                candidates.append(y)
            except Exception:
                pass
        return bar_bottom, (min(candidates) if candidates else None)

    def _trim_expanded_blank_138i(self):
        if not self.active or not self.expanded:
            return
        try:
            self.app.update_idletasks()
            bar_bottom, content_top = self._compact_visible_content_top_138i()
            if bar_bottom is None or content_top is None:
                return
            gap = int(content_top) - int(bar_bottom)
            # Retain a small visual breathing gap, but remove a true stretch spacer.
            if gap <= 28:
                return
            cur_h = int(self.app.winfo_height())
            min_h = self._EXPANDED_HEIGHT_MIN_138I
            shrink = min(max(0, gap - 18), max(0, cur_h - min_h))
            if shrink <= 0:
                return
            new_h = cur_h - shrink
            self.app.geometry(f"{int(self.app.winfo_width())}x{new_h}+{self.app.winfo_x()}+{self.app.winfo_y()}")
        except Exception:
            pass

    def _schedule_dense_reflow_138i(self):
        self._trim_passes_138i = 0
        def run():
            if not self.active or not self.expanded:
                return
            self._trim_passes_138i += 1
            self._trim_expanded_blank_138i()
            if self._trim_passes_138i < 2:
                try:
                    self.app.after(90, run)
                except Exception:
                    pass
        try:
            self.app.after(90, run)
        except Exception:
            pass

    def _set_size(self, expanded=False):
        super()._set_size(expanded)
        if expanded:
            self._schedule_dense_reflow_138i()
        else:
            try:
                self.app.after_idle(self._align_attach_138i)
            except Exception:
                pass

    def toggle_chat(self):
        out = super().toggle_chat()
        try:
            self.app.after_idle(self._apply_compact_wordmark_138i)
            self.app.after_idle(self._align_attach_138i)
        except Exception:
            pass
        return out

    def enter(self):
        out = super().enter()
        try:
            self.app.after_idle(self._apply_compact_wordmark_138i)
            self.app.after_idle(self._align_attach_138i)
        except Exception:
            pass
        return out


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        old._apply_compact_wordmark_138i()
        old._align_attach_138i()
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            try:
                old.exit()
            except Exception:
                pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_COMPACT_CHAT_RESTORE_ATTACH_WIDEN_v15_138J
# Corrects the v15.138i regression without rolling back its compact wordmark:
#   * disable the height-trimming path that could shrink expanded Compact Mode
#     until the real Native Chat area disappeared;
#   * restore a safe expanded height and force the existing Chat tab to remap;
#   * collapse only empty orphaned chat-chrome ancestors, rather than shrinking
#     the whole window to chase blank space;
#   * widen/pad the compact Attach cavity so the rounded ElegantButton is never
#     clipped or squeezed by the composer row.
# ===========================================================================
PORTALAI_COMPACT_CHAT_RESTORE_ATTACH_WIDEN_v15_138J = True


_CompactModeController_v15_138I = CompactModeController


class CompactModeController(_CompactModeController_v15_138I):
    _ATTACH_WIDTH_PX_138J = 136
    _ATTACH_HEIGHT_PX_138J = 34
    _EXPANDED_WIDTH_CAP_138J = 1220
    _EXPANDED_HEIGHT_MIN_138J = 500
    _EXPANDED_HEIGHT_MAX_138J = 580

    # v15.138i attempted to remove the blank band by shrinking the entire window.
    # On the live Native Chat tree that could push the real transcript outside the
    # visible client area.  Keep these methods as deliberate no-ops so any callbacks
    # inherited from v15.138i cannot shrink the window after expansion.
    def _trim_expanded_blank_138i(self):
        return

    def _schedule_dense_reflow_138i(self):
        return

    def _attach_spot(self, parent):
        p = self._colors()
        holder = tk.Frame(
            parent,
            bg=p.get("panel3", p.get("panel")),
            width=self._ATTACH_WIDTH_PX_138J,
            height=self._ATTACH_HEIGHT_PX_138J,
            bd=0,
            highlightthickness=0,
        )
        holder.pack_propagate(False)
        button = self._mk_button(holder, "Attach", self._button_action("Attach"))
        # A small inner margin prevents ElegantButton's rounded perimeter from being
        # painted flush against the non-propagating holder and visually clipping.
        button.pack(fill="both", expand=True, padx=2, pady=2)
        self._attach_holder_138g = holder
        self._attach_button_138g = button
        self._attach_holder_138j = holder
        self._attach_button_138j = button
        return holder

    def _align_attach_138i(self):
        holder = getattr(self, "_attach_holder_138j", None) or getattr(self, "_attach_holder_138g", None)
        button = getattr(self, "_attach_button_138j", None) or getattr(self, "_attach_button_138g", None)
        entry = getattr(self, "_compact_entry_widget", None)
        if holder is None or button is None:
            return
        try:
            if not holder.winfo_exists() or not button.winfo_exists():
                return
            entry_h = 28
            if entry is not None and entry.winfo_exists():
                entry_h = max(int(entry.winfo_reqheight()), int(entry.winfo_height()), 28)
            holder_h = max(self._ATTACH_HEIGHT_PX_138J, entry_h + 4)
            holder.configure(width=self._ATTACH_WIDTH_PX_138J, height=holder_h)
            holder.pack_propagate(False)
            holder.pack_configure(side="left", padx=(4, 6), pady=0)
            button.pack_configure(fill="both", expand=True, padx=2, pady=2)
        except Exception:
            pass

    def _expanded_geometry(self):
        # Start from the known-safe v15.138h width policy rather than the v15.138i
        # dense-height override.  Add only a tiny amount of horizontal room.
        try:
            width, _ = _CompactModeController_v15_138H._expanded_geometry(self)
        except Exception:
            try:
                sw = int(self.app.winfo_screenwidth())
                width = max(860, min(1200, sw - 40))
            except Exception:
                width = 1100
        try:
            sw = int(self.app.winfo_screenwidth())
            sh = int(self.app.winfo_screenheight())
        except Exception:
            sw, sh = 1200, 800
        width = min(max(int(width), 900), max(760, min(self._EXPANDED_WIDTH_CAP_138J, sw - 32)))
        height = max(
            self._EXPANDED_HEIGHT_MIN_138J,
            min(self._EXPANDED_HEIGHT_MAX_138J, max(420, sh - 150)),
        )
        return width, height

    def _is_descendant_138j(self, widget, ancestor):
        cur = widget
        while cur is not None:
            if cur is ancestor:
                return True
            try:
                cur = cur.master
            except Exception:
                break
        return False

    def _has_real_mapped_descendant_138j(self, frame):
        try:
            children = list(frame.winfo_children())
        except Exception:
            return False
        for child in children:
            try:
                if not child.winfo_ismapped():
                    continue
                cls = str(child.winfo_class())
            except Exception:
                continue
            if cls in {"Frame", "TFrame", "Labelframe", "TLabelframe"}:
                if self._has_real_mapped_descendant_138j(child):
                    return True
                continue
            if cls in {"Label", "TLabel"}:
                try:
                    txt = str(child.cget("text") or "").strip()
                    img = str(child.cget("image") or "").strip()
                    if txt or img:
                        return True
                except Exception:
                    pass
                continue
            # Any mapped input, transcript, list, button, canvas, or scrollbar is
            # real content and prevents its ancestor from being collapsed.
            return True
        return False

    def _collapse_orphaned_chat_chrome_138j(self):
        """Hide only empty ancestors left behind by compact-hidden native controls.

        This attacks the actual source of the blank band without changing window
        height.  Only ancestors of widgets already hidden by Compact Mode are
        considered, and the Chat root itself is never hidden.
        """
        try:
            self.app.update_idletasks()
        except Exception:
            pass
        candidates = []
        for snap in list(getattr(self, "_hidden", []) or []):
            try:
                hidden_widget = snap[0]
                if not self._is_descendant_138j(hidden_widget, self.chat_root):
                    continue
                cur = hidden_widget.master
                while cur is not None and cur is not self.chat_root:
                    if self._is_descendant_138j(cur, self.chat_root) and cur not in candidates:
                        candidates.append(cur)
                    cur = cur.master
            except Exception:
                pass

        # Deepest first. Appending snapshots means normal Compact exit restores the
        # parent before the previously hidden children (reverse restore order).
        candidates.sort(key=lambda w: len(str(w).split(".")), reverse=True)
        for frame in candidates:
            try:
                if not frame.winfo_exists() or not frame.winfo_ismapped():
                    continue
                if str(frame.winfo_class()) not in {"Frame", "TFrame", "Labelframe", "TLabelframe"}:
                    continue
                if self._has_real_mapped_descendant_138j(frame):
                    continue
                # Don't collapse tiny separators; target actual layout containers.
                if int(frame.winfo_height()) < 12 or int(frame.winfo_width()) < 80:
                    continue
                self._hide_unique(frame)
            except Exception:
                pass

    def _restore_expanded_chat_geometry_138j(self):
        if not self.active or not self.expanded:
            return
        try:
            self._show_tab_host()
        except Exception:
            pass
        try:
            self.show_tab("chat")
        except Exception:
            pass
        try:
            self._collapse_orphaned_chat_chrome_138j()
        except Exception:
            pass

        # Reassert fill/expand only on the existing managers.  This never reparents
        # Native Chat and does not recreate its session/widgets.
        for widget in (getattr(self, "tab_host", None), getattr(self, "chat_root", None)):
            if widget is None:
                continue
            try:
                mgr = str(widget.winfo_manager())
                if mgr == "pack":
                    widget.pack_configure(fill="both", expand=True)
                elif mgr == "grid":
                    widget.grid_configure(sticky="nsew")
                    info = widget.grid_info()
                    parent = widget.master
                    row = int(info.get("row", 0)); col = int(info.get("column", 0))
                    parent.grid_rowconfigure(row, weight=1)
                    parent.grid_columnconfigure(col, weight=1)
            except Exception:
                pass
        try:
            self.app.update_idletasks()
            self.tab_host.event_generate("<Configure>")
            self.chat_root.event_generate("<Configure>")
        except Exception:
            pass

    def _set_size(self, expanded=False):
        # Do not call v15.138i's _set_size: it schedules the destructive dense trim.
        try:
            w, h = self._expanded_geometry() if expanded else self._collapsed_geometry()
            self.app.geometry(f"{int(w)}x{int(h)}+{self.app.winfo_x()}+{self.app.winfo_y()}")
        except Exception:
            pass
        if expanded:
            for delay in (0, 70, 180):
                try:
                    self.app.after(delay, self._restore_expanded_chat_geometry_138j)
                except Exception:
                    pass
        else:
            try:
                self.app.after_idle(self._align_attach_138i)
            except Exception:
                pass

    def enter(self):
        out = super().enter()
        try:
            self._collapse_orphaned_chat_chrome_138j()
            self.app.after_idle(self._align_attach_138i)
        except Exception:
            pass
        return out

    def toggle_chat(self):
        out = super().toggle_chat()
        if self.expanded:
            for delay in (0, 80, 200):
                try:
                    self.app.after(delay, self._restore_expanded_chat_geometry_138j)
                except Exception:
                    pass
        else:
            try:
                self.app.after_idle(self._align_attach_138i)
            except Exception:
                pass
        return out


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, "_portalai_compact_controller", None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        old._apply_compact_wordmark_138i()
        old._align_attach_138i()
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            try:
                old.exit()
            except Exception:
                pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_COMPACT_COLLAPSED_HEIGHT_FIX_v15_138K
# v15.138j correctly restored expanded Native Chat, but its custom _set_size()
# bypassed the final collapsed-bar geometry flush inherited from the older compact
# controller.  With the wider Attach holder, the cached collapsed height could be
# captured before row two finished negotiating and the whole compact bar became too
# short.  Keep v15.138j expanded behavior untouched and give collapsed mode an
# independent, post-layout measured height.
# ===========================================================================
PORTALAI_COMPACT_COLLAPSED_HEIGHT_FIX_v15_138K = True

_CompactModeController_v15_138J = CompactModeController


class CompactModeController(_CompactModeController_v15_138J):
    _COLLAPSED_HEIGHT_MIN_138K = 104
    _COLLAPSED_HEIGHT_MAX_138K = 148
    _COLLAPSED_BOTTOM_SLACK_138K = 12

    def _collapsed_geometry(self):
        # Preserve the established compact width policy exactly.  Only height is
        # remeasured from the actual two-row compact bar after Tk layout settles.
        try:
            sw = int(self.app.winfo_screenwidth())
        except Exception:
            sw = 1200
        width = max(620, min(860, sw - 40))

        height = self._COLLAPSED_HEIGHT_MIN_138K
        bar = getattr(self, '_compact_bar', None)
        if bar is not None:
            try:
                if bar.winfo_exists():
                    req_h = max(1, int(bar.winfo_reqheight()))
                    live_h = max(1, int(bar.winfo_height()))
                    top = max(0, int(bar.winfo_y()))
                    measured = top + max(req_h, live_h) + self._COLLAPSED_BOTTOM_SLACK_138K
                    height = max(
                        self._COLLAPSED_HEIGHT_MIN_138K,
                        min(self._COLLAPSED_HEIGHT_MAX_138K, int(measured)),
                    )
            except Exception:
                pass
        return int(width), int(height)

    def _settle_collapsed_geometry_138k(self):
        if not getattr(self, 'active', False) or getattr(self, 'expanded', False):
            return
        try:
            # Attach alignment can increase row-two requested height.  Align first,
            # then perform one bounded layout flush and resize only if needed.
            self._align_attach_138i()
        except Exception:
            pass
        try:
            bar = getattr(self, '_compact_bar', None)
            if bar is not None and bar.winfo_exists():
                bar.update_idletasks()
        except Exception:
            pass
        try:
            w, h = self._collapsed_geometry()
            cur_w = int(self.app.winfo_width())
            cur_h = int(self.app.winfo_height())
            if abs(cur_w - int(w)) > 1 or abs(cur_h - int(h)) > 1:
                self.app.geometry(f"{int(w)}x{int(h)}+{self.app.winfo_x()}+{self.app.winfo_y()}")
        except Exception:
            pass

    def _schedule_collapsed_settle_138k(self):
        # A few bounded one-shot passes cover Tk/Windows DPI geometry negotiation.
        # There is no polling loop and expanded mode never enters this path.
        for delay in (0, 45, 120):
            try:
                self.app.after(delay, self._settle_collapsed_geometry_138k)
            except Exception:
                pass

    def _set_size(self, expanded=False):
        if expanded:
            # The expanded v15.138j path is known-good.  Do not modify it.
            return super()._set_size(True)

        # Discard the older cached pre-Attach height and let dynamic dispatch use
        # the measured v15.138k collapsed geometry in v15.138j's sizing path.
        try:
            self._collapsed_height_138c = None
        except Exception:
            pass
        out = super()._set_size(False)
        self._schedule_collapsed_settle_138k()
        return out

    def enter(self):
        out = super().enter()
        self._schedule_collapsed_settle_138k()
        return out

    def toggle_chat(self):
        out = super().toggle_chat()
        if not getattr(self, 'expanded', False):
            self._schedule_collapsed_settle_138k()
        return out


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, '_portalai_compact_controller', None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        old._apply_compact_wordmark_138i()
        old._align_attach_138i()
        if old.active and not old.expanded:
            old._schedule_collapsed_settle_138k()
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            try:
                old.exit()
            except Exception:
                pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after_idle(lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl


# ===========================================================================
# PORTALAI_DEFAULT_SINGLE_ROW_NAV_FIX_v15_138L
# Keep the established default full-UI window size, but delay the 9->10 pt
# navigation-font jump until the window is genuinely roomy.  At the old 1150 px
# breakpoint, the normal ~1180 px startup geometry increased the tab font just
# enough to wrap Help onto a second ResponsiveFlow row.
# ===========================================================================
PORTALAI_DEFAULT_SINGLE_ROW_NAV_FIX_v15_138L = True

_DynamicTabFontController_v15_138K = DynamicTabFontController

class DynamicTabFontController(_DynamicTabFontController_v15_138K):
    @staticmethod
    def _size_for_width(width):
        width = int(width or 0)
        if width < 900:
            return 8
        # Default startup width (~1180 px) remains at 9 pt so the seven section
        # tabs plus Compact/Theme controls stay on one row.
        if width < 1260:
            return 9
        if width < 1400:
            return 10
        if width < 1700:
            return 11
        return 12

# ===========================================================================
# PORTALAI_DEFAULT_NAV_FIT_FIX_v15_138M
# v15.138l only delayed the font-size jump, but the GUI itself still hard-capped
# startup width at 1180 px.  v15.138m pairs the installer-side 1260 px startup
# geometry + 7 px tab padding with a conservative 9 pt default nav tier.
# ===========================================================================
PORTALAI_DEFAULT_NAV_FIT_FIX_v15_138M = True

_DynamicTabFontController_v15_138L = DynamicTabFontController

class DynamicTabFontController(_DynamicTabFontController_v15_138L):
    @staticmethod
    def _size_for_width(width):
        width = int(width or 0)
        if width < 900:
            return 8
        if width < 1380:
            return 9
        if width < 1600:
            return 10
        if width < 1800:
            return 11
        return 12


# ===========================================================================
# PORTALAI_UI_PERFORMANCE_FIX_v15_138N
# Performance-only cleanup.  No geometry, palette, branding, typography, button
# placement, or responsive breakpoints are changed here.
#
# The cumulative frontend had acquired several maintenance loops over the v15.138
# polish series:
#   * a complete Control Center widget-tree scan every 2.2 s for small-cap fonts;
#   * a complete Native Chat widget-tree scan every 1.0 s, including tag traversal;
#   * a watermark visibility poll every 650 ms;
#   * multiple full-tree hover discovery passes during startup;
#   * Compact toggle paths that could schedule the same expensive chat-geometry
#     restore several times for one click.
# These are reduced to bounded discovery / content-change work while preserving
# the already-correct visuals and controls.
# ===========================================================================
PORTALAI_UI_PERFORMANCE_FIX_v15_138N = True


# ---------------------------------------------------------------------------
# 1) Decorative font discovery is startup work, not a permanent polling job.
# ---------------------------------------------------------------------------
_NativeSmallCapsController_v15_138M = NativeSmallCapsController

class NativeSmallCapsController(_NativeSmallCapsController_v15_138M):
    _DISCOVERY_DELAYS_138N = (350, 1200, 3200)

    def __init__(self, *args, **kwargs):
        self._portalai_discovery_index_138n = 0
        self._portalai_discovery_after_138n = None
        super().__init__(*args, **kwargs)

    def _schedule(self):
        if not getattr(self, 'alive', False):
            return
        idx = int(getattr(self, '_portalai_discovery_index_138n', 0))
        if idx >= len(self._DISCOVERY_DELAYS_138N):
            self._portalai_discovery_after_138n = None
            return
        delay = int(self._DISCOVERY_DELAYS_138N[idx])
        self._portalai_discovery_index_138n = idx + 1
        try:
            self._portalai_discovery_after_138n = self.app.after(delay, self._tick)
        except Exception:
            self._portalai_discovery_after_138n = None

    def close(self):
        self.alive = False
        aid = getattr(self, '_portalai_discovery_after_138n', None)
        if aid is not None:
            try:
                self.app.after_cancel(aid)
            except Exception:
                pass
        self._portalai_discovery_after_138n = None


def install_true_smallcaps_ui(app, palette):
    current = getattr(app, '_portalai_smallcaps_controller', None)
    if isinstance(current, NativeSmallCapsController):
        # Palette changes do not affect font choice.  Do not rescan the entire
        # application every time Light/Dark is toggled.
        current.apply_palette(palette)
        return current
    if current is not None:
        try:
            current.close()
        except Exception:
            pass
    ctl = NativeSmallCapsController(app, palette)
    try:
        app._portalai_smallcaps_controller = ctl
    except Exception:
        pass
    return ctl


# ---------------------------------------------------------------------------
# 2) Slow the watermark's fallback visibility poll.  Geometry remains event-driven
#    through the existing target <Configure>/<Map> bindings.
# ---------------------------------------------------------------------------
_ChatWatermarkOverlay_v15_138M = ChatWatermarkOverlay

class ChatWatermarkOverlay(_ChatWatermarkOverlay_v15_138M):
    _POLL_MS_138N = 1400

    def _refresh(self, _event=None, force_geometry=False):
        try:
            target = self._find_target()
            if (target is None or self.win is None or self.label is None or
                    not self.chat_root.winfo_ismapped() or not self.app.winfo_viewable()):
                self._hide()
                self.app.after(self._POLL_MS_138N, self._refresh)
                return
            ww = max(1, int(target.winfo_width())); hh = max(1, int(target.winfo_height()))
            size = 196 if ww >= 760 and hh >= 430 else 144
            mode = 'dark' if str(self.mode_getter()).lower() == 'dark' else 'light'
            key = f'chatwm_{mode}{size}'
            img = (self.brand_images or {}).get(key)
            if img is None:
                self._hide()
                self.app.after(self._POLL_MS_138N, self._refresh)
                return
            if key != self._last_key:
                self.label.configure(image=img)
                self.label._portalai_image = img
                self._last_key = key
                try:
                    self.win.attributes('-alpha', 0.22 if mode == 'dark' else 0.18)
                except Exception:
                    pass
            margin = 22
            x = int(target.winfo_rootx() + max(0, ww - size - margin))
            y = int(target.winfo_rooty() + max(0, hh - size - margin))
            geom = (size, x, y)
            if force_geometry or geom != self._last_geom:
                self.win.geometry(f'{size}x{size}+{x}+{y}')
                self._last_geom = geom
            if not self._shown:
                self.win.deiconify(); self.win.lift(); self._make_clickthrough(); self._shown = True
            self.app.after(self._POLL_MS_138N, self._refresh)
        except tk.TclError:
            return
        except Exception:
            try:
                self.app.after(1800, self._refresh)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# 3) Chat maintenance: keep identity/context behavior, but only redo expensive Text
#    role-tag work when the Text content signature changes.  Tree discovery backs
#    off after startup instead of running every second forever.
# ---------------------------------------------------------------------------
def _portalai_chat_text_signature_138n(widget):
    try:
        end = str(widget.index('end-1c'))
    except Exception:
        return None
    try:
        # Last visible character catches common equal-length edits without reading
        # the transcript body.
        tail = str(widget.get('end-2c', 'end-1c')) if end != '1.0' else ''
    except Exception:
        tail = ''
    return (end, tail)


def install_native_chat_frontend(app, chat_root, native_chat_panel, palette, brand_images, mode_getter):
    state = {'alive': True, 'passes': 0, 'after': None, 'scrollbar_passes': 0}
    overlay = ChatWatermarkOverlay(app, chat_root, brand_images, mode_getter, lambda: palette)
    try:
        from themed_popup_menu import ThemedPopupMenu
        chat_menu = ThemedPopupMenu(app, lambda: palette)
    except Exception:
        chat_menu = None

    def schedule(delay):
        if not state.get('alive'):
            return
        old = state.get('after')
        if old is not None:
            try:
                app.after_cancel(old)
            except Exception:
                pass
        try:
            state['after'] = app.after(int(delay), tick)
        except Exception:
            state['after'] = None

    def tick():
        state['after'] = None
        if not state.get('alive'):
            return
        try:
            mapped = bool(chat_root.winfo_ismapped())
        except Exception:
            mapped = True
        if not mapped:
            schedule(3500)
            return
        try:
            for w in _walk(chat_root):
                try:
                    cls = str(w.winfo_class())
                except Exception:
                    cls = ''

                # Visible widget labels: update only when source text actually changed.
                try:
                    txt = w.cget('text')
                except Exception:
                    txt = None
                if txt is not None:
                    raw = str(txt)
                    if getattr(w, '_portalai_brand_source_138n', None) != raw:
                        try:
                            branded = frontend_brand_text(raw, chat=True)
                            if branded != raw:
                                w.configure(text=branded)
                                raw = branded
                        except Exception:
                            pass
                        try:
                            w._portalai_brand_source_138n = raw
                        except Exception:
                            pass

                # Pinning is already self-guarded after the first successful pass.
                try:
                    if not getattr(w, '_portalai_nice_identity_pinned', False):
                        _pin_label_identity(w)
                except Exception:
                    pass

                # Context menu installation is likewise one-time per widget.
                try:
                    if not (getattr(w, '_portalai_themed_chat_context_138e', False) or
                            getattr(w, '_portalai_themed_chat_context', False)):
                        _install_themed_chat_context(w, app, native_chat_panel, chat_menu, palette)
                except Exception:
                    pass

                # Tag traversal on a long transcript is the expensive part.  Only run
                # it when the Text content endpoint/tail changed since the last pass.
                if cls == 'Text':
                    sig = _portalai_chat_text_signature_138n(w)
                    if sig != getattr(w, '_portalai_role_signature_138n', None):
                        try:
                            _rename_chat_role_tags(w)
                        except Exception:
                            pass
                        try:
                            w._portalai_role_signature_138n = sig
                        except Exception:
                            pass

            state['passes'] = int(state.get('passes', 0)) + 1
            # Scrollbar discovery only needs startup/lazy-construction passes.
            if state['scrollbar_passes'] < 2:
                try:
                    upgrade_vertical_scrollbars(chat_root, palette)
                except Exception:
                    pass
                state['scrollbar_passes'] += 1

            # Catch lazy startup widgets quickly, then back off to a low-frequency
            # safety discovery pass.  Identity writes are synchronous once pinned.
            schedule(450 if state['passes'] < 2 else 2200)
        except tk.TclError:
            return
        except Exception:
            schedule(2800)

    # Immediate discovery plus one later hover pass is sufficient; the old wrapper
    # performed four full application-tree hover scans through 2.5 seconds.
    schedule(60)
    for delay in (150, 900):
        try:
            app.after(delay, lambda a=app: _portalai_accelerate_elegant_hover(a))
        except Exception:
            pass

    # If the Chat surface is remapped after being hidden, wake maintenance promptly.
    try:
        chat_root.bind('<Map>', lambda _e: schedule(80), add='+')
    except Exception:
        pass
    return {'overlay': overlay, 'state': state, 'chat_menu': chat_menu}


# ---------------------------------------------------------------------------
# 4) Width-only responsive scheduling.  Moving/resizing height used to wake the
#    navigation and compact layout debouncers even when their width bucket could not
#    possibly change.
# ---------------------------------------------------------------------------
_DynamicTabFontController_v15_138M = DynamicTabFontController

class DynamicTabFontController(_DynamicTabFontController_v15_138M):
    def __init__(self, *args, **kwargs):
        self._portalai_last_configure_width_138n = None
        super().__init__(*args, **kwargs)

    def register(self, button):
        super().register(button)
        if button is not None:
            # Override ttk's inherited minimum character width for navigation
            # only. Size each label with its existing font/padding, so all eight
            # sections fit at startup without shrinking type or changing themes.
            button.configure(width=0)

    def _on_configure(self, event=None):
        try:
            if event is not None and event.widget is not self.app:
                return
            width = int(getattr(event, 'width', 0) or self.app.winfo_width())
        except Exception:
            return
        if width == self._portalai_last_configure_width_138n:
            return
        self._portalai_last_configure_width_138n = width
        self._schedule(70)


# ---------------------------------------------------------------------------
# 5) Compact mode: eliminate duplicate restore/settle callback fan-out.  The final
#    v15.138m geometry/layout methods remain unchanged; one size transition gets one
#    geometry restore instead of several overlapping inherited schedules.
# ---------------------------------------------------------------------------
_CompactModeController_v15_138M = CompactModeController

class CompactModeController(_CompactModeController_v15_138M):
    def _bind_fast_hover(self, button, normal, hover):
        button.use_native_hover()

    def __init__(self, *args, **kwargs):
        self._portalai_compact_last_width_138n = None
        self._portalai_restore_after_138n = None
        self._portalai_collapse_after_138n = []
        super().__init__(*args, **kwargs)

    def _compact_configure(self, event=None):
        if not getattr(self, 'active', False):
            return
        try:
            if event is not None and event.widget is not self.app:
                return
            width = int(getattr(event, 'width', 0) or self.app.winfo_width())
        except Exception:
            return
        if width == self._portalai_compact_last_width_138n:
            return
        self._portalai_compact_last_width_138n = width
        return _CompactModeController_v15_138M._compact_configure(self, event)

    def _cancel_compact_perf_callbacks_138n(self):
        aid = getattr(self, '_portalai_restore_after_138n', None)
        if aid is not None:
            try:
                self.app.after_cancel(aid)
            except Exception:
                pass
        self._portalai_restore_after_138n = None
        for aid in list(getattr(self, '_portalai_collapse_after_138n', []) or []):
            try:
                self.app.after_cancel(aid)
            except Exception:
                pass
        self._portalai_collapse_after_138n = []

    def _set_size(self, expanded=False):
        self._cancel_compact_perf_callbacks_138n()
        try:
            if not expanded:
                self._collapsed_height_138c = None
        except Exception:
            pass
        try:
            w, h = self._expanded_geometry() if expanded else self._collapsed_geometry()
            cur = (int(self.app.winfo_width()), int(self.app.winfo_height()))
            if abs(cur[0] - int(w)) > 1 or abs(cur[1] - int(h)) > 1:
                self.app.geometry(f'{int(w)}x{int(h)}+{self.app.winfo_x()}+{self.app.winfo_y()}')
        except Exception:
            pass

        if expanded:
            try:
                self._portalai_restore_after_138n = self.app.after(100, self._restore_expanded_chat_geometry_138j)
            except Exception:
                self._portalai_restore_after_138n = None
        else:
            # Two bounded post-layout measurements preserve the known-good v15.138k
            # collapsed height without the old three-pass fan-out.
            for delay in (55, 135):
                try:
                    aid = self.app.after(delay, self._settle_collapsed_geometry_138k)
                    self._portalai_collapse_after_138n.append(aid)
                except Exception:
                    pass

    def toggle_chat(self):
        if not getattr(self, 'active', False):
            return
        self.expanded = not bool(getattr(self, 'expanded', False))
        try:
            if self.expanded:
                self._show_tab_host()
            else:
                self._hide_tab_host()
        except Exception:
            pass
        try:
            if self._expand_button is not None:
                self._expand_button.configure(text='Collapse chat' if self.expanded else 'Expand chat')
        except Exception:
            pass
        try:
            self._layout_signature_138h = None
        except Exception:
            pass
        self._set_size(self.expanded)
        try:
            self._layout_toolbar()
            self._normalize_button_labels()
        except Exception:
            pass

    def exit(self, *args, **kwargs):
        self._cancel_compact_perf_callbacks_138n()
        return super().exit(*args, **kwargs)


def install_compact_mode(app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
                         chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs):
    old = getattr(app, '_portalai_compact_controller', None)
    if isinstance(old, CompactModeController):
        old.palette = palette
        old._refresh_colors()
        old._apply_compact_wordmark_138i()
        old._align_attach_138i()
        return old
    if old is not None:
        try:
            old.exit(force=True)
        except Exception:
            try:
                old.exit()
            except Exception:
                pass
    ctl = CompactModeController(
        app, content, tabbar, tab_host, tab_pages, selected_tab, show_tab,
        chat_root, native_chat_panel, start_components, tabs_right, palette, **kwargs,
    )
    try:
        app._portalai_compact_controller = ctl
        app.after(120, lambda a=app: _portalai_accelerate_elegant_hover(a))
    except Exception:
        pass
    return ctl
