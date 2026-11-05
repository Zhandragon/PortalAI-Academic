"""Publish CPU preparation and reviewed crash recovery without model promotion."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LAB = ROOT / 'Maintenance/Research/Takehi-PortalAI-20261103'
REPOS = Path('C:/Users/genes/source/PortalAI-mission-audit-20261029')
sys.path.insert(0, str(ROOT / 'Tools/WeightSpace'))
from experiment import atomic_json, sha, space


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def git(repo, *arguments):
    return subprocess.check_output(['git', *arguments], cwd=repo, text=True, timeout=300).strip()


def main():
    receipt_path = BASE / 'CODING-PREPARATION-PUBLISHED.json'
    assert not receipt_path.exists(), 'Publication already recorded; do not replay.'
    frozen = read(LAB / 'experiments/27-abliterated/005-independent-confirmation/frozen.json')
    assert all(sha(ROOT / path) == digest for path, digest in frozen['source_and_data_pins'].items())
    subset = LAB / 'final-benchmarks/MBPP/portable-subset.json'
    report = read(subset)
    assert report['input_rows'] == 257 and report['selected_rows'] == 129 and report['excluded_rows'] == 128
    assert report['model_generations_run'] == 0
    files = {name: LAB / name for name in ('mbpp_adapter.py', 'test_mbpp_adapter.py', 'prepare_mbpp_subset.py')}
    files['portable-subset.json'] = subset
    files['review_confirmation_crash_20261105.py'] = BASE / 'review_confirmation_crash_20261105.py'
    files['CRASH-REVIEW.json'] = BASE / 'CrashReview-20261105T005909Z/REVIEW.json'
    files[Path(__file__).name] = Path(__file__)
    rel = 'Research/WeightSpace/InstalledGGUF/Finalization/CodingPreparation'
    validation = {
        'prepared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'adapter_cpu_tests_passed': 10,
        'raw_test_rows_reviewed': 257,
        'selected_reference_programs_passed': 129,
        'excluded_rows_with_reasons': 128,
        'model_generations_run': 0,
        'confirmation_source_and_data_pins_unchanged': True,
        'source_sha256': {name: sha(path) for name, path in files.items()},
        'final_benchmark_executor_implemented': False,
        'final_benchmark_plan_frozen': False,
        'original_models_replaced': False,
    }
    readme = '''# CPU coding preparation and reviewed recovery

This is preparation for a conditional final benchmark, not model performance
evidence. Independent confirmation remains in progress. No original model or
production selection has changed.

The adapter parses the pinned sanitized MBPP test syntax into the existing
portable pure-function checker. Ten CPU tests passed, including rejected
nonliteral calls, unsupported value types, name collisions and input mutation.
All 257 test rows were reviewed. Exactly 129 reference programs pass the owned
512 MiB / five-second checker. The other 128 rows are excluded with individual
reasons in portable-subset.json. This is explicitly a restricted subset, not a
full MBPP score. The selected cases must still be included in a disjointness-
checked, immutable final plan with seeds, repetitions, prompts and other domains.
No final model answers have been generated or used to select these cases.

The original locations of mbpp_adapter.py, test_mbpp_adapter.py and
prepare_mbpp_subset.py are Maintenance/Research/Takehi-PortalAI-20261103.
The subset lives under that directory's final-benchmarks/MBPP. This source
depends on the existing portable evaluator and is published for inspection.

The first confirmation worker exited on 2026-11-05 at 00:59:09 UTC with a Windows
native access violation (0xC0000005 in python312.dll). The cause is undetermined.
All 188 committed cases, request hashes, JSON mirrors, frozen inputs and both
model hashes passed review. Recovery copies were verified on D and E before a
single reviewed continuation of the unchanged worker. Completed cases were
preserved; the interrupted pass stays accounted. The resumed worker completed
new cases. Another error stops for review; no automatic error-retry loop was
added. CRASH-REVIEW.json and the review source preserve that evidence. This does
not establish that the underlying crash cause was fixed.
'''
    for edition in ('Full', 'Academic'):
        repo = REPOS / edition
        assert not git(repo, 'status', '--porcelain'), 'Review existing checkout changes first.'
        target = repo / rel
        assert not target.exists(), 'Staged preparation already exists; review partial publication.'
        target.mkdir()
        for name, source in files.items():
            shutil.copy2(source, target / name)
            assert sha(source) == sha(target / name)
        atomic_json(target / 'VALIDATION.json', validation)
        (target / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    for drive in ('D', 'E'):
        target = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69/CodingPreparation')
        assert not target.exists()
        space(target.parent, sum(path.stat().st_size for path in files.values()) + 1024**2)
        shutil.copytree(REPOS / 'Academic' / rel, target)
        assert all(sha(target / name) == sha(source) for name, source in files.items())
    heads = {}
    for edition in ('Full', 'Academic'):
        repo = REPOS / edition
        git(repo, 'add', '--', rel)
        staged = git(repo, 'diff', '--cached', '--name-only').splitlines()
        expected = {rel + '/' + name for name in (*files, 'README.md', 'VALIDATION.json')}
        assert set(staged) == expected
        git(repo, 'diff', '--cached', '--check')
        git(repo, 'commit', '-m', 'Prepare restricted coding benchmark and record reviewed confirmation recovery')
        git(repo, 'push', 'origin', 'main')
        head = git(repo, 'rev-parse', 'HEAD')
        assert git(repo, 'ls-remote', 'origin', 'refs/heads/main').split()[0] == head
        assert not git(repo, 'status', '--porcelain')
        heads[edition] = head
    receipt = dict(validation, repository_heads=heads, published_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    for drive in ('D', 'E'):
        base = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69')
        atomic_json(base / receipt_path.name, receipt)
        path = base / 'WORK-STATE.json'
        value = read(path)
        history = base / 'Work-History' / (sha(path) + '-WORK-STATE.json')
        history.parent.mkdir(exist_ok=True)
        if not history.exists():
            shutil.copy2(path, history)
        assert sha(history) == sha(path)
        value.update(repository_heads=heads, checkpoint_updated_at_utc=receipt['published_at_utc'],
                     coding_preparation='Maintenance/Validation/Weight-Final-r69/CodingPreparation',
                     coding_reference_subset={'rows': 129, 'source_rows': 257, 'adapter_cpu_tests': 10, 'model_generations': 0},
                     reviewed_confirmation_restarts=1,
                     crash_review='Maintenance/Validation/Weight-Final-r69/CrashReview-20261105T005909Z/REVIEW.json',
                     recovery_note='First native access violation reviewed; 188 cases and frozen identities verified, both-drive recovery copies saved, unchanged worker resumed. Root cause undetermined. If the error recurs, investigate before any further restart.')
        atomic_json(path, value)
    print(json.dumps({'published_heads': heads, 'independent_D_E_snapshots_verified': True,
                      'model_study_complete': False, 'original_models_changed': False}), flush=True)


if __name__ == '__main__':
    main()
