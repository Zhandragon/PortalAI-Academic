"""Verified Python 3.12 inference extras; never copy MMAudio's Python 3.11 ABI."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request

from import_amd_runtime import ROOT, digest, wheel_check
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space, atomic_json, portable_env

PINS = {'colorlog':'6.12.0','open_clip_torch':'3.3.0','torchdiffeq':'0.2.5',
        'timm':'1.0.29','ftfy':'6.3.1','numpy':'2.0.2'}


def main(prefix='amd-audio', pins=PINS, relative_dest='Runtime/AMDAudio/packages', exact=True):
    dest=ROOT/relative_dest
    if dest.exists(): raise RuntimeError('AMD audio destination exists; verify instead of replacing')
    report=json.loads((ROOT/f'Maintenance/Imports/{prefix}-resolution.json').read_text(encoding='utf-8'))
    wheelhouse=ROOT/f'Cache/{prefix}-wheelhouse';wheelhouse.mkdir(parents=True,exist_ok=True)
    assets=[]
    found={r['metadata']['name'].replace('-','_'):r['metadata']['version'] for r in report['install']}
    if (exact and found!=pins) or any(found.get(k)!=v for k,v in pins.items()):
        raise RuntimeError('Dependency resolution differs from reviewed pins')
    for row in report['install']:
        name=row['metadata']['name'];version=row['metadata']['version'];info=row['download_info']
        url=info['url'];parsed=urllib.parse.urlparse(url);filename=urllib.parse.unquote(Path(parsed.path).name)
        if parsed.scheme!='https' or parsed.hostname!='files.pythonhosted.org' or not filename.endswith('.whl'):
            raise ValueError('Unexpected audio dependency URL')
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json',timeout=45) as response:metadata=json.load(response)
        artifact=next(a for a in metadata['urls'] if a['filename']==filename)
        size=artifact['size'];sha=artifact['digests']['sha256']
        if info['archive_info']['hashes']['sha256']!=sha:raise RuntimeError('Resolution disagrees with publisher hash')
        require_space(ROOT,size*4)
        target=wheelhouse/filename
        if not target.exists():
            part=target.with_suffix('.part')
            with urllib.request.urlopen(url,timeout=45) as src,part.open('wb') as out:
                total=0
                for block in iter(lambda:src.read(1024**2),b''):
                    total+=len(block)
                    if total>size:raise RuntimeError('Artifact exceeded declared size')
                    out.write(block)
            if part.stat().st_size!=size or digest(part)!=sha:raise RuntimeError('Downloaded artifact hash/size mismatch')
            part.rename(target)
        if target.stat().st_size!=size or digest(target)!=sha:raise RuntimeError('Cached artifact hash/size mismatch')
        wheel_check(target)
        assets.append({'name':name,'version':version,'bytes':size,'sha256':sha,'wheel':target.relative_to(ROOT).as_posix()})
    locked=wheelhouse/'locked.txt'
    locked.write_text('\n'.join((ROOT/a['wheel']).as_uri()+' --hash=sha256:'+a['sha256'] for a in assets),encoding='utf-8')
    stage=dest.with_name('packages-stage')
    if stage.exists():raise RuntimeError('Review previous stage before retrying')
    subprocess.run([sys.executable,'-B','-m','pip','install','--no-index','--no-deps','--require-hashes',
                    '--no-compile','--target',str(stage),'-r',str(locked)],cwd=ROOT,env=portable_env(ROOT),check=True)
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage,dest)
    atomic_json(ROOT/f'Maintenance/Imports/{prefix}-lock.json',{'status':'installed-dependencies-only',
        'assets':assets,'python':'3.12','hash_provenance':'PyPI publisher SHA256, byte sizes and wheel RECORD'})


if __name__=='__main__':main()
