"""Verify and unpack the pinned portable CMake bundle; never install globally."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,tarfile,tempfile
VERSION='3.31.8'
URL='https://github.com/Kitware/CMake/releases/download/v3.31.8/cmake-3.31.8-macos-universal.tar.gz'
SHA256='d1449f969c54d5c00886d5b643340d493dfb3c81cb39ee29b35453395c11ebf7'
SIZE=78373419

def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def install(archive,destination,expected=SHA256,size=SIZE):
    archive=Path(archive);destination=Path(destination)
    if archive.is_symlink() or archive.stat().st_size!=size or digest(archive)!=expected:
        raise ValueError('CMake download failed its pinned size/SHA-256 check; nothing was installed')
    if destination.exists() or destination.is_symlink():raise ValueError('CMake destination already exists; review it before replacing')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Only this newly created stage is cleaned up on failure. No existing tools are removed.
    with tempfile.TemporaryDirectory(prefix='.cmake-stage-',dir=destination.parent) as temp:
        stage=Path(temp)
        with tarfile.open(archive,'r:gz') as z:
            members=z.getmembers()
            if sum(m.size for m in members)>700*1024**2:raise ValueError('CMake archive exceeds extraction budget')
            for m in members:
                if not (stage/m.name).resolve().is_relative_to(stage.resolve()):raise ValueError('Unsafe CMake archive path')
                if m.isdev() or m.isfifo():raise ValueError('Unsupported CMake archive member')
            z.extractall(stage,members=members,filter='data')
        roots=list(stage.iterdir())
        if len(roots)!=1 or not roots[0].is_dir():raise ValueError('Unexpected CMake archive layout')
        executable=roots[0]/'CMake.app/Contents/bin/cmake'
        if not executable.is_file():raise ValueError('CMake executable is missing')
        receipt={'version':VERSION,'archive_sha256':expected,'files':{p.relative_to(roots[0]).as_posix():digest(p) for p in roots[0].rglob('*') if p.is_file() and not p.is_symlink()}}
        (roots[0]/'portalai-cmake.json').write_text(json.dumps(receipt,indent=2))
        os.replace(roots[0],destination)
    return destination/'CMake.app/Contents/bin/cmake'

def verify(destination):
    root=Path(destination)
    if root.is_symlink():raise ValueError('Linked portable CMake folder refused')
    receipt=json.loads((root/'portalai-cmake.json').read_text())
    if receipt.get('archive_sha256')!=SHA256:raise ValueError('Portable CMake has a different archive pin')
    for rel,h in receipt['files'].items():
        p=root/rel
        if not p.resolve().is_relative_to(root.resolve()) or p.is_symlink() or digest(p)!=h:raise ValueError('Portable CMake file verification failed')
    return root/'CMake.app/Contents/bin/cmake'

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--archive',type=Path);ap.add_argument('--destination',type=Path,required=True);ap.add_argument('--verify',action='store_true');a=ap.parse_args()
    try:print(verify(a.destination) if a.verify else install(a.archive,a.destination))
    except (OSError,ValueError,tarfile.TarError) as e:raise SystemExit('PortalAI: '+str(e))
