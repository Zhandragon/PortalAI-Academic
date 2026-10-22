"""Bounded real Klein4 CPU diagnostic, separate from authenticated chat/handoff."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Tools', 'Agent')]
from validation_artifacts import ValidationArtifacts
from runtime_policy import GIB, memory_info
from mission_supervisor import WorkerJob
from native_flux import plan, command
from sdcpp_bridge import validate_png


def run(artifacts, variant, cancel=False, reference=False):
    profile = plan(ROOT, engine='sdcpp-cpu', width=128, height=128, variant=variant)
    output = artifacts.path('synthetic-klein4.png')
    if output.exists(): raise RuntimeError('Choose a fresh diagnostic directory')
    source = None
    if reference:
        from platform_runtime import ffmpeg_path
        source = artifacts.path('synthetic-source.png')
        subprocess.run([str(ffmpeg_path(ROOT)), '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=128x128', '-frames:v', '1', str(source)], check=True, timeout=20,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    argv = command(profile, ROOT, 'A blue ceramic teapot on a plain white table', None, 52, output,
                   4, source)
    gate = artifacts.path('worker.gate'); request = artifacts.path('request.json')
    request.write_text(json.dumps({'gate':str(gate), 'command':argv}), encoding='utf-8')
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'PORTALAI_PROFILE_ID', 'PORTALAI_PROFILE_EPOCH'):
        env.pop(key, None)
    temp = artifacts.path('tmp'); temp.mkdir(exist_ok=True)
    env.update(TEMP=str(temp), TMP=str(temp))
    report = {'passed':False, 'scope':'Synthetic standalone CPU inference only; not production handoff or physical Radeon/Intel/Linux validation',
              'variant':variant, 'reference_edit':reference, 'cancel_test':cancel, 'memory_cap_gib':10}
    proc = job = None; started = time.monotonic()
    try:
        with artifacts.path('worker.log').open('xb') as log:
            proc = subprocess.Popen([sys.executable, '-I', '-B', str(ROOT/'Agent/sdcpp_worker.py'), str(request)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            job = WorkerJob(proc); job.limit_memory(10*GIB); gate.touch()
            while proc.poll() is None:
                if cancel and time.monotonic()-started > 2:
                    job.close(); job = None; proc.wait(timeout=10); break
                if memory_info()[1] < 3*GIB: raise RuntimeError('Diagnostic free-memory floor reached')
                if time.monotonic()-started > 600: raise TimeoutError('Klein4 CPU diagnostic timed out')
                time.sleep(.2)
            if cancel:
                if output.exists(): raise RuntimeError('Cancelled inference produced an unexpected image')
            else:
                if proc.returncode: raise RuntimeError('Native engine failed; see worker.log')
                validate_png(output, 128, 128)
            report['passed'] = True
    except Exception as exc:
        report['error'] = str(exc)
    finally:
        if job: job.close()
        if proc:
            if proc.poll() is None: proc.kill()
            proc.wait(timeout=10)
        report.update(elapsed_seconds=round(time.monotonic()-started, 2), owned_worker_stopped=proc is None or proc.poll() is not None)
        artifacts.path('report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', required=True)
    parser.add_argument('--variant', choices=['official','uncensored'], default='uncensored')
    parser.add_argument('--cancel', action='store_true'); parser.add_argument('--reference', action='store_true')
    args = parser.parse_args()
    result = run(ValidationArtifacts(ROOT, args.artifacts_dir), args.variant, args.cancel, args.reference)
    print(json.dumps(result), flush=True); raise SystemExit(0 if result['passed'] else 1)
