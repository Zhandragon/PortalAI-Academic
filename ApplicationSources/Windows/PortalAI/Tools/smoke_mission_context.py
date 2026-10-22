"""Live 4B planning after 30 real, scripted note actions and controller reload."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Agent'))
from runtime_policy import atomic_json, load_policy, build_plan, portable_env
from mission_runner import Missions
from mission_supervisor import running
from service_manager import acquire_gpu_lease, release_gpu_lease, qwen_gpu_handoff_begin, qwen_gpu_handoff_end, _wait_qwen_ready


def main():
    if running(ROOT): raise RuntimeError('Finish active supervision before the context test')
    lease = acquire_gpu_lease('mission-context-smoke'); state = proc = None
    report = {'passed': False, 'real_model': True, 'seeded_actions': '30 real note actions with scripted planning', 'checks': []}
    try:
        state = qwen_gpu_handoff_begin('mission-context-smoke')
        policy = load_policy(ROOT); policy.update(selection='qwen4-q4', context_tokens=8192)
        plan = build_plan(ROOT, policy=policy)
        with (ROOT/'Maintenance/Reports/mission-context-model.log').open('wb') as log:
            proc = subprocess.Popen(plan['command'], cwd=ROOT, env=portable_env(ROOT), stdout=log, stderr=log,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            _wait_qwen_ready(180)
            base = ROOT/'Maintenance/Reports/context-tests'/uuid.uuid4().hex
            (base/'Agent').mkdir(parents=True)
            atomic_json(base/'Agent/hardware_profiles.json', {'storage': {'minimum_free_gib': 1, 'minimum_free_fraction': .01, 'output_reserve_gib': 0}})
            store = Missions(base)
            m = store.create('This is a compaction self-test. Thirty note actions have already run. First verify the exact token in record 3 using {"action":"history","start":3,"count":1}. After that verification, complete with that exact token. Do not use recall, write notes, or repeat previous actions.', max_steps=34)
            token = 'CONTEXT_RECOVERY_'+uuid.uuid4().hex[:12]
            for i in range(30):
                text = token if i == 2 else ('Background measurement '+str(i)+'; '+'unrelated data '*100)
                m = store.run(m['id'], 1, model=lambda _, text=text: {'action': 'note', 'text': text})
            # A fresh controller must derive context from the saved mission.
            store = Missions(base)
            m = store.run(m['id'], 3)
            status = json.loads((store.folder(m['id'])/'context-status.json').read_text())
            passed = (m['status'] == 'complete' and token in m['history'][-1]['action'].get('text', '') and
                      m['history'][30]['action'] == {'action': 'history', 'start': 3, 'count': 1} and
                      len(m['history']) == 32 and status['compacted'])
            report.update(passed=passed, mission=m['id'], root=str(base), status=m['status'], context=status,
                          final_actions=m['history'][30:], note_count=30)
            if not passed: raise AssertionError('Live context recovery did not match the expected actions')
    except Exception as exc:
        report['error'] = type(exc).__name__+': '+str(exc)
        raise
    finally:
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=15)
                except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=10)
            if state and state.get('active'): report['restoration'] = qwen_gpu_handoff_end(state)
        finally:
            release_gpu_lease(lease)
            atomic_json(ROOT/'Maintenance/Reports/mission-context-smoke.json', report)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
