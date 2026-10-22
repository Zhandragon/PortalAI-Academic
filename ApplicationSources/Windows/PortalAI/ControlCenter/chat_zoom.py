"""Conversation-only zoom; no history rebuild, disk images or player restart.

The preference is owned by the caller's captured-profile ChatStore. All drawing,
image conversion and event cleanup stay on Tk's thread. Ordinary scrolling and
widgets outside the transcript retain their existing bindings and fonts.
"""
from __future__ import annotations

import math
import re
import tkinter as tk
from tkinter import font as tkfont

MIN_ZOOM, MAX_ZOOM, ZOOM_STEP = 75, 200, 10


def normalize_zoom(value):
    try:
        number = float(value)
        if not math.isfinite(number):
            return 100
        return max(MIN_ZOOM, min(MAX_ZOOM, round(number)))
    except (TypeError, ValueError, OverflowError):
        return 100


def image_size(width, height, percent, available=1400):
    """Keep aspect ratio, viewport fit and a bounded in-memory preview."""
    factor = min(normalize_zoom(percent) / 100, max(40, available) / max(1, width),
                 1400 / max(1, width), 1400 / max(1, height))
    return max(1, round(width * factor)), max(1, round(height * factor))


def resize_ppm(data, width, height):
    """Resize Tk's own P6 export with stdlib only, without a large zoom temporary."""
    match = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', data)
    if not match:
        raise ValueError('Unexpected Tk preview format')
    source_width, source_height = map(int, match.groups())
    pixels = memoryview(data)[match.end():]
    if source_width * source_height > 4_000_000 or len(pixels) != source_width * source_height * 3:
        raise ValueError('Preview exceeds its bounded pixel inventory')
    if width * height > 1_960_000 or min(width, height) < 1:
        raise ValueError('Invalid preview dimensions')
    xs = [min(source_width - 1, x * source_width // width) * 3 for x in range(width)]
    rows = []
    previous_y, row = -1, b''
    for y in range(height):
        source_y = min(source_height - 1, y * source_height // height)
        if source_y != previous_y:
            offset = source_y * source_width * 3
            row = b''.join(pixels[offset + x:offset + x + 3] for x in xs)
            previous_y = source_y
        rows.append(row)
    return f'P6\n{width} {height}\n255\n'.encode('ascii') + b''.join(rows)


class ChatZoom:
    def __init__(self, transcript, settings, save_settings):
        self.chat = transcript
        self.app = transcript.winfo_toplevel()
        self.settings, self.save_settings = settings, save_settings
        self.percent = normalize_zoom(settings.get('chat_zoom_percent', 100))
        self.closed = False
        self._widgets, self._fonts, self._tag_fonts, self._images = {}, {}, {}, {}
        self._font_pool = {}
        self._bindings = []
        self._save_after = self._draw_after = None
        self._map_binding = self.app.bind('<Map>', self._mapped, add='+')
        self._configure_binding = self.chat.bind('<Configure>', self._resized, add='+')
        self._destroy_binding = self.chat.bind('<Destroy>', self._destroyed, add='+')
        self._discover(self.chat)
        self._apply_fonts()
        self._schedule_images()

    def _inside(self, widget):
        path = str(widget)
        return path == str(self.chat) or path.startswith(str(self.chat) + '.')

    def _enabled(self):
        guard = getattr(self.app, '_portalai_modal_guard', None)
        return not self.closed and not getattr(guard, 'surface', None)

    def _mapped(self, event):
        if not self.closed and self._inside(event.widget):
            # Text windows unmap/remap during ordinary scrolling. Reconfiguring
            # every transcript font here invalidates the whole text layout.
            if str(event.widget) not in self._widgets:
                self._discover(event.widget)
                self._schedule_images()
            elif str(event.widget) in self._images:
                self._schedule_images()

    def _resized(self, _event=None):
        if not self.closed:
            self._schedule_images()

    def _destroyed(self, event):
        if event.widget is self.chat:
            self.close()

    def _discover(self, widget):
        key = str(widget)
        if key not in self._widgets:
            self._widgets[key] = widget
            events = {'<Control-MouseWheel>': self._wheel,
                      '<Destroy>': self._forget_event,
                      '<Control-Button-4>': lambda e: self._wheel(e, 1),
                      '<Control-Button-5>': lambda e: self._wheel(e, -1),
                      '<Control-Key-plus>': lambda e: self._key(e, 1),
                      '<Control-Key-equal>': lambda e: self._key(e, 1),
                      '<Control-Key-minus>': lambda e: self._key(e, -1),
                      '<Control-Key-0>': lambda e: self._key(e, 0)}
            for event, callback in events.items():
                self._bindings.append((widget, event, widget.bind(event, callback, add='+')))
            try:
                spec = widget.cget('font')
                # ElegantButton leaves its default font implicit; copy a local
                # font instead of changing a shared ttk style or Tk named font.
                spec = spec or ('Segoe UI', 9, 'bold')
                actual = tuple(widget.tk.splitlist(widget.tk.call('font', 'actual', spec)))
                if actual not in self._font_pool:
                    base = tkfont.Font(root=self.app, font=spec)
                    size = int(base.cget('size'))
                    self._font_pool[actual] = (base, size)
                    scaled = (-1 if size < 0 else 1) * max(1, round(abs(size) * self.percent / 100))
                    if scaled != size:base.configure(size=scaled)
                base, size = self._fonts[key] = self._font_pool[actual]
                # At 100% the existing font is already correct. Changing its
                # name during Map makes Tk lay out the newly visible card again.
                if self.percent != 100:widget.configure(font=base)
            except tk.TclError:
                pass  # Frames, scrollbars and image containers have no font.
            if isinstance(widget, tk.Text) and widget is not self.chat:
                widget._portalai_zoom_base_width = int(widget.cget('width'))
            if isinstance(widget, tk.Label):
                try:
                    wrap = float(widget.winfo_pixels(str(widget.cget('wraplength'))))
                    if wrap > 0: widget._portalai_zoom_wraplength = wrap
                except (tk.TclError, ValueError): pass
            try:
                source = str(widget.cget('image') or '')
                if source and int(widget.tk.call('image', 'width', source)) * int(widget.tk.call('image', 'height', source)) <= 4_000_000:
                    self._images[key] = {'source': source, 'display': None, 'size': None}
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            self._discover(child)

    def _forget_event(self, event):
        key = str(event.widget)
        if event.widget is self.chat:
            return  # The transcript's own destroy binding closes the controller.
        self._widgets.pop(key, None)
        self._fonts.pop(key, None)
        self._images.pop(key, None)
        used = {str(font) for font, _ in self._fonts.values()}
        self._font_pool = {key:value for key,value in self._font_pool.items() if str(value[0]) in used}
        # Tk destroys the widget's callback commands itself; discard our Python
        # records too so switching a long history does not retain dead frames.
        self._bindings[:] = [row for row in self._bindings if row[0] is not event.widget]

    def _apply_fonts(self):
        applied = set()
        for key, (font, size) in list(self._fonts.items()):
            if not self._widgets[key].winfo_exists():
                self._fonts.pop(key, None)
                self._images.pop(key, None)
                self._widgets.pop(key, None)
                continue
            sign = -1 if size < 0 else 1
            if self.percent != 100 and str(self._widgets[key].cget('font')) != str(font):
                self._widgets[key].configure(font=font)
            if str(font) not in applied:
                font.configure(size=sign * max(1, round(abs(size) * self.percent / 100)))
                applied.add(str(font))
        for name in self.chat.tag_names():
            spec = self.chat.tag_cget(name, 'font')
            if spec and name not in self._tag_fonts:
                font = tkfont.Font(root=self.app, font=spec)
                self._tag_fonts[name] = (font, int(font.cget('size')))
                self.chat.tag_configure(name, font=font)
        for font, size in self._tag_fonts.values():
            font.configure(size=(-1 if size < 0 else 1) * max(1, round(abs(size) * self.percent / 100)))

    def _wheel(self, event, direction=None):
        if not self._enabled():
            return 'break'
        if direction is None:
            delta = getattr(event, 'delta', 0)
            if not delta:
                return 'break'
            direction = 1 if delta > 0 else -1
        self.set_percent(self.percent + direction * ZOOM_STEP)
        return 'break'

    def _key(self, _event, direction):
        if self._enabled():
            self.set_percent(100 if direction == 0 else self.percent + direction * ZOOM_STEP)
        return 'break'

    def set_percent(self, value):
        if not self._enabled():
            return
        value = normalize_zoom(value)
        if value == self.percent:
            return
        # Preserve the logical top line rather than jumping to the newest reply.
        anchor = self.chat.index('@0,0')
        self.percent = value
        self._discover(self.chat)
        self._apply_fonts()
        self.chat.yview(anchor)
        self._schedule_images()
        self.settings['chat_zoom_percent'] = value
        if self._save_after is not None:
            self.app.after_cancel(self._save_after)
        self._save_after = self.app.after(450, self._persist)

    def _persist(self):
        self._save_after = None
        if not self.closed:
            # ChatStore checks the captured login epoch immediately before save.
            self.save_settings()

    def add_menu(self, menu):
        menu.add_command(label='Zoom in (Ctrl + scroll up)', command=lambda: self.set_percent(self.percent + ZOOM_STEP))
        menu.add_command(label='Zoom out (Ctrl + scroll down)', command=lambda: self.set_percent(self.percent - ZOOM_STEP))
        menu.add_command(label=f'Reset chat zoom ({self.percent}%, Ctrl+0)', command=lambda: self.set_percent(100))

    def _schedule_images(self):
        if self._draw_after is None:
            self._draw_after = self.app.after(80, self._draw_images)

    def _draw_images(self):
        self._draw_after = None
        if self.closed:
            return
        available = max(80, self.chat.winfo_width() - 52)
        for key, widget in list(self._widgets.items()):
            if not widget.winfo_exists():
                self._images.pop(key, None)
                continue
            if isinstance(widget, tk.Text) and widget is not self.chat:
                font = self._fonts.get(key)
                if font:
                    width = max(8, min(widget._portalai_zoom_base_width,
                                      int((available - 40) / max(1, font[0].measure('0')))))
                    if int(widget.cget('width')) != width:
                        widget.configure(width=width)
            if hasattr(widget, '_portalai_zoom_wraplength'):
                fraction = getattr(widget, '_portalai_zoom_wrap_fraction', 1)
                wrap = max(50, min(widget._portalai_zoom_wraplength * self.percent / 100,
                                  (available - 36) * fraction))
                if float(widget.cget('wraplength')) != wrap:
                    widget.configure(wraplength=wrap)
        # At most one changed visible preview per event-loop slice. Collapsed
        # thumbnails do not allocate larger images until their panel is opened.
        for key, item in list(self._images.items()):
            widget = self._widgets[key]
            if not widget.winfo_exists() or not widget.winfo_ismapped():
                continue
            try:
                source = item['source']
                width = int(widget.tk.call('image', 'width', source))
                height = int(widget.tk.call('image', 'height', source))
                size = image_size(width, height, self.percent, available - 36)
                background = str(widget.cget('bg'))
                signature = (*size, background)
                if signature == item['size']:
                    continue
                if size == (width, height):
                    widget.configure(image=source)
                    item['display'] = None
                else:
                    # Tk exports this widget's already loaded private thumbnail;
                    # no source-file reopening, worker, capability or disk cache.
                    # Flatten transparent pixels against the actual themed
                    # label surface before PPM conversion; never turn them black.
                    data = widget.tk.call(source, 'data', '-format', 'ppm', '-background', background)
                    photo = tk.PhotoImage(master=widget, data=resize_ppm(data, *size), format='PPM')
                    widget.configure(image=photo)
                    item['display'] = photo
                item['size'] = signature
            except (tk.TclError, ValueError):
                # Leave a usable original preview rather than break chat zoom.
                self._images.pop(key, None)
            self._draw_after = self.app.after(1, self._draw_images)
            break

    def close(self):
        if self.closed:
            return
        self.closed = True
        for timer in (self._save_after, self._draw_after):
            if timer is not None:
                try: self.app.after_cancel(timer)
                except tk.TclError: pass
        self._save_after = self._draw_after = None
        for widget, event, binding in self._bindings:
            try: widget.unbind(event, binding)
            except tk.TclError: pass
        self._bindings.clear()
        for widget, event, binding in ((self.app, '<Map>', self._map_binding),
                (self.chat, '<Configure>', self._configure_binding),
                (self.chat, '<Destroy>', self._destroy_binding)):
            try: widget.unbind(event, binding)
            except tk.TclError: pass
        for key, item in self._images.items():
            try: self._widgets[key].configure(image=item['source'])
            except tk.TclError: pass
        self._images.clear()
        self._font_pool.clear()
