"""Prepare exact final cases on CPU; never load a model or alter confirmation."""
import collections
import json
import os
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
DEST = LAB / 'final-benchmarks'
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from experiment import atomic_json, sha, space
from final_case_plan import DATASET_ORDER, MMLU_SELECTION_SEED, adapt_row, select_mmlu, screen_cases, sample_requests


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_rows(name, pin):
    folder = DEST / name
    raw = folder / pin['file']
    assert sha(raw) == pin['sha256'], 'Pinned raw dataset changed: ' + name
    pins = {str(raw.relative_to(ROOT)): sha(raw)}
    if raw.suffix == '.jsonl':
        with raw.open(encoding='utf-8') as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
    else:
        converted = folder / pin.get('converted_file', 'converted.json')
        if pin.get('converted_sha256'):
            assert sha(converted) == pin['converted_sha256']
        rows = read(converted)
        # Verify the existing conversion against the pinned Parquet, instead of
        # trusting a newly observed JSON digest as proof of data equivalence.
        import pyarrow.parquet as pq
        original = pq.read_table(raw, use_threads=False).to_pylist()
        assert rows == original, 'Converted data differs from pinned source: ' + name
        pins[str(converted.relative_to(ROOT))] = sha(converted)
    return rows, pins


def main():
    target = DEST / 'prepared-case-plan.json'
    assert not target.exists(), 'Review any existing prepared plan instead of regenerating it.'
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    # Reuse the installed same-ABI portable converter. No pip or host runtime.
    packages = ROOT.parent / 'Utilities/Portable Abliterator/runtime/Lib/site-packages'
    sys.path.insert(0, str(packages))
    import pyarrow
    pyarrow.set_cpu_count(1)
    pyarrow.set_io_thread_count(1)
    assert Path(pyarrow.__file__).resolve().is_relative_to(packages.resolve())
    manifest = read(DEST / 'manifest.json')
    protocol = read(LAB / 'protocol.json')
    frozen_path = LAB / 'experiments/27-abliterated/005-independent-confirmation/frozen.json'
    frozen = read(frozen_path)
    assert sha(frozen_path) == '66df185172caa72f306a692fe7ce0e973d0444fcc983d3158078683753dd0c95'
    assert all(sha(ROOT / path) == expected for path, expected in frozen['source_and_data_pins'].items())
    input_pins = {str((DEST / 'manifest.json').relative_to(ROOT)): sha(DEST / 'manifest.json')}
    candidates, source_counts, repetitions = [], {}, {}
    for name in DATASET_ORDER:
        pin = manifest['datasets'][name]
        rows, pins = load_rows(name, pin)
        input_pins.update(pins)
        source_counts[name] = len(rows)
        repetitions[name] = pin.get('samples_per_case', 1)
        if name == 'MMLU-Pro':
            rows = select_mmlu(rows)
        if name == 'MBPP':
            subset_path = DEST / name / 'portable-subset.json'
            subset = read(subset_path)
            assert subset['source'] == pin and subset['converted_sha256'] == sha(DEST / name / 'converted.json')
            assert all(sha(LAB / path) == expected for path, expected in subset['source_sha256'].items())
            assert sha(ROOT / 'Tools/WeightSpace/code_check.py') == subset['checker_sha256']
            originals = {row['task_id']: row for row in rows}
            for case in subset['cases']:
                identifier = int(case['id'].removeprefix('mbpp-sanitized-'))
                candidates.append(dict(case, id='final-MBPP:' + str(identifier), dataset=name, domain='coding',
                                       source_question=originals[identifier]['prompt']))
            input_pins[str(subset_path.relative_to(ROOT))] = sha(subset_path)
        else:
            candidates.extend(adapt_row(name, row, index) for index, row in enumerate(rows))
    with (LAB / 'practice.jsonl').open(encoding='utf-8') as stream:
        prior = [(row['id'], row['problem']) for row in map(json.loads, stream)]
    prior.extend((row['id'], row['prompt']) for row in read(LAB / 'discovery-broad.json'))
    for name in ('practice.jsonl', 'discovery-broad.json', 'protocol.json'):
        input_pins[str((LAB / name).relative_to(ROOT))] = sha(LAB / name)
    cases, excluded = screen_cases(candidates, prior)
    requests = sample_requests(cases, repetitions)
    domains = sorted({case['domain'] for case in cases})
    counts = dict(collections.Counter(case['dataset'] for case in cases))
    result = {
        'prepared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'purpose': 'CPU-only final-case preparation; not an executable or completed model benchmark',
        'ready_for_model_execution': False,
        'model_generations_run': 0,
        'final_execution_plan_frozen': False,
        'confirmation_frozen_sha256': sha(frozen_path),
        'candidate_sha256': frozen['candidate_sha256'],
        'sampling_to_preserve': protocol['models']['27-abliterated']['sampling'],
        'input_pins': input_pins,
        'source_sha256': {name: sha(LAB / name) for name in ('final_case_plan.py', 'test_final_case_plan.py', 'prepare_final_case_plan.py')},
        'raw_source_rows': source_counts,
        'prior_pool_questions_screened': len(prior),
        'exact_overlap_policy': 'Casefold and whitespace normalization of source questions; exclude all practice/discovery-pool overlaps and later final duplicates. No claim of semantic decontamination.',
        'exclusions': excluded,
        'mmlu_selection': {'rule': 'lowest SHA256(seed + NUL + question_id), before overlap exclusions',
                           'seed': MMLU_SELECTION_SEED, 'requested_count': 1000,
                           'selected_case_ids': [case['id'] for case in candidates if case['dataset'] == 'MMLU-Pro']},
        'samples_per_case': repetitions,
        'unique_cases_per_dataset': counts,
        'unique_cases_total': len(cases),
        'planned_requests_per_arm': len(requests),
        'planned_requests_both_arms': len(requests) * 2,
        'domains_prepared': domains,
        'missing_required_domains': sorted({'math', 'coding', 'tools', 'instruction'} - set(domains)),
        'cases': cases, 'requests': requests,
        'missing_benchmarks': manifest.get('missing_benchmarks', {}),
        'remaining_before_execution': ['separate final executor with pinned source/runtime/model identities',
                                      'fresh tool-use cases and actual-harness validation plan',
                                      'audited positive independent confirmation',
                                      'checkpoint, resource, duplicate-worker and interruption tests'],
        'promotion_permitted': False,
    }
    encoded_bytes = len((json.dumps(result, indent=2) + '\n').encode())
    space(DEST, encoded_bytes + 4 * 1024**2)
    atomic_json(target, result)
    print(json.dumps({key: result[key] for key in ('unique_cases_per_dataset', 'unique_cases_total',
                    'planned_requests_per_arm', 'missing_required_domains', 'model_generations_run')}
                     | {'overlap_exclusions': len(excluded), 'parquet_conversions_verified': True}), flush=True)


if __name__ == '__main__':
    main()
