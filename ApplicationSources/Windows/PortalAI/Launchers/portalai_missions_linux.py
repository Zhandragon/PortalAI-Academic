"""Headless Linux mission entry with explicit process-lifetime ownership."""
import argparse
import json
import os
from pathlib import Path
import runpy
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'Agent'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inside-scope', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('component', choices=('mission', 'schedule', 'supervisor', 'preflight'))
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if any(a=='--root' or a.startswith('--root=') for a in args.arguments):
        parser.error('This launcher uses its own portable root; --root overrides are not accepted')
    command = args.arguments[0] if args.arguments else ''
    if args.component=='mission' and command in ('run','worker'):
        parser.error('Use supervisor arm MISSION_ID or supervisor run for owned execution; legacy direct workers are not exposed by this launcher')
    if not sys.platform.startswith('linux'):
        raise RuntimeError('This launcher requires Linux; use PortalAI.exe on Windows')
    from runtime_policy import portable_env
    os.environ.update(portable_env(ROOT))
    from linux_job import preflight,prepare_delegation
    # Reads and Stop must remain available when delegation is unavailable. Only
    # operations which can start a worker need a delegated execution scope.
    needs_scope = ((args.component == 'supervisor' and command in ('arm', 'run')) or
                   (args.component == 'schedule' and command == 'enable'))
    if args.component == 'preflight':
        try:
            result = {'ready': True, **preflight()}
        except (OSError, RuntimeError) as exc:
            result = {'ready': False, 'reason': str(exc), 'systemd_run': bool(shutil.which('systemd-run'))}
        result.update(physical_linux_desktop_test=False, gui_and_media='Bundled; see current Linux validation report',
                      live_accounts='Dedicated credentials required; Linux encryption/signing layer installed',
                      vm='Bundled QEMU/Alpine; requires accessible KVM and delegated cgroup; no emulation fallback')
        print(json.dumps(result, indent=2))
        return
    if needs_scope:
        try:
            prepare_delegation()
            preflight()
        except (OSError, RuntimeError) as exc:
            systemd = shutil.which('systemd-run')
            if args.inside_scope or not systemd:
                raise RuntimeError('Cannot start persistent Linux workers without cgroup v2 delegation: '+str(exc)) from exc
            command = [systemd, '--user', '--scope', '--collect', '--property=Delegate=yes', '--',
                       str(__import__('platform_runtime').python_path(ROOT)), '-B', '-I', str(Path(__file__).resolve()), '--inside-scope',
                       args.component, *args.arguments]
            env = dict(os.environ)
            env.pop('PORTALAI_CGROUP_ROOT', None)
            os.execve(systemd, command, env)
    script = {'mission':'mission_runner.py', 'schedule':'mission_schedule.py',
              'supervisor':'mission_supervisor.py'}[args.component]
    sys.argv = [script, *args.arguments]
    os.chdir(ROOT)
    runpy.run_path(str(ROOT/'Agent'/script), run_name='__main__')


if __name__ == '__main__':
    main()
