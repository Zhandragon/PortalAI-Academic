"""Fetch the pinned official Windows KiCad archive without running its installer."""
from pathlib import Path
import hashlib
import json
import os
import sys
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space

VERSION='9.0.2'
URL='https://github.com/KiCad/kicad-source-mirror/releases/download/9.0.2/kicad-9.0.2-x86_64.exe'
SIZE=1126170952
SHA256='9bc40bcd596dac78acc46833d65f29495c9d1645e9342e14ebabac8daff97f5b'
CHECKSUM_SOURCE='https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/k/KiCad/KiCad/9.0.2/KiCad.KiCad.installer.yaml'


def main():
    require_space(ROOT,8*1024**3,for_outputs=False)
    dest=ROOT/'Runtime/Downloads/KiCad-9.0.2.exe'
    dest.parent.mkdir(parents=True,exist_ok=True)
    part=dest.with_suffix('.partial')
    if not dest.exists():
        if part.exists():raise RuntimeError('Existing partial download requires review')
        count=0;digest=hashlib.sha256()
        with urllib.request.urlopen(URL,timeout=60) as response,part.open('xb') as output:
            while chunk:=response.read(1024**2):
                count+=len(chunk)
                if count>SIZE:raise ValueError('Asset exceeds pinned size')
                digest.update(chunk);output.write(chunk)
            output.flush();os.fsync(output.fileno())
        if count!=SIZE or digest.hexdigest()!=SHA256:raise ValueError('Asset size/hash mismatch')
        part.rename(dest)
    with dest.open('rb') as stream: actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if dest.stat().st_size!=SIZE or actual!=SHA256:raise ValueError('Saved asset verification failed')
    print(json.dumps({'version':VERSION,'path':str(dest),'bytes':SIZE,'sha256':actual,'verified':True}),flush=True)


if __name__=='__main__':main()
