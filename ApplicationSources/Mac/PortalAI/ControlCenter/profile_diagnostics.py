"""Account-aware crash logging; close diagnostic handles before vault sealing."""
from pathlib import Path
import faulthandler
import os
import sys
import threading

_guard=threading.RLock()
_root=None
_handle=None
_suspended=True


def _path(root):
    from profile_paths import enabled, private_path
    if enabled(root):
        return private_path(root,'Logs/ControlCenter_Crash.log')
    return Path(root)/'ControlCenter/PortableAI_Crash.log'


def suspend():
    """Stop writers and release the Windows file handle before snapshot/unlink."""
    global _handle,_suspended
    with _guard:
        _suspended=True
        try:faulthandler.disable()
        except Exception:pass
        if _handle is not None:
            try:_handle.flush();_handle.close()
            finally:_handle=None


def prepare(root):
    """Bind prelogin diagnostics without creating files that contaminate setup.

    Account setup inventories every private/legacy file. Even an empty public
    crash log would turn a fresh installation into a recovery-required one.
    Keeping the root still lets stderr redact details for locked accounts.
    GUIAccountGate resumes actual file logging only after authenticated login.
    """
    global _root
    with _guard:
        suspend()
        _root=Path(root).resolve()


def resume(root):
    """Append only; preserve earlier crash evidence and never truncate it."""
    global _root,_handle,_suspended
    with _guard:
        suspend();_root=Path(root).resolve()
        try:
            path=_path(_root)
            path.parent.mkdir(parents=True,exist_ok=True)
            _handle=path.open('a',encoding='utf-8',errors='replace')
            faulthandler.enable(file=_handle,all_threads=True)
            _suspended=False
        except Exception:
            if _handle is not None:
                _handle.close();_handle=None
            # A locked profile must not emit exception details into shared logs.
            _suspended=True


def record(text):
    with _guard:
        if _suspended or _root is None:return False
        try:
            path=_path(_root)  # Revalidate this login; never use a stale path.
            with path.open('a',encoding='utf-8',errors='replace') as handle:
                handle.write(str(text).rstrip()+'\n')
            return True
        except Exception:return False


def stderr(text):
    """Console output can be redirected by a launcher into a shared file."""
    from profile_paths import enabled
    if _root is not None and enabled(_root):
        text='PortalAI encountered an error. Sign in to view private diagnostics.\n'
    try:
        if sys.stderr is not None:sys.stderr.write(text);sys.stderr.flush()
    except Exception:pass
