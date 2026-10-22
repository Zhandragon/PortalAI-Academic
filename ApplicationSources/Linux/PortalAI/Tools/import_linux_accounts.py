"""Verified Linux account dependencies, matching the pinned Windows versions."""
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
from runtime_policy import atomic_json, portable_env, require_space

PLATFORM=['--platform','manylinux_2_28_x86_64','--platform','manylinux_2_17_x86_64',
          '--platform','manylinux2014_x86_64','--python-version','3.12','--implementation','cp','--abi','cp312']


def main():
    dest=ROOT/'Runtime/AccountPython/linux-packages'
    if dest.exists():raise RuntimeError('Linux account layer already exists; verify instead of replacing')
    windows=json.loads((ROOT/'Maintenance/Imports/account-runtime-lock.json').read_text())
    pins={a['name'].lower().replace('-','_'):a['version'] for a in windows['assets']}
    report_path=ROOT/'Maintenance/Imports/linux-accounts-resolution.json'
    subprocess.run([sys.executable,'-B','-m','pip','install','--dry-run','--ignore-installed',
        '--only-binary=:all:','--no-deps',*PLATFORM,'--report',str(report_path),
        *(name+'=='+version for name,version in pins.items())],env=portable_env(ROOT),check=True)
    report=json.loads(report_path.read_text(encoding='utf-8'))
    found={r['metadata']['name'].lower().replace('-','_'):r['metadata']['version'] for r in report['install']}
    if found!=pins:raise RuntimeError('Linux dependency resolution differs from reviewed account versions')
    wheelhouse=ROOT/'Cache/linux-accounts-wheelhouse';wheelhouse.mkdir(parents=True,exist_ok=True)
    assets=[];expanded=0
    for row in report['install']:
        name=row['metadata']['name'];version=row['metadata']['version'];info=row['download_info']
        url=info['url'];parsed=urllib.parse.urlsplit(url);filename=urllib.parse.unquote(Path(parsed.path).name)
        if parsed.scheme!='https' or parsed.hostname!='files.pythonhosted.org' or not filename.endswith('.whl'):
            raise ValueError('Unrecognized account wheel source')
        with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/{version}/json',timeout=45) as src:meta=json.load(src)
        artifact=next(a for a in meta['urls'] if a['filename']==filename)
        size=artifact['size'];sha=artifact['digests']['sha256']
        if info['archive_info']['hashes']['sha256']!=sha:raise RuntimeError('Publisher hash differs from resolution')
        require_space(ROOT,size*4)
        target=wheelhouse/filename
        if not target.exists():
            part=target.with_suffix('.part')
            with urllib.request.urlopen(url,timeout=45) as src,part.open('wb') as out:
                total=0
                for block in iter(lambda:src.read(1024**2),b''):
                    total+=len(block)
                    if total>size:raise RuntimeError('Wheel exceeded published byte size')
                    out.write(block)
                out.flush();os.fsync(out.fileno())
            if part.stat().st_size!=size or digest(part)!=sha:raise RuntimeError('Account wheel checksum mismatch')
            part.rename(target)
        if target.stat().st_size!=size or digest(target)!=sha:raise RuntimeError('Cached wheel differs')
        expanded+=wheel_check(target)
        assets.append({'name':name,'version':version,'url':url,'bytes':size,'sha256':sha,'wheel':target.relative_to(ROOT).as_posix()})
    require_space(ROOT,expanded*2)
    locked=wheelhouse/'locked.txt'
    locked.write_text('\n'.join((ROOT/a['wheel']).as_uri()+' --hash=sha256:'+a['sha256'] for a in assets),encoding='utf-8')
    stage=dest.with_name('linux-packages-stage')
    if stage.exists():raise RuntimeError('Previous account staging folder needs review')
    subprocess.run([sys.executable,'-B','-m','pip','install','--no-index','--no-deps','--no-compile',
        '--only-binary=:all:',*PLATFORM,'--require-hashes','--target',str(stage),'-r',str(locked)],
        env=portable_env(ROOT),check=True)
    files=[{'path':p.relative_to(stage).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size}
           for p in sorted(stage.rglob('*')) if p.is_file()]
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage,dest)
    atomic_json(ROOT/'Maintenance/Imports/linux-accounts-lock.json',{'python':'3.12','platform':'Linux x86_64 glibc>=2.28',
        'status':'installed-dependencies-only','assets':assets,'files':files,'expanded_bytes':expanded,
        'hash_provenance':'PyPI published byte size, SHA256 and wheel RECORD; versions match Windows account runtime'})
    print(json.dumps({'installed':len(files),'expanded_bytes':expanded}))


if __name__=='__main__':main()
