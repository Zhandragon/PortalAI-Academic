"""Per-pixel Windows composition of existing Tk PNGs, without a color key."""
import ctypes
from ctypes import wintypes as w
import re


def premultiplied_bgra(photo):
    """Recover alpha from Tk's black/white composites; no image dependency."""
    exports = [photo.tk.call(str(photo), 'data', '-format', 'ppm', '-background', bg)
               for bg in ('#000000', '#ffffff')]
    pixels = []
    width, height = photo.width(), photo.height()
    if width * height > 1024**2:
        raise ValueError('Brand image exceeds the overlay limit')
    for data in exports:
        header = re.match(rb'P6\s+(\d+)\s+(\d+)\s+255\s', data)
        if not header or tuple(map(int, header.groups())) != (width, height):
            raise ValueError('Unexpected Tk brand export')
        row = data[header.end():]
        if len(row) != width * height * 3:
            raise ValueError('Incomplete Tk brand export')
        pixels.append(row)
    black, white = pixels
    out = bytearray(width * height * 4)
    for i in range(width * height):
        r, g, b = black[i*3:i*3+3]
        alpha = 255 - max(0, min(255, white[i*3] - r))
        out[i*4:i*4+4] = bytes((b, g, r, alpha))
    return width, height, bytes(out)


def paint(window, photo):
    """Update only the caller's passive layered HWND; release every GDI object."""
    width, height, data = premultiplied_bgra(photo)
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    class Header(ctypes.Structure):
        _fields_ = [('size', w.DWORD), ('width', w.LONG), ('height', w.LONG),
                    ('planes', w.WORD), ('bits', w.WORD), ('compression', w.DWORD),
                    ('bytes', w.DWORD), ('x', w.LONG), ('y', w.LONG),
                    ('used', w.DWORD), ('important', w.DWORD)]
    class Blend(ctypes.Structure):
        _fields_ = [('operation', ctypes.c_ubyte), ('flags', ctypes.c_ubyte),
                    ('alpha', ctypes.c_ubyte), ('format', ctypes.c_ubyte)]
    user.GetAncestor.argtypes = [w.HWND, w.UINT]; user.GetAncestor.restype = w.HWND
    user.GetDC.argtypes = [w.HWND]; user.GetDC.restype = w.HDC
    user.ReleaseDC.argtypes = [w.HWND, w.HDC]
    get, set_ = user.GetWindowLongPtrW, user.SetWindowLongPtrW
    get.argtypes = [w.HWND, ctypes.c_int]; get.restype = ctypes.c_ssize_t
    set_.argtypes = [w.HWND, ctypes.c_int, ctypes.c_ssize_t]; set_.restype = ctypes.c_ssize_t
    gdi.CreateCompatibleDC.argtypes = [w.HDC]; gdi.CreateCompatibleDC.restype = w.HDC
    gdi.CreateDIBSection.argtypes = [w.HDC, ctypes.POINTER(Header), w.UINT,
                                  ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
    gdi.CreateDIBSection.restype = w.HBITMAP
    gdi.SelectObject.argtypes = [w.HDC, w.HANDLE]; gdi.SelectObject.restype = w.HANDLE
    gdi.DeleteObject.argtypes = [w.HANDLE]; gdi.DeleteDC.argtypes = [w.HDC]
    user.UpdateLayeredWindow.argtypes = [w.HWND, w.HDC, ctypes.POINTER(w.POINT), ctypes.POINTER(w.SIZE),
        w.HDC, ctypes.POINTER(w.POINT), w.DWORD, ctypes.POINTER(Blend), w.DWORD]
    user.UpdateLayeredWindow.restype = w.BOOL
    hwnd = user.GetAncestor(window.winfo_id(), 2)
    screen = user.GetDC(None); memory = gdi.CreateCompatibleDC(screen)
    bitmap = old = None
    try:
        header = Header(ctypes.sizeof(Header), width, -height, 1, 32, 0, len(data), 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(memory, ctypes.byref(header), 0, ctypes.byref(bits), None, 0)
        if not bitmap or not bits.value:
            raise ctypes.WinError(ctypes.get_last_error())
        ctypes.memmove(bits, data, len(data))
        old = gdi.SelectObject(memory, bitmap)
        style = get(hwnd, -20)
        # SetLayeredWindowAttributes (Tk alpha/color-key) and ULW cannot mix.
        set_(hwnd, -20, style & ~0x80000)
        set_(hwnd, -20, style | 0x80000)
        position = w.POINT(window.winfo_rootx(), window.winfo_rooty())
        size = w.SIZE(width, height); origin = w.POINT(0, 0); blend = Blend(0, 0, 255, 1)
        if not user.UpdateLayeredWindow(hwnd, screen, ctypes.byref(position), ctypes.byref(size),
                memory, ctypes.byref(origin), 0, ctypes.byref(blend), 2):
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        if old: gdi.SelectObject(memory, old)
        if bitmap: gdi.DeleteObject(bitmap)
        if memory: gdi.DeleteDC(memory)
        if screen: user.ReleaseDC(None, screen)
