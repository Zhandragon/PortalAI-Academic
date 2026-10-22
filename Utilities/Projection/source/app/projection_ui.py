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
        self.stop_deadline=None;self.local_starting=False;self.closing=False;self.hidden=False;self.close_timer=None
        self.ui_events=queue.Queue()
        app.title('PortalAI Projection')
        self.files=[];self.selected=tk.StringVar();self.name=tk.StringVar(value='My PortalAI');self.address=tk.StringVar();self.target=tk.StringVar(value=str(default_target()));self.password=tk.StringVar();self.status=tk.StringVar(value='Create a connection or select a saved connection and unlock it.')
        from projection_theme import Skin,DOCUMENTATION
        from projection_tray import create
        self.skin=Skin(self,MODULE);self.skin.build()
        self.tray=create(app,self.ui_events,MODULE/'app/assets/projection-dark.ico')
        self.show('Create or unlock a connection to see its public pairing request.\n\nNo Home Assistant password, cookie or API token is requested or saved.\n\n1. Install the supplied receiver on HA.\n2. Create/unlock a connection here and approve its public pairing request on a trusted HA device.\n3. Start projection, then open PortalAI and sign in.\n\nSee Documentation for setup, tray controls and platform help.')
        self.refresh();self.skin.update_actions();self.timer=app.after(100,self.tick)
        self.tray_timer=app.after(500,self.tray.show)
        app.bind('<Unmap>',self.on_unmap,add='+');app.protocol('WM_DELETE_WINDOW',self.close)

    def on_unmap(self,event):
        if event.widget==self.app and not self.closing and self.app.state()=='iconic':self.minimize()

    def minimize(self):
        self.skin.dismiss()
        if self.closing:return
        if self.tray.show():self.hidden=True;self.app.withdraw()
        else:
            self.hidden=False;self.status.set('Tray unavailable on this desktop; use the taskbar to reopen Projection.')
            if self.app.state()!='iconic':self.app.iconify()

    def restore(self):
        if self.closing:return
        self.skin.dismiss();self.hidden=False;self.app.deiconify();self.app.lift();self.app.focus_force()

    def screen_permission(self):
        try:
            import Quartz
            granted=Quartz.CGPreflightScreenCaptureAccess() or Quartz.CGRequestScreenCaptureAccess()
            self.status.set('Screen permission granted. Stop/start projection to activate it.' if granted else 'Enable Screen Recording for the bundled Python/Terminal in System Settings > Privacy & Security, then quit/reopen Projection. Native HA controls do not require screen recording.')
        except Exception:self.status.set('Screen permission check failed. Run Check Mac Runtime.command and review README-MAC.txt.')
    def show(self,text):self.instructions.configure(state='normal');self.instructions.delete('1.0','end');self.instructions.insert('1.0',text.replace('Windows or Linux X11/XWayland;','Windows, Linux X11/XWayland, or macOS 14+;'));self.instructions.configure(state='disabled')
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
        instructions='On HA, use Developer Tools > Actions > portalai_projection.pair_device.\nPaste this public JSON into pairing_request:\n\n'+json.dumps(value,indent=2)
        instructions+='\n\nDedicated dashboard card:\n\ntype: custom:portalai-projection\ntitle: PortalAI\ndevice_id: '+identity+'\n\nUse this device_id with the separate full_restart / force_shutdown actions. HA login happens on your trusted device. No login information is entered here.'
        self.show(instructions)
        # Public export only; no URL, private key, password, token or cookies.
        export=MODULE/'Connections'/(identity+'.public-pairing.json');export.write_text(json.dumps(value,indent=2),encoding='utf-8')
    def start(self):
        if self.closing:return
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
            threading.Thread(target=read,daemon=True).start();self.status.set('Connecting to the paired receiver...')
        except Exception as exc:self.status.set(str(exc))
    def stop(self):
        if self.worker and self.worker.poll() is None:
            if self.stop_deadline is None:self.stop_deadline=time.monotonic()+15
            try:self.worker.stdin.close()
            except OSError:pass
            self.status.set('Stopping projection; PortalAI remains under its normal account lifecycle.')
    def open_portalai(self):
        if self.local_starting or self.closing:return
        try:
            target=Path(self.target.get()).resolve()
            if not target_valid(target):raise ValueError('Select the actual PortalAI portable folder before starting it.')
            if os.name!='nt' and target.stat().st_dev!=MODULE.stat().st_dev:raise ValueError('Keep PortalAI and Projection on the same mounted drive.')
            target=os.path.relpath(target,MODULE).replace('\\','/')
        except (OSError,ValueError) as exc:self.status.set(str(exc));return
        self.local_starting=True;self.status.set('Starting local PortalAI; sign in through its normal account window.')
        self.skin.update_actions()
        def launch():
            try:
                result=subprocess.run(python_command('projection_local.py'),cwd=MODULE,
                    input=json.dumps({'target':target}),stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                    text=True,encoding='utf-8',timeout=45,**launch_options())
                reply=json.loads(result.stdout);message=reply.get('message') or 'Local start finished without a status.'
            except subprocess.TimeoutExpired:message='Local start readiness timed out. Check PortalAI before trying again; no start request was replayed.'
            except Exception:message='Local PortalAI could not be started. Check the selected folder and its runtime.'
            self.ui_events.put(('local_done',message))
        threading.Thread(target=launch,name='PortalAI-Projection-LocalStart',daemon=True).start()
    def lock(self):
        if self.worker and self.worker.poll() is None:self.status.set('Stop projection and wait for it to exit before locking.');return
        self.connection=None;self.secret=None;self.password.set('');self.address.set('');self.show('Connection locked. Select it and enter its projection unlock password to continue.');self.status.set('Locked')
    def tick(self):
        self.app.after_cancel(self.timer)
        if self.stop_deadline and self.worker and self.worker.poll() is None and time.monotonic()>self.stop_deadline:
            # Only this exact stateless projection worker is stopped.
            self.worker.terminate();self.stop_deadline=None
            self.status.set('Projection host stopped after a network timeout. PortalAI was not terminated.')
        # Bound per-frame work even if a failing receiver generates a burst.
        for _ in range(64):
            try:message=self.messages.get_nowait()
            except queue.Empty:break
            self.status.set(message)
        for _ in range(32):
            try:action,value=self.ui_events.get_nowait()
            except queue.Empty:break
            if action=='restore':self.restore()
            elif action=='menu' and not self.closing:self.skin.menu(value)
            elif action=='local_done':self.local_starting=False;self.status.set(value)
            elif action=='tray_failed' and self.hidden:self.restore();self.status.set('Tray icon unavailable; Projection has reopened.')
        self.skin.update_actions();self.timer=self.app.after(100,self.tick)

    def close(self):
        if self.close_timer:self.app.after_cancel(self.close_timer);self.close_timer=None
        self.closing=True;self.skin.dismiss();self.stop()
        if self.local_starting or (self.worker and self.worker.poll() is None):
            self.close_timer=self.app.after(200,self.close);return
        self.app.after_cancel(self.timer);self.app.after_cancel(self.tray_timer)
        for border in self.skin.borders:
            if border._after:self.app.after_cancel(border._after);border._after=None
        self.tray.close();self.connection=None;self.secret=None;self.password.set('');self.app.destroy()


if __name__=='__main__':
    app=tk.Tk();Window(app);app.mainloop()
