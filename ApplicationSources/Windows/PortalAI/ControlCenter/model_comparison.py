"""Sequential text-only model comparison through existing effort admission."""
import time
from workspace_store import Workspace, read_json, identifier


class Comparisons(Workspace):
    def __init__(self,root,check=None):super().__init__(root,'Chat/Comparisons',check)
    def list(self):
        return [self.read(rid) for rid in self.records('Runs')[-100:]]
    def read(self,rid):
        row=read_json(self.path('Runs/'+identifier(rid)+'.json'))
        if row['state']=='running':row={**row,'state':'unfinished','notice':'Saved results are retained; this record alone does not prove a worker is active. Runs are never replayed automatically.'}
        return row

    def run(self,runtime,question,levels,cancel,*,original='balanced',unlocked=False):
        if not isinstance(question,str) or not 1<=len(question.strip())<=4000:raise ValueError('Comparison prompt must contain 1–4,000 characters')
        if not isinstance(levels,list) or not 2<=len(levels)<=3 or len(set(levels))!=len(levels) or any(p not in ('fast','balanced','deep') for p in levels):raise ValueError('Choose two or three different effort profiles')
        if len(self.records('Runs'))>=100:raise ValueError('Comparison archive reached 100 runs; export/review saved results before adding more')
        from chat_model_switch import prepare_chat
        from native_chat import model_id
        from capability_tools import prompt
        row={'id':self.new_id(),'question':question,'created':time.time(),'results':[],'restored':False,'state':'running'}
        path='Runs/'+row['id']+'.json';self.save(path,row);started=time.time()
        try:
            for level in levels:
                self.check()
                if cancel.is_set():raise RuntimeError('Comparison stopped')
                preparation=prepare_chat(self.root,level,unlock_slow=unlocked,cancel_event=cancel,requested_at=started)
                self.check();model=model_id();before=time.monotonic()
                answer=prompt(runtime,{'question':question},self.check)
                self.check();row['results'].append({'profile':level,'model':model,'answer':answer,'seconds':round(time.monotonic()-before,2)})
                self.save(path,row)
            row['state']='complete'
        except Exception as exc:
            row['state']='stopped_or_failed';row['error']=str(exc)[:2000]
            raise
        finally:
            # Do not resurrect a model after Stop or a changed login. Completed
            # result rows were already saved; a crash cannot rerun them.
            self.check()
            if not cancel.is_set():
                try:
                    prepare_chat(self.root,original,unlock_slow=unlocked,cancel_event=cancel,requested_at=started)
                    row['restored']=True
                except Exception as exc:
                    row['restore_error']=str(exc)[:2000]
                self.check();self.save(path,row)
        return row


def comparison_page(panel):
    from tkinter import ttk
    p=panel.pages['Compare'];store=Comparisons(panel.root,panel.check)
    panel.skin.label(p,'Compare the models selected by two or three effort profiles, one at a time. No tools or chat history are sent. Manual model overrides remain respected; profiles may select the same model.').pack(fill='x')
    question=panel.field(p,'Shared question');levels=panel.field(p,'Profiles (comma-separated)','fast, balanced')
    saved=panel.tree(p,('Question','State','ID'));answers=panel.skin.frame(p);answers.pack(fill='both',expand=True)
    def refresh():
        saved.delete(*saved.get_children())
        for row in store.list():saved.insert('','end',iid=row['id'],values=(row['question'][:80],row['state'],row['id']))
    def display(row):
        for child in answers.winfo_children():child.destroy()
        for i,result in enumerate(row['results']):
            cell=panel.skin.frame(answers);cell.grid(row=0,column=i,sticky='nsew',padx=3);answers.columnconfigure(i,weight=1)
            panel.skin.label(cell,result['profile']+' · '+result['model']+' · '+str(result['seconds'])+'s').pack(fill='x')
            text=panel.text(cell,result['answer'],9);text.pack(fill='both',expand=True)
        refresh()
    def run():
        panel.admin()
        if panel.chat and (panel.chat.busy or panel.chat.conversation_active.is_set()):raise ValueError('Stop hands-free and finish the current chat before comparing models')
        from effort_policy import load_preferences
        original=load_preferences(panel.root)['chat'];chosen=[v.strip() for v in levels.get().split(',')];q=question.get()
        panel.job(lambda:store.run(panel.runtime,q,chosen,panel.cancelled,original=original),display)
    def load():display(store.read(panel.selected(saved)))
    panel.buttons(p,[('Run sequential comparison',run),('Refresh saved results',refresh),('View selected',load)])
    panel.invoke(refresh)
