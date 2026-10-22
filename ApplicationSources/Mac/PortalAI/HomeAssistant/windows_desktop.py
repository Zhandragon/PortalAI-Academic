"""Window-scoped Windows transport. No whole-desktop capture or global input."""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import struct
import zlib


def png_rgb(raw, width, height):
    rows = []
    for y in range(height):
        row = raw[y*width*4:(y+1)*width*4]
        rgb = bytearray(width*3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
        rows.append(b'\0'+rgb)
    def chunk(tag, data):
        return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows),3))+chunk(b'IEND',b'')


class Desktop:
    def __init__(self):
        self.u=c.WinDLL('user32',use_last_error=True)
        self.g=c.WinDLL('gdi32',use_last_error=True)
        signatures={
            'GetWindowThreadProcessId':([w.HWND,c.POINTER(w.DWORD)],w.DWORD),
            'IsWindowVisible':([w.HWND],w.BOOL),'IsWindow':([w.HWND],w.BOOL),
            'GetWindowTextW':([w.HWND,w.LPWSTR,c.c_int],c.c_int),
            'GetClassNameW':([w.HWND,w.LPWSTR,c.c_int],c.c_int),
            'GetClientRect':([w.HWND,c.POINTER(w.RECT)],w.BOOL),
            'GetWindowRect':([w.HWND,c.POINTER(w.RECT)],w.BOOL),
            'GetLastActivePopup':([w.HWND],w.HWND),
            'GetForegroundWindow':([],w.HWND),
            'GetAncestor':([w.HWND,w.UINT],w.HWND),
            'ChildWindowFromPointEx':([w.HWND,w.POINT,w.UINT],w.HWND),
            'ClientToScreen':([w.HWND,c.POINTER(w.POINT)],w.BOOL),
            'ScreenToClient':([w.HWND,c.POINTER(w.POINT)],w.BOOL),
            'PostMessageW':([w.HWND,w.UINT,w.WPARAM,w.LPARAM],w.BOOL),
            'SetWindowPos':([w.HWND,w.HWND,c.c_int,c.c_int,c.c_int,c.c_int,w.UINT],w.BOOL),
            'ShowWindowAsync':([w.HWND,c.c_int],w.BOOL),
            'GetDC':([w.HWND],w.HDC),'ReleaseDC':([w.HWND,w.HDC],c.c_int),
            'PrintWindow':([w.HWND,w.HDC,w.UINT],w.BOOL),
        }
        for name,(args,result) in signatures.items():
            fn=getattr(self.u,name);fn.argtypes=args;fn.restype=result
        for name,args,result in (
            ('CreateCompatibleDC',[w.HDC],w.HDC),('CreateCompatibleBitmap',[w.HDC,c.c_int,c.c_int],w.HBITMAP),
            ('SelectObject',[w.HDC,w.HANDLE],w.HANDLE),('DeleteObject',[w.HANDLE],w.BOOL),
            ('DeleteDC',[w.HDC],w.BOOL),('GetDIBits',[w.HDC,w.HBITMAP,w.UINT,w.UINT,c.c_void_p,c.c_void_p,w.UINT],c.c_int)):
            fn=getattr(self.g,name);fn.argtypes=args;fn.restype=result
        self.callback=c.WINFUNCTYPE(w.BOOL,w.HWND,w.LPARAM)
        self.u.EnumWindows.argtypes=[self.callback,w.LPARAM]

    def pid(self, hwnd):
        pid=w.DWORD();self.u.GetWindowThreadProcessId(hwnd,c.byref(pid));return pid.value

    def windows(self, rows):
        result=[]
        @self.callback
        def visit(hwnd,_):
            pid=self.pid(hwnd)
            if pid not in rows:return True
            name=c.create_unicode_buffer(256);self.u.GetClassNameW(hwnd,name,256)
            rect=w.RECT();self.u.GetClientRect(hwnd,c.byref(rect))
            if rect.right<80 or rect.bottom<30:return True
            # Do not expose hidden memory windows, tray helpers or Python tools.
            if not self.u.IsWindowVisible(hwnd) and name.value!='TkTopLevel':return True
            title=c.create_unicode_buffer(256);self.u.GetWindowTextW(hwnd,title,256)
            result.append({'hwnd':int(hwnd),'pid':pid,'start':rows[pid]['start'],
                           'title':title.value or 'PortalAI dialog','width':rect.right,'height':rect.bottom,
                           'class':name.value,'visible':bool(self.u.IsWindowVisible(hwnd))})
            return True
        self.u.EnumWindows(visit,0)
        return result

    def validate(self, window):
        if not self.u.IsWindow(window['hwnd']) or self.pid(window['hwnd'])!=window['pid']:
            raise RuntimeError('Window ended; refresh the viewer')
        # Kernel-recorded identity, not a cached PID or title.
        from profile_shutdown import _windows_image
        image=_windows_image(window['pid'])
        if not image or Path(image).resolve()!=Path(window['executable']).resolve():
            raise RuntimeError('Window process changed')
        kernel=c.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
        kernel.GetProcessTimes.argtypes=[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)]
        kernel.CloseHandle.argtypes=[w.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,window['pid'])
        if not handle:raise RuntimeError('Window identity unavailable')
        try:
            times=[w.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]):raise RuntimeError('Window identity unavailable')
            if ((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)//10!=window['start']//10:
                raise RuntimeError('Window process was replaced')
        finally:kernel.CloseHandle(handle)

    def capture(self, window):
        self.validate(window);hwnd=window['hwnd']
        rect=w.RECT();self.u.GetClientRect(hwnd,c.byref(rect));width,height=rect.right,rect.bottom
        if not 80<=width<=2560 or not 30<=height<=1600:raise ValueError('Window exceeds the bounded capture size')
        dc=self.u.GetDC(hwnd);memory=self.g.CreateCompatibleDC(dc)
        bitmap=self.g.CreateCompatibleBitmap(dc,width,height);previous=self.g.SelectObject(memory,bitmap)
        try:
            if not self.u.PrintWindow(hwnd,memory,3):raise RuntimeError('Window capture unavailable')
            self.g.SelectObject(memory,previous)
            info=c.create_string_buffer(struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0))
            pixels=c.create_string_buffer(width*height*4)
            if self.g.GetDIBits(memory,bitmap,0,height,pixels,info,0)!=height:raise RuntimeError('Window pixels unavailable')
            self.validate(window)
            return png_rgb(pixels.raw,width,height),width,height
        finally:
            self.g.SelectObject(memory,previous);self.g.DeleteObject(bitmap);self.g.DeleteDC(memory);self.u.ReleaseDC(hwnd,dc)

    def _post(self, hwnd, message, wp=0, lp=0):
        if not self.u.PostMessageW(hwnd,message,wp,lp):raise RuntimeError('Window input refused')

    def close(self, window):
        self.validate(window);self._post(window['hwnd'],0x10)  # Real WM_CLOSE lifecycle.

    def input(self, window, event):
        self.validate(window);hwnd=window['hwnd'];kind=event.get('kind')
        if kind=='resize':
            width=max(500,min(1920,int(event['width'])));height=max(400,min(1200,int(event['height'])))
            if window['class']!='TkTopLevel':raise ValueError('Resize the main PortalAI window')
            self.u.ShowWindowAsync(hwnd,9)
            if not self.u.SetWindowPos(hwnd,None,0,0,width,height,0x16):raise RuntimeError('Resize unavailable')
            return
        if kind in ('pointer','wheel'):
            rect=w.RECT();self.u.GetClientRect(hwnd,c.byref(rect))
            x,y=int(event['x']),int(event['y'])
            if not 0<=x<rect.right or not 0<=y<rect.bottom:raise ValueError('Pointer outside captured window')
            screen=w.POINT(x,y);self.u.ClientToScreen(hwnd,c.byref(screen));target=hwnd
            for _ in range(32):
                point=w.POINT(screen.x,screen.y);self.u.ScreenToClient(target,c.byref(point))
                child=self.u.ChildWindowFromPointEx(target,point,7)
                if not child or child==target:break
                if self.pid(child)!=window['pid']:raise RuntimeError('Child window ownership changed')
                target=child
            point=w.POINT(screen.x,screen.y);self.u.ScreenToClient(target,c.byref(point))
            packed=(point.x&0xffff)|((point.y&0xffff)<<16)
            if kind=='wheel':
                delta=120 if int(event['delta'])>0 else -120
                self._post(target,0x20a,(delta&0xffff)<<16,(screen.x&0xffff)|((screen.y&0xffff)<<16))
            else:
                action=event.get('action');right=event.get('button')==2
                message={'down':0x204 if right else 0x201,'up':0x205 if right else 0x202,'move':0x200}.get(action)
                if message is None:raise ValueError('Unknown pointer action')
                self._post(target,message,(2 if right else 1) if action in ('down','move') else 0,packed)
            return
        class GUIInfo(c.Structure):
            _fields_=[('size',w.DWORD),('flags',w.DWORD),('active',w.HWND),('focus',w.HWND),('capture',w.HWND),('menu',w.HWND),('move',w.HWND),('caret',w.HWND),('rect',w.RECT)]
        info=GUIInfo();info.size=c.sizeof(info)
        self.u.GetGUIThreadInfo.argtypes=[w.DWORD,c.POINTER(GUIInfo)]
        thread=self.u.GetWindowThreadProcessId(hwnd,None)
        if not self.u.GetGUIThreadInfo(thread,c.byref(info)):raise RuntimeError('Keyboard focus unavailable')
        target=info.focus
        if not target or self.pid(target)!=window['pid'] or self.u.GetAncestor(target,2)!=hwnd:
            raise RuntimeError('Click a text field in the selected PortalAI dialog first')
        if kind=='text':
            value=event.get('text')
            if not isinstance(value,str) or len(value)>8192:raise ValueError('Text is too long')
            for (unit,) in struct.iter_unpack('<H',value.replace('\n','\r').encode('utf-16-le')):
                self._post(target,0x102,unit,1)
        elif kind=='key':
            codes={'Enter':13,'Tab':9,'Backspace':8,'Delete':46,'Escape':27,'ArrowLeft':37,'ArrowUp':38,'ArrowRight':39,'ArrowDown':40,'Home':36,'End':35,'PageUp':33,'PageDown':34}
            key=event.get('key')
            if key not in codes:raise ValueError('Unsupported key')
            self._post(target,0x100,codes[key],1)
            if key in ('Enter','Tab','Backspace'):self._post(target,0x102,codes[key],1)
            self._post(target,0x101,codes[key],0xc0000001)
        else:raise ValueError('Unsupported input')
