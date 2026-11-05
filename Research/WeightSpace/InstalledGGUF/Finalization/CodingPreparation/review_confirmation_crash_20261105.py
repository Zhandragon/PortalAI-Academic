"""Read-only checkpoint review and recovery copy after the first native crash.

Does not retry inference, read answer scores to make research decisions, change
any frozen input, or write the research database. A reviewed restart is separate.
"""
import contextlib
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LAB = ROOT / 'Maintenance/Research/Takehi-PortalAI-20261103'
FOLDER = LAB / 'experiments/27-abliterated'
PHASE = FOLDER / '005-independent-confirmation'
DEST = BASE / 'CrashReview-20261105T005909Z'
MIRROR = Path('E:/PortalAI Windows/Maintenance/Validation/Weight-Final-r69') / DEST.name
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from checkpointed_confirmation import read, validate, requests_for, worker_lock
from confirmation_store import CaseStore
from experiment import atomic_json, sha, space
import research_guard


def main():
    research_guard.require_gpu_unpaused(LAB)
    assert not DEST.exists() and not MIRROR.exists(), 'Review already saved; inspect it instead.'
    control = read(FOLDER / 'CONFIRMATION-CONTROLLER.json')
    assert control['stage'] == 'stopped; review required'
    assert control['worker_exit_code'] == 0xC0000005
    assert control['resume_requires_explicit_user_instruction'] is False
    assert not (PHASE / 'summary.json').exists()
    with worker_lock(PHASE):
        protocol = read(LAB / 'protocol.json')
        spec = protocol['models']['27-abliterated']
        original = ROOT / 'LLM/models' / spec['filename']
        _, frozen, ids, rows = validate(FOLDER, original, spec)
        frozen_sha = sha(PHASE / 'frozen.json')
        assert frozen_sha == '66df185172caa72f306a692fe7ce0e973d0444fcc983d3158078683753dd0c95'
        assert sha(PHASE / 'candidate.gguf') == frozen['candidate_sha256']
        request_map = requests_for(frozen, frozen_sha, ids, rows)
        database = PHASE / 'completed-cases.sqlite'
        before = sha(database)
        with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            assert db.execute("SELECT value FROM metadata WHERE key='frozen_sha256'").fetchone() == (frozen_sha,)
            results = CaseStore.load(SimpleNamespace(db=db), request_map)
            records = []
            for arm, key, expected in db.execute('SELECT arm,id,payload_sha256 FROM cases ORDER BY arm,id'):
                mirror = PHASE / arm / (hashlib.sha256(key.encode()).hexdigest()[:20] + '.json')
                assert not mirror.is_symlink() and sha(mirror) == expected
                records.append({'arm': arm, 'id': key, 'sha256': expected})
        assert sha(database) == before
        with contextlib.closing(sqlite3.connect((FOLDER / 'ledger.sqlite').as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            active = db.execute("SELECT id,phase,request FROM runs WHERE status='running'").fetchall()
            assert len(active) == 1 and active[0][0] == 'checkpointed-confirmation-000-baseline'
            passes = db.execute("SELECT COUNT(*) FROM runs WHERE phase IN ('discovery','confirmation')").fetchone()[0]
            assert passes < protocol['budgets']['forward_passes_per_model']
        files = {
            'WORK-STATE.json': BASE / 'WORK-STATE.json',
            'CONFIRMATION-FINALIZER.json': BASE / 'CONFIRMATION-FINALIZER.json',
            'CONFIRMATION-CONTROLLER.json': FOLDER / 'CONFIRMATION-CONTROLLER.json',
            'worker-WORK-STATE.json': PHASE / 'WORK-STATE.json',
            'frozen.json': PHASE / 'frozen.json',
            'completed-cases.sqlite': database,
            'ledger.sqlite': FOLDER / 'ledger.sqlite',
            'confirmation-27-abliterated.log': LAB / 'confirmation-27-abliterated.log',
        }
        needed = sum(path.stat().st_size for path in files.values()) + 4 * 1024**2
        for destination in (DEST, MIRROR):
            space(destination.parent, needed)
            destination.mkdir()
            for name, source in files.items():
                shutil.copy2(source, destination / name)
                assert sha(destination / name) == sha(source)
        result = {
            'review_passed': True,
            'reviewed_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'crash_time_utc': '2026-11-05T00:59:09Z',
            'worker_pid': 23088,
            'windows_exception': '0xC0000005',
            'windows_fault_module': 'python312.dll',
            'windows_fault_offset': '0x42e88',
            'root_cause': 'Undetermined; Windows reports a native access violation, not an answer-quality failure.',
            'counts': {arm: len(values) for arm, values in results.items()},
            'database_sha256': before,
            'frozen_sha256': frozen_sha,
            'candidate_sha256': frozen['candidate_sha256'],
            'original_sha256': frozen['base_sha256'],
            'source_data_prompts_seeds_sampling_unchanged': True,
            'all_saved_case_requests_payloads_and_mirrors_verified': True,
            'forward_passes_including_interruption': passes,
            'active_ledger_entry': active,
            'record_hashes': records,
            'recovery_copies': [str(DEST), str(MIRROR)],
            'restart_policy': 'One reviewed continuation using the existing frozen worker. Preserve and account the interrupted pass; never replay completed cases. Stop again on error.',
            'production_models_changed': False,
            'inference_started_by_review': False,
        }
        for destination in (DEST, MIRROR):
            atomic_json(destination / 'REVIEW.json', result)
        print(json.dumps({key: value for key, value in result.items() if key != 'record_hashes'}), flush=True)


if __name__ == '__main__':
    main()
