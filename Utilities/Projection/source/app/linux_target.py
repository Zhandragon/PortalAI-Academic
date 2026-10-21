"""Linux identity and lifecycle, using existing pidfd/cgroup ownership gates."""
from pathlib import Path
import os
import subprocess


def gui_row(root,row):
    root=Path(root).resolve();argv=row.get('argv',[])
    scripts={str(root/p) for p in ('ControlCenter/PortableAI_GUI.py','ControlCenter/control_center_bootstrap.py','Launchers/portalai_gui_linux.py')}
    if not any(arg in scripts for arg in argv):return False
    if row.get('uid')!=os.getuid():return False
    python=root/'Runtime/LinuxPython/bin/python3'
    exe=Path(row.get('executable','')).resolve()
    if exe==python.resolve():return True
    loader=root/'Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
    if exe!=loader.resolve() or len(argv)<4 or argv[1]!='--library-path' or Path(argv[3]).resolve()!=python.resolve():return False
    try:
        return any(len(parts:=line.split(maxsplit=5))==6 and 'x' in parts[1] and Path(parts[5]).resolve()==python.resolve()
                   for line in Path(f"/proc/{row['pid']}/maps").read_text().splitlines())
    except (FileNotFoundError,ProcessLookupError):return False


def launch(manager,environment):
    from linux_job import delegated_root,preflight
    preflight();environment['PORTALAI_CGROUP_ROOT']=str(delegated_root())
    return subprocess.Popen(['/bin/sh',str(manager.root/'PortalAI.sh')],cwd=manager.root,env=environment,
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)


def stop_owned(manager,remaining):
    # Existing planner accepts only job cgroups beneath this delegated scope,
    # or direct bundled executables stopped with a verified pidfd. A GUI
    # started in another scope must first be closed normally and relaunched
    # through Projection; never widen a cgroup or kill a host shell by PID.
    from profile_shutdown import _stop_batch
    _stop_batch(manager.root,manager.inventory(True),remaining)
