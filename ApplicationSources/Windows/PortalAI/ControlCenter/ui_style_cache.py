"""Reuse presentation-only ttk styles within one Tk interpreter and theme.

Writing even an unchanged ttk style broadcasts ThemeChanged to every widget.
Keys contain colors/fonts/element names, never account data or window sizes.
The root owns the cache so no styles are reused across application lifetimes.
"""
import itertools
from tkinter import ttk

_IDS = itertools.count()


def cached_style(widget, role, signature, build):
    root = widget._root()
    cache = getattr(root, '_portalai_presentation_styles', None)
    if cache is None:
        cache = root._portalai_presentation_styles = {}
    style = ttk.Style(widget)
    key = (style.theme_use(), role, signature)
    if key not in cache:
        name = f'PortalCached{next(_IDS)}.{role}'
        build(style, name)
        cache[key] = name
    return cache[key]
