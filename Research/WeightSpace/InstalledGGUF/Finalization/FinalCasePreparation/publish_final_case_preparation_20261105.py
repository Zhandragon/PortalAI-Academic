"""Publish CPU-only case preparation and checkpoint source; no live model changes."""
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


def git(repo, *args):
    return subprocess.check_output(['git', *args], cwd=repo, text=True, timeout=300).strip()


def main():
    receipt_name = 'FINAL-CASE-PREPARATION-PUBLISHED.json'
    step = BASE / 'FINAL-CASE-PUBLICATION-STEPS.json'
    assert not step.exists() and not (BASE / receipt_name).exists(), 'Review existing publication steps rather than replaying them.'
    rel = 'Research/WeightSpace/InstalledGGUF/Finalization/FinalCasePreparation'
    plan_path = LAB / 'final-benchmarks/prepared-case-plan.json'
    plan = read(plan_path)
    assert plan['unique_cases_total'] == 4467 and plan['planned_requests_per_arm'] == 11265
    assert plan['model_generations_run'] == 0 and plan['ready_for_model_execution'] is False
    assert all(sha(ROOT / path) == expected for path, expected in plan['input_pins'].items())
    frozen = read(LAB / 'experiments/27-abliterated/005-independent-confirmation/frozen.json')
    assert all(sha(ROOT / path) == expected for path, expected in frozen['source_and_data_pins'].items())
    files = {name: LAB / name for name in ('final_case_plan.py', 'test_final_case_plan.py', 'prepare_final_case_plan.py',
                                         'final_metrics.py', 'test_final_metrics.py')}
    files[plan_path.name] = plan_path
    files['save_live_confirmation_checkpoint.py'] = BASE / 'save_live_confirmation_checkpoint.py'
    files[Path(__file__).name] = Path(__file__)
    validation = {
        'prepared_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'cpu_tests': {'test_final_case_plan.py': 9, 'test_final_metrics.py': 10},
        'total_cpu_tests_passed': 19,
        'all_parquet_conversions_checked_against_pinned_source': True,
        'case_plan_sha256': sha(plan_path),
        'unique_cases_per_dataset': plan['unique_cases_per_dataset'],
        'planned_requests_per_arm': plan['planned_requests_per_arm'],
        'overlap_exclusions': plan['exclusions'],
        'source_sha256': {name: sha(path) for name, path in files.items()},
        'source_bytes': sum(path.stat().st_size for path in files.values()),
        'confirmation_inputs_changed': False, 'model_generations_run': 0,
        'final_executor_implemented': False, 'final_execution_plan_frozen': False,
        'missing_required_domains': plan['missing_required_domains'],
        'live_checkpoint_verified_on_D_and_E': True,
        'live_checkpoint_counts': {'baseline': 399, 'candidate': 0},
        'checkpoint_source_initial_fix': 'ZipInfo normalizes Windows separators. Normalize archive member names before comparing read-back bytes; the initial in-memory validation failed before either SSD snapshot was written.',
        'original_models_replaced': False,
    }
    readme = '''# Final-case preparation (CPU only)

No final model benchmark has run. Independent confirmation is still running,
and original model selections are unchanged. These files prepare part of the
conditional final evaluation; they do not bypass the evidence gates.

The adapters, exact overlap screening and complete-pair scoring checks passed
19 synthetic CPU tests. Existing Parquet-to-JSON conversions were also compared
with every row of the pinned raw files using the existing portable PyArrow.
No new dependency, model download or host installation was needed.

The prepared plan contains 4,467 unique questions and 11,265 generation requests
per arm: MATH-500 (500, four repetitions), GSM8K (1,319, two), AMC23 (40, sixteen),
Minerva (272, four), OlympiadBench (674, four), MMLU-Pro (992, one), IFEval (541,
two), and the previously validated restricted MBPP subset (129, one).

A fixed hash seed selected 1,000 MMLU-Pro rows. Four overlapped the practice pool
and four repeated another selected question after case/whitespace normalization;
all eight were excluded without replacing them. Exclusions and selected IDs
are recorded. This is exact-text screening, not semantic decontamination. The
MBPP result must be called a restricted subset, never the full benchmark.

Prompts, answers, repetition counts and paired seeds are inspectable in
prepared-case-plan.json. This is a prepared case set, not the final execution
freeze: the separate bounded executor, fresh tool-use cases and actual-harness
checks remain to be implemented and tested. Positive audited confirmation is
required before any final model execution. GPQA remains unavailable, so these
artifacts do not support a claim of complete original-paper reproduction.

Final metrics reject missing or extra responses, altered plan seeds, invalid
telemetry and infrastructure errors disguised as wrong answers. Repetitions
are averaged within each question, questions equally within a dataset, and
datasets equally within a domain. Cutoffs and native generation latency are
reported. Missing domains block an overall required-domain score. Metrics alone
cannot authorize promotion or claim actual-harness validation.

The source modules originally live in Maintenance/Research/Takehi-PortalAI-20261103;
the prepared JSON is in its final-benchmarks directory. The checkpoint/publication
helpers live in Maintenance/Validation/Weight-Final-r69 and are maintainer tools.

The live checkpoint helper uses SQLite online backups without writing the
running database. It verifies saved request/payload hashes and preserves the
exact JSON response bytes, ledger and request records. Identical archives and
pinned input bundles were verified on D and E at 399 baseline cases. The input
bundle is reused by checksum. A restore must first check the current owner,
pause markers, model hashes and authoritative completed cases; an older mirror
must never roll back newer results. No automatic restore or duplicate worker
is started, and large model files are not duplicated in these snapshots.
'''
    for edition in ('Full', 'Academic'):
        repo = REPOS / edition
        assert not git(repo, 'status', '--porcelain')
        destination = repo / rel
        assert not destination.exists()
        destination.mkdir()
        for name, source in files.items():
            shutil.copy2(source, destination / name)
            assert sha(destination / name) == sha(source)
        atomic_json(destination / 'VALIDATION.json', validation)
        (destination / 'README.md').write_text(readme, encoding='utf-8', newline='\n')
    for drive in ('D', 'E'):
        destination = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69/FinalCasePreparation')
        assert not destination.exists()
        space(destination.parent, validation['source_bytes'] + 1024**2)
        shutil.copytree(REPOS / 'Academic' / rel, destination)
        assert all(sha(destination / name) == sha(source) for name, source in files.items())
    heads = {}
    for edition in ('Full', 'Academic'):
        repo = REPOS / edition
        git(repo, 'add', '--sparse', '--', rel)
        assert set(git(repo, 'diff', '--cached', '--name-only').splitlines()) == {rel + '/' + name for name in (*files, 'README.md', 'VALIDATION.json')}
        git(repo, 'diff', '--cached', '--check')
        git(repo, 'commit', '-m', 'Prepare disjoint final benchmark cases and verified portable checkpoints')
        heads[edition] = git(repo, 'rev-parse', 'HEAD')
        atomic_json(step, {'heads': heads, 'stage': 'committed ' + edition})
        git(repo, 'push', 'origin', 'main')
        assert git(repo, 'ls-remote', 'origin', 'refs/heads/main').split()[0] == heads[edition]
        assert not git(repo, 'status', '--porcelain')
        atomic_json(step, {'heads': heads, 'stage': 'published and verified ' + edition})
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    receipt = dict(validation, published_at_utc=stamp, repository_heads=heads)
    for drive in ('D', 'E'):
        base = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69')
        atomic_json(base / receipt_name, receipt)
        path = base / 'WORK-STATE.json'
        value = read(path)
        assert value['work_complete'] is False
        history = base / 'Work-History' / (sha(path) + '-WORK-STATE.json')
        history.parent.mkdir(exist_ok=True)
        if not history.exists():
            shutil.copy2(path, history)
        assert sha(history) == sha(path)
        value.update(repository_heads=heads, checkpoint_updated_at_utc=stamp,
                     final_case_preparation='Maintenance/Validation/Weight-Final-r69/FinalCasePreparation',
                     prepared_final_case_count=4467, prepared_final_requests_per_arm=11265,
                     final_case_plan_cpu_tests=9, final_metrics_cpu_tests=10,
                     final_case_plan_frozen=False,
                     final_case_preparation_remaining=['fresh tools domain', 'bounded final executor', 'actual-harness checks', 'positive audited confirmation before execution'])
        atomic_json(path, value)
    print(json.dumps({'published_heads': heads, 'cpu_tests_passed': 19,
                      'model_study_complete': False, 'original_models_changed': False}), flush=True)


if __name__ == '__main__':
    main()
