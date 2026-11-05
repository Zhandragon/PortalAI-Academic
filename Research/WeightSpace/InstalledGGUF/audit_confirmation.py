"""Recompute a completed confirmation from pinned, immutable saved evidence.

No model inference or tool execution occurs. This verifies the bookkeeping and
provenance; it is not a second independent assessment of each answer's math.
"""
import argparse
import contextlib
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from campaign_verdict import equivalent
from confirmation_store import CaseStore
from experiment import atomic_json, paired_summary, sha


def recompute(results, ids, summary):
    if len(ids) != 1152 or len(set(ids)) != 1152:
        raise ValueError('Confirmation requires exactly 1,152 distinct planned problems')
    if set(results) != {'baseline', 'candidate'} or any(set(values) != set(ids) for values in results.values()):
        raise ValueError('Missing, extra, or unpaired completed cases')
    for values in results.values():
        for key, value in values.items():
            if value.get('id') != key or type(value.get('grading', {}).get('correct')) is not bool:
                raise ValueError('Case identity or score is invalid')
            if value.get('finish') not in ('stop', 'length') or type(value.get('seconds')) not in (int, float):
                raise ValueError('Case telemetry is invalid')
    scores = {arm: {key: value['grading']['correct'] for key, value in values.items()} for arm, values in results.items()}
    paired = paired_summary(scores['baseline'], scores['candidate'])
    times = {arm: sum(value['seconds'] for value in values.values()) for arm, values in results.items()}
    if times['baseline'] <= 0 or times['candidate'] < 0:
        raise ValueError('Invalid total elapsed time')
    ratio = times['candidate'] / times['baseline']
    cutoffs = {arm: sum(value['finish'] == 'length' for value in values.values()) for arm, values in results.items()}
    if not equivalent(paired, summary.get('paired')) or not equivalent(ratio, summary.get('latency_ratio')) or cutoffs != summary.get('cutoffs'):
        raise ValueError('Saved summary differs from the underlying completed cases')
    if summary.get('eligible_for_separate_final_benchmarks') is not (paired['lower_95'] > 0):
        raise ValueError('Recorded confirmation gate differs from recomputed evidence')
    return {'recomputed_paired': paired, 'recomputed_latency_ratio': ratio, 'recomputed_cutoffs': cutoffs}


def audit(model):
    from checkpointed_confirmation import read, validate, requests_for
    protocol = read(LAB / 'protocol.json')
    spec = protocol['models'][model]
    folder = LAB / 'experiments' / model
    out = folder / '005-independent-confirmation'
    destination = folder / 'CONFIRMATION-AUDIT.json'
    assert not destination.exists(), 'An existing audit requires review, not overwrite.'
    assert read(folder / 'CONFIRMATION-CONTROLLER.json')['stage'] == 'complete; review before conditional final benchmarks'
    state = read(out / 'WORK-STATE.json')
    assert state['stage'] == 'complete' and state['counts'] == {'baseline': 1152, 'candidate': 1152}
    original = ROOT / 'LLM/models' / spec['filename']
    out, frozen, ids, rows = validate(folder, original, spec)
    frozen_sha = sha(out / 'frozen.json')
    summary = read(out / 'summary.json')
    assert summary['frozen_sha256'] == frozen_sha and summary['frozen_candidate_sha256'] == frozen['candidate_sha256']
    assert summary['base_unchanged'] and summary['production_model_changed'] is False
    retired = read(out / 'candidate-retired.json')
    assert retired['sha256'] == frozen['candidate_sha256'] and retired['original_modified'] is False
    assert not (out / 'candidate.gguf').exists() and not (out / 'candidate.gguf.partial').exists()
    database = out / 'completed-cases.sqlite'
    before = sha(database)
    request_map = requests_for(frozen, frozen_sha, ids, rows)
    with contextlib.closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert connection.execute("SELECT value FROM metadata WHERE key='frozen_sha256'").fetchone() == (frozen_sha,)
        # Reuse the pinned immutable-record validation without opening a writer.
        results = CaseStore.load(SimpleNamespace(db=connection), request_map)
        records = []
        for arm, identifier, expected in connection.execute('SELECT arm,id,payload_sha256 FROM cases ORDER BY arm,id'):
            mirror = out / arm / (hashlib.sha256(identifier.encode()).hexdigest()[:20] + '.json')
            assert mirror.resolve().parent == (out / arm).resolve() and not mirror.is_symlink()
            assert sha(mirror) == expected
            records.append({'arm': arm, 'id': identifier, 'sha256': expected})
        for arm in results:
            assert len(list((out / arm).glob('*.json'))) == 1152
    assert sha(database) == before, 'Read-only audit altered the checkpoint'
    with contextlib.closing(sqlite3.connect((folder / 'ledger.sqlite').as_uri() + '?mode=ro', uri=True)) as ledger:
        assert ledger.execute("SELECT COUNT(*) FROM runs WHERE status='running'").fetchone() == (0,)
        passes = ledger.execute("SELECT COUNT(*) FROM runs WHERE phase IN ('discovery','confirmation')").fetchone()[0]
        assert passes <= protocol['budgets']['forward_passes_per_model']
    computed = recompute(results, ids, summary)
    result = {'passed': True, 'checked_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'model': model, 'summary_sha256': sha(out / 'summary.json'), 'frozen_sha256': frozen_sha,
              'frozen_candidate_sha256': frozen['candidate_sha256'], 'base_sha256': frozen['base_sha256'],
              'completed_cases_per_arm': {arm: len(values) for arm, values in results.items()},
              'database_sha256': before, 'record_hashes': records, 'accounted_forward_passes': passes,
              'pinned_prompt_seed_sampling_and_model_identities_verified': True,
              'original_unchanged': True, 'temporary_candidate_retired': True,
              'production_model_changed': False, 'inference_rerun': False, **computed}
    atomic_json(destination, result)
    print(json.dumps({'confirmation_audit_passed': True, 'model': model,
                      'paired': computed['recomputed_paired']}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    audit(parser.parse_args().model)
