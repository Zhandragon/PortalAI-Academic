"""Continue an admitted frozen confirmation in bounded owned workers.

No automatic retry follows an error or a manual pause. Normal five-hour
checkpoint boundaries may continue, always preserving the scientific ledger.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from run_owned import run
from experiment import atomic_json
import research_guard
research_guard.LAB = LAB


def main():
    protocol = json.loads((LAB / 'protocol.json').read_text())
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True, choices=tuple(protocol['models']))
    args = parser.parse_args()
    folder = LAB / 'experiments' / args.model
    out = folder / '005-independent-confirmation'
    summary = json.loads((folder / '004-generation-screen/summary.json').read_text())
    assert summary['eligible_for_independent_confirmation'], 'Discovery did not qualify.'
    assert not (out / 'summary.json').exists(), 'Completed confirmation is never replayed.'
    control = folder / 'CONFIRMATION-CONTROLLER.json'
    previous = -1
    while True:
        research_guard.require_gpu_unpaused()
        options = ['--model', args.model, '--work-seconds', '18000']
        if out.exists():
            options.append('--resume')
        atomic_json(control, {'pid': os.getpid(), 'stage': 'running bounded worker',
                             'time_unix': time.time(), 'automatic_promotion': False})
        code = run(LAB / 'checkpointed_confirmation.py', options,
                   LAB / ('confirmation-' + args.model + '.log'), timeout=21600)
        if code:
            status_path = out / 'WORK-STATE.json'
            status = json.loads(status_path.read_text()) if status_path.is_file() else {}
            paused = status.get('stage') == 'paused' or research_guard.gpu_paused()
            atomic_json(control, {'pid': os.getpid(), 'stage': 'paused by user' if paused else 'stopped; review required',
                                 'worker_exit_code': code, 'automatic_retry': False,
                                 'resume_requires_explicit_user_instruction': paused})
            if paused:
                print(json.dumps({'paused_by_user': True, 'completed_cases_preserved': True}), flush=True)
                return
            raise RuntimeError('Confirmation worker stopped; inspect its durable checkpoint before resuming.')
        state = json.loads((out / 'WORK-STATE.json').read_text())
        count = sum(state['counts'].values())
        if state['stage'] == 'complete':
            assert count == 2304 and (out / 'summary.json').is_file()
            assert (out / 'candidate-retired.json').is_file() and not (out / 'candidate.gguf').exists()
            atomic_json(control, {'pid': os.getpid(), 'stage': 'complete; review before conditional final benchmarks',
                                 'completed_cases': count, 'automatic_promotion': False})
            print(json.dumps({'confirmation_complete': True, 'model': args.model,
                              'production_model_changed': False}), flush=True)
            return
        assert state['stage'] == 'checkpointed' and count > previous, 'No forward progress; inspect before retrying.'
        previous = count
        print(json.dumps({'checkpointed_cases': count, 'model': args.model,
                          'continuing_same_frozen_experiment': True}), flush=True)


if __name__ == '__main__':
    main()
