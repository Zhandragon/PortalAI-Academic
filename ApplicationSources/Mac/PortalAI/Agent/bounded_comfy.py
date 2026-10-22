"""Own a scaled ComfyUI session with an OS-enforced memory and lifetime limit."""
from instance_runtime import port as _instance_port, url as _instance_url
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference, comfy_directory_args
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request

from runtime_policy import ROOT, atomic_json, portable_env, memory_info
from platform_runtime import python_path, worker_process_options
from mission_supervisor import WorkerJob
from process_diagnostics import file_excerpt


def backend_flags(profile, windows=None):
    windows=os.name=='nt' if windows is None else windows
    backend=profile.get('backend')
    allowed={'rocm'} if windows else {'cpu','cuda','rocm'}
    if backend not in allowed:
        raise ValueError('Scaled ComfyUI requires Windows ROCm or Linux CPU/CUDA/ROCm')
    return ['--cpu'] if backend=='cpu' else ['--lowvram','--disable-xformers',
        '--use-split-cross-attention','--disable-triton-backend','--disable-comfy-compiler',
        '--disable-async-offload','--reserve-vram','2','--cache-none']


def checked_extra_args(args,root):
    """Do not let optional diagnostics override device, listener or memory policy."""
    args=list(args);index=0
    while index<len(args):
        flag=args[index]
        if flag in {'--disable-all-custom-nodes','--disable-metadata'}:
            index+=1;continue
        if flag not in {'--user-directory','--output-directory','--input-directory','--temp-directory'}:
            raise ValueError('Unsupported scaled ComfyUI override: '+str(flag))
        if index+1>=len(args):raise ValueError('Missing ComfyUI directory argument')
        directory=media_reference(root,args[index+1])
        if not directory.is_relative_to(root):raise ValueError('ComfyUI directories must stay on the portable drive')
        args[index+1]=str(directory);index+=2
    return args


def owns_pid(job,pid):
    """Verify this exact bounded job owns the listener, not just its image name."""
    if job.linux is not None:
        from linux_job import MOUNT
        try:
            rows=Path(f'/proc/{int(pid)}/cgroup').read_text().splitlines()
            relative=next(row[3:] for row in rows if row.startswith('0::'))
            if not relative.startswith('/') or '..' in Path(relative).parts:return False
            return (MOUNT/relative.lstrip('/')).resolve().is_relative_to(job.linux.group.resolve())
        except (OSError,ValueError,StopIteration):return False
    import ctypes
    from ctypes import wintypes as w
    lib=ctypes.WinDLL('kernel32',use_last_error=True)
    lib.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];lib.OpenProcess.restype=w.HANDLE
    lib.IsProcessInJob.argtypes=[w.HANDLE,w.HANDLE,ctypes.POINTER(w.BOOL)]
    lib.IsProcessInJob.restype=w.BOOL
    lib.CloseHandle.argtypes=[w.HANDLE]
    handle=lib.OpenProcess(0x1000,False,int(pid))
    if not handle:return False
    try:
        present=w.BOOL()
        return bool(lib.IsProcessInJob(handle,job.handle,ctypes.byref(present)) and present.value)
    finally:lib.CloseHandle(handle)


def owned_listeners(service,job,port):
    listeners=service._listening_pids(port)
    if not listeners or not all(owns_pid(job,pid) for pid in listeners):
        raise RuntimeError('Scaled ComfyUI listener is outside this bounded worker job')
    return listeners


@contextmanager
def session(profile, root=ROOT, port=_instance_port('comfyui'), extra_args=(), timeout=120):
    """Caller holds the GPU lease and stops peers before entering this context.

    The worker is gated before Torch imports. Its entire process tree receives
    the profile's memory ceiling and dies on controller crash or context exit.
    This is resource containment, not a VM or a security sandbox.
    """
    import service_manager as service
    root=Path(root).resolve()
    flags=backend_flags(profile)
    extra_args=checked_extra_args(extra_args,root)
    if type(port) is not int or not 1<=port<=65535:raise ValueError('Invalid ComfyUI port')
    if type(profile.get('max_memory_bytes')) is not int or profile['max_memory_bytes']<256*1024**2:
        raise ValueError('Scaled ComfyUI requires a memory ceiling of at least 256 MiB')
    if service.port_open(port):
        raise RuntimeError('Scaled ComfyUI port is already occupied; refusing to attach to another process')
    staging=private_path(root, 'Cache/ComfyWorkers');staging.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as folder:
        folder=Path(folder);gate=folder/'gate';request=folder/'request.json';log=folder/'log'
        work=root/'Generative/ComfyUI_windows_portable'
        command=[str(python_path(root)),'-B','-I',str(root/'Agent/comfy_amd_entry.py'),
                 '--disable-auto-launch','--listen','127.0.0.1','--port',str(port),*flags,*extra_args,*comfy_directory_args(root)]
        env=portable_env(root);env['PORTALAI_TORCH_BACKEND']=profile['backend']
        atomic_json(request,{'command':command,'gate':str(gate)})
        process=job=None
        try:
            with log.open('wb') as output:
                process=subprocess.Popen([str(python_path(root)),'-B','-I',str(root/'Agent/sdcpp_worker.py'),str(request)],
                    cwd=work,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=output,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0), **worker_process_options())
                job=WorkerJob(process)
                job.limit_memory(profile['max_memory_bytes'])
                gate.touch()
                deadline=time.monotonic()+timeout
                while True:
                    job.check()
                    if process.poll() is not None:
                        raise RuntimeError(f'Scaled ComfyUI exited ({process.returncode}): '+file_excerpt(log))
                    if memory_info()[1]<profile.get('min_free_ram_bytes',2*1024**3):
                        raise RuntimeError('Scaled ComfyUI stopped at the free RAM reserve')
                    if time.monotonic()>deadline:raise TimeoutError('Scaled ComfyUI startup timed out')
                    if not service.port_open(port):time.sleep(.25);continue
                    listeners=owned_listeners(service,job,port)
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/system_stats',timeout=1) as response:
                            stats=json.load(response)
                        if not isinstance(stats.get('system'),dict):raise ValueError('Unexpected ComfyUI API response')
                        if owned_listeners(service,job,port)!=listeners:
                            raise RuntimeError('Scaled ComfyUI listener changed during readiness')
                        break
                    except OSError:time.sleep(.25)
                yield {'process':process,'job':job,'memory_limit_bytes':profile['max_memory_bytes']}
        finally:
            try:
                if job:job.close()
            finally:
                try:
                    if process:
                        if process.poll() is None:process.kill()
                        process.wait(timeout=10)
                finally:
                    if log.exists():
                        destination=media_runtime(root)/'scaled-comfy.log';destination.parent.mkdir(parents=True,exist_ok=True)
                        # Keep bounded diagnostics without retaining entire successful jobs.
                        with log.open('rb') as source:
                            source.seek(max(0,log.stat().st_size-128*1024))
                            destination.write_bytes(source.read())
