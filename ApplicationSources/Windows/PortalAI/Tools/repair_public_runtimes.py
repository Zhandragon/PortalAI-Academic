"""Rebuild allowlisted public package layers from retained, checksum-verified wheels."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from runtime_policy import require_space, portable_path, atomic_json
from profile_paths import _contained
from portable_permissions import grant_runtime_read_execute, checked_tree
from portable_pip_paths import pip_path
from portable_fs import Path, walk, raise_walk_error

LAYERS={
    'amd-runtime':('Runtime/AMDPython/packages','amd-runtime-lock.json',False),
    'amd-audio':('Runtime/AMDAudio/packages','amd-audio-lock.json',False),
    'amd-music':('Runtime/AMDMusic/packages','amd-music-lock.json',False),
    'amd-music-api':('Runtime/AMDMusic/api-packages','amd-music-api-lock.json',False),
    'linux-accounts':('Runtime/AccountPython/linux-packages','linux-accounts-lock.json',True),
    **{'linux-'+k:('Runtime/LinuxPackages/'+k,'linux-'+k+'-lock.json',True)
       for k in ('gui','science','media','extras','cudaextras','comfyextras')},
    **{'linux-torch-'+k:('Runtime/LinuxTorch/'+k,'linux-torch-'+k+'.json',True)
       for k in ('cpu','cu128','rocm7.2')},
}

# Clean Windows recipients retain public repair wheels alongside each isolated
# runtime. Legacy Cache receipts remain supported; no arbitrary Runtime path is
# accepted and one layer cannot borrow another layer's wheelhouse.
PUBLIC_WHEELHOUSES={
    'amd-runtime':'Runtime/AMDPython/wheelhouse',
    'amd-audio':'Runtime/AMDAudio/wheelhouse',
    'amd-music':'Runtime/AMDMusic/wheelhouse',
    'amd-music-api':'Runtime/AMDMusic/api-wheelhouse',
}


def reviewed_wheel_path(root, name, relative):
    path=_contained(root,portable_path(root,relative))
    public=PUBLIC_WHEELHOUSES.get(name)
    if (path.suffix!='.whl' or not (path.is_relative_to(root/'Cache') or
            (public is not None and path.parent==root/public))):
        raise ValueError('Unreviewed wheel path')
    return path


def digest(path):
    with path.open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def verify_staged_wheels(stage, wheels):
    """Recheck installed payloads after an interrupted maintenance worker."""
    import base64
    import csv
    import io
    import zipfile
    for wheel, _ in wheels:
        with zipfile.ZipFile(wheel) as z:
            records=[n for n in z.namelist() if n.endswith('.dist-info/RECORD') and n.count('/')==1]
            if len(records)!=1:raise ValueError('Missing unique wheel RECORD')
            for relative, checksum, size in csv.reader(io.StringIO(z.read(records[0]).decode('utf-8'))):
                if not checksum:continue
                parts=Path(relative).parts
                if parts[0].endswith('.data'):
                    if parts[1] in ('scripts','headers'):continue  # Verified at their installed historical paths below.
                    if parts[1] not in ('purelib','platlib','data','headers'):raise ValueError('Unreviewed wheel relocation')
                    parts=parts[2:]
                path=Path(portable_path(stage,str(Path(*parts))))
                algorithm,expected=checksum.split('=',1)
                # pip prints success before its cross-volume --target copy has
                # finished. An interrupted copy may leave missing payloads.
                # Restore only named members of the reverified pinned wheel.
                if not path.exists():
                    path.parent.mkdir(parents=True,exist_ok=True)
                    with z.open(relative) as src,path.open('xb') as dst:shutil.copyfileobj(src,dst)
                actual=bytes.fromhex(digest(path))
                if (algorithm!='sha256' or path.stat().st_size!=int(size) or
                    expected not in (actual.hex(),base64.urlsafe_b64encode(actual).rstrip(b'=').decode())):
                    raise ValueError('Staged wheel payload checksum mismatch: '+relative)


def repair(name, root=ROOT, *, resume_stage=False):
    """Run offline maintenance only after PortalAI has completely shut down."""
    from contextlib import ExitStack
    from mission_runner import process_lock
    from profile_shutdown import _snapshot, _select
    root=Path(root).resolve()
    profile_lock=_contained(root,root/'Private/profile-runtime.lock')
    if not profile_lock.is_file():
        raise RuntimeError('Public runtime repair requires the existing account controller lock')
    if _select(root,_snapshot()):
        raise RuntimeError('Close PortalAI and its bundled background processes before runtime repair')
    # Hold the same existing lock as account recovery. A GUI cannot start and
    # later interrupt the maintenance worker with its normal shutdown sweep.
    with ExitStack() as locks:
        try:locks.enter_context(process_lock(profile_lock))
        except OSError as exc:
            raise RuntimeError('Close PortalAI before runtime repair; its controller lock is in use or inaccessible') from exc
        if _select(root,_snapshot()):
            raise RuntimeError('A bundled process started before runtime repair; close it and retry')
        return _repair_stopped(name,root,resume_stage=resume_stage)


def _repair_stopped(name, root, *, resume_stage=False):
    root=Path(root).resolve()
    relative, receipt_name, linux=LAYERS[name]
    dest=_contained(root,root/relative)
    stage=_contained(root,dest.with_name(dest.name+'-stage'))
    if stage.exists() and not resume_stage:raise FileExistsError('Retained runtime stage requires review: '+stage.name)
    if resume_stage:
        checked_tree(root,stage)
    receipt_path=_contained(root,root/'Maintenance/Imports'/receipt_name)
    raw=receipt_path.read_bytes();receipt=json.loads(raw)
    assets=receipt.get('assets')
    if not assets:raise ValueError('Runtime has no pinned wheel receipt')
    wheels=[];expanded=0
    import zipfile
    for asset in assets:
        if not asset.get('wheel'):continue  # Pure files are copied against historical hashes below.
        path=reviewed_wheel_path(root,name,asset['wheel'])
        if path.stat().st_size!=asset['bytes'] or digest(path)!=asset['sha256']:
            raise ValueError('Cached wheel differs from pinned receipt: '+path.name)
        with zipfile.ZipFile(path) as z:
            for member in z.infolist():
                portable_path(stage,member.filename)
                if (member.external_attr>>16)&0o170000==0o120000:raise ValueError('Linked wheel member')
                expanded+=member.file_size
        wheels.append((path,asset['sha256']))
    require_space(root,expanded*2+1024**3)
    stamp=time.strftime('%Y%m%d_%H%M%S')
    recovery=_contained(root,root/'Maintenance/Patches'/('PublicRuntime_'+name+'_'+stamp))
    recovery.mkdir(parents=True)
    (recovery/receipt_name).write_bytes(raw)
    mirror=Path.home()/'PortalAI-Recovery'/recovery.name
    if os.name=='nt' and root==ROOT:
        mirror.mkdir(parents=True)
        shutil.copyfile(recovery/receipt_name,mirror/receipt_name)
        if digest(mirror/receipt_name)!=digest(recovery/receipt_name):raise RuntimeError('Receipt recovery mirror mismatch')
    requirements=recovery/'locked.txt'
    requirements.write_text('\n'.join(p.as_uri()+' --hash=sha256:'+sha for p,sha in wheels),encoding='utf-8')
    env=dict(os.environ)
    for key in list(env):
        if key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','__PYVENV_LAUNCHER__') or key.startswith('PORTALAI_'):
            env.pop(key,None)
    env.update(PIP_NO_CACHE_DIR='1',PIP_DISABLE_PIP_VERSION_CHECK='1',PYTHONDONTWRITEBYTECODE='1')
    temporary=recovery/'tmp';temporary.mkdir()
    env.update(TEMP=pip_path(temporary),TMP=pip_path(temporary))
    from import_linux_packages import PLATFORM
    argv=[str(root/'Runtime/BootstrapPython/python.exe'),'-I','-B',str(root/'Tools/portable_pip_runner.py'),'install',
          '--no-index','--no-deps','--no-compile','--require-hashes','--only-binary=:all:']
    if linux:argv+=PLATFORM
    argv+=['--target',pip_path(stage),'-r',pip_path(requirements)]
    print(json.dumps({'runtime':name,'phase':'install','wheels':len(wheels),'expanded_bytes':expanded}),flush=True)
    if resume_stage:
        verify_staged_wheels(stage,wheels)
    else:
        with (recovery/'install.log').open('wb') as log:
            subprocess.run(argv,cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,
                           check=True,timeout=3600,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    old_files=receipt.get('files') or receipt.get('installed_files') or []
    # Existing pure packages and reviewed extra files remain byte-identical. Never
    # copy unlisted vendor/user state, or silently replace a source modification.
    generated=[]
    for row in old_files:
        target=Path(portable_path(stage,row['path']))
        if not target.is_file():
            source=_contained(root,portable_path(dest,row['path']))
            if digest(source)!=row['sha256']:raise ValueError('Retained runtime file changed: '+row['path'])
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if digest(target)!=row['sha256']:
            rel=Path(row['path'])
            if rel.parts[0]=='bin' or (rel.parent.name.endswith('.dist-info') and rel.name in ('RECORD','direct_url.json','INSTALLER','REQUESTED')):
                generated.append(row['path'])
            else:raise ValueError('Rebuilt runtime content differs from historical receipt: '+row['path'])
    permissions=grant_runtime_read_execute(root,stage)
    checked_tree(root,stage)
    files=[]
    for folder, _, names in walk(stage,onerror=raise_walk_error,followlinks=False):
        for filename in sorted(names):
            p=Path(folder)/filename
            files.append({'path':p.relative_to(stage).as_posix(),'sha256':digest(p),'bytes':p.stat().st_size})
    preserved=_contained(root,dest.with_name(dest.name+'-inaccessible-'+stamp))
    for path in (dest,stage,preserved):
        if path.parent.resolve()!=dest.parent.resolve():raise ValueError('Runtime rename escaped reviewed parent')
        _contained(root,path)
    if preserved.exists():raise FileExistsError('Retained runtime already exists')
    from profile_shutdown import _snapshot
    for row in _snapshot().values():
        candidates=[row.get('executable') or '',*row.get('argv',[])]
        if any(Path(x).is_absolute() and Path(x).is_relative_to(dest) for x in candidates):
            raise RuntimeError('Runtime is in use; verified stage retained for review')
    dest.rename(preserved)
    try:stage.rename(dest)
    except BaseException:
        if not dest.exists():preserved.rename(dest)
        raise
    updated={**receipt,'files':files,'portable_permissions':permissions,
             'repair':{'original_receipt_sha256':hashlib.sha256(raw).hexdigest(),'regenerated_packaging_files':generated}}
    atomic_json(receipt_path,updated)
    result={'runtime':name,'repaired':True,'files':len(files),'wheels':len(wheels),
            'preserved_originals':preserved.relative_to(root).as_posix(),'originals_hash_verified':False,
            'private_profiles_changed':False,'permissions':permissions,'regenerated_packaging_files':len(generated)}
    (recovery/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair',choices=sorted(LAYERS),required=True)
    parser.add_argument('--resume-stage',action='store_true',help='Reverify a reviewed interrupted stage against pinned wheel RECORDs before activation')
    args=parser.parse_args();repair(args.repair,resume_stage=args.resume_stage)
