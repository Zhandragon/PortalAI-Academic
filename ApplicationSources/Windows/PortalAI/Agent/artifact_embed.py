"""Windows embedding restricted to the requesting GUI and our Chromium PID."""
import ctypes as C
from ctypes import wintypes as W
import os
import time


class EmbeddedWindow:
    def __init__(self,parent,browser,page):
        if os.name!='nt' or type(parent) is not int or parent<=0:raise ValueError('Embedded preview requires a Windows GUI host')
        self.user=C.WinDLL('user32',use_last_error=True);u=self.user
        self.callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        signatures={'IsWindow':([W.HWND],W.BOOL),'GetWindowThreadProcessId':([W.HWND,C.POINTER(W.DWORD)],W.DWORD),
            'GetParent':([W.HWND],W.HWND),'SetParent':([W.HWND,W.HWND],W.HWND),
            'GetWindowLongPtrW':([W.HWND,C.c_int],C.c_ssize_t),'SetWindowLongPtrW':([W.HWND,C.c_int,C.c_ssize_t],C.c_ssize_t),
            'GetClientRect':([W.HWND,C.POINTER(W.RECT)],W.BOOL),'MoveWindow':([W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.BOOL],W.BOOL),
            'EnumWindows':([self.callback,W.LPARAM],W.BOOL),'IsWindowVisible':([W.HWND],W.BOOL)}
        for name,(args,result) in signatures.items():getattr(u,name).argtypes=args;getattr(u,name).restype=result
        self.parent=parent;self.window=None;self.last_size=None
        self._check_parent()
        cdp=browser.new_browser_cdp_session()
        pids={int(p['id']) for p in cdp.send('SystemInfo.getProcessInfo')['processInfo'] if p['type']=='browser'}
        if len(pids)!=1:raise RuntimeError('Could not identify the owned preview browser')
        session=page.context.new_cdp_session(page)
        info=session.send('Browser.getWindowForTarget')
        session.send('Browser.setWindowBounds',{'windowId':info['windowId'],'bounds':{'windowState':'fullscreen'}})
        deadline=time.monotonic()+5
        while time.monotonic()<deadline and not self.window:
            matches=[]
            @self.callback
            def visit(hwnd,_):
                pid=W.DWORD();u.GetWindowThreadProcessId(hwnd,C.byref(pid))
                if pid.value in pids and u.IsWindowVisible(hwnd):matches.append(hwnd)
                return True
            u.EnumWindows(visit,0)
            if len(matches)==1:self.window=matches[0]
            else:page.wait_for_timeout(50)
        if not self.window:raise RuntimeError('Could not find one owned preview window; use separate preview')
        self._check_parent()
        style=u.GetWindowLongPtrW(self.window,-16)
        u.SetWindowLongPtrW(self.window,-16,(style & ~0x80CF0000)|0x40000000)  # WS_CHILD, no popup/caption/resize border.
        C.set_last_error(0);previous=u.SetParent(self.window,parent)
        if not previous and C.get_last_error():raise C.WinError(C.get_last_error())
        if u.GetParent(self.window)!=parent:raise RuntimeError('Preview embedding failed; use separate preview')
        self.resize()

    def _check_parent(self):
        pid=W.DWORD()
        if not self.user.IsWindow(self.parent):raise RuntimeError('Preview host closed')
        self.user.GetWindowThreadProcessId(self.parent,C.byref(pid))
        if pid.value!=os.getppid():raise PermissionError('Preview host must belong to the requesting PortalAI GUI')

    def resize(self):
        self._check_parent();rect=W.RECT()
        if not self.user.GetClientRect(self.parent,C.byref(rect)):raise C.WinError(C.get_last_error())
        size=(max(1,rect.right-rect.left),max(1,rect.bottom-rect.top))
        if size!=self.last_size:
            if not self.user.MoveWindow(self.window,0,0,*size,True):raise C.WinError(C.get_last_error())
            self.last_size=size
