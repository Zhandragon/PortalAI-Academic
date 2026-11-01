"""Explicit text-only comparisons; ordinary chat never starts extra models."""
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

    def run_models(self,runtime,question,models,cancel,*,rounds=1,parallel=False):
        from comparison_workers import installed,plans_for,parallel_admission,ModelWorker
        from voice_memory import run_voice_stage
        from chat_model_switch import _require_idle,_owned_listener
        from concurrent.futures import ThreadPoolExecutor
        from contextlib import ExitStack
        if not isinstance(question,str) or not 1<=len(question.strip())<=4000:raise ValueError('Comparison prompt must contain 1–4,000 characters')
        choices={r['id'] for r in installed(self.root)}
        if not isinstance(models,list) or not 2<=len(models)<=3 or len(set(models))!=len(models) or any(m not in choices for m in models):raise ValueError('Choose two or three different installed model IDs')
        if type(rounds) is not int or not 1<=rounds<=3:raise ValueError('Comparison allows one to three rounds')
        if len(self.records('Runs'))>=100:raise ValueError('Comparison archive reached 100 runs')
        started=time.monotonic()
        def check():
            self.check()
            if cancel.is_set():raise RuntimeError('Comparison stopped')
            if time.monotonic()-started>600:raise TimeoutError('Comparison exceeded its ten-minute overall limit; completed answers are retained')
        def idle():
            check()
            if _owned_listener()['open']:_require_idle()
        row={'id':self.new_id(),'question':question,'created':time.time(),'models':models,'rounds':rounds,'results':[],
             'parallel_requested':bool(parallel),'state':'running','restored':False,'admission':[]}
        path='Runs/'+row['id']+'.json';self.save(path,row)
        retained=ExitStack();resident=[]
        def compare(guard):
            peers=[]
            for round_number in range(1,rounds+1):
                pending=list(models);current=[]
                while pending:
                    guard()
                    if resident:
                        plans=[w.plan for w in resident];admitted=True;reason='Reusing the two admitted workers for this bounded comparison'
                    else:
                        plans,hw=plans_for(self.root,pending[:2] if parallel else pending[:1])
                        admitted,reason=parallel_admission(plans,hw) if parallel else (False,'Sequential mode selected')
                    batch=plans if admitted else plans[:1]
                    row['admission'].append({'round':round_number,'models':[p['model']['id'] for p in batch],'parallel':admitted,'reason':reason})
                    def answer(worker):
                        before=time.monotonic();result=worker.answer(question,peers)
                        return {**result,'profile':'Round '+str(round_number),'round':round_number,'model':worker.plan['model']['id'],'seconds':round(time.monotonic()-before,2)}
                    with ExitStack() as stack:
                        owner=retained if admitted and len(models)==2 else stack
                        workers=resident or [owner.enter_context(ModelWorker(self.root,plan,guard,parallel=admitted)) for plan in batch]
                        if owner is retained:resident[:]=workers
                        if admitted:
                            with ThreadPoolExecutor(max_workers=2,thread_name_prefix='PortalAI-comparison') as pool:
                                futures=[pool.submit(answer,w) for w in workers]
                                results=[]
                                try:
                                    for future in futures:results.append(future.result())
                                except BaseException:
                                    for worker in workers:worker.close()
                                    raise
                        else:results=[answer(workers[0])]
                        for result in results:
                            guard();row['results'].append(result);current.append(result);self.save(path,row)
                    pending=pending[len(batch):]
                peers=[{'model':r['model'],'answer':r['answer'][:1000],'truncated':r.get('truncated',False)} for r in current]
            return row
        def operation(guard):
            # Both workers close before the original chat model is restored.
            with retained:return compare(guard)
        try:
            run_voice_stage(self.root,'model comparison',lambda:None,operation,check=check,handoff_check=idle,require_handoff=True)
            row.update(state='complete',restored=True,seconds=round(time.monotonic()-started,2));self.save(path,row);return row
        except BaseException as exc:
            row.update(state='stopped_or_failed',error=str(exc)[:2000])
            try:self.save(path,row)
            except Exception:pass  # A revoked profile/Stop cannot write through a stale identity.
            raise

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
    panel.skin.label(p,'Compare effort profiles or choose two or three installed model IDs. No tools or chat history are sent. Extra rounds review earlier answers, which remain unverified suggestions. Optional parallel mode requires two fully offloaded models with combined memory reserves; otherwise it runs sequentially.').pack(fill='x')
    question=panel.field(p,'Shared question');levels=panel.field(p,'Profiles (comma-separated)','fast, balanced')
    models=panel.field(p,'Installed model IDs (comma-separated)');rounds=panel.field(p,'Rounds (1–3)','1')
    import tkinter as tk
    parallel=tk.BooleanVar(value=False)
    panel.skin.check(p,'Allow two models in parallel when memory and CPU permit',parallel).pack(anchor='w')
    saved=panel.tree(p,('Question','State','ID'));answers=panel.skin.frame(p);answers.pack(fill='both',expand=True)
    def refresh():
        saved.delete(*saved.get_children())
        for row in store.list():saved.insert('','end',iid=row['id'],values=(row['question'][:80],row['state'],row['id']))
    def display(row):
        for child in answers.winfo_children():child.destroy()
        for i,result in enumerate(row['results']):
            cell=panel.skin.frame(answers);cell.grid(row=i//3,column=i%3,sticky='nsew',padx=3);answers.columnconfigure(i%3,weight=1)
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
    def run_models():
        panel.admin()
        if panel.chat and (panel.chat.busy or panel.chat.conversation_active.is_set()):raise ValueError('Stop hands-free and finish the current chat before comparing models')
        chosen=[v.strip() for v in models.get().split(',')];q=question.get();count=int(rounds.get());allow=parallel.get()
        panel.job(lambda:store.run_models(panel.runtime,q,chosen,panel.cancelled,rounds=count,parallel=allow),display)
    def catalogue():
        from comparison_workers import installed
        panel.job(lambda:installed(panel.root))
    panel.buttons(p,[('Compare effort profiles',run),('List installed models',catalogue),('Compare selected models',run_models),('Refresh saved results',refresh),('View selected',load)])
    panel.invoke(refresh)
