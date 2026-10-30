"""Read-only interpreter/package inventory. Never changes or merges runtimes."""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
AREAS=('Runtime','Runtimes','Generative','Voice','Video','Music','MusicUnderstanding','OpenWebUI','Tools/KiCad','SpeechToText')
IGNORE={'__pycache__','.git','models','checkpoints','.cache','node_modules','Cache','Outputs','Data'}
IMPORTANT={'torch','torchvision','torchaudio','numpy','transformers','diffusers','onnxruntime','onnxruntime-gpu','scipy','mmcv','mmcv-full','mmpose','open-webui','qwen-tts','demucs','av','wxpython','pydantic'}

def walk(folder):
    for base,dirs,files in os.walk(folder,followlinks=False):
        dirs[:]=[d for d in dirs if d not in IGNORE and not (Path(base)/d).is_junction() and not (Path(base)/d).is_symlink()]
        for name in files:yield Path(base)/name

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def audit(root):
    root=root.resolve();executables=[];layers=[]
    for area in AREAS:
        for p in walk(root/area):
            if p.name.lower() in ('python.exe','python3.12.exe') and '/lib/venv/scripts/' not in p.as_posix().lower():executables.append(p)
            if p.name=='METADATA' and p.parent.name.endswith('.dist-info'):
                text=p.read_text(errors='replace');name=re.search(r'^Name: (.+)$',text,re.M);version=re.search(r'^Version: (.+)$',text,re.M)
                if name and version:layers.append((p.parent.parent,name[1].lower().replace('_','-'),version[1]))
    env=os.environ.copy()
    for k in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','__PYVENV_LAUNCHER__'):env.pop(k,None)
    env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONNOUSERSITE']='1'
    rows=[]
    for exe in sorted(executables):
        folder=exe.parent.parent if exe.parent.name.lower()=='scripts' else exe.parent
        data={'path':exe.relative_to(root).as_posix(),'sha256':digest(exe),'distribution':folder.relative_to(root).as_posix()}
        command=[str(exe),'-B','-I','-S','-c',"import sys,json;print(json.dumps({'version':sys.version.split()[0],'abi':sys.implementation.cache_tag,'prefix':sys.prefix,'base_prefix':sys.base_prefix}))"]
        try:
            result=subprocess.run(command,env=env,capture_output=True,text=True,timeout=15,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));data['probe']=json.loads(result.stdout.strip()) if result.returncode==0 else {'error':(result.stderr or result.stdout)[-1200:]}
        except Exception as exc:data['probe']={'error':str(exc)}
        data['configuration']={p.name:p.read_text(errors='replace')[:6000] for p in [folder/'pyvenv.cfg',*folder.glob('python*._pth')] if p.is_file()}
        core=[];total=0;native=collections.Counter()
        for p in walk(folder):
            size=p.stat().st_size;total+=size;rel=p.relative_to(folder).as_posix()
            if '/site-packages/' not in '/'+rel and p.suffix in ('.exe','.dll','.zip') and len(p.relative_to(folder).parts)<=2:core.append({'path':rel,'bytes':size,'sha256':digest(p)})
            if p.suffix=='.pyd':
                abi=re.search(r'\.(cp\d+|abi3)-',p.name);native[abi[1] if abi else 'untagged']+=1
        data.update(scanned_bytes=total,core=core,native_extensions=dict(native));rows.append(data)
    packages=[]
    for folder in sorted({r[0] for r in layers}):
        matches=[(name,version) for p,name,version in layers if p==folder]
        packages.append({'path':folder.relative_to(root).as_posix(),'distributions':len(matches),'selected_versions':dict((n,v) for n,v in matches if n in IMPORTANT)})
    return {'schema':1,'read_only':True,'root':str(root),'runtime_changes':False,'numpy_changes':False,'interpreters':rows,'package_layers':packages,
            'exclusions':'User data, models, caches, recovery archives and venv template executables. Sizes are logical bytes in scanned distribution trees, not reclaimable/deduplicated allocation.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=ROOT);args=parser.parse_args()
    print(json.dumps(audit(args.root),indent=2))
