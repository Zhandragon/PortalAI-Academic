"""Public suite discovery and independent utility launchers. No account access."""
from pathlib import Path
import json
import os
import platform
import subprocess
import sys
import time

PLATFORMS = ('Windows', 'Mac', 'Linux')
_pending = None


def current_platform():
    name = platform.system()
    value = {'Windows': 'Windows', 'Darwin': 'Mac', 'Linux': 'Linux'}.get(name)
    if value is None:
        raise RuntimeError('This operating system has no PortalAI utility launcher.')
    return value


def edition(root):
    root = Path(root)
    marker = root / 'Maintenance/Imports/distribution-version.json'
    # Academic policy remains authoritative even if a public receipt is missing.
    if (root / 'Agent/academic_policy.py').is_file():
        return 'Academic'
    if marker.is_file():
        value = json.loads(marker.read_text(encoding='utf-8-sig')).get('edition')
        if value not in ('Full', 'Academic'):
            raise RuntimeError('The installed edition could not be verified.')
        return value
    return 'Full'


def editions(root):
    return ('Academic',) if edition(root) == 'Academic' else ('Full', 'Academic')


def utility_roots(root, folder):
    root = Path(root).resolve()
    return (root.parent / 'Utilities' / folder, root.parent / folder)


def require_file(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError('Required utility file is missing: ' + path.name)
    return str(path)


def utility_command(root, kind, os_name=None):
    if kind == 'abliterator' and edition(root) != 'Full':
        raise PermissionError('Abliterator is available in the Full edition.')
    os_name = os_name or current_platform()
    if os_name not in PLATFORMS:
        raise ValueError('Unsupported operating system')
    folder = {'abliterator': 'Portable Abliterator', 'projection': 'PortalAI-Projection'}[kind]
    for home in utility_roots(root, folder):
        if kind == 'projection' and os_name == 'Windows':
            runtime, script = home / 'Runtime/Python/pythonw.exe', home / 'app/projection_ui.py'
            if runtime.is_file() and script.is_file():
                return [str(runtime), '-B', '-I', str(script)], home
        launchers = {
            ('abliterator', 'Windows'): ('Abliterator.exe',),
            ('abliterator', 'Mac'): ('Start Abliterator.command',),
            ('abliterator', 'Linux'): ('Start Abliterator.sh',),
            ('projection', 'Mac'): ('Start Projection.command',),
            ('projection', 'Linux'): ('Start Projection.sh',),
        }.get((kind, os_name), ())
        for name in launchers:
            path = home / name
            if path.is_file():
                return ([str(path)] if os_name == 'Windows' else ['/bin/bash' if os_name == 'Mac' else '/bin/sh', str(path)]), home
    title = 'PortalAI Abliterator' if kind == 'abliterator' else 'PortalAI Home Assistant Projection'
    raise FileNotFoundError(title + ' is not installed for ' + os_name + '. Select it in the suite installer when a compatible package is available.')


def installer_folder(root, target_edition, target_os):
    if target_edition not in editions(root):
        raise PermissionError('Academic installations expose only Academic installers.')
    if target_os not in PLATFORMS:
        raise ValueError('Unknown installer platform')
    parent = Path(root).resolve().parent
    candidates = [parent / 'Utilities/Installers' / target_edition / target_os]
    if target_edition == 'Full':
        candidates += [parent / ('Utilities/PortalAI ' + target_os + ' Installer'),
                       parent / 'Utilities/PortalAI Universal/Packages']
    else:
        candidates += [parent / ('Utilities/Academic/PortalAI ' + target_os + ' Installer'),
                       parent / 'Utilities/Academic/Packages']
    for folder in candidates:
        if not folder.is_dir():
            continue
        if folder == candidates[0] and any(folder.iterdir()):
            return folder
        for p in folder.iterdir():
            name = p.name
            if p.is_file() and 'Installer' in name and target_os in name and name.endswith(('.zip', '.tar.gz', '.exe', '.sh')):
                if ('Academic' in name) == (target_edition == 'Academic'):
                    return folder
        if target_edition == 'Full' and (folder / ('PortalAI-Install.exe' if target_os == 'Windows' else 'install-macos.sh' if target_os == 'Mac' else 'install.sh')).is_file():
            return folder
    raise FileNotFoundError(target_edition + ' ' + target_os + ' installer is not downloaded. Select its installer copy in suite setup.')


def clean_environment():
    return {k: v for k, v in os.environ.items()
            if not k.startswith('PORTALAI_') and k not in ('PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV')}


def spawn(command, cwd):
    options = dict(cwd=str(cwd), env=clean_environment(), stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    return subprocess.Popen(command, **options)


def launch(root, kind):
    command, home = utility_command(root, kind)
    return spawn(command, home)


def reveal(root, target_edition, target_os):
    folder = installer_folder(root, target_edition, target_os)
    if os.name == 'nt':
        os.startfile(str(folder))
    else:
        subprocess.Popen(['/usr/bin/open' if sys.platform == 'darwin' else 'xdg-open', str(folder)],
                         env=clean_environment(), close_fds=True)
    return folder


def request_after_exit(root, action):
    """Called only by an idle, unauthenticated Login dialog."""
    global _pending
    if action not in ('recover', 'reset'):
        raise ValueError('Unknown maintenance action')
    root = Path(root).resolve()
    require_file(root / 'Tools' / ('recover_profile_login.py' if action == 'recover' else 'portalai_full_reset.py'))
    _pending = (root, action)


def launch_after_exit():
    """Bootstrap calls this only after GUI return and instance-lock release."""
    global _pending
    request, _pending = _pending, None
    if request is None:
        return None
    root, action = request
    interpreter = Path(sys.executable)
    if os.name == 'nt' and interpreter.with_name('pythonw.exe').is_file():
        interpreter = interpreter.with_name('pythonw.exe')
    return spawn([str(interpreter), '-B', '-I', str(root / 'Agent/suite_utilities.py'),
                  '--after-exit', action, '--parent', str(os.getpid()), '--root', str(root)], root)


def wait_parent(pid, timeout=60):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise RuntimeError('PortalAI exit could not be verified.')
        try:
            if kernel.WaitForSingleObject(handle, timeout * 1000) != 0:
                raise RuntimeError('PortalAI has not finished closing. No maintenance was started.')
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while os.getppid() == pid:
            if time.monotonic() >= deadline:
                raise RuntimeError('PortalAI has not finished closing.')
            time.sleep(.1)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--after-exit', required=True, choices=('recover', 'reset'))
    parser.add_argument('--parent', required=True, type=int)
    parser.add_argument('--root', required=True, type=Path)
    args = parser.parse_args()
    wait_parent(args.parent)
    script = args.root / 'Tools' / ('recover_profile_login.py' if args.after_exit == 'recover' else 'portalai_full_reset.py')
    command = [sys.executable, '-B', '-I', require_file(script)]
    if args.after_exit == 'recover':
        command.append('--window')
    spawn(command, args.root)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        import tkinter as tk
        from tkinter import messagebox
        window = tk.Tk(); window.withdraw()
        messagebox.showerror('PortalAI maintenance did not start', str(exc), parent=window)
        window.destroy()
