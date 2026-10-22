"""Background missing-file monitor and explicit verified-repair sheet."""
import queue
import tkinter as tk
from elegant_native_ui import ElegantButton
from rounded_text import RoundedText
import executable_recovery as recovery

GUIDANCE=(
    'A required runtime file has disappeared. Review the file list and your antivirus alert. '
    'A matching installation checksum identifies the original file; it does not establish that a detection is false.\n\n'
    'If you trust this PortalAI installation, temporarily turn off the relevant antivirus shield, '
    'then click Proceed to restore the verified backup. For Avast, review Protection > Quarantine and its shield controls. '
    'PortalAI will not change antivirus settings or add exclusions.\n\n'
    'Re-enable protection immediately after repair. If the file is quarantined again, review the detection with '
    'the antivirus vendor instead of repeatedly restoring it. Restoration does not start the engine or resume a mission.'
)

def description(report):
    lines=[GUIDANCE,'','FILES']
    for row in report.get('missing',[]):
        lines.extend([row['path'],row.get('evidence','Cause not confirmed.'),
                      'Verified backup available' if row.get('backup_verified') else 'No usable verified backup; repair from the official installer or review quarantine.',
                      'SHA-256: '+row['sha256'],''])
    return '\n'.join(lines)

class RecoveryUI:
    def __init__(self,app,root,*,jobs,colors,open_panel,close_panel,can_show,guard_factory,log):
        self.app=app;self.root=root;self.jobs=jobs;self.colors=colors
        self.open_panel=open_panel;self.close_panel=close_panel;self.can_show=can_show
        self.guard_factory=guard_factory;self.log=log;self.events=queue.Queue()
        self.busy=False;self.seen=set();self.pending=None;self.last_report=None
        app.after(500,self.pump);app.after(3000,self.periodic)

    def periodic(self):
        self.request()
        self.app.after(30000,self.periodic)

    def request(self,manual=False):
        if self.busy:return
        try:guard=self.guard_factory(False);guard()
        except (PermissionError,RuntimeError):return
        self.busy=True
        def work():
            try:
                report=recovery.inspect(self.root,verify_backups=True);guard()
                self.events.put(('scan',report,manual,guard))
            except Exception as exc:self.events.put(('error',str(exc),manual,guard))
        try:self.jobs.thread(target=work,name='PortalAIExecutableCheck',daemon=True).start()
        except RuntimeError:self.busy=False

    def pump(self):
        try:
            while True:
                kind,data,manual,guard=self.events.get_nowait();self.busy=False
                try:guard()
                except (PermissionError,RuntimeError):continue
                if kind=='scan':
                    self.last_report=data
                    keys={(r['path'],r['sha256']) for r in data['missing']}
                    self.seen.intersection_update(keys)
                    if keys-self.seen or manual:self.pending=data
                elif kind=='restored':
                    text='Restored '+str(len(data['restored']))+' file(s). Re-enable your antivirus protection now.\n\n'
                    text+='\n'.join(data['restored'])
                    if data['errors']:text+='\n\nCould not restore:\n'+'\n'.join(r['path']+': '+r['error'] for r in data['errors'])
                    text+='\n\nNo engine or mission was started. Retry Startup or explicitly enable the mission when ready.'
                    self.message('Executable recovery',text)
                elif manual:self.message('Executable recovery',str(data))
                else:self.log('Executable recovery check: '+str(data))
        except queue.Empty:pass
        if self.pending is not None and self.can_show():
            data=self.pending;self.pending=None
            try:self.guard_factory(False)()
            except (PermissionError,RuntimeError):pass
            else:
                self.seen.update((r['path'],r['sha256']) for r in data['missing'])
                self.show(data)
        self.app.after(500,self.pump)

    def message(self,title,text):
        body=self.open_panel(title,width=.84,height=.8);colors=self.colors()
        viewer=RoundedText(body,palette=colors,scrollbars=True,wrap='word',font=('Segoe UI',10),bg=colors.get('model_bg',colors['panel']),fg=colors['text'],insertbackground=colors['text'])
        viewer.pack(fill='both',expand=True,padx=16,pady=14);viewer.insert('1.0',text);viewer.configure(state='disabled')
        ElegantButton(body,text='Close',command=self.close_panel,bg=colors['button'],fg=colors['text']).pack(pady=(0,12))

    def show(self,report):
        if not report['missing']:
            self.message('Executable recovery',f"All {report['registered']} registered runtime files are present.\n\n"+
                         ('No backup inventory is available. Use the updated installer or reviewed update handoff to provision verified backups.' if not report['registered'] else 'Backups are restored only for missing files after you click Proceed.'))
            return
        body=self.open_panel('Missing executables — review antivirus',width=.9,height=.9);colors=self.colors()
        row=tk.Frame(body,bg=colors['bg']);row.pack(fill='x',padx=16,pady=(12,4))
        viewer=RoundedText(body,palette=colors,scrollbars=True,wrap='word',font=('Segoe UI',10),bg=colors.get('model_bg',colors['panel']),fg=colors['text'],insertbackground=colors['text'])
        viewer.pack(fill='both',expand=True,padx=16,pady=(8,14));viewer.insert('1.0',description(report));viewer.configure(state='disabled')
        paths=[r['path'] for r in report['missing'] if r.get('backup_verified')]
        proceed_guard=self.guard_factory(True)
        def proceed():
            try:guard=proceed_guard;guard()
            except (PermissionError,RuntimeError) as exc:self.message('Executable recovery',str(exc));return
            if self.busy:return
            self.busy=True;button.configure(state='disabled');cancel.configure(state='disabled')
            def work():
                try:
                    result=recovery.restore(self.root,paths,guard);guard()
                    self.events.put(('restored',result,True,guard))
                except Exception as exc:self.events.put(('error',str(exc)+'\nRe-enable antivirus protection now.',True,guard))
            try:self.jobs.thread(target=work,name='PortalAIExecutableRepair',daemon=True).start()
            except RuntimeError:self.busy=False
        button=ElegantButton(row,text='Proceed — restore backups',command=proceed,bg=colors['button'],fg=colors['text'],state='normal' if paths else 'disabled')
        button.pack(side='left',padx=(0,8))
        cancel=ElegantButton(row,text='Cancel',command=self.close_panel,bg=colors['button'],fg=colors['text']);cancel.pack(side='right')
        self.proceed_button=button
