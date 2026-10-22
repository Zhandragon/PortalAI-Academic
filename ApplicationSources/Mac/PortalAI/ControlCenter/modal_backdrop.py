"""Owned-window visual snapshots, held only in memory for modal presentation."""
import os
import struct
import tkinter as tk
from dataclasses import dataclass


@dataclass(frozen=True)
class HostSnapshot:
    width: int
    height: int
    rgb: bytes


def snapshot_host(app, host, palette):
    # Visual decoration is optional; never compromise the modal input guard
    # or prevent verified sign-in/shutdown if native capture is unavailable.
    try:
        return _snapshot_host(app, host)
    except (OSError, tk.TclError, ValueError):
        return None


def _snapshot_host(app, host):
    if os.name != 'nt': return None
    import ctypes
    from ctypes import wintypes as w
    app.update_idletasks()
    width, height = app.winfo_width(), app.winfo_height()
    if width < 2 or height < 2 or width*height > 16_000_000: return None
    x, y = host.winfo_rootx()-app.winfo_rootx(), host.winfo_rooty()-app.winfo_rooty()
    hw, hh = host.winfo_width(), host.winfo_height()
    if min(x, y) < 0 or hw < 2 or hh < 2 or x+hw > width or y+hh > height: return None
    user = ctypes.WinDLL('user32', use_last_error=True)
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user.GetDC.argtypes=[w.HWND]; user.GetDC.restype=w.HDC
    user.ReleaseDC.argtypes=[w.HWND,w.HDC]
    user.PrintWindow.argtypes=[w.HWND,w.HDC,w.UINT]; user.PrintWindow.restype=w.BOOL
    user.RedrawWindow.argtypes=[w.HWND,ctypes.c_void_p,w.HANDLE,w.UINT]
    user.RedrawWindow.restype=w.BOOL
    gdi.CreateCompatibleDC.argtypes=[w.HDC]; gdi.CreateCompatibleDC.restype=w.HDC
    gdi.CreateCompatibleBitmap.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int]; gdi.CreateCompatibleBitmap.restype=w.HBITMAP
    gdi.SelectObject.argtypes=[w.HDC,w.HANDLE]; gdi.SelectObject.restype=w.HANDLE
    gdi.DeleteObject.argtypes=[w.HANDLE]; gdi.DeleteDC.argtypes=[w.HDC]
    gdi.GetDIBits.argtypes=[w.HDC,w.HBITMAP,w.UINT,w.UINT,ctypes.c_void_p,ctypes.c_void_p,w.UINT]
    hwnd=app.winfo_id(); dc=user.GetDC(hwnd)
    memory=bitmap=previous=None
    try:
        if not dc:return None
        memory=gdi.CreateCompatibleDC(dc)
        if not memory:return None
        bitmap=gdi.CreateCompatibleBitmap(dc,width,height)
        if not bitmap:return None
        previous=gdi.SelectObject(memory,bitmap)
        # Commit queued child painting without waiting for compositor timing.
        user.RedrawWindow(hwnd,None,None,0x0001|0x0100|0x0080)
        if not user.PrintWindow(hwnd,memory,3): return None
        info=ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0))
        pixels=ctypes.create_string_buffer(width*height*4)
        if gdi.GetDIBits(memory,bitmap,0,height,pixels,info,0)!=height:return None
        raw=pixels.raw; rgb=bytearray(hw*hh*3)
        for row in range(hh):
            source=raw[((y+row)*width+x)*4:((y+row)*width+x+hw)*4]
            target=bytearray(hw*3)
            target[0::3]=source[2::4]; target[1::3]=source[1::4]; target[2::3]=source[0::4]
            rgb[row*hw*3:(row+1)*hw*3]=target
        return HostSnapshot(hw,hh,bytes(rgb))
    finally:
        if previous:gdi.SelectObject(memory,previous)
        if bitmap:gdi.DeleteObject(bitmap)
        if memory:gdi.DeleteDC(memory)
        if dc:user.ReleaseDC(hwnd,dc)


def dim_color(color):
    if len(color)==7 and color.startswith('#'):
        return '#'+''.join(f'{round(int(color[i:i+2],16)*.58):02x}' for i in (1,3,5))
    return '#202123'


class DimBackdrop:
    def __init__(self, parent, snapshot, palette):
        self.widget=tk.Canvas(parent, bd=0, highlightthickness=0, takefocus=0, cursor='arrow')
        self.widget.place(x=0,y=0,relwidth=1,relheight=1)
        self.snapshot=snapshot; self.photo=None; self.palette=dict(palette)
        if snapshot is not None:
            # bytes.translate is bounded native code; no Python per-pixel loops.
            rgb=snapshot.rgb.translate(bytes(round(i*.58) for i in range(256)))
            self.photo=tk.PhotoImage(master=parent, data=f'P6\n{snapshot.width} {snapshot.height}\n255\n'.encode()+rgb, format='PPM')
        self.widget.bind('<Configure>', lambda event:self.resize(event.width,event.height))
        self.apply_palette(palette)

    def resize(self, width, height):
        self.widget.delete('all')
        if self.photo is not None:
            self.widget.create_image(0,0,image=self.photo,anchor='nw')
        else:
            self.widget.create_text(32,42,text='PortalAI · Control Center',anchor='nw',
                                    fill=self.palette.get('gold_shine','#D6BA70'),font=('Georgia',22,'bold'))
            self.widget.create_text(32,94,text='Welcome to PortalAI',anchor='nw',
                                    fill=self.palette.get('muted','#B7AFA4'),font=('Georgia',13))

    def apply_palette(self, palette):
        self.palette=dict(palette)
        self.widget.configure(bg=dim_color(palette.get('bg','#202123')))
        self.resize(self.widget.winfo_width(),self.widget.winfo_height())

    def close(self):
        self.snapshot=None; self.photo=None; self.widget.destroy()
