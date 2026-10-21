"""Separately launched, explicitly armed portable recovery helper (Windows)."""
from pathlib import Path
import json
import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog,ttk

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
from host_runtime import package_paths,resolve_target,target_valid
sys.path[:0]=package_paths()
from connection_vault import unlock
from recovery_transport import pairing_request
from recovery_runtime import RecoveryRunner

MESSAGES={
    'online':'Armed and connected to HA. Waiting for an explicit Recover apps command.',
    'unavailable':'Recovery receiver unavailable or not approved. Helper is waiting; no apps are restarted automatically.',
    'recovering':'HA requested recovery. Checking owned processes and launch guards...',
    'launch_requested':'Launch requested. Open the existing HA projection card and use the normal PortalAI login/recovery screen.',
    'already_running':'Projection and PortalAI are already running. No duplicate was launched.',
    'projection_restored_review_workers':'Projection is available or was launched. PortalAI still has workers/closing state: inspect it and use its existing explicit Force Shutdown only if appropriate.',
    'refused_or_uncertain':'Recovery refused or uncertain. Inspect app/drive state; no force-kill or task replay was attempted.',
    'arming_failed':'Could not arm: check drive, target, source integrity, or another already-armed recovery helper.',
    'shutdown_failed':'Could not confirm the helper-owned projection worker stopped. Keep this window open and retry Disarm.',
    'disarmed':'Recovery disarmed. Any projection worker started by this helper has been stopped; PortalAI keeps its normal lifecycle.'}

class Window:
    def __init__(self,app):
        self.app=app;self.runner=None;self.events=queue.Queue();self.closing=False
        self.path=tk.StringVar();self.password=tk.StringVar();self.status=tk.StringVar(value='Disarmed. Select an existing saved projection connection.')
        app.title('PortalAI Portable Recovery');app.geometry('780x660');app.minsize(620,520)
        page=ttk.Frame(app,padding=18);page.pack(fill='both',expand=True);page.columnconfigure(1,weight=1);page.rowconfigure(6,weight=1)
        ttk.Label(page,text='Portable HA recovery',font=('Segoe UI',20,'bold')).grid(row=0,column=0,columnspan=3,sticky='w')
        self.intro=ttk.Label(page,text='Keep this separate helper open. It survives companion/app crashes, but not Windows freezes or loss of this SSD.',wraplength=720)
        self.intro.grid(row=1,column=0,columnspan=3,sticky='ew',pady=10)
        ttk.Label(page,text='Saved connection').grid(row=2,column=0,sticky='w')
        self.entry=ttk.Entry(page,textvariable=self.path);self.entry.grid(row=2,column=1,sticky='ew')
        self.browse_button=ttk.Button(page,text='Browse',command=self.browse);self.browse_button.grid(row=2,column=2,padx=6)
        ttk.Label(page,text='Projection unlock password').grid(row=3,column=0,sticky='w',pady=8)
        self.password_entry=ttk.Entry(page,textvariable=self.password,show='*');self.password_entry.grid(row=3,column=1,sticky='ew')
        controls=ttk.Frame(page);controls.grid(row=4,column=0,columnspan=3,sticky='w',pady=8)
        self.arm_button=ttk.Button(controls,text='Unlock and arm',command=self.arm);self.arm_button.pack(side='left')
        ttk.Button(controls,text='Disarm',command=self.disarm).pack(side='left',padx=8)
        self.status_label=ttk.Label(page,textvariable=self.status,wraplength=720)
        self.status_label.grid(row=5,column=0,columnspan=3,sticky='ew',pady=8)
        body=ttk.Frame(page);body.grid(row=6,column=0,columnspan=3,sticky='nsew')
        self.text=tk.Text(body,wrap='word',height=18)
        scroll=ttk.Scrollbar(body,orient='vertical',command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set);scroll.pack(side='right',fill='y');self.text.pack(side='left',fill='both',expand=True)
        page.bind('<Configure>',lambda event:[label.configure(wraplength=max(280,event.width-44)) for label in (self.intro,self.status_label)])
        self.show('Install RecoveryHelper/ha/custom_components/portalai_recovery on HA from a trusted device, add portalai_recovery: to configuration.yaml, and restart HA.\n\nUnlock here, then approve the PUBLIC pairing JSON below using portalai_recovery.pair_device. Existing projection pairing is preserved. No HA password or API token is needed.\n\nDisarm/closing stops only a projection worker this helper started. PortalAI must still use its normal account shutdown/sealing flow.')
        app.protocol('WM_DELETE_WINDOW',self.close);self.timer=app.after(100,self.tick)
    def show(self,value):
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',value);self.text.configure(state='disabled')
    def browse(self):
        if self.runner is not None:return
        chosen=filedialog.askopenfilename(parent=self.app,initialdir=MODULE/'Connections',title='Existing encrypted projection connection')
        if chosen:self.path.set(chosen)
    def arm(self):
        if self.runner is not None or self.closing:return
        connection=None
        try:
            if os.name!='nt':raise RuntimeError('Windows only')
            path=Path(self.path.get())
            if path.resolve().parent!=(MODULE/'Connections').resolve():raise ValueError('Select the existing connection in this companion Connections folder')
            connection=unlock(path,self.password.get());self.password.set('')
            if not target_valid(resolve_target(connection['target'])):raise ValueError('Saved PortalAI target unavailable; update it through Projection first')
            public=pairing_request(connection)
            self.show('PUBLIC recovery pairing (approve once on the trusted HA device):\n\n'+json.dumps(public,indent=2)+
                '\n\nDashboard button:\n\ntype: button\nname: Recover PortalAI apps\nicon: mdi:lifebuoy\ntap_action:\n  action: perform-action\n  perform_action: portalai_recovery.recover_apps\n  data:\n    device_id: '+public['device_id']+
                '\n  confirmation:\n    text: Restore projection and open PortalAI login without killing processes or replaying work?\n')
            self.runner=RecoveryRunner(connection,self.events.put);self.runner.start()
            for widget in (self.arm_button,self.entry,self.browse_button,self.password_entry):widget.configure(state='disabled')
            self.status.set('Arming the separate recovery channel...')
        except Exception:self.status.set('Could not unlock/arm. Check the selected connection, password, target and drive.');self.password.set('')
        finally:
            if connection is not None:connection.clear()
    def disarm(self):
        if self.runner is not None:self.runner.disarm();self.status.set('Disarming; waiting for any admitted recovery and owned projection worker to stop...')
    def close(self):self.closing=True;self.disarm()
    def tick(self):
        while not self.events.empty():
            event=self.events.get_nowait();self.status.set(MESSAGES[event])
        if self.runner is not None and not self.runner.thread.is_alive() and not self.runner.cleanup_failed:
            self.runner=None
            for widget in (self.arm_button,self.entry,self.browse_button,self.password_entry):widget.configure(state='normal')
        if self.closing and self.runner is None:self.app.destroy();return
        self.timer=self.app.after(100,self.tick)

if __name__=='__main__':
    app=tk.Tk();Window(app);app.mainloop()
