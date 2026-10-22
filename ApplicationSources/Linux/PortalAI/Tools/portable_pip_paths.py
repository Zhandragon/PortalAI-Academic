"""Represent already-reviewed absolute paths for portable pip subprocesses.

Win32's extended path spelling avoids long temporary filenames without changing
the machine's LongPathsEnabled policy. Callers retain all containment/link checks.
"""
import os
from pathlib import Path


def pip_path(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('A reviewed absolute pip path is required')
    value = str(path)
    if os.name != 'nt' or value.startswith('\\\\?\\'):
        return value
    if value.startswith('\\\\'):
        return '\\\\?\\UNC\\' + value[2:]
    return '\\\\?\\' + value
