"""Read-only login preflight, then the ordinary authenticated PortalAI launcher."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]


def inspect(root=ROOT):
    from account_runtime import preflight
    from local_accounts import LocalAccounts
    from profile_runtime import ProfileRuntime
    from profile_shutdown import _windows_snapshot
    if os.name != 'nt':
        raise RuntimeError('This recovery launcher supports Windows only.')
    preflight()
    store = LocalAccounts(root)
    data = store._read()  # Structural read only; no login, registry rewrite or reset.
    runtime = ProfileRuntime(root, store)
    marker = runtime._read_marker()
    rows = _windows_snapshot()
    controllers = [row for row in rows.values()
                   if Path(row['executable']).resolve().is_relative_to(root)
                   and any(Path(arg).name.lower() in ('portableai_gui.py', 'control_center_bootstrap.py')
                           for arg in row.get('argv', []))]
    projection = None
    # Continue the user's already-running optional companion. These are public
    # module/input paths only; the launcher never opens its encrypted connection.
    for module in (root.parent/'Utilities/PortalAI-Projection', root.parent/'PortalAI-Projection'):
        module = module.resolve()
        worker = module/'app/projection_worker.py'
        interpreter = module/'Runtime/Python/pythonw.exe'
        if not worker.is_file() or not interpreter.is_file():
            continue
        if any(row.get('session') == rows[os.getpid()].get('session')
               and Path(row['executable']).resolve() == interpreter
               and str(worker) in row.get('argv', []) for row in rows.values()):
            projection = module
            break
    return {'controllers': len(controllers),
            'interrupted': bool(marker and marker['state'] != 'closed'),
            'recovery_current': store._recovery_current(data),
            'detached_images': sum('detached_image' in row for row in rows.values()),
            'projection': str(projection) if projection is not None else None}


def launch_environment(projection):
    env = {key: value for key, value in os.environ.items() if not key.startswith('PORTALAI_')}
    if projection:
        import hashlib
        from profile_paths import _contained
        module = Path(projection)
        _contained(module, module/'app/host_runtime.py')
        import importlib.util
        spec = importlib.util.spec_from_file_location('login_recovery_host_runtime', module/'app/host_runtime.py')
        host = importlib.util.module_from_spec(spec); spec.loader.exec_module(host)
        scope = module/'state/input'/hashlib.sha256(host.input_owner().encode()).hexdigest()[:32]
        _contained(module, scope)
        env.update(PORTALAI_PROJECTION_HOME=str(module), PORTALAI_PROJECTION_INPUT=str(scope), PORTALAI_NATIVE_STATE='2')
    return env


def main():
    print('PortalAI login recovery\n')
    print('This preserves your password, accounts, pairing and recovery files.')
    print('Your password is entered only in the normal PortalAI sign-in window.\n')
    try:
        result = inspect()
    except Exception as exc:
        print('Preflight could not verify the installation: '+type(exc).__name__+'.')
        print('Keep the drive connected and preserve existing recovery files. No repair or reset was performed.')
        return 1
    print('Encryption runtime and registry structure: readable.')
    print('Interrupted workspace:', 'present; normal authenticated recovery is needed' if result['interrupted'] else 'none recorded')
    print('Processes attached to a disconnected drive mount:', result['detached_images'])
    if not result['recovery_current']:
        print('The account registry recovery copy needs administrator verification at sign-in.')
    if result['controllers']:
        print('\nPortalAI is already open. Close it normally, then click this launcher again.')
        print('No process was killed. If normal close cannot finish, retain the error for reviewed recovery.')
        return 2
    answer = input('\nPress Enter to open normal PortalAI sign-in, or type Cancel: ').strip()
    if answer:
        print('Canceled; no account files changed.')
        return 0
    # Recheck immediately before launch; PortalAI still enforces its real runtime
    # lock, account authentication and process/sealing gates after it opens.
    fresh = inspect()
    if fresh['controllers']:
        print('PortalAI opened while you were reviewing this screen. Use that window.')
        return 2
    env = launch_environment(fresh['projection'])
    subprocess.Popen([str(ROOT/'PortalAI.exe')], cwd=ROOT, env=env,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    print('Opened the normal PortalAI sign-in. Enter your current account password there.')
    print('Verified recovery can stop leftover owned workers and resume/seal interrupted workspace data.')
    print('The HA recovery helper is separate; it restarts exited apps and does not unlock profiles.')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Recovery launch stopped: '+type(exc).__name__+'. Keep the drive connected and retry after review.')
        print('No password reset or manual recovery-file removal was attempted.')
        raise SystemExit(1) from None
