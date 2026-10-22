"""Offline repair of the public Windows account runtime; no credential changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Tools')]

# Clean recipients keep pinned public repair assets with the account runtime.
# Retain the exact legacy location for already installed, verified receipts.
WHEELHOUSE_DIRS = frozenset((
    'Runtime/AccountPython/wheelhouse',
    'Cache/account-runtime-wheelhouse',
))


def digest(path):
    with path.open('rb') as handle: return hashlib.file_digest(handle, 'sha256').hexdigest()


def verified_assets(root):
    from profile_paths import _contained
    from import_amd_runtime import wheel_check
    receipt = _contained(root, root/'Maintenance/Imports/account-runtime-lock.json')
    data = json.loads(receipt.read_text(encoding='utf-8'))
    rows = data.get('assets')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('Invalid account runtime package receipt')
    seen = set()
    for row in rows:
        relative = Path(row['wheel'])
        if (relative.parent.as_posix() not in WHEELHOUSE_DIRS or
                relative.suffix != '.whl' or relative.name.casefold() in seen or
                not re.fullmatch('[a-f0-9]{64}', row.get('sha256', '')) or
                type(row.get('bytes')) is not int or not 0 < row['bytes'] <= 128*1024**2):
            raise ValueError('Account runtime receipt names an unreviewed package')
        seen.add(relative.name.casefold())
        wheel = _contained(root, root/relative)
        if wheel.stat().st_nlink != 1 or wheel.stat().st_size != row['bytes'] or digest(wheel) != row['sha256']:
            raise ValueError('Account package does not match its verified receipt')
        wheel_check(wheel)
    if not {'cryptography', 'eth-account'} <= {row['name'].replace('_', '-') for row in rows}:
        raise ValueError('Account runtime receipt is incomplete')
    return rows


def repair(root=ROOT):
    if os.name != 'nt': raise RuntimeError('This repair is for the Windows account runtime')
    root = Path(root).resolve()
    from profile_paths import _contained
    from profile_shutdown import _snapshot, _select
    from mission_runner import process_lock
    from portable_permissions import grant_runtime_read_execute
    from portable_pip_paths import pip_path
    from runtime_policy import require_space
    base = _contained(root, root/'Runtime/AccountPython')
    directory = _contained(root, base/'packages')
    stage = _contained(root, base/'packages-stage')
    with process_lock(_contained(root, base/'repair.lock')):
        if _select(root, _snapshot()):
            raise RuntimeError('Close PortalAI and its owned background components before runtime repair')
        if stage.exists(): raise RuntimeError('A prior packages-stage directory requires review; it was not removed')
        # The profile lock also covers a controller that started between inventory checks.
        profile_lock = _contained(root, root/'Private/profile-runtime.lock')
        if not profile_lock.is_file():
            raise RuntimeError('This repair requires an existing account installation')
        with process_lock(profile_lock):
            assets = verified_assets(root)
            require_space(root, sum(row['bytes'] for row in assets)*12)
            stamp = time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
            recovery = _contained(root, root/'Maintenance/Patches'/('AccountRuntime_'+stamp))
            recovery.mkdir(parents=True)
            wheels = recovery/'wheels'; wheels.mkdir()
            for row in assets:
                target = wheels/Path(row['wheel']).name
                shutil.copyfile(root/row['wheel'], target)
                if target.stat().st_size != row['bytes'] or digest(target) != row['sha256']:
                    raise RuntimeError('Recovery package copy failed verification')
            (recovery/'original-receipt.json').write_text(json.dumps({'assets': assets}, indent=2), encoding='utf-8')
            locked = recovery/'requirements.txt'
            locked.write_text('\n'.join((wheels/Path(row['wheel']).name).as_uri()+' --hash=sha256:'+row['sha256'] for row in assets), encoding='utf-8')
            python = _contained(root, root/'Runtime/BootstrapPython/python.exe')
            env = dict(os.environ)
            for name in list(env):
                if (name in ('PORTALAI_ACCOUNT_UNLOCK', 'PORTALAI_PROFILE_ID', 'PORTALAI_PROFILE_EPOCH',
                             'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', '__PYVENV_LAUNCHER__') or
                        name.startswith('PORTALAI_HYDRATION_')):
                    env.pop(name, None)
            env.update(PIP_NO_CACHE_DIR='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
                       TEMP=pip_path(recovery), TMP=pip_path(recovery), PYTHONDONTWRITEBYTECODE='1')
            options = dict(cwd=root, env=env, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            subprocess.run([str(python), '-I', '-B', str(root/'Tools/portable_pip_runner.py'), 'install', '--no-index', '--no-deps',
                            '--require-hashes', '--no-compile', '--target', pip_path(stage), '-r', pip_path(locked)], **options)
            permissions = grant_runtime_read_execute(root, stage)
            probe = ("import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);import cryptography,eth_account;"
                     "assert Path(cryptography.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve());"
                     "from cryptography.hazmat.primitives.ciphers.aead import AESGCM;"
                     "from cryptography.hazmat.primitives.kdf.scrypt import Scrypt;"
                     "key=Scrypt(salt=b'PortalAI-runtime!',length=32,n=131072,r=8,p=1).derive(b'public self-test');"
                     "a=AESGCM(key);n=b'PortalAItest!';assert a.decrypt(n,a.encrypt(n,b'ok',None),None)==b'ok'")
            # Native package loaders (including PyCryptodome) may reject the
            # extended spelling as an import root. Only pip needs that spelling.
            subprocess.run([str(python), '-I', '-B', '-c', probe, str(stage)], **options)
            preserved = _contained(root, base/('packages-preserved-'+stamp))
            if preserved.exists(): raise FileExistsError('Runtime recovery destination already exists')
            for candidate in (stage, directory, preserved):
                if candidate.parent.resolve() != base.resolve(): raise ValueError('Runtime rename escaped its parent')
                _contained(root, candidate)
            existed = directory.exists()
            if existed: directory.rename(preserved)
            try: stage.rename(directory)
            except BaseException:
                if existed and not directory.exists(): preserved.rename(directory)
                raise
            report = {'repaired': True, 'packages': len(assets), 'permissions': permissions,
                      'preserved_runtime': preserved.relative_to(root).as_posix() if existed else None,
                      'private_profiles_changed': False, 'passwords_changed': False,
                      'preserved_runtime_checksum_verified': False}
            (recovery/'result.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair', action='store_true', help='Rebuild only public account packages from verified local wheels')
    args = parser.parse_args()
    if args.repair: print(json.dumps(repair(), indent=2))
    else:
        from account_runtime import preflight
        print(json.dumps(preflight(), indent=2))
