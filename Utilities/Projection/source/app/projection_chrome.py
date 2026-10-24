"""PortalAI's decorated window shell, with stable native Windows ownership."""
import ctypes
import os
import tkinter as tk
from ornate_ui import ConnectedBorder, RoundedWindowController, work_area_geometry, install_title_filigree
from elegant_native_ui import ElegantButton, ui_font


class ProjectionChrome:
    def __init__(self, skin):
        self.skin=skin;self.app=skin.app;self.window=skin.window
        self.custom=os.name=='nt';self.maximized=False;self.restore_geometry=None;self.drag=None
        self.closed=False;self.map_timer=None
        if self.custom:self.app.overrideredirect(True)
        p=skin.palette
        self.shell=tk.Frame(self.app,bg=p['bg'],bd=0,highlightthickness=0)
        self.shell.pack(fill='both',expand=True,padx=4,pady=4)
        self.border=ConnectedBorder(self.shell,p,radius=18,erase_corners=False)
        self.titlebar=tk.Frame(self.shell,bg=p['panel3'],height=42)
        self.titlebar.pack(fill='x',padx=9,pady=(9,0));self.titlebar.pack_propagate(False)
        self.title=tk.Label(self.titlebar,text='PORTALAI  ·  PROJECTION',anchor='w',
                            bg=p['panel3'],fg=p['text'],font=(ui_font(self.app),10,'bold'))
        self.title.pack(side='left',fill='both',expand=True,padx=12)
        self.actions=tk.Frame(self.titlebar,bg=p['panel3']);self.actions.pack(side='right',padx=5,pady=5)
        self.buttons={}
        for key,label,command in [('minimize','—',self.window.minimize),('maximize','▢',self.toggle_maximize),('close','✕',self.window.close)]:
            button=ElegantButton(self.actions,text=label,command=command,width=4,
                bg=p['danger'] if key=='close' else p['button'],fg='#FFFFFF' if key=='close' else p['text'],cursor='hand2')
            button.pack(side='left',padx=3);self.buttons[key]=button
        self.filigree=install_title_filigree(self.shell,p)
        self.body=tk.Frame(self.shell,bg=p['bg']);self.body.pack(fill='both',expand=True,padx=10,pady=(0,10))
        for w in (self.titlebar,self.title):
            w.bind('<ButtonPress-1>',self.begin_move)
            w.bind('<B1-Motion>',self.move)
            w.bind('<Double-Button-1>',self.toggle_maximize)
        self.grips=[]
        if self.custom:
            specs={'n':dict(relwidth=1,height=4),'s':dict(rely=1,relwidth=1,height=4,anchor='sw'),
                   'w':dict(relheight=1,width=4),'e':dict(relx=1,relheight=1,width=4,anchor='ne'),
                   'nw':dict(width=8,height=8),'ne':dict(relx=1,width=8,height=8,anchor='ne'),
                   'sw':dict(rely=1,width=8,height=8,anchor='sw'),'se':dict(relx=1,rely=1,width=8,height=8,anchor='se')}
            for edge,position in specs.items():
                cursor='size_ns' if edge in ('n','s') else 'size_we' if edge in ('e','w') else 'size_nw_se' if edge in ('nw','se') else 'size_ne_sw'
                grip=tk.Frame(self.app,bg=p['bg'],cursor=cursor);grip.place(**position)
                grip.bind('<ButtonPress-1>',lambda e,d=edge:self.begin_resize(e,d))
                grip.bind('<B1-Motion>',self.resize);self.grips.append(grip)
        self.rounding=RoundedWindowController(self.app,self.hwnd,lambda:self.maximized,radius=18)
        self.app.bind('<Map>',self.mapped,add='+')
        self.app.bind('<Alt-F4>',lambda e:(self.window.close(),'break')[1],add='+')
        self.map_timer=self.app.after_idle(self.taskbar_style)

    def hwnd(self):
        if not self.custom:return None
        from ctypes import wintypes as w
        user=ctypes.PyDLL('user32',use_last_error=True)
        user.GetParent.argtypes=[w.HWND];user.GetParent.restype=w.HWND
        child=w.HWND(self.app.winfo_id());return user.GetParent(child) or child

    def taskbar_style(self):
        self.map_timer=None
        if self.closed or not self.custom:return
        from ctypes import wintypes as w
        user=ctypes.PyDLL('user32',use_last_error=True);hwnd=self.hwnd()
        user.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int];user.GetWindowLongW.restype=ctypes.c_long
        user.SetWindowLongW.argtypes=[w.HWND,ctypes.c_int,ctypes.c_long];user.SetWindowLongW.restype=ctypes.c_long
        style=user.GetWindowLongW(hwnd,-20)
        user.SetWindowLongW(hwnd,-20,(style|0x40000)&~0x80)

    def mapped(self,event):
        if event.widget is self.app and not self.closed and self.map_timer is None:
            self.map_timer=self.app.after_idle(self.taskbar_style)

    def minimize_to_taskbar(self):
        if not self.custom:self.app.iconify();return
        from ctypes import wintypes as w
        # Dispatch through Tk's event loop; synchronous ShowWindow from Python
        # can enter a Tk callback outside _tkinter's saved thread state.
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];user.PostMessageW.restype=w.BOOL
        self.taskbar_style()
        if not user.PostMessageW(self.hwnd(),0x0112,0xF020,0):
            raise OSError('Windows could not minimize the Projection window')

    def restore_native(self):
        if not self.custom:return
        from ctypes import wintypes as w
        user=ctypes.PyDLL('user32',use_last_error=True)
        user.IsIconic.argtypes=[w.HWND];user.IsIconic.restype=w.BOOL
        user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM];user.PostMessageW.restype=w.BOOL
        if user.IsIconic(self.hwnd()):user.PostMessageW(self.hwnd(),0x0112,0xF120,0)
        self.taskbar_style()

    def begin_move(self,event):
        self.drag=(event.x_root,event.y_root,self.app.winfo_x(),self.app.winfo_y())
        return 'break'

    def move(self,event):
        if self.maximized or not self.drag:return 'break'
        x,y,wx,wy=self.drag;self.app.geometry(f'{wx+event.x_root-x:+d}{wy+event.y_root-y:+d}')
        return 'break'

    def begin_resize(self,event,edge):
        self.drag=(event.x_root,event.y_root,self.app.winfo_x(),self.app.winfo_y(),self.app.winfo_width(),self.app.winfo_height(),edge)
        return 'break'

    def resize(self,event):
        if self.maximized or not self.drag or len(self.drag)!=7:return 'break'
        sx,sy,x,y,width,height,edge=self.drag;dx=event.x_root-sx;dy=event.y_root-sy
        minw,minh=self.app.minsize();nw,nh=width,height
        if 'e' in edge:nw=max(minw,width+dx)
        if 's' in edge:nh=max(minh,height+dy)
        if 'w' in edge:nw=max(minw,width-dx);x+=width-nw
        if 'n' in edge:nh=max(minh,height-dy);y+=height-nh
        self.app.geometry(f'{nw}x{nh}{x:+d}{y:+d}');return 'break'

    def toggle_maximize(self,event=None):
        if self.maximized:
            self.app.geometry(self.restore_geometry);self.maximized=False
        else:
            self.restore_geometry=self.app.geometry();x,y,w,h=work_area_geometry(self.hwnd(),self.app)
            self.app.geometry(f'{w}x{h}{x:+d}{y:+d}');self.maximized=True
        self.buttons['maximize'].configure(text='❐' if self.maximized else '▢')
        self.app.update_idletasks();self.rounding.refresh();return 'break'

    def apply_palette(self,p):
        self.shell.configure(bg=p['bg']);self.body.configure(bg=p['bg'])
        for w in (self.titlebar,self.actions):w.configure(bg=p['panel3'])
        self.title.configure(bg=p['panel3'],fg=p['text'])
        for w in self.grips:w.configure(bg=p['bg'])
        for key,w in self.buttons.items():
            w.configure(bg=p['danger'] if key=='close' else p['button'],fg='#FFFFFF' if key=='close' else p['text'])
        self.border.apply_palette(p);self.filigree.event_generate('<Configure>')

    def close(self):
        self.closed=True
        for owner,attr in ((self,'map_timer'),(self.rounding,'_after'),(self.border,'_after')):
            timer=getattr(owner,attr,None)
            if timer:
                self.app.after_cancel(timer);setattr(owner,attr,None)
