"""Standalone portable projection connection manager."""
from pathlib import Path
import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
from host_runtime import package_paths,python_command,launch_options,target_valid,resolve_target,default_target
sys.path[:0]=package_paths()
from connection_vault import new_connection,public_pairing,save,unlock,url


class Window:
    def __init__(self,app):
        self.app=app;self.connection=None;self.path=None;self.worker=None;self.messages=queue.Queue();self.secret=None
        self.stop_deadline=None
        app.title('PortalAI Projection');app.geometry('780x700');app.minsize(620,570)
        page=ttk.Frame(app,padding=20);page.pack(fill='both',expand=True);page.columnconfigure(1,weight=1);page.rowconfigure(10,weight=1)
        ttk.Label(page,text='PortalAI Projection',font=('Segoe UI',20,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
        ttk.Label(page,text='A separate portable host for the real PortalAI interface.',wraplength=700).grid(row=1,column=0,columnspan=3,sticky='w',pady=(4,14))
        self.files=[];self.selected=tk.StringVar();self.name=tk.StringVar(value='My PortalAI');self.address=tk.StringVar();self.target=tk.StringVar(value=str(default_target()));self.password=tk.StringVar();self.status=tk.StringVar(value='Create a connection or select a saved connection and unlock it.')
        ttk.Label(page,text='Saved connection').grid(row=2,column=0,sticky='w');self.saved=ttk.Combobox(page,textvariable=self.selected,state='readonly');self.saved.grid(row=2,column=1,sticky='ew',padx=8)
        ttk.Button(page,text='New',command=self.new).grid(row=2,column=2)
        for row,label,var in ((3,'Connection name',self.name),(4,'Home Assistant Cloud URL',self.address),(5,'PortalAI folder',self.target),(6,'Projection unlock password',self.password)):
            ttk.Label(page,text=label).grid(row=row,column=0,sticky='w',pady=7)
            ttk.Entry(page,textvariable=var,show='*' if row==6 else '').grid(row=row,column=1,columnspan=1 if row==5 else 2,sticky='ew',padx=8)
        ttk.Button(page,text='Browse',command=self.browse).grid(row=5,column=2)
        bar=ttk.Frame(page);bar.grid(row=7,column=0,columnspan=3,sticky='ew',pady=10)
        for label,command in [('Create / Unlock',self.load),('Save changes',self.save),('Change unlock password',self.change_password),('Lock',self.lock)]:ttk.Button(bar,text=label,command=command).pack(side='left',padx=(0,5))
        controls=ttk.Frame(page);controls.grid(row=8,column=0,columnspan=3,sticky='w')
        ttk.Button(controls,text='Start projection',command=self.start).pack(side='left',padx=(0,6));ttk.Button(controls,text='Stop projection',command=self.stop).pack(side='left',padx=(0,6));ttk.Button(controls,text='Open PortalAI locally',command=self.open_portalai).pack(side='left')
        ttk.Label(page,textvariable=self.status,wraplength=710).grid(row=9,column=0,columnspan=3,sticky='ew',pady=12)
        self.instructions=tk.Text(page,height=12,wrap='word',font=('Segoe UI',10));self.instructions.grid(row=10,column=0,columnspan=3,sticky='nsew')
        self.show('No Home Assistant password, cookie or API token is requested or saved.\n\n1. Install the supplied receiver on your HA instance once.\n2. Create/unlock a connection here. Copy its public pairing request to HA on a trusted device.\n3. Start projection, then use the HA card to open PortalAI and sign in.\n\nThe unlock password encrypts connection details and a projection-only device key at rest. It is separate from your PortalAI and HA passwords. A process with unrestricted access as this OS user can tamper with this app while unlocked.\n\nWindows or Linux X11/XWayland; no incoming LAN port or router change is needed.')
        self.refresh();self.timer=app.after(100,self.tick);app.protocol('WM_DELETE_WINDOW',self.close)
    def show(self,text):self.instructions.configure(state='normal');self.instructions.delete('1.0','end');self.instructions.insert('1.0',text);self.instructions.configure(state='disabled')
    def refresh(self):
        self.files=sorted((MODULE/'Connections').glob('*.enc'));self.saved['values']=[p.stem for p in self.files]
    def new(self):
        if self.worker and self.worker.poll() is None:self.status.set('Stop projection before changing connections.');return
        self.connection=None;self.secret=None;self.path=None;self.selected.set('');self.password.set('');self.address.set('');self.status.set('Enter a connection name, HTTPS HA URL and a new projection unlock password.')
    def browse(self):
        target=filedialog.askdirectory(parent=self.app,initialdir=self.target.get())
        if target:self.target.set(target)
    def guard_stopped(self):
        if self.worker and self.worker.poll() is None:raise RuntimeError('Stop projection before changing this connection')
    def current_settings(self):
        target=Path(self.target.get()).resolve()
        if not target_valid(target):raise ValueError('Select the actual PortalAI portable folder')
        # Relative drive paths survive a new SSD drive letter.
        try:relative=os.path.relpath(target,MODULE)
        except ValueError:raise ValueError('Keep PortalAI and this projection module on the same drive')
        if os.name!='nt' and target.stat().st_dev!=MODULE.stat().st_dev:raise ValueError('Keep PortalAI and Projection on the same mounted drive')
        return url(self.address.get()),relative.replace('\\','/'),self.name.get().strip() or 'PortalAI'
    def load(self):
        try:
            self.guard_stopped();password=self.password.get()
            if self.selected.get():
                index=self.saved.current()
                if not 0<=index<len(self.files):raise ValueError('Select a saved connection')
                path=self.files[index];connection=unlock(path,password)
                self.name.set(connection['name']);self.address.set(connection['url']);self.target.set(str(resolve_target(connection['target'])))
            else:
                address,target,name=self.current_settings();connection=new_connection(address,target,name)
                path=MODULE/'Connections'/(connection['device_id']+'.enc');save(path,connection,password)
            self.connection=connection;self.path=path;self.secret=password;self.password.set('');self.refresh();self.selected.set(path.stem);self.pairing()
            self.status.set('Connection unlocked. Approve pairing in HA on a trusted device, then Start projection.')
        except Exception as exc:self.status.set('Could not unlock/create connection: '+(str(exc) or 'Wrong password or damaged encrypted file'))
    def save(self):
        try:
            self.guard_stopped()
            if self.connection is None:raise RuntimeError('Unlock a connection first')
            address,target,name=self.current_settings();updated={**self.connection,'url':address,'target':target,'name':name}
            save(self.path,updated,self.secret);self.connection=updated;self.pairing();self.status.set('Encrypted connection saved. A different HA instance must approve this device before connecting.')
        except Exception as exc:self.status.set(str(exc))
    def change_password(self):
        try:
            self.guard_stopped()
            if self.connection is None:raise RuntimeError('Unlock the connection first')
            password=simpledialog.askstring('Change projection unlock password','New projection unlock password (12+ characters):',show='*',parent=self.app)
            if password is None:return
            confirm=simpledialog.askstring('Confirm password','Repeat the new password:',show='*',parent=self.app)
            if password!=confirm:raise ValueError('Passwords differ')
            save(self.path,self.connection,password);self.secret=password;self.status.set('Projection unlock password changed. HA authentication was not changed.')
        except Exception as exc:self.status.set(str(exc))
    def pairing(self):
        value=public_pairing(self.connection);identity=value['device_id']
        instructions='On HA, use Developer Tools â†’ Actions â†’ portalai_projection.pair_device.\nPaste this public JSON into pairing_request:\n\n'+json.dumps(value,indent=2)
        instructions+='\n\nDedicated dashboard card:\n\ntype: custom:portalai-projection\ntitle: PortalAI\ndevice_id: '+identity+'\n\nUse this device_id with the separate full_restart / force_shutdown actions. HA login happens on your trusted device. No login information is entered here.'
        self.show(instructions)
        # Public export only; no URL, private key, password, token or cookies.
        export=MODULE/'Connections'/(identity+'.public-pairing.json');export.write_text(json.dumps(value,indent=2),encoding='utf-8')
    def start(self):
        try:
            self.guard_stopped()
            if self.connection is None:raise RuntimeError('Unlock a connection first')
            self.worker=subprocess.Popen(python_command('projection_worker.py'),cwd=MODULE,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',**launch_options())
            self.stop_deadline=None
            self.worker.stdin.write(json.dumps(self.connection)+'\n');self.worker.stdin.flush()
            worker=self.worker
            def read():
                for line in worker.stdout:
                    try:self.messages.put(json.loads(line)['status'])
                    except (ValueError,KeyError):pass
            threading.Thread(target=read,daemon=True).start();self.status.set('Connecting to the paired receiverâ€¦')
        except Exception as exc:self.status.set(str(exc))
    def stop(self):
        if self.worker and self.worker.poll() is None:
            if self.stop_deadline is None:self.stop_deadline=time.monotonic()+15
            try:self.worker.stdin.close()
            except OSError:pass
            self.status.set('Stopping projection; PortalAI remains under its normal account lifecycle.')
    def open_portalai(self):
        if not self.worker or self.worker.poll() is not None:self.status.set('Start projection first, then use Open PortalAI in HA.');return
        try:self.worker.stdin.write('{"command":"open"}\n');self.worker.stdin.flush();self.status.set('Opening PortalAI through the standalone hostâ€¦')
        except OSError:self.status.set('Projection host has stopped. Start it again before opening PortalAI.')
    def lock(self):
        if self.worker and self.worker.poll() is None:self.status.set('Stop projection and wait for it to exit before locking.');return
        self.connection=None;self.secret=None;self.password.set('');self.address.set('');self.show('Connection locked. Select it and enter its projection unlock password to continue.');self.status.set('Locked')
    def tick(self):
        if self.stop_deadline and self.worker and self.worker.poll() is None and time.monotonic()>self.stop_deadline:
            # Popen retains this exact process handle. Only the stateless
            # projection host is stopped; PortalAI/profile processes stay alone.
            self.worker.terminate();self.stop_deadline=None
            self.status.set('Projection host stopped after a network timeout. PortalAI was not terminated.')
        while not self.messages.empty():self.status.set(self.messages.get_nowait())
        self.timer=self.app.after(100,self.tick)
    def close(self):
        self.stop()
        if self.worker and self.worker.poll() is None:self.app.after(200,self.close);return
        self.connection=None;self.secret=None;self.app.destroy()


if __name__=='__main__':
    app=tk.Tk();Window(app);app.mainloop()
