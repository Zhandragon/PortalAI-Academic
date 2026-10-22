"""Unlock portable dedicated accounts for one PortalAI GUI process session."""
import getpass
import argparse
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_accounts import vault_read
from runtime_policy import portable_env

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    selection=parser.add_mutually_exclusive_group()
    selection.add_argument('--mission',help='Arm this existing mission in a headless account session')
    selection.add_argument('--schedule',help='Enable this existing schedule in a headless account session')
    args=parser.parse_args()
    if os.name!='nt' and not (args.mission or args.schedule):
        parser.error('Linux dedicated-account vault sessions currently require --mission ID or --schedule ID. '
                     'PortalAI.sh opens the Linux GUI with its separate local-profile login; '
                     'this helper does not pass a vault unlock across that login.')
    if args.mission or args.schedule:
        from mission_supervisor import running
        if running(ROOT):
            raise RuntimeError('A supervisor is already running with its existing environment. Stop it before opening a new unlocked account session.')
    os.environ['PORTALAI_ACCOUNT_UNLOCK']=getpass.getpass('Dedicated account-vault passphrase: ')
    try:
        vault_read(ROOT)  # Authenticate before launching; never print decrypted content.
        if args.mission or args.schedule:
            component='supervisor' if args.mission else 'schedule'
            operation='arm' if args.mission else 'enable'
            identifier=args.mission or args.schedule
            from platform_runtime import python_path
            script=(ROOT/'Agent'/('mission_supervisor.py' if args.mission else 'mission_schedule.py')) if os.name=='nt' else ROOT/'Launchers/portalai_missions_linux.py'
            argv=[str(python_path(ROOT)),'-B',str(script)]
            if os.name!='nt':argv.append(component)
            subprocess.run([*argv,operation,identifier],cwd=ROOT,env=portable_env(ROOT,include_account_unlock=True),check=True,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            print('Account session request finished. Check supervisor status; only its child processes inherit the unlock secret. No system environment setting was saved.')
        else:
            executable=ROOT/'Runtime/BootstrapPython/pythonw.exe'
            if not executable.is_file():raise RuntimeError('Bundled GUI Python is missing')
            subprocess.Popen([str(executable),'-B',str(ROOT/'ControlCenter/control_center_bootstrap.py')],
                cwd=ROOT,env=portable_env(ROOT,include_account_unlock=True),stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            print('Launched the PortalAI GUI with the vault unlocked for it and its child processes. No system environment setting was saved. Close an already-open GUI before using this launcher.')
    finally:
        os.environ.pop('PORTALAI_ACCOUNT_UNLOCK',None)
