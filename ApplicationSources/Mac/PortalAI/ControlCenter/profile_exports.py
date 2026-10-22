"""Explicit verified plaintext exports; never overwrite another file or profile."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile


def export_profile(root, session, kind, destination):
    from profile_context import CapturedProfile
    from profile_workspace import ProfileWorkspace
    from profile_paths import _contained
    from runtime_policy import require_space
    profile = CapturedProfile(root)
    if profile.identity is None or profile.identity[0] != session.user_id:
        raise PermissionError('Export requires the active authenticated profile')
    session.profile_key
    if kind not in ('history', 'outputs', 'both'):
        raise ValueError('Unknown export kind')
    root = Path(root).resolve(); destination = Path(destination).absolute()
    from native_export_grants import permitted,finish
    native=permitted(root,session,destination)
    if (destination.resolve().is_relative_to(root/'Private') and not native) or destination.exists():
        raise ValueError('Choose a new export file outside Private account storage')
    if not destination.parent.is_dir():
        raise ValueError('Choose an existing export directory')
    store = ProfileWorkspace(root, session)
    history=('Data/Chat/', 'Data/Memory/')
    outputs=('Outputs/', 'User Folder/', 'Benchmarks/', 'Patch/Videos/')
    prefixes=history if kind=='history' else outputs if kind=='outputs' else history+outputs
    from profile_hydration import materialize
    for prefix in prefixes:
        profile.check(); session.profile_key
        materialize(root, prefix.rstrip('/'), recursive=True)
    profile.check()
    rows = [row for row in store.inventory() if row['path'].startswith(prefixes)]
    needed = sum(row['bytes'] for row in rows) + len(rows)*2048 + 8*1024**2
    if native:permitted(root,session,destination,sum(row['bytes'] for row in rows)+len(rows)*2048+4096)
    if destination.parent.stat().st_dev == root.stat().st_dev:
        require_space(root, needed, for_outputs=True)
    elif shutil.disk_usage(destination.parent).free < needed + 64*1024**2:
        raise RuntimeError('Export destination has insufficient free space')
    created = False
    created_identity = None
    try:
        with destination.open('xb') as out:
            created = True
            stat = os.fstat(out.fileno()); created_identity = (stat.st_dev, stat.st_ino)
            with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                for row in rows:
                    profile.check(); session.profile_key
                    source = store.workspace/row['path']
                    _contained(root, source)
                    if source.stat().st_nlink != 1:
                        raise RuntimeError('Linked export sources require review')
                    hasher = hashlib.sha256(); size = 0
                    with source.open('rb') as src, archive.open(row['path'], 'w', force_zip64=True) as dst:
                        while block := src.read(1024**2):
                            profile.check(); dst.write(block); hasher.update(block); size += len(block)
                    if size != row['bytes'] or hasher.hexdigest() != row['sha256']:
                        raise RuntimeError('Source changed during export; no verified export was produced')
                archive.writestr('PortalAI-export-manifest.json', json.dumps({'version':1,'kind':kind,'files':rows}, ensure_ascii=True))
            out.flush(); os.fsync(out.fileno())
        with zipfile.ZipFile(destination) as archive:
            if set(archive.namelist()) != {row['path'] for row in rows} | {'PortalAI-export-manifest.json'}:
                raise RuntimeError('Export manifest does not match archive')
            for row in rows:
                hasher=hashlib.sha256(); size=0
                with archive.open(row['path']) as src:
                    while block := src.read(1024**2): hasher.update(block); size += len(block)
                if size != row['bytes'] or hasher.hexdigest() != row['sha256']:
                    raise RuntimeError('Export verification failed')
        profile.check(); session.profile_key
        return finish(root,session,destination,{'verified':True,'path':str(destination),'files':len(rows)})
    except BaseException:
        if created:
            try:
                stat = destination.lstat()
                if (stat.st_dev, stat.st_ino) == created_identity:
                    destination.unlink()
            except FileNotFoundError:
                pass
        raise


def export_factory(root, kind):
    def choose(session, parent):
        from tkinter import filedialog
        path = filedialog.asksaveasfilename(parent=parent, title='Export '+kind+' (unencrypted copy)',
                                          defaultextension='.zip', filetypes=[('ZIP archive','*.zip')],
                                          initialfile='PortalAI-'+kind+'.zip')
        if not path: return None
        return lambda: export_profile(root,session,kind,path)
    return choose
