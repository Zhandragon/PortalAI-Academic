"""Reuse checked core graders; isolate the additional pinned final evaluators."""
import json
import subprocess
import sys
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path[:0] = [str(ROOT / 'Tools/WeightSpace'), str(ROOT / 'Agent')]
from evaluation import grade as core_grade
from mission_supervisor import WorkerJob
from suite_utilities import clean_environment


def grade(case, text):
    if case['kind'] not in ('ifeval', 'choice'):
        return core_grade(case, text)
    payload = json.dumps({'case': case, 'text': text}).encode()
    if len(payload) > 2 * 1024**2:
        raise ValueError('Final grader input exceeds 2 MiB')
    environment = clean_environment()
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        environment[name] = '1'
    process = subprocess.Popen([sys.executable, '-B', '-I', str(LAB / 'final_grade_worker.py')],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=environment,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    job = None
    try:
        job = WorkerJob(process)
        job.limit_memory(512 * 1024**2)
        output, error = process.communicate(payload, timeout=30)
        if process.returncode:
            raise RuntimeError('Final grader infrastructure failed: ' + error.decode(errors='replace')[-600:])
        result = json.loads(output)
        if type(result.get('correct')) is not bool:
            raise ValueError('Final grader did not return a boolean score')
        return result
    finally:
        if job:
            job.close()
        elif process.poll() is None:
            process.kill()
        process.wait(timeout=15)
