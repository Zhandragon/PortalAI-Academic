"""Keep direct probe lifetime bounded; gate imports until job ownership exists."""
import subprocess,sys
from pathlib import Path
lab=Path(__file__).parent;sys.path[:0]=[str(lab),str(lab.parents[2]/'Agent')]
from research_guard import require_gpu_unpaused
require_gpu_unpaused()
from mission_supervisor import WorkerJob
with (lab/'direct-probe-progress.log').open('wb') as log:
    proc=subprocess.Popen([sys.executable,'-B','-I',str(lab/'probe_baseline.py'),*sys.argv[1:]],stdin=subprocess.PIPE,stdout=log,stderr=log,cwd=lab,creationflags=subprocess.CREATE_NO_WINDOW)
    job=None
    try:
        job=WorkerJob(proc);job.limit_memory(16*1024**3)
        proc.stdin.write(b'start\n');proc.stdin.flush();proc.stdin.close()
        code=proc.wait(timeout=1800)
    finally:
        if job:job.close()
        elif proc.poll() is None:proc.kill()
        proc.wait(timeout=15)
    raise SystemExit(code)
