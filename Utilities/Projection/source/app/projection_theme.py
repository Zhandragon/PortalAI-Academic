"""Portable Projection appearance; no connection secrets in these preferences."""
import json
import os
import re
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, ttk
from ornate_ui import ConnectedBorder, heading_font
from elegant_native_ui import ElegantButton, blend

DEFAULT={'mode':'dark','accent':'#55B7C7','border':'#B88A32'}
DOCUMENTATION='''PORTALAI PROJECTION

GETTING STARTED
Projection is a separate portable companion. Select the PortalAI folder on the same drive. Create or unlock a saved connection, approve its public pairing request on a trusted Home Assistant device, then choose Start projection. The Home Assistant receiver and frontend must be installed on your HA server using the supplied HA Setup utility.

YOUR CONNECTION
The projection unlock password encrypts the connection URL and projection-only device key at rest. It is separate from your PortalAI and Home Assistant passwords. Never paste a Home Assistant password, cookie or API token here. The pairing JSON is public. Keep Connections/ when updating or moving this companion.

START, STOP AND LOCAL PORTALAI
Start projection connects the unlocked connection to its paired receiver. Stop projection disconnects that receiver; it leaves PortalAI running under its normal account lifecycle. Start local PortalAI opens the selected portable application, even before you pair or start projection. Sign in through PortalAI normally. An existing PortalAI process is reused; this action does not restart it or replay tasks.

MINIMIZE AND TRAY
The minimize button hides Projection behind its dark PortalAI emblem. Projection can keep working while hidden. Left-click the tray icon to reopen the window. Right-click it for Start/Stop projection, Start local PortalAI, Appearance, Documentation and Exit. The same themed menu is available by right-clicking inside this launcher window. Escape dismisses the menu. Exit or the window close button stops projection before closing; minimizing does not lock an unlocked connection.

APPEARANCE
Choose dark or light mode and custom accent and border colors. Projection uses the main PortalAI application's rounded buttons and connected ornamental borders. These preferences belong to this companion and are saved on the portable drive. Changing them does not change your connection or restart projection. The dark tray emblem stays distinct from the main PortalAI icon in either theme.

PLATFORM NOTES
Windows uses the notification area (the icon may be in its overflow panel). macOS uses the menu bar; Control-click also opens the menu. Screen projection on Mac requires Screen Recording permission, while the native HA controls do not. Linux needs the bundled Tk runtime and an X11/XWayland tray manager. If a tray cannot be created, minimizing keeps an ordinary taskbar window so you can always return. Linux launch and lifecycle still require the supplied regular-user systemd delegation.

MULTIPLE DRIVES AND AGENTS
Choose the intended PortalAI folder for each companion. Each portable application keeps its own account and instance identity. Configure agent names and ports in PortalAI's existing instance settings. Projection creates no incoming LAN listener and needs no router port forwarding. A second window cannot override PortalAI's root ownership and account guards.

TROUBLESHOOTING
If Start projection is unavailable, unlock a saved connection first. Stop and wait before changing or locking a connection. If HA cannot connect, confirm its HTTPS Cloud URL and receiver installation, and approve the public pairing request. If local PortalAI cannot start, verify the selected portable folder and review its runtime check utility; do not delete account or recovery files. Updates require a normal restart. Updating this drive does not deploy code to the remote HA server.
'''

def read_settings(module):
    p=Path(module)/'state/ui-settings.json'
    try:
        if p.parent.is_symlink() or p.is_symlink() or p.stat().st_size>4096:return dict(DEFAULT)
        value=json.loads(p.read_text(encoding='utf-8'))
        return validate(value)
    except (OSError,ValueError,TypeError):return dict(DEFAULT)

def validate(value):
    if not isinstance(value,dict):raise ValueError('Invalid appearance preferences')
    result=dict(DEFAULT)
    if value.get('mode') in ('dark','light'):result['mode']=value['mode']
    for key in ('accent','border'):
        if key in value:
            if not isinstance(value[key],str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value[key]):raise ValueError('Use a six-digit color')
            result[key]=value[key].upper()
    return result

def save_settings(module,value):
    p=Path(module)/'state/ui-settings.json';value=validate(value)
    if p.parent.is_symlink() or p.is_symlink():raise OSError('Linked appearance settings refused')
    p.parent.mkdir(exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix='.appearance-',dir=p.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(value,f);f.flush();os.fsync(f.fileno())
        os.replace(temp,p)
    finally:
        if os.path.exists(temp):os.unlink(temp)

class Skin:
    def __init__(self,window,module):
        self.window=window;self.app=window.app;self.module=module;self.settings=read_settings(module)
        self.items=[];self.borders=[];self.popup=None;self.palette={}
        self.style=ttk.Style(self.app);self.style.theme_use('clam');self.apply()

    def frame(self,parent,card=False,**kw):
        f=tk.Frame(parent,bg=self.palette['panel' if card else 'bg'],**kw);self.items.append((f,'card' if card else 'frame'))
        if card:self.borders.append(ConnectedBorder(f,self.palette))
        return f

    def label(self,parent,text='',kind='text',**kw):
        f=tk.Label(parent,text=text,bg=parent.cget('bg'),fg=self.palette[kind],anchor='w',justify='left',**kw);self.items.append((f,kind));return f

    def button(self,parent,text,command,accent=False):
        b=ElegantButton(parent,text=text,command=command,bg=self.palette['accent' if accent else 'button'],fg=self.palette['ink' if accent else 'text'],padx=12,pady=7)
        self.items.append((b,'primary' if accent else 'button'));return b

    def text(self,parent,**kw):
        f=tk.Text(parent,wrap='word',relief='flat',bd=0,padx=12,pady=10,font=('TkDefaultFont',10),**kw)
        self.items.append((f,'entry'));self.paint(f,'entry');return f

    def paint(self,w,kind):
        p=self.palette
        if kind in ('button','primary'):
            primary=kind=='primary';w.configure(bg=p['accent' if primary else 'button'],fg=p['ink' if primary else 'text']);return
        if kind=='entry':w.configure(bg=p['input'],fg=p['text'],insertbackground=p['text'],selectbackground=p['accent'],selectforeground=p['ink']);return
        if kind in ('frame','card'):w.configure(bg=p['panel' if kind=='card' else 'bg']);return
        w.configure(bg=w.master.cget('bg'),fg=p[kind])

    def apply(self):
        dark=self.settings['mode']=='dark';bg='#131B22' if dark else '#F3EEE4';panel='#1D2933' if dark else '#FFF9EC'
        self.palette.update(bg=bg,panel=panel,input='#111A21' if dark else '#FFFCF6',text='#E9E4D8' if dark else '#25231F',muted='#A5B6BD' if dark else '#58615F',button='#30434E' if dark else '#E4D8BE',ink='#102027',accent=self.settings['accent'],gold_mid=self.settings['border'],gold_shine=blend(self.settings['border'],'#FFFFFF',.4),shadow='#080C10' if dark else '#BEAD8D')
        p=self.palette;self.app.configure(bg=bg)
        for name in ('TFrame','TLabel','TNotebook','TNotebook.Tab'):self.style.configure(name,background=panel,foreground=p['text'])
        self.style.configure('TNotebook',background=bg,borderwidth=0);self.style.configure('TNotebook.Tab',padding=(18,9))
        self.style.map('TNotebook.Tab',background=[('selected',panel),('active',p['button'])],foreground=[('selected',p['accent'])])
        for name in ('TEntry','TCombobox'):
            self.style.configure(name,fieldbackground=p['input'],background=p['input'],foreground=p['text'],insertcolor=p['text'],bordercolor=p['gold_mid'],lightcolor=panel,darkcolor=panel,padding=6,arrowsize=14)
            self.style.map(name,fieldbackground=[('readonly',p['input'])],foreground=[('readonly',p['text'])],selectbackground=[('readonly',p['accent'])],selectforeground=[('readonly',p['ink'])])
        self.app.option_add('*TCombobox*Listbox.background',p['input']);self.app.option_add('*TCombobox*Listbox.foreground',p['text'])
        for w,kind in self.items:
            if w.winfo_exists():self.paint(w,kind)
        for border in self.borders:border.apply_palette(p)
        if hasattr(self,'accent_label'):
            self.accent_label.configure(text=self.settings['accent']);self.border_label.configure(text=self.settings['border'])
        if os.name=='nt':
            try:
                import ctypes as c
                hwnd=c.windll.user32.GetParent(self.app.winfo_id());value=c.c_int(dark)
                c.windll.dwmapi.DwmSetWindowAttribute(c.c_void_p(hwnd),20,c.byref(value),4)
            except Exception:pass

    def change(self,key,value):
        self.settings=validate({**self.settings,key:value})
        if hasattr(self,'mode'):self.mode.set(self.settings['mode'])
        self.apply()
        try:save_settings(self.module,self.settings)
        except OSError:self.window.status.set('Appearance applied for this session; preferences could not be saved on the drive.')

    def choose(self,key):
        value=colorchooser.askcolor(self.settings[key],parent=self.app,title='Projection '+key+' color')[1]
        if value:self.change(key,value)

    def build(self):
        w=self.window;p=self.palette;app=self.app
        app.geometry('900x810');app.minsize(720,680)
        shell=self.frame(app);shell.pack(fill='both',expand=True,padx=18,pady=14)
        header=self.frame(shell);header.pack(fill='x',pady=(0,12))
        self.logo=tk.PhotoImage(master=app,file=str(Path(self.module)/'app/assets/projection-dark.png'))
        app.iconphoto(True,self.logo)
        self.small_logo=self.logo.subsample(2,2);emblem=self.label(header,image=self.small_logo);emblem.pack(side='left',padx=(0,12))
        title=self.frame(header);title.pack(side='left',fill='x',expand=True)
        self.label(title,'PortalAI Projection',font=(heading_font(app),24,'bold'),kind='accent').pack(anchor='w')
        self.label(title,'Your portable companion for Home Assistant',kind='muted').pack(anchor='w',pady=(2,0))
        self.button(header,'Minimize to tray',w.minimize).pack(side='right')
        self.tabs=ttk.Notebook(shell);self.tabs.pack(fill='both',expand=True)
        self.connection=self.frame(self.tabs,card=True);self.appearance=self.frame(self.tabs,card=True);self.documentation=self.frame(self.tabs,card=True)
        for page,title in ((self.connection,'Connection'),(self.appearance,'Appearance'),(self.documentation,'Documentation')):self.tabs.add(page,text=title)
        def content(parent):
            inner=self.frame(parent);self.items[-1]=(inner,'card');inner.configure(bg=p['panel']);inner.pack(fill='both',expand=True,padx=20,pady=22);return inner
        page=content(self.connection);page.columnconfigure(1,weight=1);page.rowconfigure(9,weight=1)
        self.label(page,'Saved connection').grid(row=0,column=0,sticky='w',pady=7)
        w.saved=ttk.Combobox(page,textvariable=w.selected,state='readonly');w.saved.grid(row=0,column=1,sticky='ew',padx=10)
        self.button(page,'New',w.new).grid(row=0,column=2,sticky='ew')
        for row,label,var in ((1,'Connection name',w.name),(2,'Home Assistant Cloud URL',w.address),(3,'PortalAI folder',w.target),(4,'Projection unlock password',w.password)):
            self.label(page,label).grid(row=row,column=0,sticky='w',pady=8)
            ttk.Entry(page,textvariable=var,show='*' if row==4 else '').grid(row=row,column=1,columnspan=1 if row==3 else 2,sticky='ew',padx=(10,0))
        self.button(page,'Browse',w.browse).grid(row=3,column=2,padx=(8,0),sticky='ew')
        bar=self.frame(page,card=False);bar.configure(bg=p['panel']);bar.grid(row=5,column=0,columnspan=3,sticky='ew',pady=(12,8))
        # These frames share their card background across theme switches.
        self.items[-1]=(bar,'card')
        for text,fn in [('Create / Unlock',w.load),('Save changes',w.save),('Change password',w.change_password),('Lock',w.lock)]:self.button(bar,text,fn).pack(side='left',padx=(0,7))
        controls=self.frame(page);self.items[-1]=(controls,'card');controls.configure(bg=p['panel']);controls.grid(row=6,column=0,columnspan=3,sticky='ew',pady=(4,6))
        self.start_button=self.button(controls,'Start projection',w.start,True);self.start_button.pack(side='left',padx=(0,7))
        self.stop_button=self.button(controls,'Stop projection',w.stop);self.stop_button.pack(side='left',padx=(0,7))
        self.local_button=self.button(controls,'Start local PortalAI',w.open_portalai);self.local_button.pack(side='left')
        import sys
        if sys.platform=='darwin':self.button(page,'Screen permission',w.screen_permission).grid(row=7,column=0,columnspan=3,sticky='w',pady=4)
        self.label(page,textvariable=w.status,wraplength=630,kind='accent').grid(row=8,column=0,columnspan=3,sticky='ew',pady=(9,10))
        w.instructions=self.text(page,height=10);w.instructions.grid(row=9,column=0,columnspan=3,sticky='nsew')
        scroll=ttk.Scrollbar(page,command=w.instructions.yview);scroll.grid(row=9,column=3,sticky='ns');w.instructions.configure(yscrollcommand=scroll.set)
        self.label(shell,'Right-click inside this window for actions and help.',kind='muted').pack(anchor='w',pady=(10,0))
        a=content(self.appearance)
        self.label(a,'Make Projection your own',font=(heading_font(app),21,'bold'),kind='accent').pack(anchor='w',pady=(0,10))
        self.label(a,'Shared PortalAI styling, saved separately on this drive.',kind='muted').pack(anchor='w',pady=(0,22))
        self.mode=tk.StringVar(value=self.settings['mode']);combo=ttk.Combobox(a,textvariable=self.mode,values=('dark','light'),state='readonly',width=18);combo.pack(anchor='w');combo.bind('<<ComboboxSelected>>',lambda e:self.change('mode',self.mode.get()))
        for key in ('accent','border'):
            row=self.frame(a);self.items[-1]=(row,'card');row.configure(bg=p['panel']);row.pack(anchor='w',pady=15)
            self.button(row,'Choose '+key+' color',lambda k=key:self.choose(k)).pack(side='left')
            label=self.label(row,self.settings[key]);label.pack(side='left',padx=14);setattr(self,key+'_label',label)
        def reset():
            self.settings=dict(DEFAULT);self.mode.set(DEFAULT['mode']);self.change('mode',DEFAULT['mode'])
        self.button(a,'Restore default appearance',reset).pack(anchor='w',pady=12)
        self.label(a,'The dark tray emblem stays the same in both themes.\nMinimizing leaves an unlocked connection available.',kind='muted').pack(anchor='w',pady=20)
        d=content(self.documentation);d.rowconfigure(0,weight=1);d.columnconfigure(0,weight=1)
        docs=self.text(d);docs.insert('1.0',DOCUMENTATION);docs.configure(state='disabled');docs.grid(row=0,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(d,command=docs.yview);scroll.grid(row=0,column=1,sticky='ns');docs.configure(yscrollcommand=scroll.set)
        app.bind('<Button-3>',self.context_event,add='+')
        if sys.platform=='darwin':app.bind('<Control-Button-1>',self.context_event,add='+')
        self.apply()

    def page(self,name):
        self.window.restore();self.tabs.select(getattr(self,name))

    def context_event(self,event):
        self.menu((event.x_root,event.y_root));return 'break'

    def dismiss(self):
        if self.popup is not None:
            try:self.popup.destroy()
            except tk.TclError:pass
            self.popup=None

    def menu(self,position=None):
        self.dismiss();w=self.window;p=self.palette
        pop=tk.Toplevel(self.app);self.popup=pop;pop.withdraw();pop.overrideredirect(True);pop.configure(bg=p['gold_mid']);pop.attributes('-topmost',True)
        inner=tk.Frame(pop,bg=p['panel'],padx=9,pady=9);inner.pack(fill='both',expand=True,padx=2,pady=2)
        tk.Label(inner,text='PORTALAI  /  PROJECTION',bg=p['panel'],fg=p['accent'],font=('TkDefaultFont',10,'bold'),anchor='w').pack(fill='x',padx=8,pady=(4,9))
        active=bool(w.worker and w.worker.poll() is None)
        actions=[('Reopen Projection','Return to connection controls.',w.restore,True),('Minimize to tray','Keep projection running in the background.',w.minimize,True),('Start projection','Connect the unlocked device to Home Assistant.',w.start,w.connection is not None and not active),('Stop projection','Disconnect projection; leave PortalAI running.',w.stop,active),('Start local PortalAI','Open the selected portable application and sign in.',w.open_portalai,not w.local_starting),('Appearance','Choose colors and ornamental borders.',lambda:self.page('appearance'),True),('Documentation','Pairing, tray behavior and troubleshooting.',lambda:self.page('documentation'),True),('Exit Projection','Disconnect and close this companion.',w.close,True)]
        self.menu_buttons=[]
        for title,help_text,command,enabled in actions:
            def invoke(fn=command):self.dismiss();fn()
            button=tk.Button(inner,text=title+'\n'+help_text,anchor='w',justify='left',bg=p['panel'],fg=p['text'],activebackground=p['button'],activeforeground=p['accent'],disabledforeground=p['muted'],relief='flat',bd=0,padx=10,pady=6,command=invoke,state='normal' if enabled else 'disabled',takefocus=1)
            button.pack(fill='x');self.menu_buttons.append(button)
        pop.bind('<Escape>',lambda e:self.dismiss());pop.bind('<FocusOut>',lambda e:pop.after_idle(self._dismiss_unfocused))
        pop.update_idletasks();x,y=position or (self.app.winfo_pointerx(),self.app.winfo_pointery())
        # Clamp to the virtual desktop, including monitors left of the primary.
        left=self.app.winfo_vrootx();top=self.app.winfo_vrooty();width=self.app.winfo_vrootwidth();height=self.app.winfo_vrootheight()
        x=max(left,min(x,left+width-pop.winfo_reqwidth()));y=max(top,min(y,top+height-pop.winfo_reqheight()))
        pop.geometry(f'+{x}+{y}' if x>=0 and y>=0 else f'{x:+d}{y:+d}');pop.deiconify();pop.lift();pop.focus_force();self.menu_buttons[0].focus_set()

    def _dismiss_unfocused(self):
        if self.popup is None:return
        try:
            focused=self.popup.focus_displayof()
            if focused is None or focused.winfo_toplevel()!=self.popup:self.dismiss()
        except tk.TclError:self.dismiss()

    def update_actions(self):
        active=bool(self.window.worker and self.window.worker.poll() is None)
        self.start_button.configure(state='normal' if self.window.connection is not None and not active else 'disabled')
        self.stop_button.configure(state='normal' if active else 'disabled')
        self.local_button.configure(state='disabled' if self.window.local_starting else 'normal')
