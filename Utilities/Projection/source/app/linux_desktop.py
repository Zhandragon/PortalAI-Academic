"""Capture owned Tk X11/XWayland client windows, never the desktop drawable."""
import ctypes as c
import http.client
import json
import os
from pathlib import Path
import struct
import threading
import uuid
import zlib

MODULE=Path(__file__).resolve().parents[1]

class XImage(c.Structure):
    _fields_=[('width',c.c_int),('height',c.c_int),('xoffset',c.c_int),('format',c.c_int),('data',c.c_void_p),
        ('byte_order',c.c_int),('bitmap_unit',c.c_int),('bitmap_bit_order',c.c_int),('bitmap_pad',c.c_int),
        ('depth',c.c_int),('bytes_per_line',c.c_int),('bits_per_pixel',c.c_int),('red_mask',c.c_ulong),
        ('green_mask',c.c_ulong),('blue_mask',c.c_ulong),('obdata',c.c_void_p),('functions',c.c_void_p*6)]

class Visual(c.Structure):
    _fields_=[('ext_data',c.c_void_p),('visualid',c.c_ulong),('visual_class',c.c_int),('red_mask',c.c_ulong),
        ('green_mask',c.c_ulong),('blue_mask',c.c_ulong),('bits_per_rgb',c.c_int),('map_entries',c.c_int)]

class Attributes(c.Structure):
    _fields_=[('x',c.c_int),('y',c.c_int),('width',c.c_int),('height',c.c_int),('border_width',c.c_int),('depth',c.c_int),
        ('visual',c.POINTER(Visual)),('root',c.c_ulong),('window_class',c.c_int),('bit_gravity',c.c_int),('win_gravity',c.c_int),
        ('backing_store',c.c_int),('backing_planes',c.c_ulong),('backing_pixel',c.c_ulong),('save_under',c.c_int),
        ('colormap',c.c_ulong),('map_installed',c.c_int),('map_state',c.c_int),('all_event_masks',c.c_long),
        ('your_event_mask',c.c_long),('do_not_propagate_mask',c.c_long),('override_redirect',c.c_int),('screen',c.c_void_p)]

def png(data,width,height):
    def chunk(kind,value):return struct.pack('>I',len(value))+kind+value+struct.pack('>I',zlib.crc32(kind+value)&0xffffffff)
    scan=b''.join(b'\0'+data[y*width*3:(y+1)*width*3] for y in range(height))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan,3))+chunk(b'IEND',b'')

class Desktop:
    def __init__(self,manager):
        if not os.environ.get('DISPLAY'):raise RuntimeError('Linux projection requires an X11 or XWayland desktop session (DISPLAY)')
        self.manager=manager;self.u=self;self.lock=threading.Lock();self.redirected=set()
        native=MODULE/'Runtime/LinuxNative'
        self.x=c.CDLL(str(native/'libX11.so.6'));self.comp=c.CDLL(str(native/'libXcomposite.so.1'))
        def bind(lib,name,args,result):
            fn=getattr(lib,name);fn.argtypes=args;fn.restype=result;return fn
        ptr=c.c_void_p;window=c.c_ulong
        bind(self.x,'XInitThreads',[],c.c_int)()
        bind(self.x,'XOpenDisplay',[c.c_char_p],ptr)
        bind(self.x,'XSync',[ptr,c.c_int],c.c_int)
        bind(self.x,'XFreePixmap',[ptr,window],c.c_int)
        bind(self.x,'XGetWindowAttributes',[ptr,window,c.POINTER(Attributes)],c.c_int)
        bind(self.x,'XGetImage',[ptr,window,c.c_int,c.c_int,c.c_uint,c.c_uint,window,c.c_int],c.POINTER(XImage))
        bind(self.x,'XDestroyImage',[c.POINTER(XImage)],c.c_int)
        bind(self.comp,'XCompositeQueryVersion',[ptr,c.POINTER(c.c_int),c.POINTER(c.c_int)],c.c_int)
        bind(self.comp,'XCompositeRedirectWindow',[ptr,window,c.c_int],None)
        bind(self.comp,'XCompositeNameWindowPixmap',[ptr,window],window)
        # X errors must fail this frame rather than exit the independent host.
        callback=c.CFUNCTYPE(c.c_int,ptr,ptr)
        self.error_callback=callback(self._error)
        bind(self.x,'XSetErrorHandler',[callback],ptr)(self.error_callback)
        self.display=self.x.XOpenDisplay(None)
        if not self.display:raise RuntimeError('Cannot open the current user X11 display; no access-control changes were made')
        major=c.c_int();minor=c.c_int()
        if not self.comp.XCompositeQueryVersion(self.display,c.byref(major),c.byref(minor)) or (major.value,minor.value)<(0,2):raise RuntimeError('XComposite 0.2 or newer is required for isolated window capture')

    def _error(self,*_):self.error=True;return 0

    def request(self,window,event):
        endpoint=self.manager.endpoint(window)
        conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=7)
        try:
            body=json.dumps({'hwnd':window.get('hwnd',endpoint['hwnd']),'event':event,'request_id':uuid.uuid4().hex})
            conn.request('POST','/input',body,{'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
            response=conn.getresponse();data=response.read(65537)
            if len(data)>65536:raise RuntimeError('GUI inspection exceeds limit')
            value=json.loads(data)
            if response.status!=200:raise RuntimeError(value.get('error','GUI input refused'))
            return value
        finally:conn.close()

    def windows(self,rows):
        result=[]
        for pid,row in rows.items():
            try:
                windows=self.request(row,{'kind':'inspect'})['windows']
                if not isinstance(windows,list) or len(windows)>128:raise ValueError('Invalid owned windows')
                for window in windows:
                    result.append({**window,'pid':pid,'start':row['start'],'executable':row['executable']})
            except (FileNotFoundError,ConnectionError,TimeoutError):continue
        return result

    def validate(self,window):
        from linux_process import identity
        row=identity(window['pid'])
        if row['uid']!=os.getuid() or row['start_ticks']!=window['start'] or row['executable']!=window['executable']:
            raise RuntimeError('GUI process identity changed')
        if not Path(row['executable']).is_relative_to(self.manager.root):raise RuntimeError('GUI is outside this portable root')

    def focused_window(self,windows):
        return next((w['hwnd'] for w in windows if w.get('popup')),None) or next((w['hwnd'] for w in windows if w.get('focused')),None)
    def GetForegroundWindow(self):return 0
    def GetLastActivePopup(self,hwnd):return hwnd
    def close(self,window):self.validate(window);self.request(window,{'kind':'close'})

    def capture(self,window):
        with self.lock:
            self.validate(window);width,height=window['width'],window['height']
            if not 1<=width<=2560 or not 1<=height<=1600:raise ValueError('Resize PortalAI below 2560 x 1600 before capture')
            self.x.XSync(self.display,0);self.error=False
            attrs=Attributes()
            if not self.x.XGetWindowAttributes(self.display,window['hwnd'],c.byref(attrs)) or not attrs.visual:raise RuntimeError('Owned X11 visual is unavailable')
            visual=attrs.visual.contents
            if attrs.map_state!=2 or attrs.width!=width or attrs.height!=height:raise RuntimeError('Window changed during capture; refresh required')
            if visual.visual_class!=4 or (visual.red_mask,visual.green_mask,visual.blue_mask)!=(0xff0000,0xff00,0xff):raise RuntimeError('Linux capture requires a standard TrueColor visual')
            identity=(window['pid'],window['start'],window['hwnd'])
            if identity not in self.redirected:
                self.comp.XCompositeRedirectWindow(self.display,window['hwnd'],0);self.x.XSync(self.display,0)
                if self.error:raise RuntimeError('XComposite could not redirect the owned window')
                self.redirected.add(identity)
            pixmap=self.comp.XCompositeNameWindowPixmap(self.display,window['hwnd']);self.x.XSync(self.display,0)
            if self.error or not pixmap:raise RuntimeError('Owned window is unavailable for capture')
            picture=None
            try:
                picture=self.x.XGetImage(self.display,pixmap,0,0,width,height,c.c_ulong(-1).value,2);self.x.XSync(self.display,0)
                if self.error or not picture:raise RuntimeError('Owned window capture failed')
                info=picture.contents
                # A named pixmap has no visual: XGetImage may return zero
                # color masks. Use the original owned window's actual visual.
                if info.bits_per_pixel!=32 or info.byte_order!=0 or info.depth not in (24,32) or info.depth!=attrs.depth:raise RuntimeError('Linux capture currently requires a 24/32-bit TrueColor display')
                if not width*4<=info.bytes_per_line<=width*4+4096:raise RuntimeError('Unexpected X image stride')
                raw=c.string_at(info.data,info.bytes_per_line*height)
                packed=b''.join(raw[y*info.bytes_per_line:y*info.bytes_per_line+width*4] for y in range(height))
                rgb=bytearray(width*height*3);rgb[0::3]=packed[2::4];rgb[1::3]=packed[1::4];rgb[2::3]=packed[0::4]
                self.validate(window)
                return png(rgb,width,height),width,height
            finally:
                if picture:self.x.XDestroyImage(picture)
                self.x.XFreePixmap(self.display,pixmap)
