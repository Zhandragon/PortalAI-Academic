from __future__ import annotations
import sys
import os
from pathlib import Path

BOOTSTRAP_VERSION=(3,12)

def root_from(start):
    p=Path(start).resolve()
    for x in [p,*p.parents]:
        if (x/'Agent').exists() and (x/'ControlCenter').exists(): return x
    return p

def bootstrap_python(root, windowed=False):
    root=Path(root)
    if os.name=='nt':
        n='pythonw.exe' if windowed else 'python.exe'
        p=root/'Runtime'/'BootstrapPython'/n
    else:
        from platform_runtime import python_path
        p=python_path(root)
    if not p.exists():
        raise FileNotFoundError(f'PortableAI bundled Python runtime is missing: {p}. See the platform installer guide in Documentation/.')
    return str(p)

def assert_bootstrap_compatible():
    if sys.version_info[:2] != BOOTSTRAP_VERSION:
        raise RuntimeError(f'Bootstrap tools require Python 3.12.x; running {sys.version.split()[0]}')
