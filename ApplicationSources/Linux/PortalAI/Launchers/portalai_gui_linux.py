"""Linux entry for the existing themed GUI and delegated worker lifetime control."""
import os
from pathlib import Path
import runpy
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Runtime/LinuxPackages/gui')]


def main():
    if not sys.platform.startswith('linux'):
        raise RuntimeError('This launcher requires Linux; use PortalAI.exe on Windows')
    from runtime_policy import portable_env
    os.environ.update(portable_env(ROOT, before_login=True))
    from linux_job import prepare_delegation,preflight
    try:
        prepare_delegation()
        preflight()
    except (OSError,RuntimeError) as exc:
        systemd=shutil.which('systemd-run')
        if os.environ.get('PORTALAI_DELEGATION_ATTEMPTED') or not systemd:
            raise RuntimeError('PortalAI needs a delegated cgroup v2 with memory limits and cgroup.kill; '
                               'a usable systemd user scope is required on this recipient: '+str(exc)) from exc
        # The only host utility required here is the service manager, never host Python.
        env=dict(os.environ)
        env.pop('PORTALAI_CGROUP_ROOT',None)  # The new scope must discover its own identity.
        env['PORTALAI_DELEGATION_ATTEMPTED']='1'
        return os.execve(systemd,[systemd,'--user','--scope','--collect','--property=Delegate=yes','--',
                                 str(ROOT/'PortalAI.sh'),*sys.argv[1:]],env)
    runpy.run_path(str(ROOT/'ControlCenter/control_center_bootstrap.py'),run_name='__main__')

if __name__=='__main__':main()
