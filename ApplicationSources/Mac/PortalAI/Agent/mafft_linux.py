"""Run the verified Linux MAFFT payload with bundled shells, utilities and ELF loader."""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import portable_env


def command_environment(folder,root=ROOT):
    root=Path(root).resolve();folder=Path(folder)
    payload=root/'Runtime/LinuxSystem/genomics'
    helpers=payload/'usr/lib/mafft/lib/mafft'
    shellroot=root/'Runtime/LinuxSystem/genomics-tools'
    native=root/'Runtime/LinuxSystem/rootfs/usr/lib'
    loader=native/'x86_64-linux-gnu/ld-linux-x86-64.so.2'
    libraries=':'.join(map(str,(native/'x86_64-linux-gnu',native,
        payload/'usr/lib/x86_64-linux-gnu',shellroot/'usr/lib/x86_64-linux-gnu')))
    def elf(file):return [str(loader),'--library-path',libraries,str(file)]
    binpath=folder/'bin';binpath.mkdir()
    def wrapper(name,command):
        path=binpath/name;path.write_text('#!/bin/sh\nexec '+shlex.join(command)+' "$@"\n');path.chmod(0o700)
    busybox=shellroot/'usr/bin/busybox'
    apps=subprocess.check_output([str(busybox),'--list'],text=True,timeout=5).splitlines()
    for app in apps:
        if '/' not in app and app not in ('sh','bash'):wrapper(app,[str(busybox),app])
    wrapper('bash',elf(shellroot/'usr/bin/bash'))
    wrapper('perl',elf(payload/'usr/bin/perl'))
    for file in helpers.iterdir():
        if file.is_file() and file.read_bytes()[:4]==b'\x7fELF':wrapper(file.name,elf(file))
    env=portable_env(root);env['PATH']=str(binpath)+':'+env.get('PATH','')
    env['MAFFT_BINARIES']=str(binpath);env['MAFFT_TMPDIR']=str(folder)
    env['PERL5LIB']=':'.join(map(str,(payload/'usr/share/perl/5.40',payload/'usr/lib/x86_64-linux-gnu/perl/5.40')))
    env.pop('LD_LIBRARY_PATH',None)
    return [*elf(shellroot/'usr/bin/bash'),str(payload/'usr/bin/mafft')],env


def main():
    if not sys.platform.startswith('linux'):raise RuntimeError('Linux MAFFT requires Linux')
    cache=private_path(ROOT, 'Cache/MAFFT');cache.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache) as folder:
        command,env=command_environment(folder)
        progress=Path(folder)/'progress.log'
        code=subprocess.call([*command,'--progress',str(progress),*sys.argv[1:]],env=env)
        if progress.exists():
            with progress.open('rb') as source:
                source.seek(max(0,progress.stat().st_size-8000))
                sys.stderr.buffer.write(source.read())
        return code


if __name__=='__main__':raise SystemExit(main())
