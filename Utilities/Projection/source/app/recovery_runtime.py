"""Explicit app recovery. Never kills PortalAI, unlocks profiles or replays work."""
from pathlib import Path
from collections import OrderedDict
import hashlib
import json
import os
import queue
import stat
import subprocess
import threading
import time
from host_runtime import MODULE,resolve_target,target_valid,input_owner,launch_options
from recovery_transport import RecoveryClient,identity

def file_digest(path,base):
    path=Path(path);base=Path(base)
    current=base
    for part in ('',*path.relative_to(base).parts):
        if part:current=current/part
        row=current.lstat()
        if stat.S_ISLNK(row.st_mode) or getattr(row,'st_file_attributes',0)&0x400:raise ValueError('Linked launch path refused')
    before=path.stat()
    if not stat.S_ISREG(before.st_mode):raise ValueError('Regular file required')
    with path.open('rb') as stream:value=hashlib.file_digest(stream,'sha256').hexdigest()
    after=path.stat()
    if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):raise ValueError('Launch source changed')
    return value

class LaunchController:
    def __init__(self,connection,stop,*,module=MODULE,manager=None,snapshot=None,popen=subprocess.Popen,clock=time.monotonic,scope=None):
        if os.name!='nt':raise RuntimeError('This recovery helper currently supports Windows only')
        self.module=Path(module);self.connection=dict(connection);self.root=resolve_target(connection['target']) if module==MODULE else (self.module/connection['target']).resolve()
        if not target_valid(self.root):raise ValueError('Invalid PortalAI target')
        import portalai_target
        portalai_target.configure(self.root)
        from profile_shutdown import _windows_snapshot
        self.manager=manager if manager is not None else portalai_target.Manager(self.root)
        self.snapshot=snapshot or _windows_snapshot;self.popen=popen;self.clock=clock
        self.stop=stop;self.gate=threading.Lock();self.worker=None;self.main_launch=None
        self.scope=scope or self.module/'state/input'/hashlib.sha256(input_owner().encode()).hexdigest()[:32]
        self.manager.endpoint_dir=self.scope
        self.pins={}
        for base,names in ((self.module,('Runtime/Python/pythonw.exe','Runtime/Python/python312.dll','app/projection_worker.py')),
                           (self.root,('PortalAI.exe','ControlCenter/control_center_bootstrap.py'))):
            for name in names:self.pins[(base,base/name)]=file_digest(base/name,base)
    def verify(self):
        for (base,path),digest in self.pins.items():
            if file_digest(path,base)!=digest:raise ValueError('Launch code changed; disarm and review before arming again')
    def fence(self):
        result=[]
        for name in ('Agent/.runtime/qwen_last_stop.json','Agent/.runtime/native_startup_state.json','HomeAssistant/state/forced-stop.json'):
            path=self.root/name
            # Missing metadata is allowed only with the launch root still intact.
            try:
                if path.stat().st_size>16384:raise ValueError('Stop marker limit')
            except FileNotFoundError:result.append(None);continue
            result.append(file_digest(path,self.root))
        return tuple(result)
    def guard(self,deadline,fence):
        if self.stop.is_set() or self.clock()>=deadline:raise TimeoutError('Recovery expired or disarmed')
        self.verify()
        if self.fence()!=fence:raise RuntimeError('Stop superseded recovery')
    def projection_rows(self,rows):
        found=[];executables={self.module/'Runtime/Python/python.exe',self.module/'Runtime/Python/pythonw.exe'}
        script=str(self.module/'app/projection_worker.py')
        for row in rows.values():
            exe=Path(row.get('executable') or '')
            if exe in executables:
                args=row.get('argv') or []
                if not args:raise RuntimeError('Companion process identity is uncertain')
                if script in args:
                    if args!=[str(exe),'-B','-I',script]:raise RuntimeError('Unexpected projection invocation')
                    found.append(row)
        return found
    def recover(self,deadline):
        from remote_lifecycle import clean_environment
        from profile_shutdown import _marker
        from portalai_target import gui_row
        initial=self.fence();self.guard(deadline,initial)
        rows=self.snapshot();self.guard(deadline,initial)
        projection=self.projection_rows(rows)
        launched=False
        with self.gate:
            self.guard(deadline,initial)
            if not projection and (self.worker is None or self.worker.poll() is not None):
                command=[str(self.module/'Runtime/Python/pythonw.exe'),'-B','-I',str(self.module/'app/projection_worker.py')]
                self.worker=self.popen(command,cwd=self.module,env=clean_environment(),stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',**launch_options())
                # Only this inherited anonymous pipe receives the unlocked key.
                self.worker.stdin.write(json.dumps(self.connection)+'\n');self.worker.stdin.flush();launched=True
        # A fresh inventory guards the app launch separately; leftover writers
        # are not killed and an active/closing GUI is never restarted here.
        rows=self.snapshot();self.guard(deadline,initial)
        if any(gui_row(self.root,row) for row in rows.values()):
            return 'launch_requested' if launched else 'already_running'
        if self.manager.owned(rows):return 'projection_restored_review_workers'
        marker=_marker(self.root)
        if marker and marker['state']=='closing':return 'projection_restored_review_workers'
        if self.main_launch is not None and self.main_launch.poll() is None:return 'launch_requested'
        for path in (self.module/'state',self.module/'state/input',self.scope):
            if path.exists() or path.is_symlink():
                if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Linked input scope refused')
            path.mkdir(mode=0o700,exist_ok=True)
            if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Input scope changed')
        environment=clean_environment()
        environment.update(PORTALAI_PROJECTION_HOME=str(self.module),PORTALAI_PROJECTION_INPUT=str(self.scope),PORTALAI_NATIVE_STATE='2')
        with self.gate:
            self.guard(deadline,initial)
            if _marker(self.root)!=marker:raise RuntimeError('Profile state changed during recovery')
            self.main_launch=self.popen([str(self.root/'PortalAI.exe')],cwd=self.root,env=environment,
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS)
        return 'launch_requested'  # Process launch is not a claim of login/sealing/readiness.
    def close(self):
        self.stop.set()
        with self.gate:
            worker=self.worker
        try:
            if worker is not None:
                try:
                    if worker.stdin:worker.stdin.close()
                except OSError:pass
                try:worker.wait(timeout=12)
                except subprocess.TimeoutExpired:
                    # Popen retains the exact child handle. Never touch PortalAI
                    # or an independent projection process by name/PID/port.
                    worker.terminate();worker.wait(timeout=5)
                self.worker=None
        finally:self.connection.clear()

class RecoveryRunner:
    def __init__(self,connection,notify,*,controller_factory=LaunchController,client_factory=RecoveryClient):
        self.connection=dict(connection);self.notify=notify;self.stop=threading.Event()
        self.controller_factory=controller_factory;self.client_factory=client_factory
        self.thread=None;self.operation=None;self.state='idle';self.replies=queue.Queue(1);self.seen=OrderedDict()
        self.controller=None;self.cleanup_failed=False
        self.cleanup_retry=threading.Event()
    def start(self):
        self.thread=threading.Thread(target=self.run,name='PortalAI-recovery-channel',daemon=False);self.thread.start()
    def disarm(self):
        self.stop.set();self.cleanup_retry.set()
    def finish(self):
        try:
            if self.controller is not None:self.controller.close()
        except Exception:
            self.cleanup_failed=True;self.notify('shutdown_failed')
        else:
            self.cleanup_failed=False;self.controller=None;self.notify('disarmed')
        finally:self.connection.clear()
    def execute(self,command,controller):
        try:
            if self.stop.is_set():raise RuntimeError('Disarmed')
            outcome=controller.recover(command['deadline'])
        except Exception:outcome='refused_or_uncertain'
        self.state=outcome;self.notify(outcome)
        try:self.replies.put_nowait({'id':command['id'],'outcome':outcome})
        except queue.Full:pass  # Status still exposes the outcome; never rerun it.
    def run(self):
        controller=None;client=None;ownership=None
        try:
            import portalai_target
            portalai_target.configure(resolve_target(self.connection['target']))
            from mission_runner import process_lock
            ownership=process_lock(MODULE/'state/recovery.lock');ownership.__enter__()
            try:
                controller=self.controller_factory(self.connection,self.stop)
                self.controller=controller
                client=self.client_factory(self.connection,MODULE/'Runtime/cacert.pem')
                while not self.stop.is_set():
                    try:
                        if not client.session:client.authenticate();self.notify('online')
                        replies=[]
                        try:replies.append(self.replies.get_nowait())
                        except queue.Empty:pass
                        commands=client.poll(self.state,replies)
                        for command in commands:
                            key=identity(command['id'])
                            if key in self.seen:continue
                            self.seen[key]=True
                            if len(self.seen)>128:self.seen.popitem(last=False)
                            if self.stop.is_set() or time.monotonic()>=command['deadline']:continue
                            if self.operation is not None and self.operation.is_alive():continue
                            self.state='recovering';self.notify('recovering')
                            self.operation=threading.Thread(target=self.execute,args=(command,controller),daemon=False)
                            self.operation.start()
                        self.stop.wait(1)
                    except Exception:
                        client.close();client.session=None;self.notify('unavailable');self.stop.wait(3)
            finally:
                self.stop.set()
                if self.operation is not None:self.operation.join()
                if client is not None:
                    try:client.close()
                    except OSError:pass
                while True:
                    self.cleanup_retry.clear();self.finish()
                    if not self.cleanup_failed:break
                    self.cleanup_retry.wait()  # Explicit Disarm retry; retain lock/handle.
                ownership.__exit__(None,None,None);ownership=None
        except Exception:self.notify('arming_failed')
        finally:
            self.stop.set()
            self.connection.clear()
