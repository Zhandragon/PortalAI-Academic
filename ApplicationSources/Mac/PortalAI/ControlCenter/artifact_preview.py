"""Gated preview worker lifetime, tied to account/Stop and the Workspace sheet."""
import json
import os
import queue
import subprocess
import threading
import time
from workspace_services import register,unregister


class Preview:
    def __init__(self,runtime,check):
        self.runtime=runtime;self.check=check;self.process=None;self.job=None;self.lock=threading.RLock()

    def open(self,revision,*,headless=False):
        from native_chat import clean_env
        from mission_supervisor import WorkerJob
        from platform_runtime import worker_process_options
        self.close();self.check();rt=self.runtime
        payload=json.dumps({k:revision[k] for k in ('title','kind','content')}|{'headless':headless})
        with self.lock:
            self.check()
            self.process=subprocess.Popen([str(rt.boot),'-B','-I',str(rt.root/'Agent/artifact_preview_worker.py')],cwd=rt.root,
                env=clean_env(rt.root,profile=rt.profile),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),**worker_process_options())
            process=self.process
            try:
                self.job=WorkerJob(process);self.job.limit_memory(2*1024**3);register(rt.root,self)
                process.stdin.write(payload+'\n');process.stdin.flush()
            except BaseException:self.close();raise
        replies=queue.Queue(1);errors=[]
        def output():
            try:replies.put(process.stdout.readline(16384))
            except (OSError,ValueError):replies.put('')
        def diagnostic():
            try:
                while value:=process.stderr.read(1024):errors[:]=[(''.join(errors)+value)[-4096:]]
            except (OSError,ValueError):pass
        threading.Thread(target=output,daemon=True).start();threading.Thread(target=diagnostic,daemon=True).start()
        deadline=time.monotonic()+45
        try:
            while time.monotonic()<deadline:
                self.check()
                try:line=replies.get(timeout=.1)
                except queue.Empty:continue
                if not line:raise RuntimeError('Preview worker failed: '+''.join(errors)[-2000:])
                result=json.loads(line)
                if not result.get('ready'):raise RuntimeError('Preview did not become ready')
                self.check();return {**result,'artifact':revision['artifact'],'revision':revision['id']}
            raise TimeoutError('Preview startup timed out')
        except BaseException:self.close();raise

    def close(self):
        with self.lock:
            process=self.process;job=self.job;self.process=None;self.job=None
            unregister(self.runtime.root,self)
            if process:
                try:process.stdin.close()
                except (OSError,ValueError):pass
            if job:job.close(completed=False)
            if process:
                if process.poll() is None:process.kill()
                process.wait(timeout=10)
                for stream in (process.stdout,process.stderr):
                    try:stream.close()
                    except (OSError,ValueError):pass
