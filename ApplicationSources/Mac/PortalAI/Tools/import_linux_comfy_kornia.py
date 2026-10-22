"""Add the portable-CPU Kornia wheel to ComfyUI's existing isolated Linux layer."""
import json
import os
from pathlib import Path
import sys
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from import_amd_runtime import digest,wheel_check
from runtime_policy import atomic_json,require_space


def main():
    # 0.1.11..0.1.14 require AVX2 globally. 0.1.15 imports on older CPUs but
    # its Linux wheel omits image APIs required by the installed Kornia 0.8.3.
    version='0.1.10'
    with urllib.request.urlopen(f'https://pypi.org/pypi/kornia-rs/{version}/json',timeout=30) as response:
        metadata=json.load(response)
    assert metadata['info']['version']==version
    artifact=next(row for row in metadata['urls'] if row['filename']==
        f'kornia_rs-{version}-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl')
    url=artifact['url'];size=artifact['size'];sha=artifact['digests']['sha256']
    if not url.startswith('https://files.pythonhosted.org/'):raise RuntimeError('Unexpected wheel origin')
    require_space(ROOT,size*6,for_outputs=True)
    cache=ROOT/'Cache/linux-comfyextras-wheelhouse';cache.mkdir(parents=True,exist_ok=True)
    wheel=cache/artifact['filename']
    if not wheel.exists():
        part=wheel.with_suffix('.part')
        with urllib.request.urlopen(url,timeout=45) as source,part.open('wb') as output:
            total=0
            while block:=source.read(1024**2):
                total+=len(block)
                if total>size:raise RuntimeError('Download exceeds published wheel size')
                output.write(block)
            output.flush();os.fsync(output.fileno())
        if part.stat().st_size!=size or digest(part)!=sha:raise RuntimeError('Wheel byte size or SHA256 differs')
        part.replace(wheel)
    if wheel.stat().st_size!=size or digest(wheel)!=sha:raise RuntimeError('Cached wheel integrity mismatch')
    expanded=wheel_check(wheel)
    destination=ROOT/'Runtime/LinuxPackages/comfyextras'
    receipt_path=ROOT/'Maintenance/Imports/linux-comfyextras-lock.json'
    receipt=json.loads(receipt_path.read_text())
    for row in receipt['files']:
        if digest(destination/row['path'])!=row['sha256']:raise RuntimeError('Existing ComfyUI layer differs')
    require_space(ROOT,expanded*2,for_outputs=True)
    added=[]
    with zipfile.ZipFile(wheel) as archive:
        for member in archive.infolist():
            if member.is_dir():continue
            relative=Path(member.filename)
            if relative.is_absolute() or '..' in relative.parts:raise RuntimeError('Unsafe wheel member')
            target=destination/relative
            if not target.resolve().is_relative_to(destination.resolve()):raise RuntimeError('Wheel target escapes layer')
            blob=archive.read(member)
            if target.exists() and target.read_bytes()!=blob:raise RuntimeError('Package collision: '+str(relative))
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(blob)
            added.append({'path':relative.as_posix(),'bytes':len(blob),'sha256':digest(target)})
    asset={'name':'kornia_rs','version':version,'url':url,'bytes':size,'sha256':sha,
           'wheel':wheel.relative_to(ROOT).as_posix(),
           'reason':'Last pre-AVX2-baseline release with legacy Kornia image APIs; https://github.com/kornia/kornia-rs/issues/918'}
    receipt['assets']=[a for a in receipt['assets'] if a['name']!='kornia_rs']+[asset]
    paths={r['path']:r for r in receipt['files']};paths.update({r['path']:r for r in added})
    receipt['files']=list(paths.values());receipt['expanded_bytes']=sum(r['bytes'] for r in receipt['files'])
    receipt['hash_provenance']='PyPI published byte size, SHA256 and wheel RECORD; Linux-specific ComfyUI compatibility pins'
    atomic_json(receipt_path,receipt)
    atomic_json(ROOT/'Maintenance/Imports/linux-comfyextras-pins.json',{'av':'18.1.0','kornia_rs':version})
    print(json.dumps(asset))


if __name__=='__main__':main()
