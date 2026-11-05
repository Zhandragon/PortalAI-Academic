"""Freeze supported coding cases using reference compatibility, before model runs."""
import collections
import json
import sys
import time
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from mbpp_adapter import adapt, UnsupportedCase
from final_evaluation import grade
from experiment import atomic_json, sha, space


def main():
    folder = LAB / 'final-benchmarks/MBPP'
    destination = folder / 'portable-subset.json'
    assert not destination.exists(), 'An existing subset must not be silently regenerated.'
    manifest_path = LAB / 'final-benchmarks/manifest.json'
    pin = json.loads(manifest_path.read_text())['datasets']['MBPP']
    assert sha(folder / pin['file']) == pin['sha256']
    converted = folder / 'converted.json'
    rows = json.loads(converted.read_text())
    assert len(rows) == 257 and len({row['task_id'] for row in rows}) == 257
    cases, excluded, references = [], [], []
    for row in sorted(rows, key=lambda row: row['task_id']):
        try:
            adapted = adapt(row)
        except UnsupportedCase as exc:
            excluded.append({'task_id': row['task_id'], 'stage': 'syntax_and_literal_compatibility', 'reason': str(exc)})
            continue
        # The existing owned, 512 MiB / five-second pure-function process checks
        # the reference. Infrastructure errors abort; they are not exclusions.
        result = grade(adapted['case'], adapted['reference_source'])
        if not result['correct']:
            excluded.append({'task_id': row['task_id'], 'stage': 'restricted_reference_check', 'detail': result})
            continue
        cases.append(adapted['case'])
        references.append({'task_id': row['task_id'], 'entry': adapted['original_entry_function'],
                           'reference_source': adapted['reference_source'],
                           'original_test_count': adapted['original_test_count'], 'validation': result})
    assert cases and len(cases) + len(excluded) == len(rows)
    report = {
        'prepared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'benchmark': 'MBPP sanitized, portable pure-function subset',
        'full_mbpp_benchmark': False,
        'selection_policy': 'All 257 pinned test rows reviewed, selected only by supported test syntax and successful bounded reference execution; no model output used.',
        'subset_policy': 'literal-json-tests-pure-function-v1',
        'source': pin,
        'manifest_sha256': sha(manifest_path),
        'converted_sha256': sha(converted),
        'source_sha256': {name: sha(LAB / name) for name in ('mbpp_adapter.py', 'test_mbpp_adapter.py', 'prepare_mbpp_subset.py')},
        'checker_sha256': sha(ROOT / 'Tools/WeightSpace/code_check.py'),
        'input_rows': len(rows), 'selected_rows': len(cases), 'excluded_rows': len(excluded),
        'excluded_stages': dict(collections.Counter(row['stage'] for row in excluded)),
        'restrictions': ['no imports or arbitrary attributes', 'literal positional assertions only',
                         'JSON-exact argument and result types', 'no mutation of arguments',
                         'entry function renamed to solve; tests never included in prompts'],
        'cases': cases, 'reference_checks': references, 'exclusions': excluded,
        'model_generations_run': 0, 'confirmation_inputs_changed': False,
        'final_benchmark_plan_frozen': False,
        'remaining_before_final_model_use': 'Include disjointness checking, this file checksum, prompts, seeds, repetitions and all other required domains in one immutable final benchmark plan.',
    }
    space(folder, 4 * 1024**2)
    atomic_json(destination, report)
    print(json.dumps({key: report[key] for key in ('input_rows', 'selected_rows', 'excluded_rows', 'excluded_stages', 'model_generations_run')}), flush=True)


if __name__ == '__main__':
    main()
