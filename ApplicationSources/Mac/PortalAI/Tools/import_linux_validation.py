"""Verified Debian libraries for the offline Linux validation guest, not host installation.

Only package file data is unpacked. Maintainer scripts are never run. HTTPS
Release SHA256 -> Packages.xz SHA256 -> .deb SHA256 form the recorded receipt.
"""
import hashlib
import io
import json
import lzma
import os
from pathlib import Path,PurePosixPath
import posixpath
import tarfile
import urllib.request
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json,require_space

PACKAGES=('libc6','libgcc-s1','libstdc++6','libcrypt1','libx11-6','libxcb1','libxau6','libxdmcp6',
          'libxext6','libxrender1','libxft2','libfontconfig1','libfreetype6','libpng16-16t64',
          'libbrotli1','zlib1g','libbz2-1.0','libexpat1','libbsd0','libmd0')
BASE='https://deb.debian.org/debian/'


def get(url,limit):
    with urllib.request.urlopen(url,timeout=45) as response:data=response.read(limit+1)
    if len(data)>limit:raise RuntimeError('Download exceeded declared limit')
    return data


def sha(data):return hashlib.sha256(data).hexdigest()


def ar_data(blob):
    if blob[:8]!=b'!<arch>\n':raise ValueError('Not a Debian ar archive')
    offset=8
    while offset+60<=len(blob):
        header=blob[offset:offset+60];size=int(header[48:58]);name=header[:16].decode().strip().rstrip('/')
        if header[58:]!=b'`\n' or size<0 or offset+60+size>len(blob):raise ValueError('Invalid Debian archive')
        body=blob[offset+60:offset+60+size]
        if name.startswith('data.tar'):return body
        offset+=60+size+(size%2)
    raise ValueError('No Debian data archive')


def main():
    destination=ROOT/'Runtime/LinuxValidation/rootfs'
    if destination.exists():raise RuntimeError('Validation payload already exists; verify receipt rather than overwrite')
    require_space(ROOT,400*1024**2,for_outputs=True)
    release=get(BASE+'dists/trixie/Release',2*1024**2).decode()
    rows=release.split('SHA256:\n',1)[1].split('\n\n',1)[0].splitlines()
    entries=[r.split() for r in rows if len(r.split())==3]
    expected,size,relative=next(r for r in entries if r[2]=='main/binary-amd64/Packages.xz')
    compressed=get(BASE+'dists/trixie/'+relative,int(size))
    if len(compressed)!=int(size) or sha(compressed)!=expected:raise RuntimeError('Package index differs from published Release hash')
    with lzma.LZMAFile(io.BytesIO(compressed)) as f:index=f.read(160*1024**2+1)
    if len(index)>160*1024**2:raise RuntimeError('Package metadata exceeds limit')
    records={}
    for block in index.decode().split('\n\n'):
        data=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
        if data.get('Package') in PACKAGES:records[data['Package']]=data
    if set(records)!=set(PACKAGES):raise RuntimeError('Required Linux packages are missing from index')
    files={};links={};assets=[]
    cache=ROOT/'Cache/LinuxValidation';cache.mkdir(parents=True,exist_ok=True)
    for name in PACKAGES:
        row=records[name];cached=cache/Path(row['Filename']).name
        data=cached.read_bytes() if cached.exists() else get(BASE+row['Filename'],int(row['Size']))
        if len(data)!=int(row['Size']) or sha(data)!=row['SHA256']:raise RuntimeError('Debian package hash/size mismatch: '+name)
        if not cached.exists():cached.write_bytes(data)
        assets.append({'name':name,'version':row['Version'],'bytes':len(data),'sha256':sha(data),'url':BASE+row['Filename']})
        with tarfile.open(fileobj=io.BytesIO(ar_data(data)),mode='r:*') as tar:
            for entry in tar:
                path=posixpath.normpath(entry.name.removeprefix('./'))
                if path.startswith('/') or '..' in PurePosixPath(path).parts:raise ValueError('Unsafe package path')
                if entry.isfile():
                    if entry.size>40*1024**2:raise ValueError('Unexpectedly large validation library')
                    files[path]=tar.extractfile(entry).read()
                elif entry.issym() or entry.islnk():
                    target=entry.linkname
                    normalized=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(path),target))
                    if normalized.startswith('../'):raise ValueError('Package link escaped payload')
                    links[path]=normalized
        print(json.dumps({'package':name,'version':row['Version'],'verified':True}),flush=True)
    def resolve(path,seen=()):
        if path in files:return files[path]
        if path in seen or path not in links:raise ValueError('Unresolved Linux payload link: '+path)
        return resolve(links[path],(*seen,path))
    # Materialize library symlinks as identical files so Windows does not require
    # symlink privileges. The guest receives the same verified ELF file bytes.
    for path in links:
        try:files[path]=resolve(path)
        except ValueError:
            if path.startswith(('usr/lib/','usr/lib64/','lib/','lib64/')):raise
    stage=destination.with_name('rootfs-stage');stage.mkdir(parents=True)
    installed=[]
    for relative,data in sorted(files.items()):
        if not relative.startswith(('usr/lib/','usr/lib64/','lib/','lib64/','usr/share/doc/')):continue
        path=stage/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        installed.append({'path':relative,'bytes':len(data),'sha256':sha(data)})
    os.replace(stage,destination)
    atomic_json(ROOT/'Maintenance/Imports/linux-validation-libs.json',{'destination':destination.relative_to(ROOT).as_posix(),
        'verified':True,'architecture':'amd64','suite':'trixie','package_index_sha256':expected,'assets':assets,'files':installed,
        'activation':'offline test guest only; no host installation or maintainer-script execution'})
    print(json.dumps({'installed_files':len(installed),'bytes':sum(r['bytes'] for r in installed)}))


if __name__=='__main__':main()
