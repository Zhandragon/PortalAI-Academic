"""Run the VM regression with the portable 4B model, then restore chat exactly."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Tools')]
from runtime_policy import atomic_json, build_plan, load_policy, portable_env
from mission_runner import Missions, ACTIVE
from mission_schedule import Schedules
from mission_supervisor import running, read_policy
from service_manager import (acquire_gpu_lease, release_gpu_lease, qwen_gpu_handoff_begin,
                             qwen_gpu_handoff_end, _wait_qwen_ready, _listener_identity)
import smoke_vm


def main():
    store = Missions(ROOT)
    if running(ROOT) or Schedules(ROOT).any_enabled() or any(
            read_policy(store, m['id']).get('enabled') and m['status'] in ACTIVE for m in store.list()):
        raise RuntimeError('Other armed work is present; finish it before switching the test model')
    report = {'passed': False, 'test': '4B VM execution and exact original chat restoration'}
    original = _listener_identity()
    if not original['portable_qwen']:
        raise RuntimeError('A healthy owned chat server is required for the restoration test')
    lease = acquire_gpu_lease('vm-small-model-regression')
    state = None
    proc = None
    try:
        state = qwen_gpu_handoff_begin('vm-small-model-regression')
        if not state.get('active'):
            raise RuntimeError('Owned chat handoff did not start')
        policy = load_policy(ROOT)
        policy.update(selection='qwen4-q4', context_tokens=8192)
        plan = build_plan(ROOT, policy=policy)
        report.update(model=plan['model'], backend=plan['backend'], original_command=state['command_line'])
        with (ROOT/'Maintenance/Reports/vm-small-model.log').open('wb') as log:
            proc = subprocess.Popen(plan['command'], cwd=ROOT, env=portable_env(ROOT),
                                    stdout=log, stderr=log,
                                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            _wait_qwen_ready(180)
            smoke_vm.main()
            report['vm_checks'] = json.loads((ROOT/'Maintenance/Reports/vm-smoke.json').read_text(encoding='utf-8'))
            report['passed'] = report['vm_checks'].get('passed') is True
    except Exception as exc:
        report['error'] = str(exc)
        raise
    finally:
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=10)
            if state and state.get('active'):
                report['restoration'] = qwen_gpu_handoff_end(state)
                report['restored_identity'] = _listener_identity()
                exact = any(row['command_line'] == state['command_line']
                            for row in report['restored_identity']['listeners'])
                report['exact_command_restored'] = exact
                report['passed'] = report['passed'] and exact and report['restoration'].get('ready',False)
        finally:
            release_gpu_lease(lease)
            atomic_json(ROOT/'Maintenance/Reports/vm-small-model.json',report)
    print(json.dumps({'passed':report['passed'],'model':report['model']['id'],
                      'exact_command_restored':report['exact_command_restored']}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
