"""Rebuild native image engines from pinned archives, retaining inaccessible originals."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Tools')]
from import_foundation_assets import download, sha256
from import_image_backend import ASSETS
from import_linux_sdcpp import PINS, REV
from portable_permissions import grant_runtime_read_execute
from profile_paths import _contained
from runtime_policy import require_space, portable_path


def repair(root=ROOT):
    root = Path(root).resolve()
    base = _contained(root, root/'Runtime/StableDiffusion')
    stage = _contained(root, root/'Runtime/StableDiffusion-stage')
    if stage.exists(): raise FileExistsError('Retained image stage requires review')
    # An image process cannot be replaced during its work. Do not stop any process.
    from profile_shutdown import _snapshot
    for row in _snapshot().values():
        exe = str(row.get('executable') or '')
        if exe and Path(exe).is_relative_to(base):
            raise RuntimeError('Close the active native image worker before repair')
    require_space(root, 1024**3)
    stamp = time.strftime('%Y%m%d_%H%M%S')
    recovery = _contained(root, root/'Maintenance/Patches'/('ImageRuntime_'+stamp))
    recovery.mkdir(parents=True)
    stage.mkdir()
    rows = []
    for platform in ('windows', 'linux'):
        for backend in ('cpu', 'vulkan'):
            name = platform+'-'+backend
            receipt_path = root/('Maintenance/Imports/sdcpp-'+name+'.json')
            receipt_bytes = receipt_path.read_bytes()
            receipt = json.loads(receipt_bytes)
            if receipt.get('revision') != REV or not receipt.get('verified'):
                raise ValueError('Image receipt does not match the pinned revision')
            (recovery/receipt_path.name).write_bytes(receipt_bytes)
            if platform == 'windows':
                asset = next(a for a in ASSETS if a['id'] == 'sdcpp-'+name)
                cached = root/'Maintenance/Patches/SDRuntime_archives_20261011'/(asset['id']+'.zip')
            else:
                size, sha = PINS[backend]
                filename = 'sd-master-f89d9b1-bin-Linux-Ubuntu-24.04-x86_64'+('-vulkan' if backend=='vulkan' else '')+'.zip'
                asset = {'id':'sdcpp-'+name,'size':size,'sha256':sha,
                         'url':'https://github.com/leejet/stable-diffusion.cpp/releases/download/master-951-f89d9b1/'+filename}
                cached = root/'Cache/LinuxSDcpp'/filename
            archive = recovery/(asset['id']+'.zip')
            if cached.is_file(): shutil.copyfile(cached, archive)
            else: download(asset, archive, root)
            if archive.stat().st_size != asset['size'] or sha256(archive) != asset['sha256']:
                raise ValueError('Image archive failed pinned size/checksum verification')
            payload = stage/(name+'-stage'); payload.mkdir()
            with zipfile.ZipFile(archive) as package:
                for member in package.infolist():
                    target = portable_path(payload, member.filename)
                    if (member.external_attr >> 16) & 0o170000 == 0o120000:
                        raise ValueError('Linked image archive member')
                    if member.is_dir(): continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.open(member) as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
            if platform == 'linux':
                (payload/'sd-cli').rename(payload/'sd-cli.bin')
                # Preserve only the pinned, previously verified portable wrapper.
                wrapper = base/name/'sd-cli'
                expected = next(r['sha256'] for r in receipt['installed_files'] if r['path']=='sd-cli')
                if sha256(wrapper) != expected: raise ValueError('Linux image wrapper checksum mismatch')
                shutil.copyfile(wrapper, payload/'sd-cli')
            expected = {r['path']:r['sha256'] for r in receipt['installed_files']}
            actual = {p.relative_to(payload).as_posix():sha256(p) for p in payload.rglob('*') if p.is_file()}
            if actual != expected: raise ValueError('Rebuilt image files differ from historical receipt')
            permissions = grant_runtime_read_execute(root, payload)
            payload.rename(stage/name)
            rows.append({'backend':name,'files':len(actual),'archive_sha256':asset['sha256'],'permissions':permissions})
    preserved = _contained(root, base.with_name('StableDiffusion-inaccessible-'+stamp))
    for candidate in (base, stage, preserved):
        if candidate.parent.resolve() != (root/'Runtime').resolve(): raise ValueError('Image repair escaped runtime parent')
        _contained(root, candidate)
    if preserved.exists(): raise FileExistsError('Image recovery already exists')
    for row in _snapshot().values():
        exe = str(row.get('executable') or '')
        if exe and Path(exe).is_relative_to(base):
            raise RuntimeError('A native image worker started during repair; verified stage retained')
    base.rename(preserved)
    try: stage.rename(base)
    except BaseException:
        if not base.exists(): preserved.rename(base)
        raise
    result = {'repaired':True,'backends':rows,'preserved':preserved.relative_to(root).as_posix(),
              'preserved_originals_hash_verified':False,'private_profiles_changed':False}
    (recovery/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair',action='store_true')
    args=parser.parse_args()
    if args.repair: print(json.dumps(repair(),indent=2))
    else: parser.print_help()
