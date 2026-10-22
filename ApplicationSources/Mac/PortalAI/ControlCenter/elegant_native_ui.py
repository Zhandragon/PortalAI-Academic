from __future__ import annotations

"""PortableAI refined native UI v15.121.

Visual-only skin for real ttk.Button controls.

Safety properties:
- ttk owns mouse/keyboard/focus/command dispatch.
- no Canvas-backed buttons.
- no tkinter.Button monkeypatch.
- no recursive widget-tree restyling.
- no third-party runtime dependency.
- no bundled font files.

The rounded artwork is generated as small anti-aliased PNGs using only the
Python standard library, then used as ordinary ttk theme elements.
"""

import base64
import hashlib
import math
import struct
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk
from typing import Any
import zlib
from ui_style_cache import cached_style

VERSION = "15.125"
MARKER = "PORTABLEAI_REFINED_NATIVE_UI_v15_121A"

GOLD = "#B88A32"
GOLD_LIGHT = "#D5B56E"
CYAN = "#3195A9"
CYAN_LIGHT = "#55B7C7"

DISPLAY_CANDIDATES = (
    "Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Variable Display",
    "Aptos Display", "Segoe UI",
)
UI_CANDIDATES = (
    "Segoe UI Variable Text", "Aptos", "Segoe UI", "Tahoma",
)

_IMAGE_CACHE: dict[tuple, tuple[str, tuple[tk.PhotoImage, ...]]] = {}
_STYLE_REFS: dict[int, ttk.Style] = {}
_COUNTER = 0


def _rgb(value: str) -> tuple[int, int, int] | None:
    value = str(value or "").strip()
    if len(value) == 4 and value.startswith("#"):
        value = "#" + "".join(x * 2 for x in value[1:])
    if len(value) != 7 or not value.startswith("#"):
        return None
    try:
        return tuple(int(value[i:i+2], 16) for i in (1, 3, 5))
    except ValueError:
        return None


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(x))) for x in rgb)


def blend(a: str, b: str, t: float) -> str:
    ra, rb = _rgb(a), _rgb(b)
    if ra is None or rb is None:
        return str(a)
    t = max(0.0, min(1.0, float(t)))
    return _hex(tuple(round(x + (y-x) * t) for x, y in zip(ra, rb)))


def _luma(color: str) -> float:
    x = _rgb(color)
    if x is None:
        return 0.5
    return (0.2126*x[0] + 0.7152*x[1] + 0.0722*x[2]) / 255.0


def _kind(color: str) -> str:
    x = _rgb(color)
    if not x:
        return "neutral"
    r, g, b = x
    if r > g * 1.18 and r > b * 1.12:
        return "danger"
    if g > r * 1.20 and b > r * 1.22 and abs(g-b) < 65:
        return "cyan"
    if r > b * 1.35 and g > b * 1.15 and r >= g:
        return "gold"
    return "neutral"


def _family(root: tk.Misc, candidates: tuple[str, ...], fallback: str) -> str:
    owner = root._root()
    cache = getattr(owner, '_portalai_font_families', None)
    if cache is None:
        cache = owner._portalai_font_families = {}
    key = (candidates, fallback)
    if key in cache:
        return cache[key]
    try:
        fams = {str(f).casefold(): str(f) for f in tkfont.families(root)}
        for c in candidates:
            if c.casefold() in fams:
                cache[key] = fams[c.casefold()]
                return cache[key]
    except Exception:
        pass
    cache[key] = fallback
    return fallback


def ui_font(root: tk.Misc) -> str:
    return _family(root, UI_CANDIDATES, "Segoe UI")


def display_font(root: tk.Misc) -> str:
    return _family(root, DISPLAY_CANDIDATES, "Segoe UI")


def _rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    rgb = _rgb(color) or (128, 128, 128)
    return rgb[0], rgb[1], rgb[2], max(0, min(255, int(alpha)))


def _inside_round(x: float, y: float, left: float, top: float,
                  right: float, bottom: float, radius: float) -> bool:
    if x < left or x > right or y < top or y > bottom:
        return False
    r = max(0.0, min(radius, (right-left)/2.0, (bottom-top)/2.0))
    if r <= 0:
        return True
    cx = min(max(x, left+r), right-r)
    cy = min(max(y, top+r), bottom-r)
    dx, dy = x-cx, y-cy
    return dx*dx + dy*dy <= r*r


def _over(dst: tuple[float,float,float,float], src: tuple[int,int,int,int]):
    """Alpha-composite src over premultiplied-ish float dst."""
    dr,dg,db,da = dst
    sr,sg,sb,sa8 = src
    sa = sa8 / 255.0
    oa = sa + da * (1-sa)
    if oa <= 1e-9:
        return 0.0,0.0,0.0,0.0
    # store straight RGB in 0..255 plus alpha 0..1
    rr = (sr*sa + dr*da*(1-sa)) / oa
    gg = (sg*sa + dg*da*(1-sa)) / oa
    bb = (sb*sa + db*da*(1-sa)) / oa
    return rr,gg,bb,oa


def _png_bytes(width: int, height: int, rgba_rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind+data) & 0xffffffff)
    raw = b"".join(b"\x00" + row for row in rgba_rows)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def _round_png(fill: str, border: str, shadow: str,
               *, width: int = 30, height: int = 24, radius: float = 5.5) -> bytes:
    """Generate a crisp AA rounded rectangle with a one-pixel visual shadow."""
    ss = 4
    fill_rgba = _rgba(fill, 255)
    border_rgba = _rgba(border, 255)
    shadow_rgba = _rgba(shadow, 54)
    rows: list[bytes] = []
    # Leave a transparent pixel around corners and reserve lower pixel for shadow.
    outer = (1.0, 0.6, width-2.0, height-2.6)
    inner = (2.15, 1.75, width-3.15, height-3.75)
    shadow_rect = (1.0, 1.65, width-2.0, height-1.55)
    out = bytearray()
    for py in range(height):
        out.clear()
        for px in range(width):
            rr=gg=bb=aa=0.0
            accum_r=accum_g=accum_b=accum_a=0.0
            for sy in range(ss):
                for sx in range(ss):
                    x = px + (sx + 0.5)/ss
                    y = py + (sy + 0.5)/ss
                    c = (0.0,0.0,0.0,0.0)
                    if _inside_round(x,y,*shadow_rect,radius):
                        c = _over(c, shadow_rgba)
                    if _inside_round(x,y,*outer,radius):
                        c = _over(c, border_rgba)
                    if _inside_round(x,y,*inner,max(2.0,radius-1.25)):
                        c = _over(c, fill_rgba)
                    accum_r += c[0] * c[3]
                    accum_g += c[1] * c[3]
                    accum_b += c[2] * c[3]
                    accum_a += c[3]
            n = ss*ss
            a = accum_a / n
            if a > 1e-9:
                r = accum_r / n / a
                g = accum_g / n / a
                b = accum_b / n / a
            else:
                r=g=b=0
            out.extend((round(max(0,min(255,r))), round(max(0,min(255,g))), round(max(0,min(255,b))), round(max(0,min(255,a*255)))))
        rows.append(bytes(out))
    return _png_bytes(width, height, rows)


def _photo(master: tk.Misc, fill: str, border: str, shadow: str) -> tk.PhotoImage:
    png = _round_png(fill, border, shadow)
    data = base64.b64encode(png).decode("ascii")
    return tk.PhotoImage(master=master, data=data, format="png")


def _state_colors(bg: str, active_bg: str | None, parent_bg: str):
    kind = _kind(bg)
    is_light = _luma(parent_bg) >= 0.43
    neutral_edge = blend(bg, "#5D554A" if is_light else "#D8CBB7", .24 if is_light else .18)
    if kind == "cyan":
        normal_border = blend(bg, "#123C45", .30)
    elif kind == "gold":
        normal_border = blend(bg, "#5C431A", .28)
    elif kind == "danger":
        normal_border = blend(bg, "#3A1115", .28)
    else:
        normal_border = neutral_edge
    hover = str(active_bg or blend(bg, CYAN if kind == "neutral" else "#FFFFFF", .055 if kind == "neutral" else .085))
    pressed = blend(hover, "#000000" if _luma(hover) > .46 else "#FFFFFF", .075)
    disabled = blend(bg, parent_bg, .48)
    hover_border = (
        blend(bg, "#FFFFFF", .30) if kind == "danger" else
        GOLD_LIGHT if kind == "gold" else
        CYAN_LIGHT
    )
    focus_border = GOLD_LIGHT
    disabled_border = blend(normal_border, parent_bg, .60)
    shadow = "#000000" if is_light else "#000000"
    return (
        (bg, normal_border, shadow),
        (hover, hover_border, shadow),
        (pressed, hover_border, shadow),
        (disabled, disabled_border, shadow),
        (bg, focus_border, shadow),
    )


def _visuals(master: tk.Misc, bg: str, active_bg: str | None, parent_bg: str):
    root_id = id(master.tk)
    states = _state_colors(str(bg), active_bg, str(parent_bg))
    key = (root_id, ttk.Style(master).theme_use(), states)
    cached = _IMAGE_CACHE.get(key)
    if cached:
        return cached
    token = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:12]
    element = f"PortableAI.Refined.{token}"
    images = tuple(_photo(master, *args) for args in states)
    style = _STYLE_REFS.setdefault(root_id, ttk.Style(master))
    try:
        style.element_create(
            element, "image",
            images[0],
            ("disabled", images[3]),
            ("pressed", images[2]),
            ("active", images[1]),
            ("focus", images[4]),
            border=(7, 7, 7, 7),
            sticky="nsew",
        )
    except tk.TclError:
        pass
    result = (element, images)
    _IMAGE_CACHE[key] = result
    return result


def _compact_pad(value: Any, *, vertical: bool) -> int:
    try:
        x = max(0, int(float(value)))
    except Exception:
        x = 6 if not vertical else 3
    if vertical:
        # Old tk.Button pady values were designed for flat controls.  Mirroring
        # them in ttk created the giant v15.120 capsules.  Preserve intent, not pixels.
        return max(1, min(2, round(x * .25)))
    return max(4, min(8, round(x * .52)))


class ElegantButton(ttk.Button):
    """Compact rounded real ttk.Button compatible with PortableAI's Tk subset."""

    def __init__(self, master=None, cnf=None, **kw):
        global _COUNTER
        values = dict(cnf or {}) if isinstance(cnf, dict) else {}
        values.update(kw)

        self._bg = values.pop("bg", values.pop("background", "#EEE7DA"))
        self._fg = values.pop("fg", values.pop("foreground", "#25231F"))
        self._active_bg = values.pop("activebackground", None)
        self._active_fg = values.pop("activeforeground", None)
        self._disabled_fg = values.pop("disabledforeground", None)
        values.pop("highlightbackground", None)
        values.pop("highlightcolor", None)
        values.pop("highlightthickness", None)
        values.pop("relief", None)
        values.pop("bd", None)
        values.pop("borderwidth", None)
        values.pop("overrelief", None)
        values.pop("default", None)

        self._padx = values.pop("padx", 8)
        self._pady = values.pop("pady", 3)
        self._font = values.pop("font", None)
        self._requested_width = values.pop("width", None)

        try:
            self._parent_bg = master.cget("bg")
        except Exception:
            self._parent_bg = "#F3EEE4"

        supported = {}
        for k in ("text", "command", "state", "cursor", "image",
                  "compound", "takefocus", "underline"):
            if k in values:
                supported[k] = values.pop(k)
        # Preserve explicit small character widths, but prevent old large widths
        # from forcing inflexible layouts. Text + compact padding normally sizes best.
        try:
            w = int(float(self._requested_width)) if self._requested_width not in (None, "") else 0
        except Exception:
            w = 0
        if 0 < w <= 14:
            supported["width"] = w

        _COUNTER += 1
        self._style_name = f"PortableAI.Refined.{_COUNTER}.TButton"
        supported["style"] = self._style_name
        super().__init__(master, **supported)
        self._apply_style()

    def _apply_style(self):
        # PORTABLEAI_THEME_PARENT_REFRESH_v15_125
        # Rounded button corners are transparent, so the parent color must be
        # refreshed after a live light/dark theme switch instead of using the
        # startup theme forever.
        try:
            current_parent_bg = self.master.cget("bg")
        except Exception:
            try:
                current_parent_bg = self.master.cget("background")
            except Exception:
                current_parent_bg = self._parent_bg
        if current_parent_bg:
            self._parent_bg = str(current_parent_bg)
        element, _images = _visuals(self, self._bg, self._active_bg, self._parent_bg)
        font = self._font or (ui_font(self), 9, "bold")
        padx = _compact_pad(self._padx, vertical=False)
        pady = _compact_pad(self._pady, vertical=True)
        disabled_fg = self._disabled_fg or blend(str(self._fg), str(self._parent_bg), .50)
        active_fg = self._active_fg or self._fg
        signature = (element, str(font), self._fg, self._parent_bg, padx, pady, disabled_fg, active_fg)
        def build(style, name):
            self._build_style(style, name, element, font, padx, pady, disabled_fg, active_fg)
        name = cached_style(self, 'Refined.TButton', signature, build)
        self._style_name = name
        if super().cget('style') != name:
            super().configure(style=name)

    def _build_style(self, style, name, element, font, padx, pady, disabled_fg, active_fg):
        style.layout(
            name,
            [(element, {
                "sticky": "nsew",
                "children": [
                    ("Button.padding", {
                        "sticky": "nsew",
                        "children": [("Button.label", {"sticky": "nsew"})],
                    }),
                ],
            })],
        )
        style.configure(
            name,
            foreground=self._fg,
            background=self._parent_bg,
            font=font,
            padding=(padx, pady),
            anchor="center",
            borderwidth=0,
            relief="flat",
        )
        style.map(
            name,
            foreground=[
                ("disabled", disabled_fg),
                ("active", active_fg),
                ("pressed", active_fg),
            ],
        )

    def configure(self, cnf=None, **kw):
        if cnf is None and not kw:
            return super().configure()
        values = dict(cnf or {}) if isinstance(cnf, dict) else {}
        values.update(kw)
        aliases = {"background": "bg", "foreground": "fg"}
        values = {aliases.get(k, k): v for k, v in values.items()}
        visual = False
        passthrough = {}
        for key, value in values.items():
            if key == "bg": self._bg = value; visual = True
            elif key == "fg": self._fg = value; visual = True
            elif key == "activebackground": self._active_bg = value; visual = True
            elif key == "activeforeground": self._active_fg = value; visual = True
            elif key == "disabledforeground": self._disabled_fg = value; visual = True
            elif key == "font": self._font = value; visual = True
            elif key == "padx": self._padx = value; visual = True
            elif key == "pady": self._pady = value; visual = True
            elif key == "width":
                self._requested_width = value
                try:
                    w = int(float(value))
                except Exception:
                    w = 0
                if 0 < w <= 14:
                    passthrough["width"] = w
                else:
                    passthrough["width"] = 0
            elif key in {"relief", "bd", "borderwidth", "highlightthickness",
                         "highlightcolor", "highlightbackground", "overrelief", "default"}:
                continue
            elif key in {"text", "command", "state", "cursor", "image",
                         "compound", "takefocus", "underline"}:
                passthrough[key] = value
            else:
                continue
        if passthrough:
            super().configure(**passthrough)
        if visual:
            self._apply_style()
        return None

    config = configure

    def use_native_hover(self):
        """Keep palette colors immutable while ttk owns transient hover state."""
        self.bind('<Enter>',lambda _e:(self.state(['active']),'break')[1])
        self.bind('<Leave>',lambda _e:(self.state(['!active']),'break')[1])
        self._portalai_fast_hover_138f = True

    def cget(self, key):
        key = {"background": "bg", "foreground": "fg"}.get(key, key)
        visual = {
            "bg": self._bg,
            "fg": self._fg,
            "activebackground": self._active_bg,
            "activeforeground": self._active_fg,
            "disabledforeground": self._disabled_fg,
            "font": self._font,
            "padx": self._padx,
            "pady": self._pady,
            "width": self._requested_width,
        }
        if key in visual:
            return visual[key]
        return super().cget(key)

    def __getitem__(self, key):
        return self.cget(key)

    def __setitem__(self, key, value):
        self.configure(**{key: value})
