"""Gate a native worker behind a bounded Windows Job; no inherited account keys."""
import argparse,os,subprocess,sys,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_supervisor import WorkerJob
from suite_utilities import clean_environment

def run(script,arguments,log,timeout=43200,cancel=None):
    log=Path(log);log.parent.mkdir(parents=True,exist_ok=True)
    if not 1<=timeout<=86400:raise ValueError('Invalid owned worker deadline')
    with log.open('ab') as stream:
        proc=subprocess.Popen([sys.executable,'-B','-I',str(script),*map(str,arguments)],stdin=subprocess.PIPE,
            stdout=stream,stderr=stream,cwd=str(HERE),env=clean_environment(),creationflags=subprocess.CREATE_NO_WINDOW)
        job=None
        try:
            job=WorkerJob(proc);job.limit_memory(24*1024**3)
            proc.stdin.write(b'start\n');proc.stdin.flush();proc.stdin.close()
            deadline=time.monotonic()+timeout
            while True:
                try:return proc.wait(timeout=.25)
                except subprocess.TimeoutExpired:
                    if cancel is not None and cancel.is_set():raise InterruptedError('Stopped by the user; unfinished artifacts retained for review.')
                    if time.monotonic()>=deadline:raise TimeoutError('Owned worker deadline exceeded')
        finally:
            if job:job.close()
            elif proc.poll() is None:proc.kill()
            proc.wait(timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--log',required=True,type=Path);p.add_argument('--timeout',type=int,default=43200);p.add_argument('script',type=Path);p.add_argument('arguments',nargs=argparse.REMAINDER)
    a=p.parse_args();raise SystemExit(run(a.script,a.arguments,a.log,a.timeout))
