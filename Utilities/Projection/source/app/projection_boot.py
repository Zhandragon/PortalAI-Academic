"""Enter a delegated user scope before any projection identity is unlocked."""
from pathlib import Path
import os
import runpy
import shutil
import sys

MODULE=Path(__file__).resolve().parents[1]

def delegated():
    if os.geteuid()==0:return False
    relative=next((s[3:] for s in Path('/proc/self/cgroup').read_text().splitlines() if s.startswith('0::')),None)
    if not relative:return False
    current=(Path('/sys/fs/cgroup')/relative.lstrip('/')).resolve()
    base=Path(os.environ.get('PORTALAI_CGROUP_ROOT',str(current))).resolve()
    if base==Path('/sys/fs/cgroup') or not base.is_relative_to('/sys/fs/cgroup') or not current.is_relative_to(base):return False
    if base.stat().st_uid!=os.getuid() or not os.access(base/'cgroup.procs',os.W_OK):return False
    os.environ['PORTALAI_CGROUP_ROOT']=str(base)
    return True

def prepare_scope():
    base=Path(os.environ['PORTALAI_CGROUP_ROOT'])
    relative=next(s[3:] for s in Path('/proc/self/cgroup').read_text().splitlines() if s.startswith('0::'))
    current=(Path('/sys/fs/cgroup')/relative.lstrip('/')).resolve()
    if current==base:
        controller=base/'portalai-controller';controller.mkdir(exist_ok=True)
        if controller.is_symlink() or controller.resolve().parent!=base:raise RuntimeError('Invalid controller cgroup')
        (controller/'cgroup.procs').write_text(str(os.getpid()))
    if 'memory' not in (base/'cgroup.controllers').read_text().split():raise RuntimeError('Delegated scope needs memory control')
    if 'memory' not in (base/'cgroup.subtree_control').read_text().split():
        if (base/'cgroup.procs').read_text().split():raise RuntimeError('Start Projection in its own user scope')
        (base/'cgroup.subtree_control').write_text('+memory')
    import uuid
    probe=base/('projection-probe-'+uuid.uuid4().hex);probe.mkdir()
    try:
        if not os.access(probe/'cgroup.kill',os.W_OK):raise RuntimeError('Linux 5.14+ writable cgroup.kill is required')
    finally:probe.rmdir()

if not delegated():
    binary=shutil.which('systemd-run')
    if not binary or os.environ.get('PORTALAI_PROJECTION_DELEGATED')=='1':
        raise SystemExit('Projection needs a regular-user delegated cgroup v2 scope with memory control and cgroup.kill (Linux 5.14+). Start from a graphical systemd user session; no sudo or PID fallback is used.')
    os.environ.pop('PORTALAI_CGROUP_ROOT',None);os.environ['PORTALAI_PROJECTION_DELEGATED']='1'
    os.execv(binary,[binary,'--user','--scope','--collect','--property=Delegate=yes','--','/bin/sh',str(MODULE/'Start Projection.sh')])
prepare_scope()
runpy.run_path(str(MODULE/'app/projection_ui.py'),run_name='__main__')
