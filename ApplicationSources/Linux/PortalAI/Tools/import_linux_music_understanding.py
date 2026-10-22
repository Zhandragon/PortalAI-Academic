"""Import only the missing Linux music-specialist wheels, without host installs."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Agent'))
sys.path.insert(0, str(ROOT/'Tools'))
from runtime_policy import require_space, atomic_json
from import_amd_runtime import wheel_check

ASSETS = (
    ('demucs', '4.1.0', 'demucs-4.1.0-py3-none-any.whl', 100567,
     '4916a804702033ce934a6cdfa7e38dde03f7a7a6e85f41d0120eefe9e2966758'),
    ('julius', '0.2.8', 'julius-0.2.8-py3-none-any.whl', 21819,
     '6891235cbc355e629d839f87489bff8ca46e57a0e7cc35abb909c7a2aa538c25'),
    ('lameenc', '1.8.4', 'lameenc-1.8.4-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl', 247546,
     '00d619c0a617f66feccbbd2fa9ed3857958ea503f9fe0038cb8b1d950b8b6452'),
    ('sphn', '0.2.1', 'sphn-0.2.1-cp312-cp312-manylinux_2_24_x86_64.whl', 18101967,
     '27527d82ae2db9fbd8b7cbd787160e5d8002d385c785d217bd1c6fed32c37b06'),
)


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    destination = ROOT/'Runtime/LinuxPackages/musicunderstanding'
    receipt = ROOT/'Maintenance/Imports/linux-musicunderstanding-lock.json'
    if destination.exists():
        lock = json.loads(receipt.read_text())
        for row in lock['files']:
            file = destination/row['path']
            if not file.resolve().is_relative_to(destination.resolve()) or file.stat().st_size != row['bytes'] or digest(file) != row['sha256']:
                raise RuntimeError('Installed music dependency verification failed')
        print(json.dumps({'verified':True, 'files':len(lock['files']), 'downloaded':False}))
        return
    require_space(ROOT, 512*1024**2)
    cache = ROOT/'Runtime/Downloads/linux-musicunderstanding'
    cache.mkdir(parents=True, exist_ok=True)
    assets = []; expanded = 0
    for name, version, filename, size, sha in ASSETS:
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=40) as response:
            metadata = json.load(response)
        artifact = next(row for row in metadata['urls'] if row['filename'] == filename)
        if artifact['size'] != size or artifact['digests']['sha256'] != sha or not artifact['url'].startswith('https://files.pythonhosted.org/'):
            raise RuntimeError('Publisher metadata differs from reviewed music dependency')
        path = cache/filename
        if not path.exists():
            part = path.with_suffix('.part')
            with urllib.request.urlopen(artifact['url'], timeout=60) as source, part.open('wb') as output:
                total = 0
                while block := source.read(1024**2):
                    total += len(block)
                    if total > size: raise RuntimeError('Download exceeds published byte size')
                    output.write(block)
                output.flush(); os.fsync(output.fileno())
            if part.stat().st_size != size or digest(part) != sha:
                raise RuntimeError('Music wheel size/hash mismatch')
            part.rename(path)
        if path.stat().st_size != size or digest(path) != sha:
            raise RuntimeError('Cached music wheel size/hash mismatch')
        expanded += wheel_check(path)
        assets.append({'name':name,'version':version,'wheel':path.relative_to(ROOT).as_posix(),
                       'bytes':size,'sha256':sha,'url':artifact['url']})
    require_space(ROOT, expanded*2)
    stage = destination.with_name(destination.name+'-stage-'+uuid.uuid4().hex)
    stage.mkdir()
    for asset in assets:
        with zipfile.ZipFile(ROOT/asset['wheel']) as archive:
            for entry in archive.infolist():
                path = PurePosixPath(entry.filename)
                if path.is_absolute() or '..' in path.parts or '\\' in entry.filename:
                    raise RuntimeError('Unsafe wheel path')
                if entry.is_dir(): continue
                if any(part.endswith('.data') for part in path.parts):
                    raise RuntimeError('Unexpected wheel relocation requires review')
                target = stage/path.as_posix()
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists(): raise RuntimeError('Dependency path collision')
                target.write_bytes(archive.read(entry))
    rows = [{'path':p.relative_to(stage).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}
            for p in sorted(stage.rglob('*')) if p.is_file()]
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage, destination)
    lock = {'verified':True,'platform':'Linux x86_64 CPython 3.12','assets':assets,'files':rows,
            'source':'PyPI exact versions, published size/SHA256 and wheel RECORD',
            'download_bytes':sum(row['bytes'] for row in assets), 'installed_bytes':sum(row['bytes'] for row in rows)}
    atomic_json(receipt, lock)
    print(json.dumps({key:lock[key] for key in ('verified','download_bytes','installed_bytes')}))


if __name__ == '__main__': main()
