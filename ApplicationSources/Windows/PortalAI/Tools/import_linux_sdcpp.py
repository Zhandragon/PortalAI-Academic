"""Import the pinned upstream Linux CPU/Vulkan release with publisher SHA256."""
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space,atomic_json
REV='f89d9b13d730eabeede7314ce49dacd18d3c90c2'
PINS={'cpu':(26122036,'2390e744f0c97f452df851581262c145218aa54157db795010c3244a46e07319'),
      'vulkan':(36987163,'441a12efaf319bebd577f09a35fff862e154ebae2a19bdfdd61185e0d6071718')}
def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
    for backend,(size,sha) in PINS.items():
        name='sd-master-f89d9b1-bin-Linux-Ubuntu-24.04-x86_64'+('-vulkan' if backend=='vulkan' else '')+'.zip'
        url='https://github.com/leejet/stable-diffusion.cpp/releases/download/master-951-f89d9b1/'+name
        cache=ROOT/'Cache/LinuxSDcpp'/name;cache.parent.mkdir(parents=True,exist_ok=True)
        require_space(ROOT,size*5)
        if not cache.exists():
            part=cache.with_suffix('.part')
            with urllib.request.urlopen(url,timeout=60) as src,part.open('wb') as out:
                count=0
                for block in iter(lambda:src.read(1024**2),b''):
                    count+=len(block)
                    if count>size:raise RuntimeError('Release exceeds pinned size')
                    out.write(block)
            if part.stat().st_size!=size or digest(part)!=sha:raise RuntimeError('Release checksum mismatch')
            part.rename(cache)
        if cache.stat().st_size!=size or digest(cache)!=sha:raise RuntimeError('Cached release differs')
        destination=ROOT/('Runtime/StableDiffusion/linux-'+backend)
        if destination.exists():raise RuntimeError('Existing runtime needs explicit reviewed replacement')
        folder=destination.with_name(destination.name+'-stage')
        if folder.exists():raise RuntimeError('Retained image stage requires review')
        with zipfile.ZipFile(cache) as z:
            for item in z.infolist():
                if item.is_dir():continue
                rel=Path(item.filename)
                if rel.is_absolute() or '..' in rel.parts:raise ValueError('Unsafe release path')
                file=folder/rel;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(z.read(item))
        cli=next(folder.rglob('sd-cli'))
        if cli.parent!=folder:raise RuntimeError('Unexpected upstream directory layout')
        cli.rename(folder/'sd-cli.bin')
        cli.write_text('''#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../../.." && pwd)
LIB="$ROOT/Runtime/LinuxSystem/rootfs/usr/lib"
unset LD_LIBRARY_PATH
cd "$HERE"
exec "$LIB/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$HERE:$LIB/x86_64-linux-gnu:$LIB" "$HERE/sd-cli.bin" "$@"
''',newline='\n')
        files=[{'path':p.relative_to(folder).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size} for p in folder.rglob('*') if p.is_file()]
        from portable_permissions import grant_runtime_read_execute
        grant_runtime_read_execute(ROOT, folder)
        folder.rename(destination)
        atomic_json(ROOT/f'Maintenance/Imports/sdcpp-linux-{backend}.json',{'verified':True,'revision':REV,'url':url,'bytes':size,'sha256':sha,'installed_files':files})
        print(json.dumps({'installed':backend,'files':len(files)}),flush=True)
if __name__=='__main__':main()
