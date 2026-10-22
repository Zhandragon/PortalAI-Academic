from __future__ import annotations

"""PortableAI elegant-tech typography helpers, v15.118.

v15.118 deliberately uses native Tk buttons for reliability.  The earlier
Canvas-backed RoundedButton is retired; RoundedButton remains as a compatibility
alias to tk.Button so older source imports continue to work safely.
"""

import tkinter as tk
import tkinter.font as tkfont

VERSION = "15.118"
MARKER = "PORTABLEAI_NATIVE_CONTROLS_v15_118"

GOLD = "#C7A866"
GOLD_SHINE = "#D9C083"
CYAN = "#3F94A8"
CYAN_BRIGHT = "#58B7C7"

DISPLAY_CANDIDATES = (
    "Bahnschrift SemiBold", "Bahnschrift", "Segoe UI Variable Display",
    "Aptos Display", "Segoe UI",
)
UI_CANDIDATES = ("Segoe UI Variable Text", "Aptos", "Segoe UI", "Tahoma")
MONO_CANDIDATES = ("Cascadia Mono", "Cascadia Code", "Consolas", "Courier New")

DISPLAY_FONT = "Bahnschrift"
UI_FONT = "Segoe UI Variable Text"
MONO_FONT = "Cascadia Mono"
_FONT_CACHE: dict[int, tuple[str, str, str]] = {}


def _existing_family(root: tk.Misc, candidates: tuple[str, ...], fallback: str) -> str:
    try:
        families = {str(x).casefold(): str(x) for x in tkfont.families(root)}
        for candidate in candidates:
            found = families.get(candidate.casefold())
            if found:
                return found
    except Exception:
        pass
    return fallback


def resolve_fonts(root: tk.Misc | None = None) -> tuple[str, str, str]:
    global DISPLAY_FONT, UI_FONT, MONO_FONT
    if root is None:
        root = getattr(tk, "_default_root", None)
    if root is None:
        return DISPLAY_FONT, UI_FONT, MONO_FONT
    key = id(root.tk)
    cached = _FONT_CACHE.get(key)
    if cached:
        return cached
    display = _existing_family(root, DISPLAY_CANDIDATES, "Segoe UI")
    ui = _existing_family(root, UI_CANDIDATES, "Segoe UI")
    mono = _existing_family(root, MONO_CANDIDATES, "Consolas")
    DISPLAY_FONT, UI_FONT, MONO_FONT = display, ui, mono
    out = (display, ui, mono)
    _FONT_CACHE[key] = out
    return out


def display_font(root: tk.Misc | None = None) -> str:
    return resolve_fonts(root)[0]


def ui_font(root: tk.Misc | None = None) -> str:
    return resolve_fonts(root)[1]


def mono_font(root: tk.Misc | None = None) -> str:
    return resolve_fonts(root)[2]


def apply_root_typography(root: tk.Misc) -> tuple[str, str, str]:
    display, ui, mono = resolve_fonts(root)
    try:
        root.option_add("*Font", (ui, 9))
        root.option_add("*Menu.Font", (ui, 9))
        root.option_add("*Listbox.Font", (ui, 9))
    except Exception:
        pass
    return display, ui, mono


def install_elegant_buttons(tk_module=tk) -> None:
    """Compatibility no-op. v15.118 never monkeypatches tkinter.Button."""
    return None


# Backward-compatible symbol: intentionally the real native Tk Button.
RoundedButton = tk.Button

__all__ = [
    "VERSION", "MARKER", "RoundedButton", "install_elegant_buttons",
    "apply_root_typography", "resolve_fonts", "display_font", "ui_font",
    "mono_font", "DISPLAY_FONT", "UI_FONT", "MONO_FONT",
]
