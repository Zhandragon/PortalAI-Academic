"""Bounded, owned Windows AEC capture with the same PCM interface as WinMM."""
from collections import deque
import hashlib
import json
from pathlib import Path
import subprocess
import threading
import time


class EchoCapture:
    sample_rate=16000
    channels=1
    echo_cancelled=True
    def __init__(self,root,microphone='auto',check=lambda:None):
        from mission_supervisor import WorkerJob
        from runtime_policy import portable_env
        self.root=Path(root);self.check=check;self.closed=threading.Event();self.ready=threading.Event();self.condition=threading.Condition()
        self._close_lock=threading.Lock();self._close_done=False
        self.chunks=deque(maxlen=12);self.error='';self.proc=self.job=None
        helper=self.root/'Tools/voice_echo_capture.exe';manifest=json.loads(helper.with_suffix('.json').read_text())
        if helper.stat().st_size!=manifest['bytes'] or hashlib.sha256(helper.read_bytes()).hexdigest()!=manifest['sha256']:raise RuntimeError('Echo capture helper failed integrity validation')
        check()
        try:
            self.proc=subprocess.Popen([str(helper),'--capture',microphone],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=portable_env(self.root),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.job=WorkerJob(self.proc);self.job.limit_memory(256*1024**2);check();self.proc.stdin.write(b'go\n');self.proc.stdin.flush();self.proc.stdin.close()
            self.reader=threading.Thread(target=self._read,name='PortalAI-AEC-pipe',daemon=True);self.reader.start()
            deadline=time.monotonic()+8
            while not self.ready.wait(.05):
                check()
                if self.closed.is_set() or self.proc.poll() is not None:raise RuntimeError(self.error or 'Windows echo capture could not start')
                if time.monotonic()>deadline:raise TimeoutError('Windows echo capture did not become ready')
            if self.error:raise RuntimeError(self.error)
        except BaseException:self.close();raise
    def _read(self):
        try:
            if self.proc.stdout.read(4)!=b'PAEC':raise RuntimeError('Windows echo capture returned no valid stream')
            self.ready.set()
            while not self.closed.is_set():
                raw=self.proc.stdout.read(3200)
                if len(raw)!=3200:raise RuntimeError('Echo capture ended unexpectedly')
                with self.condition:self.chunks.append(raw);self.condition.notify_all()
        except Exception as exc:
            self.error=str(exc)
            if self.proc.poll() is not None:
                self.error+=': '+self.proc.stderr.read(2048).decode('utf-8','replace')
        finally:
            self.ready.set()
            with self.condition:self.condition.notify_all()
    def read_chunk(self,timeout=.35):
        self.check()
        with self.condition:
            if not self.chunks and not self.closed.is_set() and not self.error:self.condition.wait(timeout)
            if self.error:raise RuntimeError(self.error)
            if self.closed.is_set():return b''
            return self.chunks.popleft() if self.chunks else b''
    def drain_pending(self):
        with self.condition:self.chunks.clear()
    def close(self):
        self.closed.set()
        with self.condition:self.condition.notify_all()
        # The capture loop's finally and cancellation fallback may arrive together.
        # Serialize the complete teardown so an OS job handle or pipe closes once.
        with self._close_lock:
            if self._close_done:return
            if self.job:self.job.close();self.job=None
            if self.proc:
                if self.proc.poll() is None:self.proc.kill()
                self.proc.wait(timeout=5)
                reader=getattr(self,'reader',None)
                if reader and reader is not threading.current_thread():reader.join(2)
                for pipe in (self.proc.stdin,self.proc.stdout,self.proc.stderr):
                    if pipe and not pipe.closed:pipe.close()
            self._close_done=True
