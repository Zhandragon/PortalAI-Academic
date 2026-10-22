"""Run a finite Linux tool behind the shared gate and delegated cgroup owner."""
import subprocess
import tempfile
import time
from pathlib import Path

from runtime_policy import ROOT, atomic_json, memory_info
from platform_runtime import python_path
from mission_supervisor import WorkerJob
from profile_paths import private_path


def run(command, *, cwd, env, timeout=240, memory_bytes=12*1024**3):
    staging=private_path(ROOT,'Cache/LinuxWorkers');staging.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=staging) as folder:
        folder=Path(folder);gate=folder/'gate';request=folder/'request.json'
        atomic_json(request,{'command':list(map(str,command)),'gate':str(gate)})
        process=subprocess.Popen([str(python_path(ROOT)),'-B','-I',str(ROOT/'Agent/sdcpp_worker.py'),str(request)],
            cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',errors='replace')
        job=None;deadline=time.monotonic()+timeout
        try:
            job=WorkerJob(process);job.limit_memory(memory_bytes);gate.touch()
            while True:
                job.check()
                if time.monotonic()>deadline:raise TimeoutError('Linux worker timed out')
                if memory_info()[1]<2*1024**3:raise RuntimeError('Linux worker stopped at the host RAM reserve')
                try:
                    stdout,stderr=process.communicate(timeout=.5);break
                except subprocess.TimeoutExpired:pass
            return subprocess.CompletedProcess(command,process.returncode,stdout,stderr)
        finally:
            if job:job.close()
            if process.poll() is None:process.kill();process.wait(timeout=5)
            process.stdout.close();process.stderr.close()
