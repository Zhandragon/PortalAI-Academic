"""Build Windows r82 from a checksum-verified r81 package without running installer UI.

Preserve all dependency pins, native installer bytes and edition/trial policy.
Only reviewed generated-output workflow sources are replaced; native layers are retained.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import zipfile

VERSION = '2026.11.22-Desktop-r82'
GUIDE = 'Documentation/Nice_Output_Workflow_20261122.txt'

def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def dump(path, value):
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')

def build(repo, previous, stage, runtime_root, trial=False):
    assert sha(previous) == Path(str(previous)+'.sha256').read_text().split()[0]
    stage.mkdir(parents=True, exist_ok=False)
    package = stage/'package'
    package.mkdir()
    with zipfile.ZipFile(previous) as archive:
        for item in archive.infolist():
            assert '/' not in item.filename and '\\' not in item.filename
            with archive.open(item) as src, (package/item.filename).open('xb') as dest:
                shutil.copyfileobj(src, dest, 1024**2)
    for row in json.loads((package/'PACKAGE_SHA256.json').read_text()):
        p = package/row['path']
        assert p.stat().st_size == row['bytes'] and sha(p) == row['sha256']
    release = json.loads((package/'release.json').read_text())
    old = release['distribution_version']
    assert old == '2026.11.21-Desktop-r81'
    edition = release['upgrade']['edition']
    assert bool(release.get('trial')) == trial
    original_components = json.dumps(release['components'], sort_keys=True)
    assert sha(package/'payload.zip') == release['payload']['sha256']
    app = repo/'ApplicationSources/Windows/PortalAI'
    manifest=json.loads((repo/'tools/nice-output-update-Windows.json').read_text())
    overlay={row['path']:(app/row['path']).read_bytes() for row in manifest['files']}
    for row in manifest['files']:
        assert hashlib.sha256(overlay[row['path']]).hexdigest()==row['sha256'],row['path']
    # Verified r81 already contains the pinned native capability layers.
    if trial:
        module_spec = importlib.util.spec_from_file_location('handsfree_trial_overlay', repo/'TrialSources/build_overlay.py')
        trial_builder = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(trial_builder)
        overlay.update(trial_builder.sources('Windows'))
    rows = []
    old_rows = {row['member']: row for row in release['payload']['members']}
    replacement = stage/'payload-r82.zip'
    with zipfile.ZipFile(package/'payload.zip') as src:
        stamp = src.read('PortalAI/ControlCenter/release_version.py')
        assert old.encode() in stamp
        if trial:
            assert b'TRIAL_EDITION = True' in overlay['ControlCenter/release_version.py']
        else:
            assert overlay['ControlCenter/release_version.py'] == (app/'ControlCenter/release_version.py').read_bytes()
        with zipfile.ZipFile(replacement, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as dest:
            for name in sorted(set(src.namelist()) | {'PortalAI/'+n for n in overlay}):
                if name.endswith('/'):
                    continue
                original = src.read(name) if name in old_rows else None
                if original is not None:
                    row = old_rows[name]
                    assert len(original) == row['bytes'] and hashlib.sha256(original).hexdigest() == row['sha256'], name
                relative = name.removeprefix('PortalAI/')
                data = overlay.get(relative, original)
                assert data is not None
                row = dict(old_rows.get(name, {'member': name, 'dest': name.replace('PortalAI/', 'PortalAI Windows/', 1)}))
                row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
                rows.append(row)
                dest.writestr(name, data)
    replacement.replace(package/'payload.zip')
    release['payload'].update(bytes=(package/'payload.zip').stat().st_size, sha256=sha(package/'payload.zip'), members=rows)
    release.update(distribution_version=VERSION, release='PortalAI-'+VERSION+'-suite-'+edition+('-Trial' if trial else '')+'-Windows', supersedes_release=old)
    upgrade = {**release['upgrade'], **json.loads((package/'upgrade.json').read_text())}
    upgrade['version'] = VERSION
    upgrade['compatible_versions'] = list(dict.fromkeys(upgrade.get('compatible_versions', [])+[old]))
    release['upgrade'] = upgrade
    release['nice_output_workflow'] = {'guide':'PortalAI Windows/'+GUIDE,'automatic_action_replay':False,'native_other_platforms_tested':False}
    assert json.dumps(release['components'], sort_keys=True) == original_components
    sys.path.insert(0, str(repo/'InstallerSources/Windows'))
    import installer_core
    installer_core.plan(release, [])
    installer_core.plan(release, [c['id'] for c in release['components']])
    dump(package/'release.json', release)
    dump(package/'upgrade.json', upgrade)
    plan = json.loads((package/'storage-plan.json').read_text())
    plan.update(release=release['release'], payload_bytes=sum(r['bytes'] for r in rows), payload_files=len(rows))
    dump(package/'storage-plan.json', plan)
    start = package/'START_HERE.txt'
    start.write_text(start.read_text(encoding='utf-8').replace(old, VERSION)+'\n'+(app/GUIDE).read_text(encoding='utf-8'), encoding='utf-8')
    pins = [{'path': p.name, 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in sorted(package.iterdir()) if p.name != 'PACKAGE_SHA256.json']
    dump(package/'PACKAGE_SHA256.json', pins)
    output = stage/f'PortalAI-{edition}{"-Trial" if trial else ""}-Windows-Installer-{VERSION}.zip'
    with zipfile.ZipFile(output, 'x', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for p in sorted(package.iterdir()):
            archive.write(p, p.name)
    Path(str(output)+'.sha256').write_text(sha(output)+'  '+output.name+'\n')
    with zipfile.ZipFile(output) as archive:
        for row in pins:
            assert archive.getinfo(row['path']).file_size == row['bytes']
            with archive.open(row['path']) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == row['sha256']
    with zipfile.ZipFile(package/'payload.zip') as archive:
        for row in rows:
            with archive.open(row['member']) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == row['sha256']
    report = dict(version=VERSION, edition=edition, trial=trial, archive=str(output), sha256=sha(output), payload_files=len(rows), changed_source_files=sorted(overlay), component_pins_unchanged=True, native_installer_unchanged=True, archive_and_payload_verified=True, minimum_and_full_install_plans_passed=True, recipient_install_tested=False)
    dump(stage/'validation.json', report)
    print(json.dumps(report), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('repo', 'previous', 'stage', 'runtime-root'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--trial', action='store_true')
    args = parser.parse_args()
    build(args.repo, args.previous, args.stage, args.runtime_root, args.trial)
