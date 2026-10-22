"""Projection-only tray. Native callbacks enqueue actions; Tk owns every menu."""
import os,queue,sys,threading
from pathlib import Path

class WindowsTray:
    EVENT=0x8000+71
    def __init__(self,app,events,icon):
        self.events=events;self.icon=Path(icon);self.ready=threading.Event();self.visible=False;self.hwnd=0;self.thread=None
    def show(self):
        if self.thread and self.thread.is_alive():return self.visible
        self.ready.clear();self.thread=threading.Thread(target=self.run,name='PortalAI-Projection-Tray',daemon=True);self.thread.start()
        self.ready.wait(2);return self.visible
    def close(self):
        if self.hwnd:
            import ctypes
            ctypes.windll.user32.PostMessageW(ctypes.c_void_p(self.hwnd),0x10,0,0)
        if self.thread:self.thread.join(1)
    def run(self):
        import ctypes as c
        from ctypes import wintypes as w
        user=c.WinDLL('user32',use_last_error=True);shell=c.WinDLL('shell32',use_last_error=True);kernel=c.WinDLL('kernel32',use_last_error=True)
        callback=c.WINFUNCTYPE(c.c_ssize_t,w.HWND,w.UINT,w.WPARAM,w.LPARAM)
        class WNDCLASS(c.Structure):
            _fields_=[('style',w.UINT),('proc',callback),('extra',c.c_int),('window_extra',c.c_int),('instance',w.HINSTANCE),('icon',w.HICON),('cursor',w.HANDLE),('background',w.HBRUSH),('menu',w.LPCWSTR),('name',w.LPCWSTR)]
        class NID(c.Structure):
            _fields_=[('size',w.DWORD),('window',w.HWND),('id',w.UINT),('flags',w.UINT),('message',w.UINT),('icon',w.HICON),('tip',w.WCHAR*128),('state',w.DWORD),('mask',w.DWORD),('info',w.WCHAR*256),('version',w.UINT),('title',w.WCHAR*64),('infoflags',w.DWORD),('guid',c.c_ubyte*16),('balloon',w.HICON)]
        signatures={
            'RegisterClassW':([c.POINTER(WNDCLASS)],w.ATOM),'UnregisterClassW':([w.LPCWSTR,w.HINSTANCE],w.BOOL),
            'CreateWindowExW':([w.DWORD,w.LPCWSTR,w.LPCWSTR,w.DWORD,c.c_int,c.c_int,c.c_int,c.c_int,w.HWND,w.HMENU,w.HINSTANCE,c.c_void_p],w.HWND),
            'DefWindowProcW':([w.HWND,w.UINT,w.WPARAM,w.LPARAM],c.c_ssize_t),
            'LoadImageW':([w.HINSTANCE,w.LPCWSTR,w.UINT,c.c_int,c.c_int,w.UINT],w.HANDLE),
            'DestroyIcon':([w.HICON],w.BOOL),'DestroyWindow':([w.HWND],w.BOOL),'RegisterWindowMessageW':([w.LPCWSTR],w.UINT),
            'GetMessageW':([c.POINTER(w.MSG),w.HWND,w.UINT,w.UINT],c.c_int),
            'TranslateMessage':([c.POINTER(w.MSG)],w.BOOL),'DispatchMessageW':([c.POINTER(w.MSG)],c.c_ssize_t),
            'GetCursorPos':([c.POINTER(w.POINT)],w.BOOL),'PostQuitMessage':([c.c_int],None)}
        for name,(args,result) in signatures.items():f=getattr(user,name);f.argtypes=args;f.restype=result
        kernel.GetModuleHandleW.argtypes=[w.LPCWSTR];kernel.GetModuleHandleW.restype=w.HINSTANCE
        shell.Shell_NotifyIconW.argtypes=[w.DWORD,c.POINTER(NID)];shell.Shell_NotifyIconW.restype=w.BOOL
        instance=kernel.GetModuleHandleW(None);name='PortalAIProjectionTray_'+str(os.getpid())+'_'+str(id(self))
        icon=user.LoadImageW(None,str(self.icon),1,32,32,0x10)
        if not icon:self.ready.set();return
        nid=NID();nid.size=c.sizeof(NID);nid.id=1;nid.flags=7;nid.message=self.EVENT;nid.icon=icon;nid.tip='PortalAI Projection · click to reopen'
        restart=user.RegisterWindowMessageW('TaskbarCreated')
        def add():
            self.visible=bool(shell.Shell_NotifyIconW(0,c.byref(nid)))
            if not self.visible:self.events.put(('tray_failed',None))
        @callback
        def proc(hwnd,message,wp,lp):
            if message==restart:add();return 0
            if message==self.EVENT:
                event=int(lp)&0xffff
                if event in (0x202,0x203):self.events.put(('restore',None))
                elif event in (0x205,0x7b):
                    point=w.POINT();user.GetCursorPos(c.byref(point));self.events.put(('menu',(point.x,point.y)))
                return 0
            if message==0x10:user.DestroyWindow(hwnd);return 0
            if message==2:
                shell.Shell_NotifyIconW(2,c.byref(nid));self.visible=False;user.PostQuitMessage(0);return 0
            return user.DefWindowProcW(hwnd,message,wp,lp)
        wc=WNDCLASS();wc.proc=proc;wc.instance=instance;wc.name=name;registered=False
        try:
            registered=bool(user.RegisterClassW(c.byref(wc)))
            if not registered:return
            hwnd=user.CreateWindowExW(0,name,name,0,0,0,0,0,None,None,instance,None)
            if not hwnd:return
            self.hwnd=int(hwnd);nid.window=hwnd;add();self.ready.set();msg=w.MSG()
            while user.GetMessageW(c.byref(msg),None,0,0)>0:user.TranslateMessage(c.byref(msg));user.DispatchMessageW(c.byref(msg))
        finally:
            self.hwnd=0;self.visible=False;self.ready.set();user.DestroyIcon(icon)
            if registered:user.UnregisterClassW(name,instance)

class MacTray:
    def __init__(self,app,events,icon):self.events=events;self.icon=Path(icon).with_suffix('.png');self.item=None;self.target=None
    def show(self):
        if self.item is not None:return True
        try:
            import AppKit as A
            import objc
            events=self.events
            # Registered once; each instance retains its own event queue.
            global _MacTarget
            if '_MacTarget' not in globals():
                class ProjectionTrayTarget(A.NSObject):
                    def clicked_(self,sender):
                        event=A.NSApp.currentEvent()
                        right=event.type()==A.NSEventTypeRightMouseUp or bool(event.modifierFlags()&A.NSEventModifierFlagControl)
                        self.events.put(('menu' if right else 'restore',None))
                _MacTarget=ProjectionTrayTarget
            self.target=_MacTarget.alloc().init();self.target.events=events
            image=A.NSImage.alloc().initWithContentsOfFile_(str(self.icon));image.setSize_((22,22));image.setTemplate_(False)
            self.item=A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
            button=self.item.button();button.setImage_(image);button.setToolTip_('PortalAI Projection · click to reopen')
            button.setTarget_(self.target);button.setAction_('clicked:');button.sendActionOn_(A.NSEventMaskLeftMouseUp|A.NSEventMaskRightMouseUp)
            return True
        except Exception:self.close();return False
    def close(self):
        if self.item is not None:
            import AppKit as A
            A.NSStatusBar.systemStatusBar().removeStatusItem_(self.item);self.item=None;self.target=None

class TkTray:
    def __init__(self,app,events,icon):self.app=app;self.events=events;self.icon=Path(icon).with_suffix('.png');self.created=False;self.callbacks=[];self.image=None
    def show(self):
        if self.created:return True
        try:
            import tkinter as tk
            # X11 desktops without a tray manager must retain a taskbar window.
            if self.app.tk.call('tk','windowingsystem')=='x11':
                from ctypes import CDLL,c_void_p,c_char_p,c_ulong,c_int
                x=CDLL('libX11.so.6');x.XOpenDisplay.argtypes=[c_char_p];x.XOpenDisplay.restype=c_void_p
                x.XDefaultScreen.argtypes=[c_void_p];x.XDefaultScreen.restype=c_int
                x.XInternAtom.argtypes=[c_void_p,c_char_p,c_int];x.XInternAtom.restype=c_ulong
                x.XGetSelectionOwner.argtypes=[c_void_p,c_ulong];x.XGetSelectionOwner.restype=c_ulong
                x.XCloseDisplay.argtypes=[c_void_p]
                display=x.XOpenDisplay(None)
                if not display:return False
                try:
                    atom=x.XInternAtom(display,('_NET_SYSTEM_TRAY_S'+str(x.XDefaultScreen(display))).encode(),0)
                    if not x.XGetSelectionOwner(display,atom):return False
                finally:x.XCloseDisplay(display)
            self.image=tk.PhotoImage(master=self.app,file=str(self.icon)).subsample(3,3)
            self.callbacks=[self.app.register(lambda:self.events.put(('restore',None))),self.app.register(lambda:self.events.put(('menu',None)))]
            self.app.tk.call('tk','systray','create','-image',self.image,'-text','PortalAI Projection','-button1',self.callbacks[0],'-button3',self.callbacks[1]);self.created=True;return True
        except Exception:self.close();return False
    def close(self):
        if self.created:
            try:self.app.tk.call('tk','systray','destroy')
            except Exception:pass
        self.created=False
        for name in self.callbacks:
            try:self.app.deletecommand(name)
            except Exception:pass
        self.callbacks=[];self.image=None

def create(app,events,icon):
    cls=WindowsTray if os.name=='nt' else MacTray if sys.platform=='darwin' else TkTray
    return cls(app,events,icon)
