"""Linux process identity and portable service ownership, without port-based killing."""
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import time

from runtime_policy import ROOT,atomic_json,portable_env


def identity(pid):
    base=Path('/proc')/str(int(pid))
    stat=(base/'stat').read_text().rsplit(')',1)[1].split()
    return {'pid':int(pid),'start_ticks':int(stat[19]),'uid':base.stat().st_uid,
            'executable':str((base/'exe').resolve(strict=True)),
            'argv':(base/'cmdline').read_bytes().rstrip(b'\0').decode().split('\0')}


def owned(row,root=ROOT):
    return row['uid']==os.getuid() and Path(row['executable']).is_relative_to(Path(root).resolve())

def is_llama(row,root=ROOT):
    root=Path(root).resolve()
    if not owned(row,root):return False
    exe=Path(row['executable'])
    if exe.name=='llama-server':return exe.is_relative_to(root/'LLM')
    loader=root/'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
    argv=row['argv']
    if exe!=loader.resolve() or len(argv)<4 or argv[1]!='--library-path':return False
    program=Path(argv[3]).resolve()
    if program.name!='llama-server' or not program.is_relative_to(root/'LLM'):return False
    # Command text alone is not ownership proof: the ELF must be executable-mapped.
    return any(len(parts:=line.split(maxsplit=5))==6 and 'x' in parts[1] and parts[5]==str(program)
               for line in Path(f"/proc/{row['pid']}/maps").read_text().splitlines())


def stop(row,root=ROOT):
    if row['pid']==os.getpid():raise RuntimeError('Refusing to stop the controller')
    # pidfd binds the signal to this exact process, even if its PID is reused.
    try:fd=os.pidfd_open(row['pid'])
    except ProcessLookupError:return
    try:
        current=identity(row['pid'])
        if current!=row or not owned(current,root):raise RuntimeError('Process ownership changed before stop')
        signal.pidfd_send_signal(fd,signal.SIGTERM)
        import select
        if not select.select([fd],[],[],8)[0]:signal.pidfd_send_signal(fd,signal.SIGKILL)
    finally:os.close(fd)


def listeners(port):
    inodes=set()
    for name in ('tcp','tcp6'):
        for line in Path('/proc/net',name).read_text().splitlines()[1:]:
            fields=line.split()
            if fields[3]=='0A' and int(fields[1].rsplit(':',1)[1],16)==port:inodes.add(fields[9])
    result=[]
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal():continue
        try:
            if process.stat().st_uid!=os.getuid():continue
            if any(os.readlink(fd).removeprefix('socket:[').removesuffix(']') in inodes for fd in (process/'fd').iterdir()):result.append(int(process.name))
        except (OSError,PermissionError):continue
    return sorted(result)


def launch(command,cwd=ROOT,name=None,extra_env=None):
    argv=shlex.split(command) if isinstance(command,str) else list(command)
    if not argv or not Path(argv[0]).resolve().is_relative_to(ROOT.resolve()):raise RuntimeError('Service executable is outside the portable root')
    from platform_runtime import linux_elf_command
    argv,native_cwd=linux_elf_command(ROOT,argv)
    if native_cwd:cwd=native_cwd
    elif Path(argv[0]).name=='ld-linux-x86-64.so.2' and len(argv)>3 and Path(argv[3]).name=='llama-server':cwd=Path(argv[3]).parent
    env=portable_env(ROOT)
    if extra_env:env.update(extra_env)
    # The explicit loader/wrapper owns its library path. Never leak the bundled
    # glibc into a recipient's /bin/sh or desktop utilities.
    env.pop('LD_LIBRARY_PATH',None)
    from media_paths import media_runtime
    log=media_runtime(ROOT)/f'linux-{name or "worker"}.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('ab') as out:
        process=subprocess.Popen(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=out,start_new_session=True)
    # A shell wrapper execs the portable loader/Python before its identity is saved.
    deadline=time.monotonic()+5
    while True:
        row=identity(process.pid)
        if owned(row,ROOT):break
        if process.poll() is not None or time.monotonic()>deadline:
            raise RuntimeError('Portable service did not establish an owned executable')
        time.sleep(.02)
    if name:atomic_json(ROOT/'Agent/.runtime'/f'linux-{name}.json',row)
    return process.pid
