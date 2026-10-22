"""Verified Linux package layers, matching reviewed portable Windows dependencies."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
import base64
import csv
import io
import shutil
import uuid

from import_amd_runtime import ROOT, digest, wheel_check
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json, portable_env, require_space

PLATFORM=[value for minor in range(41,16,-1) for value in ('--platform',f'manylinux_2_{minor}_x86_64')]+[
          '--platform','manylinux2014_x86_64','--platform','linux_x86_64',
          '--python-version','3.12','--implementation','cp','--abi','cp312']


def main():
    import argparse,importlib.metadata as md
    parser=argparse.ArgumentParser();parser.add_argument("kind",choices=["gui","science","media","extras","cudaextras","comfyextras","kornia_compat"]);args=parser.parse_args()
    kind=args.kind
    if kind=='kornia_compat':
        from import_linux_kornia_compat import main as import_compat
        return import_compat()
    dest=ROOT/('Runtime/LinuxPackages/'+kind)
    if dest.exists():raise RuntimeError('Linux platform layer already exists; verify instead of replacing')
    sources={'gui':['Runtime/BootstrapPython/Lib/site-packages'],
             'science':['Runtime/ScientificPython/packages','Runtime/SciencePackages'],
             'media':['Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages',
                      'Voice/Qwen3-TTS/.venv/Lib/site-packages','Runtime/AMDAudio/packages',
                      'Runtime/AMDMusic/packages','Runtime/AMDMusic/api-packages'], 'extras':[], 'cudaextras':[], 'comfyextras':[]}[kind]
    pins={};distributions={};pure={}
    excluded={'torch','torchvision','torchaudio','triton','triton_windows','sageattention','flash_attn','xformers',
              'pywin32','win32_setctime','pywin32_ctypes','pynvml','nvidia_ml_py','pip','setuptools','wheel','av',
              'comfy_kitchen','comfy_aimdo','comfyui_workflow_templates','comfyui_workflow_templates_core',
              'comfyui_workflow_templates_media_api','comfyui_workflow_templates_media_image',
              'comfyui_workflow_templates_media_video','comfyui_workflow_templates_media_other'}
    for source in sources:
        for dist in md.distributions(path=[str(ROOT/source)]):
            name=dist.metadata['Name'].lower().replace('-','_')
            if name not in excluded and not name.startswith('nvidia_'):
                pins[name]=dist.version;distributions[name]=dist
    if kind=='gui':pins={'pillow':'12.3.0','psutil':'7.2.2'}
    if kind=='media':pins['av']='16.1.0'
    if kind=='extras':pins={'comfy-aimdo':'0.5.3','comfy-kitchen':'0.2.33','faster-whisper':'1.2.1','ctranslate2':'4.8.2','piper-tts':'1.8.0','pycdlib':'1.14.0'}
    if kind=='comfyextras':pins={'av':'18.1.0','kornia_rs':'0.1.10'}
    if kind=='cudaextras':
        pins={'nvidia-cublas-cu12':'12.8.4.1','nvidia-cuda-runtime-cu12':'12.8.90','nvidia-cuda-cupti-cu12':'12.8.90','nvidia-cuda-nvrtc-cu12':'12.8.93','nvidia-cufft-cu12':'11.3.3.83','nvidia-curand-cu12':'10.3.9.90','nvidia-cusolver-cu12':'11.7.3.90','nvidia-cusparse-cu12':'12.5.8.93','nvidia-nvjitlink-cu12':'12.8.93','nvidia-nvtx-cu12':'12.8.90','nvidia-cufile-cu12':'1.13.1.3'}
    pins={k.replace('-','_'):v for k,v in pins.items()}
    for name,dist in distributions.items():
        if name not in pins or name in ('av','soundfile','comfy_angle'):continue
        wheel=dist.read_text('WHEEL') or ''
        if 'Root-Is-Purelib: true' in wheel and '-none-any' in wheel:
            pure[name]=dist;del pins[name]
    atomic_json(ROOT/f'Maintenance/Imports/linux-{kind}-pins.json',pins)
    report_path=ROOT/f'Maintenance/Imports/linux-{kind}-resolution.json'
    subprocess.run([sys.executable,'-B','-m','pip','install','--dry-run','--ignore-installed',
        '--only-binary=:all:','--no-deps',*PLATFORM,'--report',str(report_path),
        *(name+'=='+version for name,version in pins.items())],env=portable_env(ROOT),check=True)
    report=json.loads(report_path.read_text(encoding='utf-8'))
    found={r['metadata']['name'].lower().replace('-','_'):r['metadata']['version'] for r in report['install']}
    if found!=pins:raise RuntimeError('Linux dependency resolution differs from reviewed platform versions')
    wheelhouse=ROOT/f'Cache/linux-{kind}-wheelhouse';wheelhouse.mkdir(parents=True,exist_ok=True)
    assets=[];expanded=0
    for row in report['install']:
        name=row['metadata']['name'];version=row['metadata']['version'];info=row['download_info']
        url=info['url'];parsed=urllib.parse.urlsplit(url);filename=urllib.parse.unquote(Path(parsed.path).name)
        if parsed.scheme!='https' or parsed.hostname!='files.pythonhosted.org' or not filename.endswith('.whl'):
            raise ValueError('Unrecognized platform wheel source')
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
        # Gmsh's official wheel uses SHA256 hex in RECORD instead of base64url.
        # Verify the same digest bytes; publisher archive SHA256 was checked above.
        expanded+=wheel_check(target,allow_hex_record=name.lower()=='gmsh')
        assets.append({'name':name,'version':version,'url':url,'bytes':size,'sha256':sha,'wheel':target.relative_to(ROOT).as_posix()})
    require_space(ROOT,expanded*2)
    locked=wheelhouse/'locked.txt'
    locked.write_text('\n'.join((ROOT/a['wheel']).as_uri()+' --hash=sha256:'+a['sha256'] for a in assets),encoding='utf-8')
    stage=dest.with_name(kind+'-stage-'+uuid.uuid4().hex[:8])
    if stage.exists():raise RuntimeError('Previous platform staging folder needs review')
    subprocess.run([sys.executable,'-B','-m','pip','install','--no-index','--no-deps','--no-compile',
        '--only-binary=:all:',*PLATFORM,'--require-hashes','--target',str(stage),'-r',str(locked)],
        env=portable_env(ROOT),check=True)
    # Existing pure Python packages are ABI-independent. Reuse only files whose
    # installed wheel RECORD hashes verify; never reuse Windows native binaries.
    for name,dist in pure.items():
        source=Path(dist.locate_file('')).resolve();count=0
        for relative,checksum,size in csv.reader(io.StringIO(dist.read_text('RECORD') or '')):
            if not checksum or relative.startswith('../') or '__pycache__' in relative:continue
            if relative.startswith('OpenGL/DLLS/'):continue  # Universal PyOpenGL includes unused Windows helpers.
            path=(source/relative).resolve()
            if not path.is_relative_to(source) or path.suffix.lower() in ('.pyd','.dll','.exe','.so'):raise RuntimeError('Native/unsafe file in pure dependency')
            blob=path.read_bytes();algorithm,expected=checksum.split('=',1)
            actual=base64.urlsafe_b64encode(hashlib.sha256(blob).digest()).rstrip(b'=').decode()
            if algorithm!='sha256' or actual!=expected or len(blob)!=int(size):raise RuntimeError('Installed pure package RECORD mismatch: '+relative)
            target=stage/relative;target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and target.read_bytes()!=blob:raise RuntimeError('Package file collision: '+relative)
            target.write_bytes(blob);count+=1
        if count==0:raise RuntimeError('Empty pure package RECORD: '+name)
        assets.append({'name':name,'version':dist.version,'source':'existing portable pure Python wheel, RECORD verified','files':count})
    if kind=='science':
        import zipfile
        asset=next(a for a in assets if a['name'].lower()=='gmsh')
        with zipfile.ZipFile(ROOT/asset['wheel']) as archive:
            name=next(n for n in archive.namelist() if n.endswith('/libgmsh.so.4.15'))
            (stage/'libgmsh.so.4.15').write_bytes(archive.read(name))
    files=[{'path':p.relative_to(stage).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size}
           for p in sorted(stage.rglob('*')) if p.is_file()]
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage,dest)
    atomic_json(ROOT/f'Maintenance/Imports/linux-{kind}-lock.json',{'python':'3.12','platform':'Linux x86_64; bundled glibc 2.41 loader',
        'status':'installed-dependencies-only','assets':assets,'files':files,'expanded_bytes':expanded,
        'hash_provenance':'PyPI published byte size, SHA256 and wheel RECORD; versions match Windows platform runtime'})
    print(json.dumps({'installed':len(files),'expanded_bytes':expanded}))


if __name__=='__main__':main()
