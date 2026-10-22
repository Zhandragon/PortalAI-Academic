"""Process-local, single-use export destinations registered by the real GUI.

This is not a path service. Only an authenticated GUI may register a new private
staging filename; ordinary export paths retain their original restrictions.
"""
from pathlib import Path
import os
import threading

LIMIT=20*1024*1024
_lock=threading.RLock()
_grants={}
_revoked=set()


def register(root,session,path,profile,complete):
    root=Path(root).resolve();path=Path(path).absolute()
    from account_permissions import require_user
    if require_user(root,session) is not session:raise PermissionError('export_account')
    profile.check()
    if profile.identity[0]!=session.user_id or not path.resolve().is_relative_to(profile.private('Data/Maintenance/NativeExports')):
        raise PermissionError('export_scope')
    if path.exists():raise FileExistsError('export_exists')
    with _lock:
        if len(_grants)>=2:raise RuntimeError('export_capacity')
        _grants[str(path)]=(root,session,profile,complete)


def permitted(root,session,path,needed=0):
    with _lock:grant=_grants.get(str(Path(path).absolute()))
    if grant is None:return False
    if str(Path(path).absolute()) in _revoked:raise PermissionError('export_revoked')
    if grant[0]!=Path(root).resolve() or grant[1] is not session:raise PermissionError('export_authority')
    grant[2].check();session.profile_key
    if needed>LIMIT:raise ValueError('Native download limit is 20 MiB; use a local export for larger archives')
    return True


def finish(root,session,path,result):
    path=Path(path).absolute()
    with _lock:grant=_grants.get(str(path))
    if grant is None:return result
    stat=path.lstat();identity=(stat.st_dev,stat.st_ino)
    try:
        if path.is_symlink() or stat.st_nlink!=1:raise PermissionError('export_link')
        if result.get('verified') is not True:raise RuntimeError('export_not_verified')
        permitted(root,session,path,stat.st_size)
        with path.open('rb') as stream:
            opened=os.fstat(stream.fileno())
            if (opened.st_dev,opened.st_ino)!=identity:raise PermissionError('export_replaced')
            data=stream.read(LIMIT+1)
        if len(data)>LIMIT or len(data)!=stat.st_size:raise ValueError('export_size_changed')
        permitted(root,session,path,len(data))
        grant[3](data)
        return {**result,'path':'Native download (expires after 120 seconds)'}
    finally:
        with _lock:_grants.pop(str(path),None);_revoked.discard(str(path))
        current=path.lstat()
        if not path.is_symlink() and (current.st_dev,current.st_ino)==identity:path.unlink()


def discard(path):
    # A running writer owns its file cleanup. Retiring admission is never a
    # license to delete a file whose creation identity is unknown here.
    with _lock:
        key=str(Path(path).absolute())
        if key in _grants:_revoked.add(key)
