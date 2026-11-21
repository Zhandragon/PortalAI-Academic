"""Gated tool trees that remain owned after a launching shell exits.

Completion is not a release of ownership. Stop, logout, controller exit and
failed checks close the OS job, including detached descendants. No PID lookup.
"""
import json
import subprocess
import threading
import time
from pathlib import Path


class ToolProcess:
    def __init__(self, root, command, *, cwd, env, check, shell=False,
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, python=None, monitor=True, inherited=False):
        from mission_supervisor import WorkerJob
        from platform_runtime import python_path, worker_process_options
        self.root = Path(root)
        self.check_owner = check
        self.lock = threading.RLock()
        self.job = None
        self.process = None
        self.closed = False
        self.error = None
        self.monitor = monitor
        self.started = False
        self.inherited = inherited
        if inherited:self.monitor=False  # The gated mission supervisor owns this tree.
        check()
        try:
            self.process = subprocess.Popen(
                [str(python or python_path(self.root)), '-B', '-I', str(Path(__file__).with_name('tool_process_worker.py'))],
                cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                text=text, **({'encoding':'utf-8','errors':'replace'} if text else {}),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), **({} if inherited else worker_process_options()))
            if not inherited:self.job = WorkerJob(self.process)
            check()
            # The caller registers this resource, then opens the gate under its
            # cancellation lock. A closed resource can never open its gate.
            self.payload = json.dumps({'command':command, 'shell':shell})+'\n'
            if len(self.payload.encode('utf-8')) > 1024*1024:
                raise ValueError('Tool command exceeds the launch limit')
        except BaseException:
            self.close()
            raise

    def start(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('Tool startup cancelled')
            self.check_owner()
            stream = self.process.stdin
            stream.write(self.payload if self.process.text_mode else self.payload.encode('utf-8'))
            stream.flush()
            stream.close()
            self.process.stdin = None
            self.started = True
            del self.payload
            if self.monitor:threading.Thread(target=self._watch, daemon=True, name='PortalAI-tool-owner').start()
            return self.process

    def check(self):
        with self.lock:
            if self.error:
                raise RuntimeError('Tool cancelled; its outcome may be uncertain') from self.error
            self.check_owner()
            if self.job and not self.closed:
                self.job.check()

    def _watch(self):
        try:
            while True:
                with self.lock:
                    if self.closed:
                        return
                    self.check_owner()
                    if self.process.poll() is not None and not self.job.active():
                        break
                    self.job.check()
                time.sleep(.1)
        except BaseException as exc:
            self.error = exc
        finally:
            self.close()
            # UI resource registry is optional for CLI mission workers.
            try:
                from workspace_services import unregister
                unregister(self.root, self)
            except ImportError:
                pass

    def close(self):
        with self.lock:
            if self.closed:
                return
            if self.job:
                self.job.close()
            p = self.process
            if p:
                if p.poll() is None:
                    p.kill()  # Popen owns its original process handle.
                p.wait(timeout=10)
                if p.stdin:
                    p.stdin.close()
                    p.stdin = None
                if not self.started:
                    for stream in (p.stdout,p.stderr):
                        if stream:stream.close()
            self.closed = True
