"""Save read-only SQLite snapshots and pinned resume inputs on both SSDs.

Never restores, launches or stops a worker. Recovery requires reviewing the
latest authoritative database first; an older mirror must not replace newer
committed results. Original/candidate model bytes are not duplicated here.
"""
import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LAB = ROOT / 'Maintenance/Research/Takehi-PortalAI-20261103'
FOLDER = LAB / 'experiments/27-abliterated'
PHASE = FOLDER / '005-independent-confirmation'
sys.path[:0] = [str(LAB), str(ROOT / 'Tools/WeightSpace')]
from checkpointed_confirmation import requests_for
from confirmation_store import CaseStore
from experiment import atomic_json, sha, space


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def packed(files):
    normalized = {name.replace('\\', '/'): data for name, data in files.items()}
    assert len(normalized) == len(files), 'Archive path normalization collided.'
    files = normalized
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=1)
    value = buffer.getvalue()
    with zipfile.ZipFile(io.BytesIO(value)) as archive:
        assert archive.testzip() is None
        assert all(archive.read(name) == data for name, data in files.items())
    return value


def snapshot_database(path):
    with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        target = sqlite3.connect(':memory:')
        try:
            source.backup(target, pages=128, sleep=.01)
            assert target.execute('PRAGMA integrity_check').fetchone() == ('ok',)
            return target
        except BaseException:
            target.close()
            raise


def write_verified(path, data):
    expected = hashlib.sha256(data).hexdigest()
    if path.exists():
        assert sha(path) == expected, 'An existing snapshot differs; preserve it for review.'
        return expected
    space(path.parent, len(data) + 1024**2)
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    assert sha(path) == expected
    return expected


def main():
    control = read(FOLDER / 'CONFIRMATION-CONTROLLER.json')
    assert control['stage'] == 'running bounded worker'
    assert not (PHASE / 'summary.json').exists()
    frozen = read(PHASE / 'frozen.json')
    frozen_sha = sha(PHASE / 'frozen.json')
    assert frozen_sha == '66df185172caa72f306a692fe7ce0e973d0444fcc983d3158078683753dd0c95'
    inputs = {}
    for relative, expected in frozen['source_and_data_pins'].items():
        path = ROOT / relative
        assert sha(path) == expected
        inputs[relative] = path.read_bytes()
    for name in ('run_checkpointed_confirmation.py', 'extend_discovery.py', 'discovery.py', 'research_grading.py'):
        path = LAB / name
        inputs[str(path.relative_to(ROOT))] = path.read_bytes()
    for path in (FOLDER / 'selected-recipe.json', FOLDER / '004-generation-screen/summary.json', PHASE / 'frozen.json'):
        inputs[str(path.relative_to(ROOT))] = path.read_bytes()
    manifest = {name: hashlib.sha256(value).hexdigest() for name, value in inputs.items()}
    inputs['RESUME-INPUTS.json'] = encoded({'files': manifest, 'frozen_sha256': frozen_sha,
        'scope': 'Pinned research inputs; uses the matching installed r69 portable runtime and original model. Review before restoring; do not overwrite newer committed cases.'})
    input_bytes = packed(inputs)
    input_sha = hashlib.sha256(input_bytes).hexdigest()
    ids = read(LAB / 'splits.json')['confirmation_ids']
    chosen = set(ids)
    with (LAB / 'practice.jsonl').open(encoding='utf-8') as stream:
        rows = {row['id']: row for row in map(json.loads, stream) if row['id'] in chosen}
    requests = requests_for(frozen, frozen_sha, ids, rows)
    files = {'frozen.json': (PHASE / 'frozen.json').read_bytes()}
    with contextlib.closing(snapshot_database(PHASE / 'completed-cases.sqlite')) as database:
        assert database.execute("SELECT value FROM metadata WHERE key='frozen_sha256'").fetchone() == (frozen_sha,)
        results = CaseStore.load(SimpleNamespace(db=database), requests)
        files['completed-cases.sqlite'] = database.serialize()
        for arm, identity, payload, expected in database.execute('SELECT arm,id,payload,payload_sha256 FROM cases'):
            raw = payload.encode()
            assert hashlib.sha256(raw).hexdigest() == expected
            files[arm + '/' + hashlib.sha256(identity.encode()).hexdigest()[:20] + '.json'] = raw
    with contextlib.closing(snapshot_database(FOLDER / 'ledger.sqlite')) as ledger:
        files['ledger.sqlite'] = ledger.serialize()
        for identity, expected in ledger.execute("SELECT id,request FROM runs WHERE phase='confirmation'"):
            path = PHASE / 'requests' / (identity + '.json')
            value = read(path)
            digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            assert digest == expected
            files['requests/' + path.name] = path.read_bytes()
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    report = {'saved_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'counts': {arm: len(value) for arm, value in results.items()},
              'frozen_sha256': frozen_sha, 'candidate_sha256': frozen['candidate_sha256'],
              'resume_inputs_zip_sha256': input_sha,
              'source_database_modified': False, 'model_weights_copied': False,
              'models_rehashed_during_checkpoint': False,
              'snapshot_method': 'SQLite online backup into private in-memory connections; all saved request/payload hashes validated; exported original JSON payload bytes.',
              'recovery_requirement': 'Review controller ownership, pause markers, model hashes and the latest authoritative records. Never roll back newer completed cases or replay their inference. Ledger snapshot may be later than the case snapshot; retain all accounted passes and reconcile under the exclusive worker lock.',
              'controller_pid': control['pid'], 'automatic_restore': False}
    files['CHECKPOINT.json'] = encoded(report)
    archive = packed(files)
    assert read(FOLDER / 'CONFIRMATION-CONTROLLER.json')['pid'] == control['pid']
    snapshot_name = 'checkpoint-' + stamp + '.zip'
    for drive in ('D', 'E'):
        base = Path(drive + ':/PortalAI Windows/Maintenance/Validation/Weight-Final-r69')
        destination = base / 'ProgressSnapshots'
        destination.mkdir(exist_ok=True)
        write_verified(destination / ('inputs-' + input_sha + '.zip'), input_bytes)
        archive_sha = write_verified(destination / snapshot_name, archive)
        state_path = base / 'WORK-STATE.json'
        value = read(state_path)
        assert value['work_complete'] is False
        old_sha = sha(state_path)
        history = base / 'Work-History' / (old_sha + '-WORK-STATE.json')
        history.parent.mkdir(exist_ok=True)
        if not history.exists():
            shutil.copy2(state_path, history)
        assert sha(history) == old_sha == sha(state_path)
        value.update(checkpoint_updated_at_utc=report['saved_at_utc'], completed_cases=report['counts'],
                     latest_resume_archive='Maintenance/Validation/Weight-Final-r69/ProgressSnapshots/' + snapshot_name,
                     latest_resume_archive_sha256=archive_sha,
                     resume_inputs_archive='Maintenance/Validation/Weight-Final-r69/ProgressSnapshots/inputs-' + input_sha + '.zip',
                     resume_checkpoint_scope=report['recovery_requirement'])
        atomic_json(state_path, value)
    print(json.dumps({'saved_and_verified_on_D_and_E': True, 'counts': report['counts'],
                      'checkpoint_bytes_per_drive': len(archive), 'shared_input_bytes_per_drive': len(input_bytes),
                      'worker_untouched': True}), flush=True)


if __name__ == '__main__':
    main()
