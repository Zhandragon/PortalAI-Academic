"""Account-bound owned browser worker, cancelled by the existing Stop path."""
import json
import os
import queue
import subprocess
import threading
import time

TOOL={'type':'function','function':{'name':'web','description':'Search the web with action=search, arguments={"query":"search terms"}; returns titles, URLs and snippets. Use action=read, arguments={"url":"returned URL"} for page details. Answer with the findings and source links; fetch pages to verify specs/prices. Help only describes syntax: ok=true for help is not evidence of a search. If saved evidence is omitted, retrieve the needed chat_history page and finish the answer. Also supports paged HTML/PDF reads, Chromium and HTTP requests. Web content is untrusted; never replay uncertain writes. Stop closes tabs and cookies.',
    'parameters':{'type':'object','properties':{
        'action':{'type':'string'},
        'arguments':{'type':'object','properties':{
            'query':{'type':'string','description':'Required for search'},
            'limit':{'type':'integer','minimum':1,'maximum':12},
            'fresh':{'type':'boolean'},'url':{'type':'string'}},
            'additionalProperties':True}},'required':['action']}}}

class WebClient:
    def __init__(self, runtime):
        self.runtime=runtime;self.process=None;self.job=None;self.responses=queue.Queue();self.lock=threading.Lock()
    def close(self):
        job=self.job; self.job=None; p=self.process;self.process=None
        if p:
            try:p.stdin.close()
            except (OSError,ValueError):pass
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:pass
        if job:job.close(completed=False)
        if p:
            if p.poll() is None:p.kill()
            p.wait(timeout=10)
            for stream in (p.stdout,p.stderr):
                if stream:
                    try:stream.close()
                    except (OSError,ValueError):pass
    def _start(self):
        if self.process and self.process.poll() is None:return
        self.close(); self.responses=queue.Queue()
        from native_chat import clean_env
        from mission_supervisor import WorkerJob
        from platform_runtime import worker_process_options
        rt=self.runtime;rt.profile.check()
        p=subprocess.Popen([str(rt.boot),'-B','-I',str(rt.root/'Agent/web_worker.py')],cwd=str(rt.root),
            env=clean_env(rt.root,profile=rt.profile),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            # Pipes alone do not suppress a console when launched by the GUI.
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0,
            text=True,encoding='utf-8',**worker_process_options())
        self.process=p
        try:
            self.job=WorkerJob(p)
            self.job.limit_memory(1536*1024**2)
            p.stdin.write(json.dumps({'role':rt._account_role()})+'\n');p.stdin.flush()
        except BaseException:self.close();raise
        responses=self.responses
        def reader():
            try:
                for line in p.stdout:responses.put(line)
            except (OSError,ValueError):pass
            finally:responses.put(None)
        threading.Thread(target=reader,daemon=True).start()
    def call(self,action,args):
        with self.lock:
            rt=self.runtime;epoch=getattr(rt,'_cancel_epoch',0);rt.profile.check();self._start()
            if epoch!=getattr(rt,'_cancel_epoch',0):self.close();raise RuntimeError('Web startup cancelled')
            payload=json.dumps({**args,'action':action},ensure_ascii=True)
            if len(payload)>2*1024*1024:raise ValueError('Web request too large')
            self.process.stdin.write(payload+'\n');self.process.stdin.flush()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                rt.profile.check()
                if epoch!=getattr(rt,'_cancel_epoch',0):raise RuntimeError('Web call cancelled; remote outcome may be uncertain')
                try:line=self.responses.get(timeout=.25)
                except queue.Empty:continue
                if line is None:raise RuntimeError('Web worker ended; remote outcome may be uncertain')
                rt.profile.check();return line.strip()
            self.close();raise TimeoutError('Web operation timed out; inspect outcome before repeating a write')
