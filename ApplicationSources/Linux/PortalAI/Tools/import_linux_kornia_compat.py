"""Provision the verified CPU-portable Kornia wheel without changing PyAV/Torch."""
import json
import os
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from import_amd_runtime import digest,wheel_check
from runtime_policy import atomic_json,require_space

VERSION='0.1.10'
SIZE=3042197
SHA256='f332a2a034cc791006f25c2d85e342a060887145e9236e8e43562badcadededf'
NAME=f'kornia_rs-{VERSION}-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'


def main():
    wheel=ROOT/'Cache/linux-comfyextras-wheelhouse'/NAME
    if not wheel.is_file() or wheel.stat().st_size!=SIZE or digest(wheel)!=SHA256:
        raise RuntimeError('Verified Kornia wheel missing; run import_linux_comfy_kornia.py to obtain it')
    source=json.loads((ROOT/'Maintenance/Imports/linux-comfyextras-lock.json').read_text())
    asset=next(a for a in source['assets'] if a['name']=='kornia_rs')
    if asset['version']!=VERSION or asset['bytes']!=SIZE or asset['sha256']!=SHA256:
        raise RuntimeError('Kornia publisher receipt differs from pinned compatibility wheel')
    expanded=wheel_check(wheel)
    require_space(ROOT,expanded*2,for_outputs=True)
    target=ROOT/'Runtime/LinuxPackages/kornia_compat'
    if target.exists():raise RuntimeError('Kornia compatibility layer already exists; verify instead of replacing')
    stage=target.with_name('kornia_compat-stage')
    stage.mkdir(exist_ok=False)
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            if member.is_dir():continue
            relative=Path(member.filename)
            if relative.parts[0] not in {'kornia_rs',f'kornia_rs-{VERSION}.dist-info'}:
                raise RuntimeError('Unexpected package in Kornia-only wheel')
            path=stage/relative
            if not path.resolve().is_relative_to(stage.resolve()):raise RuntimeError('Unsafe wheel member')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(member))
    files=[{'path':p.relative_to(stage).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)}
        for p in sorted(stage.rglob('*')) if p.is_file()]
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage,target)
    receipt={'python':'3.12','platform':'Linux x86_64','verified':True,'assets':[asset],
        'files':files,'expanded_bytes':sum(r['bytes'] for r in files),
        'hash_provenance':'Existing published wheel byte size/SHA256 and wheel RECORD reverified',
        'scope':'Only kornia_rs; base media, PyAV, Torch and Windows packages are unchanged'}
    atomic_json(ROOT/'Maintenance/Imports/linux-kornia_compat-lock.json',receipt)
    atomic_json(ROOT/'Maintenance/Imports/linux-kornia_compat-pins.json',{'kornia_rs':VERSION})
    print(json.dumps({'files':len(files),'expanded_bytes':receipt['expanded_bytes'],'sha256':SHA256}))


if __name__=='__main__':main()
