"""Portable interpreter selection and host-specific launch flags."""
from pathlib import Path
import os
import subprocess
import sys

MODULE=Path(__file__).resolve().parents[1]

def python_command(script):
    runtime=MODULE/('Runtime/Python/pythonw.exe' if os.name=='nt' else 'Runtime/LinuxPython/run-python')
    return [str(runtime),'-B','-I',str(MODULE/'app'/script)]

def launch_options():
    return {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}

def target_valid(root):
    return (root/('PortalAI.exe' if os.name=='nt' else 'PortalAI.sh')).is_file() and (root/'Agent/profile_shutdown.py').is_file()

def default_target():
    """Suggest the adjacent installation; explicit Browse/saved paths still win."""
    sibling=MODULE.parent/'PortalAI'
    if target_valid(sibling):return sibling
    if MODULE.parent.name.casefold()=='utilities':
        portable_root=MODULE.parent.parent/'PortalAI'
        if target_valid(portable_root):return portable_root
    return sibling

def resolve_target(relative):
    # Older Windows connections used backslashes. Normalize on read as well
    # as write so the same encrypted connection works after an OS change.
    if not isinstance(relative,str):raise ValueError('Invalid portable target')
    from pathlib import PurePosixPath,PureWindowsPath
    value=relative.replace('\\','/')
    if PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive:raise ValueError('Target must be relative to the module')
    return (MODULE/value).resolve()

def input_owner():
    if os.name!='nt':return 'uid:'+str(os.getuid())
    sid=subprocess.check_output([str(Path(os.environ['SystemRoot'])/'System32/whoami.exe'),'/user','/fo','csv','/nh'],text=True,**launch_options()).strip().split(',')[-1].strip('"')
    if not sid.startswith('S-1-'):raise RuntimeError('Cannot establish local input owner')
    return sid

def package_paths():
    return [str(MODULE/'app'),str(MODULE/('Runtime/packages' if os.name=='nt' else 'Runtime/LinuxPackages'))]
