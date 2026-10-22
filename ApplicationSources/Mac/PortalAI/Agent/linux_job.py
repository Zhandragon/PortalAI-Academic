"""Linux worker lifetime ownership using delegated cgroup v2 plus an EOF guardian.

This is process containment, not a VM/security sandbox. No sudo, host feature
activation, process-name killing, or weak process-group fallback is performed.
"""
import json
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time
import uuid

MOUNT=Path('/sys/fs/cgroup')


def current_group():
    rows=Path('/proc/self/cgroup').read_text().splitlines()
    relative=next((r[3:] for r in rows if r.startswith('0::')),None)
    if not relative or not relative.startswith('/') or '..' in Path(relative).parts:
        raise RuntimeError('Unified cgroup v2 membership is unavailable')
    return (MOUNT/relative.lstrip('/')).resolve()


def delegated_root():
    if not sys.platform.startswith('linux'):raise RuntimeError('cgroup worker ownership requires Linux')
    if os.geteuid()==0:raise RuntimeError('Run portable supervision as a regular user in a delegated cgroup')
    current=current_group()
    candidate=Path(os.environ.get('PORTALAI_CGROUP_ROOT',str(current))).resolve()
    if candidate==MOUNT or not candidate.is_relative_to(MOUNT) or not current.is_relative_to(candidate):
        raise RuntimeError('The delegated cgroup must contain this process and stay below the unified root')
    if candidate.stat().st_uid!=os.geteuid() or not os.access(candidate,os.W_OK) or not os.access(candidate/'cgroup.procs',os.W_OK):
        raise RuntimeError('Linux supervision needs a writable delegated cgroup v2 (for example a systemd user scope with Delegate=yes)')
    if not (candidate/'cgroup.controllers').is_file():raise RuntimeError('Delegated hierarchy is not cgroup v2')
    return candidate


def prepare_delegation():
    """Enable memory limits without moving another process or escaping a job.

    A newly delegated scope contains its launcher. Cgroup v2 requires that
    root to be empty before enabling memory for children. Move only ourselves,
    and only when directly in that root; a nested worker must stay in its job.
    """
    base=delegated_root()
    os.environ['PORTALAI_CGROUP_ROOT']=str(base)
    if current_group()==base:
        controller=base/'portalai-controller'
        controller.mkdir(exist_ok=True)
        if controller.resolve().parent!=base:
            raise RuntimeError('Controller cgroup escapes the delegated root')
        (controller/'cgroup.procs').write_text(str(os.getpid()))
    available=(base/'cgroup.controllers').read_text().split()
    enabled=(base/'cgroup.subtree_control').read_text().split()
    if 'memory' not in available:
        raise RuntimeError('The delegated scope must provide the memory controller')
    if 'memory' not in enabled:
        if (base/'cgroup.procs').read_text().split():
            raise RuntimeError('Other processes occupy the delegated root; start PortalAI in its own delegated scope')
        (base/'cgroup.subtree_control').write_text('+memory')
    return base


def preflight():
    base=delegated_root();test=base/('portalai-probe-'+uuid.uuid4().hex)
    test.mkdir()
    try:
        if not (test/'cgroup.kill').is_file() or not os.access(test/'cgroup.kill',os.W_OK):
            raise RuntimeError('Linux worker cancellation requires writable cgroup.kill (kernel 5.14 or newer)')
    finally:test.rmdir()
    return {'backend':'cgroup-v2','delegated_root':str(base),'os_sandbox':False}


def destroy(group):
    group=Path(group).resolve()
    if group.parent!=delegated_root() or not re.fullmatch(r'portalai-job-[0-9]+-[a-f0-9]{32}',group.name):
        raise RuntimeError('Refusing an unowned cgroup path')
    if not group.exists():return
    (group/'cgroup.kill').write_text('1')
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if 'populated 0' in (group/'cgroup.events').read_text():break
        time.sleep(.05)
    if 'populated 0' not in (group/'cgroup.events').read_text():raise RuntimeError('Owned cgroup did not drain after cancellation')
    for child in sorted((p for p in group.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):child.rmdir()
    group.rmdir()


class LinuxJob:
    def __init__(self,process):
        base=delegated_root()
        os.environ['PORTALAI_CGROUP_ROOT']=str(base)
        if process.poll() is not None:raise RuntimeError('Worker exited before lifetime ownership')
        stat=Path(f'/proc/{process.pid}/stat').read_text().rsplit(')',1)[1].split()
        if int(stat[1])!=os.getpid():raise RuntimeError('Worker is not a direct child of this controller')
        self.group=base/f'portalai-job-{os.getpid()}-{uuid.uuid4().hex}'
        self.group.mkdir();self.guardian=None;self.handle=True
        try:
            if not (self.group/'cgroup.kill').exists():raise RuntimeError('Kernel lacks cgroup.kill; worker remains gated')
            (self.group/'cgroup.procs').write_text(str(process.pid))
            prepare_delegation()
            self.guardian=subprocess.Popen([str(__import__('platform_runtime').python_path(Path(__file__).resolve().parents[1])),'-B','-I',str(Path(__file__).resolve()),'guard',str(self.group)],
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,close_fds=True,start_new_session=True,
                env={**os.environ,'PORTALAI_CGROUP_ROOT':str(base)})
            if not select.select([self.guardian.stdout],[],[],5)[0] or self.guardian.stdout.readline()!=b'READY\n':
                raise RuntimeError('Linux worker guardian failed to become ready')
            self.guardian.stdout.close()
        except BaseException:
            self.close();raise

    def check(self):
        if self.handle and self.guardian.poll() is not None:
            raise RuntimeError('Linux worker guardian exited unexpectedly')

    def close(self,completed=False):
        if not self.handle:return
        try:
            if self.guardian and self.guardian.poll() is None:
                try:
                    self.guardian.stdin.write(b'release\n' if completed else b'cancel\n');self.guardian.stdin.flush()
                except BrokenPipeError:pass
                finally:self.guardian.stdin.close()
                try:self.guardian.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    if not completed:destroy(self.group)
                    self.guardian.kill();self.guardian.wait(timeout=5)
            if not completed and self.group.exists():destroy(self.group)
            if completed:
                try:self.group.rmdir()
                except OSError:pass  # Confirmed full-mode effects may be background services.
        finally:self.handle=None


def move_to_guardians():
    """Move this monitor outside worker jobs, inside the same delegated scope."""
    base=delegated_root()
    # A nested controller lives inside its parent's worker cgroup. Its guardian
    # must survive cancellation of that outer job to kill the sibling media job.
    # Move only this guardian, before READY permits the worker gate to open.
    guardians=base/'portalai-guardians'
    guardians.mkdir(exist_ok=True)
    if guardians.resolve().parent!=base:
        raise RuntimeError('Guardian cgroup escapes the delegated root')
    (guardians/'cgroup.procs').write_text(str(os.getpid()))
    if current_group()!=guardians:
        raise RuntimeError('Guardian did not leave its controller worker cgroup')
    return guardians


def guardian(group):
    group=Path(group).resolve()
    if group.parent!=delegated_root() or not re.fullmatch(r'portalai-job-[0-9]+-[a-f0-9]{32}',group.name):
        raise RuntimeError('Unexpected guardian group')
    move_to_guardians()
    print('READY',flush=True)
    # Only this guardian inherits the pipe. Controller death closes it even if a
    # worker has detached/created a new session; cgroup ownership still applies.
    command=sys.stdin.buffer.readline(16)
    if command!=b'release\n':destroy(group)


if __name__=='__main__':
    if len(sys.argv)==3 and sys.argv[1]=='guard':guardian(sys.argv[2])
    else:print(json.dumps(preflight()))
