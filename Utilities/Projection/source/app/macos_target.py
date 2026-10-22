"""Mac launch/identity adapter using PortalAI's existing group ownership gates."""
import os
from pathlib import Path
import subprocess


def gui_row(root,row):
    root=Path(root).resolve()
    scripts={str(root/p) for p in ('Launchers/portalai_gui_macos.py','ControlCenter/control_center_bootstrap.py','ControlCenter/PortableAI_GUI.py')}
    return (row.get('uid')==os.getuid() and
            Path(row.get('executable','')).resolve()==(root/'Runtime/MacPython/bin/python3.12').resolve() and
            any(arg in scripts for arg in row.get('argv',[])))


def launch(manager,environment,*,popen=subprocess.Popen):
    from macos_job import preflight
    preflight()
    # A new group is required by profile_shutdown; no shell/open/LaunchServices
    # process is adopted. Bootstrap retains the per-root controller/port lease.
    return popen([str(manager.root/'Runtime/MacPython/bin/python3.12'),'-B','-I',
                  str(manager.root/'Launchers/portalai_gui_macos.py')],cwd=manager.root,env=environment,
                 stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)


def stop_owned(manager,remaining):
    from profile_shutdown import _stop_batch
    _stop_batch(manager.root,manager.inventory(True),remaining)
