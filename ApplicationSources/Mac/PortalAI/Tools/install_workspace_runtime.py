"""Install pinned Workspace assets with this SSD's Python, never host packages.

Run when PortalAI is stopped. Existing Runtime/Knowledge is never overwritten.
Downloads have exact size/SHA pins; wheel compatibility follows the native Python.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space
from platform_runtime import python_path


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def remove_generated_launchers(packages):
    """These unused pip entry points embed the build interpreter's drive path."""
    folder=Path(packages).resolve()/'bin'
    removed=[]
    for name in ('jsonschema','pypdfium2','rapidocr_onnxruntime','tqdm'):
        for suffix in ('','.exe'):
            path=folder/(name+suffix)
            if path.is_file():
                if path.is_symlink() or path.resolve().parent!=folder:raise ValueError('Unexpected launcher path')
                path.unlink();removed.append(path.name)
    if folder.is_dir() and not any(folder.iterdir()):folder.rmdir()
    return removed


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args();root=args.root.resolve()
    if Path(sys.executable).resolve()!=python_path(root).resolve():raise RuntimeError('Use this installation\'s bundled Python')
    target=root/'Runtime/Knowledge'
    if target.exists():raise FileExistsError('Runtime/Knowledge already exists; retain it and use a reviewed update package')
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import parse_wheel_filename
    tags=list(sys_tags());rank={tag:i for i,tag in enumerate(tags)}
    lock=json.loads((root/'Agent/workspace_assets.json').read_text());require_space(root,1024**3,for_outputs=True)
    stage=root/'Runtime'/('Workspace-install-'+uuid.uuid4().hex);stage.mkdir()
    wheels=stage/'wheels';wheels.mkdir();knowledge=stage/'Knowledge';model=knowledge/'model';model.mkdir(parents=True)
    shared=[root/p for p in ('Voice/Piper/packages','Runtime/SciencePackages','Runtime/LinuxPackages/extras','Runtime/ScienceExtras/packages')]
    installed={d.metadata['Name'].lower().replace('_','-'):d.version for d in importlib.metadata.distributions(path=[str(p) for p in shared if p.is_dir()])}
    def download(url,path,expected,size=None):
        request=urllib.request.Request(url,headers={'User-Agent':'PortalAI-Workspace/1'})
        with urllib.request.urlopen(request,context=ssl.create_default_context(),timeout=60) as response,path.open('xb') as out:
            written=0
            while block:=response.read(1024*1024):
                written+=len(block)
                if written>(size or 100*1024**2):raise ValueError('Download exceeds its pinned limit')
                out.write(block)
            out.flush();os.fsync(out.fileno())
        if (size is not None and path.stat().st_size!=size) or sha(path)!=expected:raise ValueError('Download integrity check failed: '+path.name)
    selected=[]
    for name,package in lock['packages'].items():
        if name.lower().replace('_','-') in ('numpy','onnxruntime','pillow','flatbuffers','packaging','protobuf') and installed.get(name.lower().replace('_','-'))==package['version']:continue
        choices=[]
        for item in package['wheels']:
            wheel_tags=parse_wheel_filename(item['file'])[3];positions=[rank[t] for t in wheel_tags if t in rank]
            if positions:choices.append((min(positions),item))
        if not choices:raise RuntimeError('No pinned native wheel for '+name+' on this interpreter/platform; no host fallback was installed')
        item=min(choices,key=lambda pair:pair[0])[1];path=wheels/item['file']
        print('Downloading',name,package['version'],flush=True);download(item['url'],path,item['sha256'],item['size']);selected.append(str(path))
    subprocess.run([str(python_path(root)),'-B','-I','-m','pip','install','--no-index','--no-deps','--no-compile','--target',str(knowledge/'packages'),*selected],check=True,cwd=root)
    removed=remove_generated_launchers(knowledge/'packages')
    for name,url in lock['model_urls'].items():download(url,model/name,lock['embedding']['files'][name])
    (model/'manifest.json').write_text(json.dumps(lock['embedding'],indent=2),encoding='utf-8')
    (knowledge/'provenance.json').write_text(json.dumps({'assets_sha256':sha(root/'Agent/workspace_assets.json'),'packages':{k:v['version'] for k,v in lock['packages'].items()},'omitted_generated_launchers':removed},indent=2))
    # Publication happens only after all downloads and wheel installation pass.
    os.rename(knowledge,target)
    print('Workspace runtime installed on this SSD. Download staging retained for reviewed cleanup:',stage)
    return 0


if __name__=='__main__':raise SystemExit(main())
