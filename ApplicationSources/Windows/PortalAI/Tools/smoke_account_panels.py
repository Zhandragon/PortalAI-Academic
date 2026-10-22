"""Render synthetic account panels; capture only this fixture's Windows HWND."""
import argparse
import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import struct
import sys
import time
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]


def capture_window(app,path):
    if os.name!='nt':raise RuntimeError('Pixel capture uses only the synthetic Windows fixture HWND')
    app.update_idletasks();app.update()
    time.sleep(.15);app.update()
    hwnd=app.winfo_id()
    user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
    user.GetDC.argtypes=[w.HWND];user.GetDC.restype=w.HDC
    user.ReleaseDC.argtypes=[w.HWND,w.HDC]
    user.PrintWindow.argtypes=[w.HWND,w.HDC,w.UINT];user.PrintWindow.restype=w.BOOL
    gdi.CreateCompatibleDC.argtypes=[w.HDC];gdi.CreateCompatibleDC.restype=w.HDC
    gdi.CreateCompatibleBitmap.argtypes=[w.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=w.HBITMAP
    gdi.SelectObject.argtypes=[w.HDC,w.HANDLE];gdi.SelectObject.restype=w.HANDLE
    gdi.DeleteObject.argtypes=[w.HANDLE];gdi.DeleteDC.argtypes=[w.HDC]
    gdi.GetDIBits.argtypes=[w.HDC,w.HBITMAP,w.UINT,w.UINT,ctypes.c_void_p,ctypes.c_void_p,w.UINT]
    width,height=app.winfo_width(),app.winfo_height()
    dc=user.GetDC(hwnd);memory=gdi.CreateCompatibleDC(dc)
    bitmap=gdi.CreateCompatibleBitmap(dc,width,height);previous=gdi.SelectObject(memory,bitmap)
    try:
        if not user.PrintWindow(hwnd,memory,3):raise OSError('Synthetic PrintWindow failed')
        info=ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0))
        pixels=ctypes.create_string_buffer(width*height*4)
        if gdi.GetDIBits(memory,bitmap,0,height,pixels,info,0)!=height:raise OSError('Synthetic pixels unavailable')
        raw=pixels.raw;rows=[]
        for y in range(height):
            row=raw[y*width*4:(y+1)*width*4]
            rgb=bytearray(width*3);rgb[0::3]=row[2::4];rgb[1::3]=row[1::4];rgb[2::3]=row[0::4]
            rows.append(b'\0'+rgb)
        def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))
        path.write_bytes(png+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b''))
        return {'path':str(path),'width':width,'height':height}
    finally:
        gdi.SelectObject(memory,previous);gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(hwnd,dc)


def main():
    import tkinter as tk
    import account_ui as ui
    from test_account_presentation_tk import LIGHT,DARK,fixture_controller,button,newest
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',type=Path,required=True)
    args=parser.parse_args();destination=args.artifacts_dir.resolve()
    if not destination.is_relative_to(ROOT/'Maintenance/Validation'):
        raise ValueError('Synthetic screenshots must use Maintenance/Validation')
    destination.mkdir(parents=True,exist_ok=True)
    app=tk.Tk();app.geometry('1000x780+40+40')
    controller,session=fixture_controller(ROOT);results=[]
    errors=[]
    try:
        for theme,palette,width in (('light',LIGHT,1000),('dark',DARK,1000),('narrow',LIGHT,500)):
            def render():
                try:
                    app.geometry(f'{width}x780+40+40');app.update()
                    dialog=newest(app);results.append(capture_window(app,destination/f'login-{theme}.png'))
                    dialog.close()
                except Exception as exc:
                    errors.append(exc);newest(app).close()
            app.after(180,render)
            ui.show_login(app,controller,palette,prepare_session=lambda _:None)
        app.geometry('1000x780+40+40')
        host=tk.Frame(app,bg=LIGHT['bg']);host.place(x=12,y=70,relwidth=1,width=-24,relheight=1,height=-82)
        tk.Label(app,text='PortalAI · Synthetic Controls',bg=LIGHT['bg'],fg=LIGHT['text']).place(x=20,y=20)
        app._portalai_account_host=host
        app.update()
        dialog=ui.show_accounts(host,controller,session,LIGHT)
        app.update();results.append(capture_window(app,destination/'accounts-light.png'))
        button(dialog,'Set/reset member password…').invoke();app.update()
        from account_presentation import refresh_account_theme
        refresh_account_theme(app,DARK)
        app.configure(bg=DARK['bg']);host.configure(bg=DARK['bg']);app.update()
        results.append(capture_window(app,destination/'member-dark.png'))
        if errors:raise errors[0]
        print(json.dumps({'synthetic_only':True,'production_accounts_opened':False,'screenshots':results},indent=2))
    finally:
        controller.jobs.close();controller.jobs.wait(3)
        for dialog in reversed(list(getattr(app,'_portalai_account_dialogs',()))):dialog.close()
        for timer in app.tk.call('after','info'):app.after_cancel(timer)
        app.destroy()


if __name__=='__main__':main()
