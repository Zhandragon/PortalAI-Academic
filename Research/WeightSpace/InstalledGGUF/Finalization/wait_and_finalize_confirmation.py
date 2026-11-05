"""Observe the owned confirmation and finalize only a verified terminal result.

This observer does not load a model, retry failed inference, clear a pause,
change scientific settings, or promote any edit. Positive evidence requires
the separate final benchmark stage; an error preserves the current state.
"""
import ctypes
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LAB = ROOT / 'Maintenance/Research/Takehi-PortalAI-20261103'
FOLDER = LAB / 'experiments/27-abliterated'
PHASE = FOLDER / '005-independent-confirmation'
STATE = BASE / 'CONFIRMATION-FINALIZER.json'
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from experiment import atomic_json, sha
from campaign_verdict import model_verdict


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def state(stage, **extra):
    value = dict(pid=os.getpid(), updated_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 stage=stage, original_models_replaced=False, automatic_promotion=False, **extra)
    atomic_json(STATE, value)
    print(json.dumps(value), flush=True)


def call(path, *args):
    state('running ' + path.name, arguments=list(args))
    folder = BASE / 'FinalizationLogs'
    folder.mkdir(exist_ok=True)
    log = folder / (path.stem + '-' + str(time.time_ns()) + '.log')
    with log.open('x', encoding='utf-8') as stream:
        subprocess.run([sys.executable, '-B', '-I', str(path), *args], cwd=ROOT, check=True,
                       timeout=7200, stdout=stream, stderr=subprocess.STDOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    assert not STATE.exists(), 'An existing observer must be reviewed before another is started.'
    assert read(BASE / 'SOFTWARE-DEPLOYMENT.json')['software_deployment_complete']
    control = read(FOLDER / 'CONFIRMATION-CONTROLLER.json')
    assert control['stage'] == 'running bounded worker'
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    # Hold the original process handle so later PID reuse cannot fool the observer.
    handle = kernel.OpenProcess(0x00100000, 0, control['pid'])
    assert handle and kernel.WaitForSingleObject(handle, 0) == 258
    state('waiting for frozen confirmation', controller_pid=control['pid'])
    updated = time.monotonic()
    try:
        while True:
            current = read(FOLDER / 'CONFIRMATION-CONTROLLER.json')
            assert current['pid'] == control['pid'], 'Controller identity changed; inspect before continuing.'
            running = kernel.WaitForSingleObject(handle, 0) == 258
            if not running:
                if current['stage'] == 'paused by user':
                    state('paused with the user-controlled research run', controller_pid=control['pid'], work_complete=False)
                    return
                assert current['stage'] == 'complete; review before conditional final benchmarks', current
                break
            if time.monotonic() - updated >= 300:
                connection = sqlite3.connect((PHASE / 'completed-cases.sqlite').as_uri() + '?mode=ro', uri=True)
                try:
                    counts = dict(connection.execute('SELECT arm, COUNT(*) FROM cases GROUP BY arm'))
                finally:
                    connection.close()
                state('waiting for frozen confirmation', controller_pid=control['pid'],
                      completed_cases={arm: counts.get(arm, 0) for arm in ('baseline', 'candidate')})
                updated = time.monotonic()
            time.sleep(20)
    finally:
        kernel.CloseHandle(handle)
    call(LAB / 'audit_confirmation.py', '--model', '27-abliterated')
    audit = read(FOLDER / 'CONFIRMATION-AUDIT.json')
    summary = read(PHASE / 'summary.json')
    assert audit['summary_sha256'] == sha(PHASE / 'summary.json')
    verdict = model_verdict({'discovery': read(FOLDER / '004-generation-screen/summary.json'),
                            'independent_confirmation': summary, 'confirmation_audit': audit})
    if verdict['stage'] == 'confirmation_not_established':
        call(BASE / 'finalize_confirmed_campaign.py')
        assert read(BASE / 'WORK-STATE.json')['work_complete']
        state('complete', work_complete=True, campaign_complete=True,
              reason='Audited independent confirmation did not establish an improvement; originals retained.')
        return
    assert verdict['stage'] == 'final_benchmarks_required' and not verdict['complete']
    target = BASE / 'FINAL-BENCHMARKS-REQUIRED.json'
    assert not target.exists()
    atomic_json(target, {'model': '27-abliterated', 'confirmation_summary_sha256': sha(PHASE / 'summary.json'),
                        'confirmation_audit_sha256': sha(FOLDER / 'CONFIRMATION-AUDIT.json'),
                        'verdict': verdict, 'production_model_changed': False})
    state('confirmation passed; broad final benchmarks required', work_complete=False,
          model='27-abliterated', paired=summary['paired'])


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        if STATE.exists():
            previous = read(STATE)
            state('stopped; review required', error=repr(exc), previous_stage=previous.get('stage'), work_complete=False)
        raise
