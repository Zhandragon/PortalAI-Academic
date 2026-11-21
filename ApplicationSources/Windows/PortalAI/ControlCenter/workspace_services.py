"""Explicitly started Workspace resources share the existing Stop boundary."""
from pathlib import Path
import threading

_lock=threading.RLock();_resources={};_epochs={}


def epoch(root):
    with _lock:return _epochs.get(str(Path(root).resolve()),0)


def register(root,resource,expected_epoch=None):
    key=str(Path(root).resolve())
    with _lock:
        if expected_epoch is not None and _epochs.get(key,0)!=expected_epoch:
            raise RuntimeError('Workspace operation stopped before resource startup')
        _resources.setdefault(key,set()).add(resource)


def unregister(root,resource):
    with _lock:
        values=_resources.get(str(Path(root).resolve()),set());values.discard(resource)


def close_all(root):
    key=str(Path(root).resolve())
    with _lock:
        _epochs[key]=_epochs.get(key,0)+1
        values=list(_resources.pop(key,set()))
    errors=[]
    for resource in values:
        try:resource.close()
        except Exception as exc:
            errors.append(str(exc))
            # Retain failed cleanup for the next verified-shutdown attempt.
            register(root,resource)
    return errors
