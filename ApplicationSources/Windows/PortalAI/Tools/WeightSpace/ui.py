"""Lightweight standalone Tk utility; work runs in owned background processes."""
import argparse,json,os,queue,re,sys,threading,time,uuid
from pathlib import Path
import tkinter as tk
from tkinter import filedialog,messagebox,simpledialog,ttk
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(HERE))
from run_owned import run

BG='#111719';PANEL='#1b2528';FG='#eee7da';GOLD='#d4b571';TURQUOISE='#43c7bd'

class Editor:
    def __init__(self,root,home):
        self.root=root;self.home=home;self.events=queue.Queue();self.busy=False;self.cancel=threading.Event();self.current=None;self.closing=False;self.last_log_size=-1;self.baseline_report=None;self.campaign='default'
        campaign_file=home/'campaign.json'
        if campaign_file.is_file():
            try:
                identifier=json.loads(campaign_file.read_text())['id']
                if re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',identifier):self.campaign=identifier
            except (OSError,ValueError,KeyError,TypeError):pass
        root.title('PortalAI • Weight-Space Editor');root.geometry('860x660');root.minsize(720,560);root.configure(bg=BG)
        style=ttk.Style(root);style.theme_use('clam');style.configure('TFrame',background=BG);style.configure('TLabel',background=BG,foreground=FG)
        style.configure('TButton',background=PANEL,foreground=GOLD,padding=8);style.map('TButton',background=[('active','#294044')])
        style.configure('TEntry',fieldbackground=PANEL,foreground=FG,insertcolor=FG)
        body=ttk.Frame(root,padding=22);body.pack(fill='both',expand=True);body.columnconfigure(1,weight=1)
        tk.Label(body,text='PORTALAI  /  WEIGHT-SPACE EDITOR',bg=BG,fg=GOLD,font=('Segoe UI',17,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,9))
        tk.Label(body,text='Diagnose a failure. Test a targeted subtraction. Keep only proven improvements.',bg=BG,fg=TURQUOISE,font=('Segoe UI',10)).grid(row=1,column=0,columnspan=3,sticky='w',pady=(0,18))
        self.model=tk.StringVar();self.recipe=tk.StringVar();self.cases=tk.StringVar();self.candidate=tk.StringVar()
        for index,(title,var,kind) in enumerate([('Model (.gguf)',self.model,'model'),('Edit recipe (.json)',self.recipe,'recipe'),('Task set (.json)',self.cases,'cases'),('Candidate (.gguf)',self.candidate,'candidate')],2):
            ttk.Label(body,text=title).grid(row=index,column=0,sticky='w',padx=(0,10),pady=6)
            ttk.Entry(body,textvariable=var).grid(row=index,column=1,sticky='ew',pady=6)
            ttk.Button(body,text='Choose…',command=lambda v=var,k=kind:self.choose(v,k)).grid(row=index,column=2,padx=(8,0))
        actions=ttk.Frame(body);actions.grid(row=6,column=0,columnspan=3,sticky='ew',pady=(15,12));self.buttons=[]
        for title,action in [('Inspect model','inspect'),('Evaluate original','evaluate'),('Locate failure sites','diagnose'),('Create candidate','edit'),('Compare candidate','compare')]:
            button=ttk.Button(actions,text=title,command=self.start_diagnosis if action=='diagnose' else lambda a=action:self.start(a));button.pack(side='left',padx=(0,6));self.buttons.append(button)
        self.profile=tk.StringVar();self.profile_ids={}
        ttk.Label(body,text='Saved edit profile').grid(row=7,column=0,sticky='w')
        self.profile_combo=ttk.Combobox(body,textvariable=self.profile,state='readonly',postcommand=self.refresh_profiles)
        self.profile_combo.grid(row=7,column=1,columnspan=2,sticky='ew')
        profiles=ttk.Frame(body);profiles.grid(row=8,column=0,columnspan=3,sticky='ew',pady=(8,10))
        for title,action in [('Save candidate as profile','save-profile'),('Prepare selected','prepare-profile'),('Clear prepared copy','clear-prepared')]:
            button=ttk.Button(profiles,text=title,command=lambda a=action:self.start(a));button.pack(side='left',padx=(0,6));self.buttons.append(button)
        self.refresh_profiles()
        self.status=tk.StringVar(value='Ready. Original models stay unchanged; working files remain on this portable drive.')
        ttk.Label(body,textvariable=self.status,wraplength=650).grid(row=9,column=0,columnspan=3,sticky='w',pady=(0,10))
        body.rowconfigure(10,weight=1)
        self.output=tk.Text(body,height=15,bg=PANEL,fg=FG,insertbackground=FG,relief='flat',wrap='word',font=('Consolas',10),state='disabled')
        self.output.grid(row=10,column=0,columnspan=3,sticky='nsew')
        footer=ttk.Frame(body);footer.grid(row=11,column=0,columnspan=3,sticky='ew',pady=(12,0))
        self.stop=ttk.Button(footer,text='Stop',command=self.cancel.set,state='disabled');self.stop.pack(side='left')
        ttk.Button(footer,text='Open work folder',command=self.open_work).pack(side='left',padx=8)
        ttk.Button(footer,text='Method & task format',command=self.guide).pack(side='left')
        self.new_campaign=ttk.Button(footer,text='New campaign',command=self.reset_campaign);self.new_campaign.pack(side='left',padx=8)
        ttk.Button(footer,text='Close',command=self.close).pack(side='right')
        self.show('Use a recipe measured from the selected model’s own activations. A recipe’s model checksum must match.\n\nNative evaluation: Windows NVIDIA, compatible GGUF architectures. Editing: supported dense MLP quantizations. Other formats are refused explicitly.\n\nCandidate creation requires one model-sized copy and preserves an 80 GiB free-space reserve. Compare on unseen tasks; this utility never automatically replaces a live model.')
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(150,self.poll)

    def choose(self,var,kind):
        if self.busy:return
        suffix='*.gguf' if kind in ('model','candidate') else '*.json'
        path=filedialog.askopenfilename(parent=self.root,title='Choose '+kind,initialdir=ROOT/'LLM/models' if kind=='model' else self.home,filetypes=[('Model or task file',suffix)])
        if path:var.set(path)

    def show(self,text):
        self.output.configure(state='normal');self.output.delete('1.0','end');self.output.insert('1.0',text[-18000:]);self.output.configure(state='disabled')

    def start(self,action):
        if self.busy:return
        request={'action':action,'model':self.model.get(),'campaign':self.campaign}
        if action=='diagnose':request['baseline_report']=self.baseline_report
        for key in (('recipe',) if action=='edit' else ('recipe','candidate') if action=='save-profile' else ('cases','candidate') if action=='compare' else ('cases',) if action=='evaluate' else ()):
            request[key]=getattr(self,key).get()
        if any(not Path(value).is_file() for key,value in request.items() if key not in ('action','campaign')):
            self.status.set('Choose all required existing files for this action.');return
        if action in ('prepare-profile','clear-prepared'):
            request['profile_id']=self.profile_ids.get(self.profile.get())
            if not request['profile_id']:self.status.set('Choose a saved profile first.');return
        if action=='save-profile':
            label=simpledialog.askstring('Save weight-edit profile','Name this experimental profile:',parent=self.root,initialvalue=Path(self.recipe.get()).stem)
            if label is None:return
            request['label']=label
        work=self.home/'work'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);work.mkdir(parents=True)
        path=work/'request.json';path.write_text(json.dumps(request,indent=2),encoding='utf-8')
        self.current=work;self.busy=True;self.cancel.clear();self.last_log_size=-1;self.status.set('Working independently. You can keep using the interface or stop this run.')
        for button in self.buttons:button.configure(state='disabled')
        self.stop.configure(state='normal')
        def operation():
            try:
                code=run(HERE/'utility_worker.py',[path],work/'worker.log',cancel=self.cancel)
                self.events.put(('finished',code))
            except BaseException as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=operation,daemon=True).start()

    def poll(self):
        if self.busy and self.current:
            log=self.current/'worker.log'
            if log.exists() and log.stat().st_size!=self.last_log_size:
                self.last_log_size=log.stat().st_size
                with log.open('rb') as stream:
                    stream.seek(max(0,log.stat().st_size-18000));self.show(stream.read(18000).decode('utf-8',errors='replace'))
        try:
            kind,value=self.events.get_nowait();self.busy=False
            for button in self.buttons:button.configure(state='normal')
            self.stop.configure(state='disabled')
            self.status.set('Completed. Review the saved evidence.' if kind=='finished' and value==0 else 'Stopped or failed. Original model unchanged. '+str(value))
            if self.current and kind=='finished' and value==0:
                inspect=self.current/'inspection.json';report=self.current/'report.json';profile_result=self.current/'profile-result.json'
                if profile_result.is_file():
                    result=json.loads(profile_result.read_text());self.refresh_profiles(result.get('id') or result.get('profile_id'))
                    lines=[result['message'],'','Experimental profiles can improve some tasks and regress on others. No automatic retry or completed-tool replay is enabled.']
                    if 'patch_bytes' in result:lines+=['',f"Compact patch: {result['patch_bytes']/1024**2:.2f} MiB",'Profile: '+result['label']]
                    if 'candidate' in result:lines+=['','Prepared model: '+result['candidate']]
                    self.show('\n'.join(lines))
                elif inspect.is_file():
                    result=json.loads(inspect.read_text());sites=result['dense_mlp_sites'];eligible=sum(site['editable'] for site in sites)
                    lines=['Model inspection complete','',f"Architecture: {result['architecture']}",f'Compatible dense MLP sites: {eligible} of {len(sites)}',
                           'Model checksum: '+result['model_sha256'],'','Choose a discovery task set and evaluate the original before proposing any edits.','',
                           'Available sites:']
                    lines.extend(f"  {site['name']}  ·  {site['quantization']}  ·  {site['shape'][0]} × {site['shape'][1]}" for site in sites)
                    self.show('\n'.join(lines))
                elif report.is_file():
                    result=json.loads(report.read_text());lines=['Evaluation complete','']
                    for arm,score in result.get('scores',{}).items():lines.append(f"{arm.title()}: {score['correct']} / {score['cases']} correct")
                    if 'paired' in result:
                        paired=result['paired'];lines.extend(['',f"Rescues: {paired['rescues']}  ·  Regressions: {paired['regressions']}",f"Paired accuracy change: {paired['gain']:+.1%}",f"95% interval: {paired['lower_95']:+.1%} to {paired['upper_95']:+.1%}"])
                    if 'recipes' in result:lines.extend(['Proposed recipes:',*result['recipes'],'','These are correlation-based hypotheses. Causal dose and random controls are still required.'])
                    lines.extend(['','Original model unchanged. Open the work folder for detailed evidence.']);self.show('\n'.join(lines))
            if self.current and (self.current/'candidate.gguf').is_file():self.candidate.set(str(self.current/'candidate.gguf'))
            if self.current and (self.current/'candidate-site-1.json').is_file():self.recipe.set(str(self.current/'candidate-site-1.json'))
        except queue.Empty:pass
        if self.closing and not self.busy:self.root.destroy();return
        self.root.after(200,self.poll)

    def open_work(self):
        path=self.current or self.home;os.startfile(str(path))
    def refresh_profiles(self,selected=None):
        from weight_edit_profiles import catalog
        selected=selected or self.profile_ids.get(self.profile.get())
        self.profile_ids={('Prepared' if row['prepared'] else 'Not prepared')+' · '+row['label']+' · '+row['id']:row['id'] for row in catalog(ROOT)}
        self.profile_combo.configure(values=list(self.profile_ids))
        self.profile.set(next((label for label,identifier in self.profile_ids.items() if identifier==selected),next(iter(self.profile_ids),'')))
    def guide(self):
        os.startfile(str(HERE/'README.html'))
    def start_diagnosis(self):
        if self.busy:return
        path=filedialog.askopenfilename(parent=self.root,title='Choose a completed discovery report.json',initialdir=self.home/'work',filetypes=[('Saved report','report.json')])
        if path:self.baseline_report=path;self.start('diagnose')
    def reset_campaign(self):
        if self.busy:return
        from experiment import atomic_json
        identifier=uuid.uuid4().hex
        try:atomic_json(self.home/'campaign.json',{'id':identifier})
        except (OSError,ValueError) as exc:self.status.set('Could not save the new campaign: '+str(exc));return
        self.campaign=identifier;self.status.set('New campaign started. Earlier evidence and tool budgets remain saved.')
    def close(self):
        self.closing=True
        if self.busy:self.cancel.set();self.status.set('Stopping the owned worker before closing…')
        else:self.root.destroy()

def main(home=None):
    if home is None:home=ROOT.parent/'Utilities/PortalAI Weight-Space Editor'
    home=Path(home).resolve();home.mkdir(parents=True,exist_ok=True)
    app=tk.Tk();Editor(app,home);app.mainloop()

if __name__=='__main__':main()
