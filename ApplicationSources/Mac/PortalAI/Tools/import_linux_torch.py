"""Pinned official PyTorch Linux layers; CPU, CUDA and ROCm stay separate."""
import argparse
import email
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import uuid
import zipfile

from import_amd_runtime import ROOT,digest,wheel_check
from import_linux_packages import PLATFORM
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space,portable_env,atomic_json

PINS={'torch':'2.11.0','torchvision':'0.26.0','torchaudio':'2.11.0'}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('backend',choices=['cpu','cu128','rocm7.2']);args=parser.parse_args()
    backend=args.backend;dest=ROOT/f'Runtime/LinuxTorch/{backend}'
    if dest.exists():raise RuntimeError('Existing Torch layer must be verified, not overwritten')
    cache=ROOT/f'Cache/linux-torch-{backend}';cache.mkdir(parents=True,exist_ok=True)
    require_space(ROOT,35*1024**3)
    assets=[];requirements=[]
    for name,version in PINS.items():
        index=urllib.request.urlopen(f'https://download.pytorch.org/whl/{backend}/{name}/',timeout=60).read().decode()
        urls=[html.unescape(u) for u in re.findall('href="([^"]+)"',index) if name+'-'+version+'%2B'+backend in u
              and 'cp312-cp312-manylinux_2_28_x86_64.whl#sha256=' in u]
        if len(urls)!=1:raise RuntimeError('Expected one reviewed Linux wheel: '+name)
        url,sha=urls[0].split('#sha256=');filename=urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name)
        url=url.replace('https://download-r2.pytorch.org/','https://download.pytorch.org/')
        size=int(urllib.request.urlopen(urllib.request.Request(url,method='HEAD'),timeout=60).headers['Content-Length'])
        path=cache/filename
        if not path.exists():
            part=path.with_suffix('.part');count=0
            with urllib.request.urlopen(url,timeout=60) as src,part.open('wb') as out:
                for block in iter(lambda:src.read(4*1024**2),b''):
                    count+=len(block)
                    if count>size:raise RuntimeError('Torch download exceeded expected size')
                    out.write(block)
            if count!=size or digest(part)!=sha:raise RuntimeError('Official Torch size/hash verification failed')
            part.rename(path)
        if path.stat().st_size!=size or digest(path)!=sha:raise RuntimeError('Cached Torch checksum mismatch')
        expanded=wheel_check(path);require_space(ROOT,expanded)
        assets.append({'name':name,'version':version+'+'+backend,'url':url,'bytes':size,'sha256':sha,'wheel':path.relative_to(ROOT).as_posix()})
        with zipfile.ZipFile(path) as z:
            meta=email.message_from_bytes(z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))))
        from pip._vendor.packaging.requirements import Requirement
        from pip._vendor.packaging.markers import default_environment
        environment={**default_environment(),'sys_platform':'linux','platform_system':'Linux','platform_machine':'x86_64'}
        for line in meta.get_all('Requires-Dist',[]):
            requirement=Requirement(line)
            if requirement.marker and not requirement.marker.evaluate(environment):continue
            if requirement.name.lower().startswith(('nvidia','triton','pytorch-triton','cuda')):
                requirements.append(requirement.name+('['+','.join(sorted(requirement.extras))+']' if requirement.extras else '')+str(requirement.specifier))
        print(json.dumps({'verified':name,'backend':backend,'bytes':size}),flush=True)
    if backend=='rocm7.2':
        # Upstream triton-rocm 3.6 wheel fails its own RECORD on libproton.so.
        # The official cross-vendor Triton 3.6 wheel supports AMD; compilation
        # remains disabled in the portable workflows until physical validation.
        requirements=['triton==3.6.0' if r.startswith('triton-rocm') else r for r in requirements]
    if requirements:
        report=ROOT/f'Maintenance/Imports/linux-torch-{backend}-deps-resolution.json'
        subprocess.run([sys.executable,'-B','-m','pip','install','--dry-run','--ignore-installed','--only-binary=:all:',
                        *PLATFORM,'--index-url',f'https://download.pytorch.org/whl/{backend}',
                        '--extra-index-url','https://pypi.org/simple','--report',str(report),*sorted(set(requirements))],
                        env=portable_env(ROOT),check=True)
        for row in json.loads(report.read_text())['install']:
            info=row['download_info'];url=info['url'];sha=info['archive_info'].get('hashes',{}).get('sha256')
            url=url.replace('https://download-r2.pytorch.org/','https://download.pytorch.org/')
            filename=urllib.parse.unquote(Path(urllib.parse.urlsplit(url).path).name);path=cache/filename
            if urllib.parse.urlsplit(url).hostname not in ('download.pytorch.org','download-r2.pytorch.org','files.pythonhosted.org'):
                raise RuntimeError('Unexpected GPU dependency source')
            size=int(urllib.request.urlopen(urllib.request.Request(url,method='HEAD'),timeout=60).headers['Content-Length'])
            require_space(ROOT,size*4)
            if not path.exists():
                part=path.with_suffix('.part');count=0
                with urllib.request.urlopen(url,timeout=60) as src,part.open('wb') as out:
                    for block in iter(lambda:src.read(4*1024**2),b''):
                        count+=len(block)
                        if count>size:raise RuntimeError('GPU dependency exceeded published bytes')
                        out.write(block)
                if count!=size or (sha and digest(part)!=sha):raise RuntimeError('GPU dependency checksum failure')
                if not sha:wheel_check(part)  # Official index omits archive digest; verify every hashed member.
                part.rename(path)
            if not sha:sha=digest(path)
            if path.stat().st_size!=size or digest(path)!=sha:raise RuntimeError('Cached GPU dependency checksum failure')
            wheel_check(path)
            assets.append({'name':row['metadata']['name'],'version':row['metadata']['version'],'url':url,'bytes':size,
                           'sha256':sha,'wheel':path.relative_to(ROOT).as_posix()})
    locked=cache/'locked.txt'
    locked.write_text('\n'.join((ROOT/a['wheel']).as_uri()+' --hash=sha256:'+a['sha256'] for a in assets))
    stage=dest.with_name(backend+'-stage-'+uuid.uuid4().hex[:8])
    subprocess.run([sys.executable,'-B','-m','pip','install','--no-index','--no-deps','--no-compile','--only-binary=:all:',
                    *PLATFORM,'--require-hashes','--target',str(stage),'-r',str(locked)],env=portable_env(ROOT),check=True)
    files=[{'path':p.relative_to(stage).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size} for p in sorted(stage.rglob('*')) if p.is_file()]
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage,dest)
    atomic_json(ROOT/f'Maintenance/Imports/linux-torch-{backend}.json',{'verified':True,'python':'3.12','backend':backend,
        'assets':assets,'files':files,'destination':dest.relative_to(ROOT).as_posix(),'physical_gpu_validated':False,'triton_policy':'Official cross-vendor 3.6; JIT disabled; original ROCm wheel RECORD failure retained for review' if backend=='rocm7.2' else 'upstream'})
    print(json.dumps({'installed':backend,'files':len(files)}))

if __name__=='__main__':main()
