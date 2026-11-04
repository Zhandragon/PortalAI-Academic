"""Conditional 1,152-pair confirmation with durable, resumable case checkpoints.

Every start/restart is accounted in the existing scientific pass budget. A
worker yields at a completed-case boundary after its time allowance. A manual
GPU pause is never cleared here. No result changes the frozen recipe or scores.
"""
import sys
if __name__ == '__main__' and sys.stdin.readline().strip() != 'start':
    raise SystemExit('Owned start gate required')
import argparse
import contextlib
import gc
import hashlib
import json
import os
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
ENGINE = ROOT / 'Tools/WeightSpace'
sys.path[:0] = [str(LAB), str(ENGINE), str(ROOT / 'Agent')]
from confirmation_store import CaseStore, encoded, request_digest
from experiment import Ledger, atomic_json, sha, space, paired_summary
import research_guard
research_guard.LAB = LAB


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


@contextlib.contextmanager
def worker_lock(folder):
    import msvcrt
    with (folder / 'worker.lock').open('a+b', buffering=0) as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0')
            os.fsync(stream.fileno())
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise RuntimeError('Another confirmation worker owns this experiment') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def engine_pins():
    paths = [ENGINE / name for name in (
        'native_forward.py', 'native-abi.json', 'quantized_edit.py', 'evaluation.py',
        'math_grade.py', 'published/mathqa.py', 'published/provenance.json', 'experiment.py')]
    paths += [LAB / name for name in ('checkpointed_confirmation.py', 'confirmation_store.py',
                                     'protocol.json', 'splits.json', 'practice.jsonl')]
    return {str(path.relative_to(ROOT)): sha(path) for path in paths}


def freeze(folder, model_name, model, spec, summary):
    out = folder / '005-independent-confirmation'
    assert not out.exists(), 'An existing confirmation requires --resume and matching frozen identities.'
    recipe_path = folder / 'selected-recipe.json'
    recipe = read(recipe_path)
    original_sha = sha(model)
    assert recipe['base_sha256'] == original_sha
    out.mkdir()
    frozen = {'model': model_name, 'base_sha256': original_sha, 'recipe_sha256': sha(recipe_path),
              'recipe': recipe, 'discovery_summary_sha256': sha(folder / '004-generation-screen/summary.json'),
              'candidate_sha256': summary['model_receipts']['candidate']['candidate_sha256'],
              'sampling': spec['sampling'], 'independent_question_count': 1152,
              'retuning_after_confirmation': False, 'source_and_data_pins': engine_pins(),
              'frozen_at_unix': time.time(), 'checkpoint_protocol': 1}
    # No confirmation questions or answers have been parsed before this freeze;
    # data bytes were read only to establish their immutable checksums.
    atomic_json(out / 'frozen.json', frozen)
    store = CaseStore(out / 'completed-cases.sqlite', sha(out / 'frozen.json'), create=True)
    store.close()
    return out


def validate(folder, model, spec):
    out = folder / '005-independent-confirmation'
    frozen = read(out / 'frozen.json')
    assert frozen['model'] == folder.name
    assert frozen['checkpoint_protocol'] == 1 and frozen['independent_question_count'] == 1152
    assert frozen['source_and_data_pins'] == engine_pins(), 'Frozen source or data changed.'
    assert frozen['sampling'] == spec['sampling']
    assert frozen['recipe_sha256'] == sha(folder / 'selected-recipe.json')
    assert frozen['recipe'] == read(folder / 'selected-recipe.json')
    assert frozen['discovery_summary_sha256'] == sha(folder / '004-generation-screen/summary.json')
    assert sha(model) == frozen['base_sha256'], 'Original model changed.'
    ids = read(LAB / 'splits.json')['confirmation_ids']
    assert len(ids) == len(set(ids)) == 1152
    chosen = set(ids)
    with (LAB / 'practice.jsonl').open(encoding='utf-8') as stream:
        pool = {row['id']: row for row in map(json.loads, stream)}
    rows = {key: pool[key] for key in ids}
    normalized = lambda value: ' '.join(value.casefold().split())
    texts = {normalized(row['problem']) for row in rows.values()}
    assert len(texts) == 1152
    from extend_discovery import records
    discovery_ids = {row['id'] for row in records(folder)}
    assert not chosen & discovery_ids
    assert not texts & {normalized(pool[key]['problem']) for key in discovery_ids}
    return out, frozen, ids, rows


def requests_for(frozen, frozen_sha, ids, rows):
    from native_forward import item_seed
    requests = {'baseline': {}, 'candidate': {}}
    for arm in requests:
        fingerprint = frozen['base_sha256'] if arm == 'baseline' else frozen['candidate_sha256']
        for key in ids:
            user_text = rows[key]['problem'] + '\nPlease reason step by step, and put your final answer within \\boxed{}.'
            requests[arm][key] = {'frozen_sha256': frozen_sha, 'model_sha256': fingerprint,
                                  'prompt_sha256': hashlib.sha256(user_text.encode()).hexdigest(),
                                  'seed': item_seed(key), 'sampling': frozen['sampling']}
    return requests


def run_worker(args):
    research_guard.require_gpu_unpaused()
    protocol = read(LAB / 'protocol.json')
    spec = protocol['models'][args.model]
    folder = LAB / 'experiments' / args.model
    summary = read(folder / '004-generation-screen/summary.json')
    assert summary['eligible_for_independent_confirmation'], 'Discovery did not qualify.'
    model = ROOT / 'LLM/models' / spec['filename']
    out = folder / '005-independent-confirmation'
    if not args.resume:
        out = freeze(folder, args.model, model, spec, summary)
    assert out.is_dir() and not (out / 'summary.json').exists(), 'Completed confirmation is never replayed.'
    with worker_lock(out):
        return locked_worker(args, folder, out, model, spec)


def locked_worker(args, folder, out, model, spec):
    from native_forward import Forward, metadata, render
    from quantized_edit import materialize
    from evaluation import grade
    from service_manager import acquire_gpu_lease, release_gpu_lease
    out, frozen, ids, rows = validate(folder, model, spec)
    frozen_sha = sha(out / 'frozen.json')
    requests = requests_for(frozen, frozen_sha, ids, rows)
    store = CaseStore(out / 'completed-cases.sqlite', frozen_sha)
    ledger = Ledger(folder / 'ledger.sqlite')
    lease = None
    candidate = out / 'candidate.gguf'
    started = time.monotonic()
    stage = {'model': args.model, 'pid': os.getpid(), 'frozen_sha256': frozen_sha,
             'production_model_changed': False, 'completed_cases_are_never_replayed': True}
    active_pass = None
    processed_total = 0
    try:
        results = store.load(requests)
        store.export(out)
        lease = acquire_gpu_lease('weight-space-checkpointed-confirmation-' + args.model, timeout=3)
        # Exclusive phase lock plus the GPU lease establish that a former
        # confirmation worker no longer owns this experiment. Preserve and
        # account its interruption; never reset or erase the earlier pass.
        for identifier, prior_digest in ledger.db.execute("SELECT id,request FROM runs WHERE phase='confirmation' AND status='running'").fetchall():
            assert args.resume and identifier.startswith('checkpointed-confirmation-')
            request_file = out / 'requests' / (identifier + '.json')
            assert request_file.is_file()
            prior = read(request_file)
            assert prior['frozen_sha256'] == frozen_sha
            assert hashlib.sha256(json.dumps(prior, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == prior_digest
            assert 1 <= len(prior['ids']) <= 256 and len(prior['ids']) == len(set(prior['ids']))
            assert prior['case_requests'] == {key: requests[prior['arm']][key] for key in prior['ids']}
            ledger.end(identifier, {'interrupted_owner_reconciled_under_exclusive_lock': True,
                                   'completed_cases_validated': {arm: len(values) for arm, values in results.items()},
                                   'prior_request_sha256': sha(request_file)}, False)
        for identifier, prior_digest in ledger.db.execute("SELECT id,request FROM runs WHERE phase='cpu' AND status='running' AND id LIKE 'checkpointed-confirmation-materialize-%'").fetchall():
            assert args.resume
            assert hashlib.sha256(json.dumps(frozen, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == prior_digest
            assert not candidate.with_suffix('.gguf.partial').exists(), 'Partial materialization requires review.'
            completed = candidate.is_file() and sha(candidate) == frozen['candidate_sha256']
            ledger.end(identifier, {'reviewed_under_exclusive_lock': True,
                                   'expected_candidate_verified': completed,
                                   'candidate_sha256': frozen['candidate_sha256'] if completed else None}, completed)
        if not candidate.exists():
            assert not any(results.values()), 'Missing candidate requires explicit recovery; evidence preserved.'
            assert not candidate.with_suffix('.gguf.partial').exists(), 'Partial model requires review.'
            count = ledger.db.execute("SELECT COUNT(*) FROM runs WHERE id LIKE 'checkpointed-confirmation-materialize-%'").fetchone()[0]
            identifier = 'checkpointed-confirmation-materialize-' + str(count)
            space(out, model.stat().st_size)
            ledger.begin(identifier, 'cpu', frozen)
            try:
                receipt = materialize(model, frozen['recipe'], candidate)
                assert receipt['candidate_sha256'] == frozen['candidate_sha256']
                ledger.end(identifier, receipt)
            except BaseException as exc:
                ledger.end(identifier, {'error': repr(exc)}, False)
                raise
        assert candidate.resolve().parent == out.resolve() and not candidate.is_symlink()
        assert sha(candidate) == frozen['candidate_sha256']
        atomic_json(out / 'WORK-STATE.json', dict(stage, stage='running', counts={arm: len(v) for arm, v in results.items()}))
        for arm, path in [('baseline', model), ('candidate', candidate)]:
            if len(results[arm]) == len(ids):
                continue
            meta = metadata(path)
            with Forward(path, context=34816, batch=256) as engine:
                for batch_start in range(0, len(ids), 256):
                    pending = [key for key in ids[batch_start:batch_start + 256] if key not in results[arm]]
                    if not pending:
                        continue
                    research_guard.require_gpu_unpaused()
                    if time.monotonic() - started >= args.work_seconds and processed_total:
                        atomic_json(out / 'WORK-STATE.json', dict(stage, stage='checkpointed', counts={a: len(v) for a, v in results.items()}))
                        return 'checkpointed'
                    number = ledger.db.execute("SELECT COUNT(*) FROM runs WHERE id LIKE 'checkpointed-confirmation-%' AND phase='confirmation'").fetchone()[0]
                    active_pass = 'checkpointed-confirmation-' + str(number).zfill(3) + '-' + arm
                    request = dict(frozen_sha256=frozen_sha, arm=arm, batch_start=batch_start,
                                   ids=pending, case_requests={key: requests[arm][key] for key in pending})
                    request_folder = out / 'requests'
                    request_folder.mkdir(exist_ok=True)
                    request_path = request_folder / (active_pass + '.json')
                    assert not request_path.exists()
                    atomic_json(request_path, request)
                    ledger.begin(active_pass, 'confirmation', request)
                    new_cases = 0
                    for key in pending:
                        research_guard.require_gpu_unpaused()
                        space(out, 64 * 1024**2)
                        if time.monotonic() - started >= args.work_seconds and processed_total:
                            ledger.end(active_pass, {'checkpoint_boundary': True, 'completed_in_attempt': new_cases,
                                                     'remaining_ids': [item for item in pending if item not in results[arm]]}, False)
                            active_pass = None
                            atomic_json(out / 'WORK-STATE.json', dict(stage, stage='checkpointed', counts={a: len(v) for a, v in results.items()}))
                            return 'checkpointed'
                        user_text = rows[key]['problem'] + '\nPlease reason step by step, and put your final answer within \\boxed{}.'
                        prompt = render(meta['template'], [{'role': 'user', 'content': user_text}])
                        settings = {name: value for name, value in spec['sampling'].items() if name != 'thinking'}
                        value = engine.generate(prompt, seed=requests[arm][key]['seed'],
                            progress=lambda n, seconds: print(json.dumps({'phase': 'confirmation', 'arm': arm,
                                'id': key, 'tokens': n, 'seconds': round(seconds, 1)}), flush=True) if n % 8192 == 0 else None,
                            **settings)
                        value.pop('activations')
                        # Confirmation never replays activations or tunes a
                        # recipe. Keep raw output and a token-sequence digest
                        # instead of duplicating large token arrays in SQLite
                        # and JSON mirrors for all 2,304 evaluated responses.
                        token_ids = value.pop('token_ids', None)
                        if token_ids is not None:
                            value['token_ids_sha256'] = request_digest(token_ids)
                            value['token_ids_omitted_from_checkpoint'] = True
                        value.pop('capture_counts', None)
                        value.update(id=key, source=rows[key]['source'], grading=grade({'kind': 'math', 'answer': rows[key]['answer']}, value['text']))
                        saved = store.save(arm, key, requests[arm][key], value)
                        results[arm][key] = saved
                        store.export(out, only=(arm, key))
                        new_cases += 1
                        processed_total += 1
                        print(json.dumps({'phase': 'confirmation', 'arm': arm, 'completed': len(results[arm]),
                                          'total': len(ids), 'id': key, 'correct': value['grading']['correct']}), flush=True)
                    ledger.end(active_pass, {'completed_in_attempt': new_cases, 'completed_in_arm': len(results[arm])})
                    active_pass = None
        assert all(set(values) == set(ids) for values in results.values())
        assert sha(model) == frozen['base_sha256'] and sha(candidate) == frozen['candidate_sha256']
        scores = {arm: {key: value['grading']['correct'] for key, value in values.items()} for arm, values in results.items()}
        times = {arm: sum(value['seconds'] for value in values.values()) for arm, values in results.items()}
        paired = paired_summary(scores['baseline'], scores['candidate'])
        report = {'paired': paired, 'eligible_for_separate_final_benchmarks': paired['lower_95'] > 0,
                  'latency_ratio': times['candidate'] / times['baseline'],
                  'cutoffs': {arm: sum(value['finish'] == 'length' for value in values.values()) for arm, values in results.items()},
                  'frozen_candidate_sha256': frozen['candidate_sha256'], 'base_unchanged': True,
                  'production_model_changed': False, 'checkpointed': True, 'frozen_sha256': frozen_sha,
                  'retuning_allowed': False, 'status': 'Independent confirmation complete; review before any conditional final benchmark or deployment.'}
        atomic_json(out / 'summary.json', report)
        gc.collect()
        assert candidate.resolve().parent == out.resolve() and sha(candidate) == frozen['candidate_sha256']
        candidate.unlink()
        atomic_json(out / 'candidate-retired.json', {'sha256': frozen['candidate_sha256'], 'original_modified': False,
                                                    'reason': 'Completed frozen paired confirmation; exact recipe and profile remain.'})
        atomic_json(out / 'WORK-STATE.json', dict(stage, stage='complete', counts={arm: len(v) for arm, v in results.items()}))
        print(json.dumps(report), flush=True)
        return 'complete'
    except BaseException as exc:
        if active_pass:
            row = ledger.db.execute('SELECT status FROM runs WHERE id=?', (active_pass,)).fetchone()
            if row == ('running',):
                ledger.end(active_pass, {'error': repr(exc), 'completed_cases_remain_committed': True}, False)
        atomic_json(out / 'WORK-STATE.json', dict(stage, stage='paused' if isinstance(exc, research_guard.ResearchPaused) else 'stopped; review required', error=repr(exc)))
        raise
    finally:
        if lease:
            release_gpu_lease(lease)
        store.close()
        ledger.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--work-seconds', type=int, default=18000)
    args = parser.parse_args()
    if not 60 <= args.work_seconds <= 18000:
        raise ValueError('Worker allowance must be 60 to 18000 seconds.')
    print(json.dumps({'worker_result': run_worker(args)}), flush=True)


if __name__ == '__main__':
    main()
