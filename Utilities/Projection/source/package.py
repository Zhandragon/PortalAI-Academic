"""Build clean public Projection packages from an owned companion and HA setup.

No runtime state, Connections, accounts, logs or historical receiver is copied.
Archive inputs are allowlisted; the existing source installations are read-only.
Requires Python 3.11+ on a Windows packaging host. See ../README.md.
"""
from pathlib import Path, PurePosixPath
import argparse
import gzip
import hashlib
import json
import shutil
import tarfile
import zipfile

VERSION = '20261020-r1'
PART_BYTES = 24_000_000
FORBIDDEN = {'Connections', 'state', 'Private', '.storage', '__pycache__'}


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def safe_path(root, name):
    rel = PurePosixPath(name.replace('\\', '/'))
    if rel.is_absolute() or '..' in rel.parts or any(p in FORBIDDEN for p in rel.parts):
        raise ValueError('Disallowed distribution path: ' + name)
    path = root.joinpath(*rel.parts)
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError('Source escaped its root: ' + name)
    return path


def copy_file(source, destination):
    if not source.is_file() or source.is_symlink():
        raise ValueError('Expected regular source file: ' + str(source))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha(source) != sha(destination):
        raise ValueError('Copy integrity mismatch')


def build(args):
    root = Path(__file__).resolve().parent.parent
    code = root / 'source'
    base = args.projection_source.resolve()
    ha_setup = args.ha_setup_source.resolve()
    ha = ha_setup / 'Setup Files/HomeAssistant'
    work = args.work.resolve()
    # A fresh staging folder prevents old state or stale files entering an archive.
    work.mkdir(parents=True, exist_ok=False)
    manifest = json.loads((ha / 'SHA256SUMS.json').read_bytes())
    for name, digest in manifest.items():
        if sha(safe_path(ha, name)) != digest:
            raise ValueError('HA manifest mismatch: ' + name)
    ha_zip_name = 'PortalAI-HomeAssistant-0.5.11-recovery-0.1.0.zip'
    ha_zip = ha_setup / 'Setup Files' / ha_zip_name
    expected = Path(str(ha_zip) + '.sha256').read_text().split()[0]
    if sha(ha_zip) != expected:
        raise ValueError('HA archive checksum mismatch')
    with zipfile.ZipFile(ha_zip) as z:
        expected_names = {'HomeAssistant/' + n for n in [*manifest, 'SHA256SUMS.json']}
        if set(z.namelist()) != expected_names or z.testzip() is not None:
            raise ValueError('Unexpected HA archive contents')
        for name, digest in manifest.items():
            if hashlib.sha256(z.read('HomeAssistant/' + name)).hexdigest() != digest:
                raise ValueError('HA archive differs from manifest')
    copy_file(ha_zip, root / ha_zip_name)
    (root / (ha_zip_name + '.sha256')).write_text(expected + '  ' + ha_zip_name + '\n', encoding='utf-8')

    app_names = sorted(p.name for p in (base / 'app').glob('*.py'))
    for name in app_names:
        copy_file(base / 'app' / name, code / 'app' / name)
    # Explicit supplemental dependency: added after the original Windows receipt.
    pycparser = [p.relative_to(base).as_posix() for folder in ('Runtime/packages/pycparser', 'Runtime/packages/pycparser-3.11.dist-info')
                 for p in (base / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    ws = json.loads((base / 'Runtime/NativeState/receipt.json').read_bytes())
    wheel = base / 'Runtime/NativeState' / ws['file']
    if sha(wheel) != ws['sha256']:
        raise ValueError('Native state dependency checksum mismatch')

    metadata = {'version': VERSION, 'source_base_url': 'https://raw.githubusercontent.com/Zhandragon/PortalAI-Academic/main/Utilities/Projection',
                'scope': 'Clean Windows/Linux companion plus HA 0.5.11 + Recovery 0.1.0; no macOS Projection support.',
                'packages': {}}
    provenance = {'ha_archive_sha256': expected, 'runtime_receipts': {}, 'receipt_metadata_changes': [],
                  'exclusions': 'No Connections, state, profiles, logs, captures, Tests/Validation, old receiver, PDBs or build caches.'}
    for platform in ('Windows', 'Linux'):
        stage = work / platform / 'utilities'
        companion = stage / 'PortalAI-Projection'
        receipt_name = 'receipt.json' if platform == 'Windows' else 'linux-receipt.json'
        receipt = base / 'Runtime' / receipt_name
        provenance['runtime_receipts'][platform] = sha(receipt)
        runtime_names = []
        for row in json.loads(receipt.read_bytes())['files']:
            name = row['path'].replace('\\', '/')
            source = safe_path(base, name)
            actual = sha(source)
            if actual != row['sha256']:
                # These distribution RECORD inventories changed after the upstream
                # snapshot; their installed payloads still match that snapshot.
                permitted = {'Runtime/packages/cryptography-50.0.2.dist-info/RECORD',
                             'Runtime/packages/cffi-2.1.1.dist-info/RECORD'}
                if name not in permitted:
                    raise ValueError('Runtime receipt mismatch: ' + name)
                provenance['receipt_metadata_changes'].append({'path': name, 'original_sha256': row['sha256'], 'published_sha256': actual})
            runtime_names.append(name)
        runtime_names += ['Runtime/cacert.pem', 'Runtime/NativeState/receipt.json', 'Runtime/NativeState/' + ws['file']]
        if platform == 'Windows':
            runtime_names += pycparser
        else:
            runtime_names += ['Runtime/LinuxPython/run-python', 'Runtime/LinuxFonts/fonts.conf']
        rows = []
        for name in sorted(set(runtime_names)):
            source = safe_path(base, name)
            copy_file(source, companion / name)
            rows.append({'path': name, 'bytes': source.stat().st_size, 'sha256': sha(source)})
        (companion / 'Runtime/distribution-receipt.json').write_text(json.dumps({'platform': platform, 'files': rows}, indent=2) + '\n', encoding='utf-8')
        for name in app_names:
            copy_file(code / 'app' / name, companion / 'app' / name)
        launcher = 'Start Projection.cmd' if platform == 'Windows' else 'Start Projection.sh'
        copy_file(base / launcher, companion / launcher)
        if platform == 'Windows':
            # A clean distribution has no Connections/state directories yet.
            body = (companion / launcher).read_text()
            anchor = 'cd /d "%~dp0"\n'
            if body.count(anchor) != 1:
                raise ValueError('Unexpected Windows launcher')
            init = ''.join('if not exist "%~dp0' + name + '\\" (mkdir "%~dp0' + name + '" || exit /b 1)\n'
                           for name in ('Connections', 'state', 'state\\input', 'state\\tmp', 'state\\cache'))
            (companion / launcher).write_text(body.replace(anchor, anchor + init), encoding='utf-8')
        copy_file(companion / launcher, code / launcher)
        if platform == 'Windows':
            copy_file(base / 'Start HA Recovery.cmd', companion / 'Start HA Recovery.cmd')
            copy_file(base / 'Start HA Recovery.cmd', code / 'Start HA Recovery.cmd')
        copy_file(code / 'README-bundle.txt', companion / 'README.txt')
        setup = stage / 'PortalAI HA Setup'
        for name in [*manifest, 'SHA256SUMS.json']:
            copy_file(safe_path(ha, name), setup / 'Setup Files/HomeAssistant' / name)
        if platform == 'Windows':
            for name in ('Install PortalAI HA.cmd', 'Setup Files/Setup-PortalAI-HA.ps1'):
                copy_file(ha_setup / name, setup / name)
        else:
            copy_file(code / 'Install PortalAI HA.sh', setup / 'Install PortalAI HA.sh')
        copy_file(code / 'README-bundle.txt', setup / 'README.txt')
        files = []
        for p in sorted(stage.rglob('*')):
            if p.is_file():
                name = p.relative_to(stage).as_posix()
                safe_path(stage, name)
                files.append({'name': name, 'bytes': p.stat().st_size, 'sha256': sha(p)})
        archive_name = 'PortalAI-Projection-' + platform + '.zip' if platform == 'Windows' else 'PortalAI-Projection-Linux.tar.gz'
        archive = work / platform / archive_name
        if platform == 'Windows':
            with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
                for row in files:
                    info = zipfile.ZipInfo(row['name'], (2026, 10, 20, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    z.writestr(info, (stage / row['name']).read_bytes())
        else:
            with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=0, compresslevel=9) as gz, tarfile.open(fileobj=gz, mode='w') as tar:
                for row in files:
                    source = stage / row['name']
                    info = tar.gettarinfo(str(source), arcname='utilities/' + row['name'])
                    with source.open('rb') as stream:
                        magic = stream.read(4)
                        stream.seek(0)
                        info.mode = 0o755 if source.suffix == '.sh' or source.name == 'run-python' or magic == b'\x7fELF' else 0o644
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ''
                        tar.addfile(info, stream)
        relative = 'packages/' + VERSION + '/' + platform
        destination = root / relative
        destination.mkdir(parents=True, exist_ok=False)
        parts = []
        with archive.open('rb') as stream:
            while data := stream.read(PART_BYTES):
                name = archive_name + '.part%03d' % (len(parts) + 1)
                (destination / name).write_bytes(data)
                parts.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        metadata['packages'][platform] = {'path': relative, 'archive': archive_name, 'sha256': sha(archive),
                                          'bytes': archive.stat().st_size, 'top_folder': 'utilities', 'parts': parts, 'files': files}
        print(json.dumps({'platform': platform, 'archive_bytes': archive.stat().st_size, 'files': len(files), 'parts': len(parts)}), flush=True)
    (root / 'PACKAGING.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    (code / 'PROVENANCE.json').write_text(json.dumps(provenance, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--projection-source', type=Path, required=True)
    parser.add_argument('--ha-setup-source', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True, help='New staging directory; must not exist')
    build(parser.parse_args())
