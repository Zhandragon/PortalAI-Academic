"""Optional bounded CPU import overlap; never loads weights or allocates VRAM."""
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid


class PreparedVoice:
    def __init__(self,root,check):
        self.root=Path(root).resolve();self.check=check;self.process=self.job=None
        self.lock=threading.RLock();self.taken=False;self.closed=False;self.started=time.monotonic()
        from media_paths import media_runtime
        self.logpath=media_runtime(self.root)/('voice-imports-'+uuid.uuid4().hex+'.log')

    @classmethod
    def start(cls,root,check):
        from runtime_policy import detect_hardware,GIB,portable_env,require_space
        from platform_runtime import python_path,worker_process_options
        from mission_supervisor import WorkerJob
        from workspace_services import register
        check();hw=detect_hardware()
        # On small/shared-memory systems leave all RAM to inference and the GUI.
        if os.name!='nt' or hw['ram_total_bytes']<16*GIB or hw['ram_available_bytes']<8*GIB or not hw.get('gpus'):return None
        if not any(g.get('backend','cuda')=='cuda' and g.get('index',0)==0 for g in hw['gpus']):return None
        require_space(root,1024**2,for_outputs=True);ticket=cls(root,check);ticket.logpath.parent.mkdir(parents=True,exist_ok=True)
        env=portable_env(ticket.root);env.update(PORTALAI_TORCH_BACKEND='cuda',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
        try:
            with ticket.logpath.open('xb') as log:
                ticket.process=subprocess.Popen([str(python_path(ticket.root)),'-B','-I',str(ticket.root/'Agent/nice_voice.py'),'--warm'],
                    cwd=ticket.root,env=env,stdin=subprocess.PIPE,stdout=log,stderr=log,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),**worker_process_options())
                ticket.job=WorkerJob(ticket.process);ticket.job.limit_memory(2*GIB);register(ticket.root,ticket)
                check();ticket.process.stdin.write(b'warm\n');ticket.process.stdin.flush()
            threading.Thread(target=ticket._watch,name='PortalAI-voice-import-guard',daemon=True).start();return ticket
        except BaseException:ticket.close();raise

    def _watch(self):
        try:
            while True:
                with self.lock:
                    if self.taken or self.closed:return
                    self.check()
                    if self.process.poll() is not None or time.monotonic()-self.started>120 or self.logpath.stat().st_size>1024**2:break
                    from runtime_policy import memory_info
                    if memory_info()[1]<4*1024**3:break
                time.sleep(.5)
        except Exception:pass
        self.close()

    def take(self,root,request,check,device):
        from workspace_services import unregister
        with self.lock:
            if self.closed or self.taken or self.process.poll() is not None or device!='cuda' or Path(root).resolve()!=self.root:
                self.close();return None
            check();self.check();self.job.limit_memory(16*1024**3)
            self.process.stdin.write((str(request)+'\n').encode());self.process.stdin.flush();self.process.stdin.close()
            self.taken=True;unregister(self.root,self)
            result=(self.process,self.job);self.job=None;return result

    def close(self):
        from workspace_services import unregister
        with self.lock:
            if self.closed or self.taken:return
            self.closed=True;unregister(self.root,self)
            if self.job:self.job.close();self.job=None
            if self.process:
                if self.process.poll() is None:self.process.kill()
                self.process.wait(timeout=5)
                try:self.process.stdin.close()
                except (OSError,ValueError):pass
            self.logpath.unlink(missing_ok=True)
