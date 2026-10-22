"""Passive, theme-aware page branding; never participates in content layout."""
import ctypes
import os
from pathlib import Path
import tkinter as tk

def watermark_size(width, height, *, opaque=False):
    """Hide decorative artwork before it dominates a compact viewport."""
    if width < (580 if opaque else 780) or height < (330 if opaque else 420): return 0
    return 196 if width >= 1050 and height >= 560 else 144

class PageWatermark:
    def __init__(self, app, pages, images, mode_getter, selected_getter):
        self.app, self.pages, self.images = app, pages, images
        self.mode_getter, self.selected_getter = mode_getter, selected_getter
        self.win = self.label = None
        self.timer = None
        self.closed = False
        self.key = self.geometry = None
        self.shown = False
        self.backgrounds = {}
        self._alpha_signature = None
        for size in (128, 180):
            source = Path(__file__).resolve().parent/'Branding'/f'PortalAI_Emblem_HeroClean_{size}.png'
            if source.is_file():
                self.images[f'help{size}'] = tk.PhotoImage(master=app, file=str(source))
        if os.name == 'nt':
            self.win = tk.Toplevel(app)
            self.win.withdraw(); self.win.overrideredirect(True)
            self.win.configure(bg='#010203')
            self.win.attributes('-transparentcolor', '#010203')
            self.win.transient(app)
            self.label = tk.Label(self.win, bg='#010203', bd=0, highlightthickness=0, takefocus=0)
            self.label.pack(fill='both', expand=True)
        else:
            # A real background below the content on non-Windows desktops. Do not
            # create an input-capturing transparent window without an input shape.
            for name, page in pages.items():
                canvas = tk.Canvas(page, bd=0, highlightthickness=0, takefocus=0)
                item = canvas.create_image(0, 0, anchor='se')
                self.backgrounds[name] = (canvas, item)
        self._destroy_binding = app.bind('<Destroy>', self._destroyed, add='+')
        self.refresh()

    def _clickthrough(self):
        from ctypes import wintypes as w
        user = ctypes.WinDLL('user32', use_last_error=True)
        user.GetAncestor.argtypes = [w.HWND, w.UINT]; user.GetAncestor.restype = w.HWND
        get = user.GetWindowLongPtrW; set_ = user.SetWindowLongPtrW
        get.argtypes = [w.HWND, ctypes.c_int]; get.restype = ctypes.c_ssize_t
        set_.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]; set_.restype = ctypes.c_ssize_t
        hwnd = user.GetAncestor(self.win.winfo_id(), 2)
        flags = 0x20 | 0x80 | 0x08000000  # transparent input, tool window, no activation
        set_(hwnd, -20, (get(hwnd, -20) | flags) & ~0x40000)
        if get(hwnd, -20) & flags != flags:
            raise OSError('Passive watermark window styles unavailable')

    def hide(self):
        self._alpha_signature = None
        if self.win is not None: self.win.withdraw()
        for canvas, _ in self.backgrounds.values(): canvas.place_forget()
        self.shown = False

    def _covered(self, page):
        if getattr(self.app, '_portalai_account_lock_cover', None) is not None: return True
        if any(not getattr(d, 'closed', True) for d in getattr(self.app, '_portalai_account_dialogs', ())): return True
        # Integrated menus sit beside the tab pages within their common host.
        from internal_sheet import InternalSheet
        return any((isinstance(c, InternalSheet) or getattr(c,'_portalai_launcher_sheet',False)) and c.winfo_ismapped() for c in page.master.winfo_children())

    def refresh(self):
        if self.closed: return
        if self.timer is not None:
            self.app.after_cancel(self.timer); self.timer = None
        try:
            name = self.selected_getter(); page = self.pages.get(name)
            if (page is None or not page.winfo_ismapped() or not self.app.winfo_viewable()
                    or self._covered(page) or page.winfo_width() < 460 or page.winfo_height() < 260):
                self.hide(); return
            size = watermark_size(page.winfo_width(), page.winfo_height(), opaque=name=='help')
            if not size: self.hide(); return
            mode = 'dark' if self.mode_getter() == 'dark' else 'light'
            key = f'chatwm_{mode}{size}'
            if name == 'help' and f'help{180 if size == 196 else 128}' in self.images:
                size = 180 if size == 196 else 128
                key = f'help{size}'
            img = self.images.get(key)
            if img is None: self.hide(); return
            if self.win is None:
                canvas, item = self.backgrounds[name]
                canvas.configure(bg=page.cget('bg'))
                canvas.itemconfigure(item, image=img); canvas.coords(item, size, size)
                canvas.place(relx=1, rely=1, x=-22, y=-22, width=size, height=size, anchor='se')
                canvas.tk.call('lower', canvas._w)
                self.key = key; self.shown = True
                return
            if self.key != key:
                self.label.configure(image=img)
                self.key = key
            if name != 'help':
                self.win.attributes('-transparentcolor', '#010203')
                self.win.attributes('-alpha', .22 if mode == 'dark' else .18)
                self._alpha_signature = None
            elif self._alpha_signature is None:
                self.win.attributes('-alpha', 1.)
            geom = f'{size}x{size}+{page.winfo_rootx()+page.winfo_width()-size-26}+{page.winfo_rooty()+page.winfo_height()-size-22}'
            if self.geometry != geom:
                self.win.geometry(geom); self.geometry = geom
            if not self.shown:
                self.win.update_idletasks(); self._clickthrough()
                self.win.deiconify(); self._clickthrough(); self.win.lift()
                self.shown = True
            if name == 'help':
                signature = (key, geom)
                if signature != self._alpha_signature:
                    self.win.update_idletasks()
                    from alpha_watermark import paint
                    paint(self.win, img)
                    self._alpha_signature = signature
        except (tk.TclError, OSError):
            self.hide()
        finally:
            if not self.closed: self.timer = self.app.after(220, self.refresh)

    def apply_palette(self, _palette=None):
        self.key = None
        self._alpha_signature = None
        self.refresh()

    def _destroyed(self, event):
        if event.widget is self.app: self.close()

    def close(self):
        if self.closed: return
        self.closed = True
        if self.timer is not None:
            self.app.after_cancel(self.timer); self.timer = None
        if self.win is not None:
            try: self.win.destroy()
            except tk.TclError: pass
        self.win = None
