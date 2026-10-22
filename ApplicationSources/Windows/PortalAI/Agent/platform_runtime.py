"""Resolve bundled platform runtimes without falling back to host Python."""
import os
from pathlib import Path
import sys


def python_path(root):
    root=Path(root)
    if os.name=='nt':return root/'Runtime/BootstrapPython/python.exe'
    if sys.platform.startswith('linux'):return root/'Runtime/LinuxPython/run-python'
    raise RuntimeError('Portable runtime currently targets Windows x64 and Linux x64')


def ffmpeg_path(root,probe=False):
    name='ffprobe' if probe else 'ffmpeg'
    if os.name=='nt':return Path(root)/'Tools/ffmpeg/bin'/(name+'.exe')
    return Path(root)/'Runtime/FFmpeg/linux-x64/bin'/name

def linux_elf_command(root,argv):
    """Use the bundled loader for native Linux binaries; shell wrappers stay intact."""
    root=Path(root).resolve();argv=list(argv);file=Path(argv[0])
    if not sys.platform.startswith('linux') or not file.is_absolute() or not file.resolve().is_relative_to(root):return argv,None
    with file.open('rb') as source:elf=source.read(4)==b'\x7fELF'
    if not elf or file.name=='ld-linux-x86-64.so.2':return argv,None
    lib=root/'Runtime/LinuxSystem/rootfs/usr/lib';loader=lib/'x86_64-linux-gnu/ld-linux-x86-64.so.2'
    if not loader.is_file():raise RuntimeError('Bundled Linux dynamic loader is missing')
    libs=os.pathsep.join(map(str,(file.parent,lib/'x86_64-linux-gnu',lib)))
    return [str(loader),'--library-path',libs,str(file),*argv[1:]],file.parent


def worker_process_options():
    """Keep the shared worker launch contract; Darwin needs a process group."""
    return {'start_new_session': True} if sys.platform=='darwin' else {}
