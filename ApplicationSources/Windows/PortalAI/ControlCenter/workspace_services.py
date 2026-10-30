"""Explicitly started Workspace resources share the existing Stop boundary."""
from pathlib import Path
import threading

_lock=threading.RLock();_resources={}


def register(root,resource):
    with _lock:_resources.setdefault(str(Path(root).resolve()),set()).add(resource)


def unregister(root,resource):
    with _lock:
        values=_resources.get(str(Path(root).resolve()),set());values.discard(resource)


def close_all(root):
    with _lock:values=list(_resources.pop(str(Path(root).resolve()),set()))
    errors=[]
    for resource in values:
        try:resource.close()
        except Exception as exc:errors.append(str(exc))
    return errors
