"""Create and reopen-verify a source recovery archive and its local C-drive mirror.

Models, installed runtimes, caches, user data and live endurance state are not
included. This is a source snapshot, never a complete SSD backup or restore tool.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json,portable_path,require_space,storage_budget


def digest(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def required_master_paths(root):
    """Include root manuals even when an inherited snapshot omitted them."""
    root=Path(root).resolve()
    pattern=re.compile(r'PortableAI_Master_Instructions_v\d+\.(txt|md)',re.I)
    paths=set()
    for path in root.iterdir():
        if not pattern.fullmatch(path.name):continue
        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('Master instructions must not be a linked/reparse path: '+path.name)
        if not path.is_file():
            raise ValueError('Master instructions path is not a file: '+path.name)
        portable_path(root,path.name)
        paths.add(path.name)
    if not paths:
        raise FileNotFoundError('Snapshot refused: no numbered master instructions found')
    return paths


def verify(folder):
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    archive=folder/'source.zip'
    if digest(archive)!=manifest['archive_sha256']:raise RuntimeError('Recovery archive hash mismatch')
    with zipfile.ZipFile(archive) as source:
        if source.testzip() is not None:raise RuntimeError('Recovery archive CRC failed')
        if len(source.namelist())!=len(manifest['files']):raise RuntimeError('Recovery member count differs')
        for row in manifest['files']:
            portable_path(ROOT,row['path'])
            data=source.read(row['path'])
            if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
                raise RuntimeError('Recovery member hash mismatch: '+row['path'])
    return manifest


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before',type=Path,required=True)
    ap.add_argument('--label',required=True)
    ap.add_argument('--report',default='platform-focus-final.json')
    args=ap.parse_args()
    if Path(args.report).name!=args.report:raise ValueError('Report must be a filename')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,70}',args.label):raise ValueError('Invalid snapshot label')
    before=verify(args.before.resolve())
    require_space(ROOT,32*1024**2,for_outputs=True)
    mirror_base=Path('C:/Users/genes/PortalAI-Recovery')
    if shutil.disk_usage(mirror_base).free<100*1024**2:raise RuntimeError('Insufficient recovery-mirror space')
    name=args.label+'_'+time.strftime('%Y%m%d_%H%M%S')
    folder=ROOT/'Backups'/name;mirror=mirror_base/name
    if folder.exists() or mirror.exists():raise RuntimeError('Snapshot destination already exists')
    paths={r['path'] for r in before['files'] if portable_path(ROOT,r['path']).is_file()}
    for directory in ('Agent','ControlCenter','Tools','Launchers','Documentation','Maintenance/Tests','Maintenance/Imports'):
        for file in (ROOT/directory).rglob('*'):
            if not file.is_file() or any(p.lower() in ('__pycache__','.runtime','cache','data','models','weights','.git') for p in file.relative_to(ROOT).parts):continue
            if file.suffix.lower() in ('.py','.ps1','.sh','.bat','.cmd','.vbs','.txt','.md','.json','.toml','.yaml','.yml'):
                paths.add(file.relative_to(ROOT).as_posix())
    for file in (ROOT/'Maintenance/Reports').iterdir():
        if file.is_file() and file.suffix.lower() in ('.json','.log','.txt','.xml') and file.stat().st_size<=4*1024**2:
            paths.add(file.relative_to(ROOT).as_posix())
    paths.add('AGENTS.md')
    paths.update(required_master_paths(ROOT))
    for relative in ('PortalAI.sh','Runtime/LinuxPython/run-python'):
        if (ROOT/relative).is_file():paths.add(relative)
    for directory in ('Runtime/FFmpeg/linux-x64/bin','Runtime/SoX/linux-x64/bin','Runtime/QEMU/linux-x64/bin','Runtime/MAFFT/linux-x64'):
        for file in (ROOT/directory).glob('*'):
            if file.is_file() and file.stat().st_size<16384 and file.read_bytes().startswith(b'#!'):
                paths.add(file.relative_to(ROOT).as_posix())
    for directory in ('Runtime/StableDiffusion/linux-cpu','Runtime/StableDiffusion/linux-vulkan'):
        for file in (ROOT/directory).glob('*'):
            if file.is_file() and file.stat().st_size<16384 and file.read_bytes().startswith(b'#!'):
                paths.add(file.relative_to(ROOT).as_posix())
    folder.mkdir();archive=folder/'source.zip';rows=[]
    with archive.open('wb') as handle:
        with zipfile.ZipFile(handle,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
            for relative in sorted(paths):
                data=portable_path(ROOT,relative).read_bytes()
                if len(data)>16*1024**2:raise RuntimeError('Unexpected large source file: '+relative)
                output.writestr(relative,data)
                rows.append({'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        handle.flush();os.fsync(handle.fileno())
    manifest={'scope':'Owned source/config/docs/reports only; excludes model weights, runtime binaries, user data and active endurance state',
              'files':rows,'archive_sha256':digest(archive)}
    atomic_json(folder/'manifest.json',manifest)
    verify(folder)
    mirror.mkdir()
    for filename in ('source.zip','manifest.json'):
        with (folder/filename).open('rb') as src,(mirror/filename).open('wb') as dest:
            shutil.copyfileobj(src,dest);dest.flush();os.fsync(dest.fileno())
    verify(mirror)
    old={row['path']:row['sha256'] for row in before['files']}
    changes=[row['path'] for row in rows if old.get(row['path'])!=row['sha256']]
    report={'created_at':time.time(),'backup':str(folder),'mirror':str(mirror),
        'files':len(rows),'archive_bytes':archive.stat().st_size,'archive_sha256':manifest['archive_sha256'],
        'checksum_verified':True,'files_flushed_before_reopen_verification':True,'complete_ssd_backup':False,
        'changed_or_new_since_before':changes,'storage':storage_budget(ROOT)}
    atomic_json(ROOT/'Maintenance/Reports'/args.report,report)
    print(json.dumps({k:v for k,v in report.items() if k!='changed_or_new_since_before'},indent=2))


if __name__=='__main__':main()
