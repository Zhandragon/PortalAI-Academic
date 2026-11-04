"""Sequential GPU jobs with owned process lifetime and bounded runtime."""
import subprocess,sys
from pathlib import Path
LAB=Path(__file__).parent;sys.path[:0]=[str(LAB),str(LAB.parents[2]/'Agent')]
from mission_supervisor import WorkerJob
from research_guard import require_gpu_unpaused
for model,label in [('1.7-abliterated','1.7-abl'),('4-abliterated','4-abl'),('27-standard','27'),('27-abliterated','27-abl')]:
    require_gpu_unpaused();folder=LAB/f'causal-calibration-{label}-v1'
    if folder.exists():raise FileExistsError('Inspect prior calibration before resuming')
    with (LAB/f'causal-calibration-{label}-progress.log').open('wb') as log:
        proc=subprocess.Popen([sys.executable,'-B','-I',str(LAB/'native_calibration.py'),'--model',model,'--output',folder.name],cwd=LAB,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        job=None
        try:
            job=WorkerJob(proc);code=proc.wait(timeout=1200)
            if code:raise RuntimeError('Calibration failed for '+model+'; inspect its log')
        finally:
            if job:job.close()
            elif proc.poll() is None:proc.kill()
            proc.wait(timeout=15)
    print('Completed '+model+'; no production weights modified.',flush=True)
