"""Finalize a completed, audited non-improvement; never promote or alter weights.

Each external write is recorded. Failures stop for review rather than replaying
commits, uploads or metadata changes automatically.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LAB = ROOT / 'Maintenance/Research/Takehi-PortalAI-20261103'
OLD = BASE.with_name('Weight-Profiles-r65')
STAGE = Path('E:/Backups/PortalAI-Weight-Final-Release-r69')
REPOS = Path('C:/Users/genes/source/PortalAI-mission-audit-20261029')
sys.path[:0] = [str(BASE), str(LAB), str(ROOT / 'Tools/WeightSpace')]
import github_release as gh
from experiment import atomic_json, sha, space
from campaign_verdict import model_verdict

STATE = BASE / 'RESEARCH-FINALIZATION.json'


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def state(step, **extra):
    value = dict(pid=os.getpid(), updated_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                 step=step, original_models_replaced=False, **extra)
    atomic_json(STATE, value)
    print(json.dumps(value), flush=True)


def call(path, *args):
    state('running ' + path.name, arguments=list(args))
    folder = BASE / 'FinalizationLogs'
    folder.mkdir(exist_ok=True)
    log = folder / (path.stem + '-' + str(time.time_ns()) + '.log')
    with log.open('x', encoding='utf-8') as stream:
        subprocess.run([sys.executable, '-B', '-I', str(path), *args], cwd=ROOT, check=True,
                       timeout=7200, stdout=stream, stderr=subprocess.STDOUT,
                       creationflags=subprocess.CREATE_NO_WINDOW)


def replace_json(path, value):
    if path.exists():
        backup = Path('E:/Backups/PortalAI-Weight-Final-r69/final-research-before') / (sha(path) + '-' + path.name)
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            shutil.copy2(path, backup)
        assert sha(path) == sha(backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, value)


def main():
    assert not STATE.exists(), 'Existing finalization must be reviewed, never replayed blindly.'
    folder = LAB / 'experiments/27-abliterated'
    confirmation = read(folder / '005-independent-confirmation/summary.json')
    audit = read(folder / 'CONFIRMATION-AUDIT.json')
    assert audit['summary_sha256'] == sha(folder / '005-independent-confirmation/summary.json')
    assert audit['frozen_sha256'] == sha(folder / '005-independent-confirmation/frozen.json')
    verdict = model_verdict({'discovery': read(folder / '004-generation-screen/summary.json'),
                            'independent_confirmation': confirmation, 'confirmation_audit': audit})
    assert verdict['stage'] == 'confirmation_not_established' and verdict['complete']
    assert not verdict['promotion_allowed']
    deployment = read(BASE / 'SOFTWARE-DEPLOYMENT.json')
    assert deployment['software_deployment_complete']
    state('audited confirmation did not establish improvement')
    # Only descriptive catalog metadata changes. Profile archives, cache,
    # account preferences and every original model remain untouched.
    for drive in ('D', 'E'):
        root = Path(drive + ':/PortalAI Windows')
        catalog_path = root / 'LLM/WeightEdits/EVALUATED-PROFILES.json'
        catalog = read(catalog_path)
        row = next(item for item in catalog['profiles'] if item['model'] == '27-abliterated')
        row['independent_confirmation'] = confirmation
        row['final_campaign_decision'] = verdict['decision']
        row['broad_improvement_established'] = False
        replace_json(catalog_path, catalog)
        archive = root / 'Maintenance/Validation/Weight-Final-r69/ConfirmedStudy'
        archive.mkdir(exist_ok=False)
        for source in (folder / 'CONFIRMATION-AUDIT.json', folder / '005-independent-confirmation/summary.json',
                       folder / '005-independent-confirmation/frozen.json'):
            target = archive / source.name
            space(archive, source.stat().st_size)
            shutil.copy2(source, target)
            assert sha(source) == sha(target)
    call(OLD / 'publish_campaign_snapshot.py')
    call(BASE / 'publish_optional_profile_docs.py')
    for edition in ('Full', 'Academic'):
        results = read(REPOS / edition / 'Research/WeightSpace/InstalledGGUF/RESULTS.json')
        assert results['campaign_complete'] and results['production_model_replacements'] == 0
        assert results['model_decisions']['27-abliterated']['stage'] == 'confirmation_not_established'
    call(BASE / 'final_originals_and_storage.py')
    call(BASE / 'verify_live_downloads.py')
    for edition in ('Full', 'Academic'):
        call(BASE / 'github_release.py', '--edition', edition, '--action', 'verify')
    identity = read(BASE / 'FINAL-IDENTITY.json')
    assert identity['passed'] and not identity['models_replaced']
    receipt = dict(completed_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   work_complete=True, campaign_complete=True, software_deployment_complete=True,
                   original_models_replaced=False, production_preferences_modified=False,
                   independent_confirmation_run=True, final_benchmarks_run=False,
                   final_benchmarks_reason='The prespecified independent confirmation gate did not pass.',
                   confirmation=confirmation, confirmation_audit_sha256=sha(folder / 'CONFIRMATION-AUDIT.json'),
                   independent_ssd_identity=identity, release_urls=deployment['release_urls'],
                   scope='Completed bounded installed-model campaign, not an exhaustive search over every possible edit.',
                   limitations=['Quantized adaptation rather than original BF16/vLLM execution.',
                                'No general intelligence gain established or original model replaced.',
                                'The software deployment limitations remain in SoftwareDeployment-r69/DEPLOYMENT.json.'])
    for edition in ('Full', 'Academic'):
        destination = REPOS / edition / 'Research/WeightSpace/InstalledGGUF/FinalDeployment-r69'
        destination.mkdir(exist_ok=False)
        atomic_json(destination / 'DEPLOYMENT.json', receipt)
        pair = confirmation['paired']
        (destination / 'README.md').write_text(
            '# Completed bounded weight-space campaign\n\n'
            f'The 27B abliterated candidate scored {pair["candidate_correct"]}/{pair["n"]} '
            f'against {pair["baseline_correct"]}/{pair["n"]} for its original in independent confirmation. '
            f'The paired gain was {pair["gain"]:.2%}, with a 95% interval '
            f'[{pair["lower_95"]:.2%}, {pair["upper_95"]:.2%}]. '
            'The prespecified confirmation gate did not pass, so separate final benchmarks '
            'were not warranted and no default model was changed. Optional profiles remain '
            'experimental tradeoffs. All six discovery tracks, the audited confirmation and '
            'independent D/E deployment are recorded in ../RESULTS.json and DEPLOYMENT.json.\n',
            encoding='utf-8', newline='\n')
    call(OLD / 'stage_campaign_source.py')
    heads = {}
    for edition in ('Full', 'Academic'):
        repo = REPOS / edition
        assert not subprocess.check_output(['git', 'diff', '--name-only'], cwd=repo).strip()
        assert not subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=repo).strip()
        state('publishing final research source', edition=edition)
        subprocess.run(['git', 'commit', '-m', 'Finalize audited weight-space campaign and retain original models'], cwd=repo, check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], cwd=repo, check=True, timeout=300)
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
        slug = 'Zhandragon/PortalAI' + ('-Academic' if edition == 'Academic' else '')
        token = gh.credentials(repo)
        assert gh.api(token, 'repos/' + slug + '/commits/main')['sha'] == head
        assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo).strip()
        release_state = read(STAGE / edition / 'github-release.json')
        release = gh.api(token, f'repos/{slug}/releases/{release_state["release_id"]}')
        marker = '\n### Final weight-space study\n'
        assert marker not in release['body'], 'An existing final release note requires review.'
        body = release['body'] + marker + (
            '\nThe bounded installed-model study is complete. The admitted 27B edit did not '
            'establish a gain in independently audited confirmation. The campaign did not '
            'replace originals or change production model selection. Optional profiles remain experimental. '
            f'[Final evidence](https://github.com/{slug}/tree/main/Research/WeightSpace/InstalledGGUF/FinalDeployment-r69).\n')
        changed = gh.api(token, f'repos/{slug}/releases/{release_state["release_id"]}', 'PATCH',
                         {'tag_name': release['tag_name'], 'target_commitish': release_state['commit'],
                          'body': body, 'draft': False})
        assert changed['body'] == body and not changed['draft']
        heads[edition] = head
    for path in (BASE / 'FINAL-REPORT.json', Path('E:/PortalAI Windows/Maintenance/Validation/Weight-Final-r69/FINAL-REPORT.json'), STAGE / 'FINAL-REPORT.json'):
        report = read(path)
        report['model_study_complete'] = True
        report['independent_confirmation_or_final_benchmarks_run'] = True
        report['independent_confirmation_run'] = True
        report['final_benchmarks_run'] = False
        report['model_decisions']['27-abliterated'] = {'complete': True, 'decision': verdict['decision'],
                                                     'confirmation_summary_sha256': sha(folder / '005-independent-confirmation/summary.json')}
        report['reason'] = 'Independent confirmation did not establish an accuracy gain; originals retained.'
        replace_json(path, report)
    for edition in ('Full', 'Academic'):
        call(BASE / 'github_release.py', '--edition', edition, '--action', 'verify')
    for drive in ('D', 'E'):
        target = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69/WORK-STATE.json')
        replace_json(target, dict(receipt, final_repository_heads=heads))
    state('complete', work_complete=True, campaign_complete=True, final_repository_heads=heads)


if __name__ == '__main__':
    try:
        main()
    except BaseException as exc:
        if STATE.exists():
            previous = read(STATE)
            state('stopped; review required', error=repr(exc), previous_step=previous.get('step'))
        raise
