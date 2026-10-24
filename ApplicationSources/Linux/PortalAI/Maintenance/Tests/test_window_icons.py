"""Read back real native icon pixels and exercise Tk wrapper lifetimes."""
import ctypes
from ctypes import wintypes as w
import os
from pathlib import Path
import sys
import tkinter as tk
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ControlCenter'))
import window_icons


@unittest.skipUnless(os.name == 'nt', 'Windows native icon tests')
class WindowIconTests(unittest.TestCase):
    def setUp(self):
        self.app = tk.Tk()
        self.app.withdraw()
        self.path = ROOT / 'ControlCenter/PortableAI.ico'
        self.app.iconbitmap(default=str(self.path))
        self.app.geometry('320x180+30000+30000')
        self.app.overrideredirect(True)
        self.app.deiconify()
        self.app.update()
        self.u = ctypes.WinDLL('user32')
        self.g = ctypes.WinDLL('gdi32')
        for name, args, result in (
            ('GetAncestor', [w.HWND, w.UINT], w.HWND),
            ('GetDpiForWindow', [w.HWND], w.UINT),
            ('GetClassLongPtrW', [w.HWND, ctypes.c_int], ctypes.c_size_t),
            ('SendMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], ctypes.c_ssize_t),
            ('PostMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
            ('IsIconic', [w.HWND], w.BOOL),
        ):
            f = getattr(self.u, name); f.argtypes = args; f.restype = result

    def tearDown(self):
        self.app.destroy()

    def hwnd(self):
        return self.u.GetAncestor(self.app.winfo_id(), 2)

    def icon(self, kind):
        return self.u.SendMessageW(self.hwnd(), 0x7F, kind, 0)

    def size(self, handle):
        class IconInfo(ctypes.Structure):
            _fields_ = [('icon', w.BOOL), ('x', w.DWORD), ('y', w.DWORD),
                        ('mask', w.HBITMAP), ('color', w.HBITMAP)]
        class Bitmap(ctypes.Structure):
            _fields_ = [('type', w.LONG), ('width', w.LONG), ('height', w.LONG),
                        ('stride', w.LONG), ('planes', w.WORD), ('bits', w.WORD),
                        ('data', ctypes.c_void_p)]
        self.u.GetIconInfo.argtypes = [w.HICON, ctypes.POINTER(IconInfo)]
        self.u.GetIconInfo.restype = w.BOOL
        self.g.GetObjectW.argtypes = [w.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
        self.g.GetObjectW.restype = ctypes.c_int
        self.g.DeleteObject.argtypes = [w.HGDIOBJ]; self.g.DeleteObject.restype = w.BOOL
        info = IconInfo(); bitmap = Bitmap()
        if not handle or not self.u.GetIconInfo(handle, ctypes.byref(info)):
            return None
        try:
            self.assertTrue(self.g.GetObjectW(info.color, ctypes.sizeof(bitmap), ctypes.byref(bitmap)))
            return bitmap.width, bitmap.height
        finally:
            for part in (info.mask, info.color):
                if part: self.g.DeleteObject(part)

    def install(self):
        icons = window_icons.install(self.app, self.path)
        self.assertIsNotNone(icons)
        self.app.update()
        return icons

    def assert_sharp(self):
        self.assertEqual(self.size(self.icon(1)), (256, 256))
        self.assertEqual(self.size(self.icon(0)), (64, 64))

    def test_explicit_native_icons_replace_small_class_fallback(self):
        self.assertEqual(self.size(self.u.GetClassLongPtrW(self.hwnd(), -14)), (32, 32))
        self.install()
        self.assert_sharp()

    def test_native_wrapper_recreation_and_remapping_retains_detail(self):
        self.install()
        for i in range(12):
            self.app.withdraw(); self.app.overrideredirect(bool(i % 2))
            self.app.deiconify(); self.app.update()
            self.assert_sharp()

    def test_resize_reuses_handles_without_changing_dpi_or_window_size(self):
        dpi = self.u.GetDpiForWindow(self.hwnd())
        self.install(); handles = self.icon(1), self.icon(0)
        for i in range(20):
            width = 320 + i
            self.app.geometry(f'{width}x180+30000+30000'); self.app.update()
            self.assertEqual((self.icon(1), self.icon(0)), handles)
            self.assertEqual(self.app.winfo_width(), width)
        self.assertEqual(self.u.GetDpiForWindow(self.hwnd()), dpi)

    def test_release_destroys_only_its_own_icons(self):
        class_icon = self.u.GetClassLongPtrW(self.hwnd(), -14)
        icons = self.install(); handles = self.icon(1), self.icon(0)
        icons.close(); icons.close()
        self.assertTrue(all(self.size(handle) is None for handle in handles))
        self.assertEqual(self.size(class_icon), (32, 32))
        self.app.update()

    def test_missing_artwork_leaves_working_tk_fallback(self):
        class_icon = self.u.GetClassLongPtrW(self.hwnd(), -14)
        self.assertIsNone(window_icons.install(self.app, self.path.with_name('missing-icon.ico')))
        self.app.update()
        self.assertEqual(self.size(class_icon), (32, 32))

    def test_repeated_install_reuses_the_same_controller(self):
        icons = self.install()
        self.assertIs(window_icons.install(self.app, self.path), icons)
        self.assert_sharp()

    def test_real_drop_hook_and_queued_minimize_restore_keep_icons(self):
        from native_chat import WindowsFileDrop
        self.install()
        target = tk.Frame(self.app); target.pack(fill='both', expand=True)
        self.app.update()
        drop = WindowsFileDrop(self.app, target, lambda _paths: None)
        self.assertTrue(drop.enabled)
        errors = []; self.app.report_callback_exception = lambda t, v, tb: errors.append(str(v))
        cycles = []
        def minimize():
            self.u.PostMessageW(self.hwnd(), 0x112, 0xF020, 0)
            self.app.after(60, restore)
        def restore():
            cycles.append(bool(self.u.IsIconic(self.hwnd())))
            self.app.deiconify(); self.app.state('normal')
            if len(cycles) < 6: self.app.after(60, minimize)
            else: self.app.after(60, self.app.quit)
        timeout = self.app.after(7000, self.app.quit)
        try:
            self.app.after(60, minimize); self.app.mainloop()
            self.app.after_cancel(timeout)
            self.assertEqual(cycles, [True] * 6)
            self.assertEqual(errors, [])
            self.assert_sharp()
        finally:
            drop.close()


if __name__ == '__main__':
    unittest.main()
