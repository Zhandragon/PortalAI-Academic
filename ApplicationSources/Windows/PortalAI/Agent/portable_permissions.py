"""Portable read/execute access for public, allowlisted Windows package trees.

pip moves protected owner-only temporary directories into --target installs.
Their owner SID belongs to one PC. Grant a well-known cross-machine group RX
on package files only; never touch account data, ownership, or inherited ACLs.
"""
import os
from portable_fs import Path, walk, native_path
import re
import stat
import subprocess

FAMILIES = frozenset(('AccountPython', 'AMDPython', 'AMDAudio', 'AMDMusic'))
NAMES = frozenset(('packages', 'api-packages', 'packages-stage', 'api-packages-stage'))
BACKENDS = frozenset(platform + '-' + backend for platform in ('windows', 'linux')
                     for backend in ('cpu', 'vulkan'))
PUBLIC_TREES = frozenset({
    'Runtime/LinuxPython', 'Tools/sox', 'Tools/7zip', 'Voice/Piper/packages',
    'SpeechToText/python_packages_312',
    'Runtime/QEMU/windows-x64', 'Runtime/QEMU/linux-x64', 'Runtime/VM/alpine-3.24.2',
    'Runtime/AccountPython/linux-packages',
    *('Runtime/LinuxPackages/'+kind for kind in ('gui','science','media','extras','cudaextras',
                                              'comfyextras','kornia_compat','musicunderstanding')),
    *('Runtime/LinuxTorch/'+kind for kind in ('cpu','cu128','rocm7.2')),
})


def is_stage(directory):
    return re.search(r'-stage(?:-[a-f0-9]{8})?$', Path(directory).name) is not None


def reviewed_tree(relative):
    """Exact public destinations only; never infer permission scope from a receipt."""
    relative = Path(relative)
    name = re.sub(r'-stage(?:-[a-f0-9]{8})?$', '', relative.name)
    return relative.with_name(name).as_posix() in PUBLIC_TREES


def checked_tree(root, directory):
    from profile_paths import _contained
    root = Path(root).resolve()
    directory = Path(directory).absolute()
    relative = directory.relative_to(root)
    package = (len(relative.parts) == 3 and relative.parts[0] == 'Runtime' and
               relative.parts[1] in FAMILIES and relative.parts[2] in NAMES)
    backend = (len(relative.parts) == 3 and relative.parts[:2] == ('LLM', 'backends') and
               relative.parts[2] in BACKENDS | {name + '-stage' for name in BACKENDS})
    image = (len(relative.parts) == 3 and relative.parts[0] == 'Runtime' and
             relative.parts[1] in ('StableDiffusion', 'StableDiffusion-stage') and
             relative.parts[2] in BACKENDS | {name + '-stage' for name in BACKENDS})
    if not (package or backend or image or reviewed_tree(relative)):
        raise ValueError('Only reviewed public package trees may receive portable permissions')
    _contained(root, directory)
    if not directory.is_dir():
        raise FileNotFoundError('Public package tree is missing')
    paths = [directory]
    def failed(error): raise error
    for folder, dirs, files in walk(directory, onerror=failed, followlinks=False):
        for name in dirs + files:
            path = Path(folder)/name
            info = path.lstat()
            if (stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or
                    not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or
                    (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise ValueError('Linked or nonregular package content requires review')
            paths.append(path)
    return root, directory, paths


def grant_runtime_read_execute(root, directory, *, acl_backup=None):
    if os.name != 'nt':
        return {'changed': False, 'reason': 'Windows-only package ACL policy'}
    root, directory, paths = checked_tree(root, directory)
    if not is_stage(directory) and acl_backup is None:
        raise ValueError('Existing package ACLs require a recovery copy before changes')
    executable = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/icacls.exe'
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    def invoke(arguments):
        result = subprocess.run([str(executable), *arguments], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=180, creationflags=flags)
        if result.returncode:
            raise PermissionError('Public runtime permissions could not be prepared; no account permissions were changed')
    if acl_backup is not None:
        from profile_paths import _contained
        backup = Path(acl_backup).absolute()
        _contained(root, backup)
        if not backup.is_relative_to(root/'Maintenance/Patches') or backup.exists():
            raise ValueError('Choose a new public Maintenance/Patches ACL recovery file')
        backup.parent.mkdir(parents=True, exist_ok=True)
        invoke([native_path(directory), '/save', native_path(backup), '/T', '/L', '/Q'])
        if not backup.is_file() or not backup.stat().st_size:
            raise RuntimeError('Package ACL recovery copy was not written')
        import hashlib
        checksum = hashlib.sha256(backup.read_bytes()).hexdigest()
        backup.with_suffix(backup.suffix+'.sha256').write_text(checksum+'\n', encoding='ascii')
        if hashlib.sha256(backup.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('Package ACL recovery copy did not verify')
        # An existing ACL edit has a second, host-local recovery copy before
        # mutation. This contains public-runtime ACLs only, never profile data.
        mirror = Path.home()/'PortalAI-Recovery/RuntimeACL'/backup.relative_to(root/'Maintenance/Patches')
        _contained(Path.home().resolve(), mirror)
        if mirror.exists(): raise FileExistsError('Runtime ACL recovery mirror already exists')
        mirror.parent.mkdir(parents=True, exist_ok=True)
        with mirror.open('xb') as handle: handle.write(backup.read_bytes())
        if hashlib.sha256(mirror.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('Runtime ACL recovery mirror did not verify')
        mirror.with_suffix(mirror.suffix+'.sha256').write_text(checksum+'\n', encoding='ascii')
    # Recheck the complete tree before asking the native tool to traverse it.
    checked_tree(root, directory)
    invoke([native_path(directory), '/grant', '*S-1-5-11:(OI)(CI)(RX)', '/T', '/L', '/Q'])
    # icacls silently leaves protected FILE ACLs unchanged when only directory
    # inheritance flags are supplied. A separate non-inheritable pass covers
    # pip's individually protected .py/.pyd files as well as its directories.
    invoke([native_path(directory), '/grant', '*S-1-5-11:RX', '/T', '/L', '/Q'])
    from windows_portable_access import PortableAccess
    probe = PortableAccess()
    try:
        for path in paths:
            if not probe.allows(path):
                raise PermissionError('Public runtime still lacks cross-machine read/execute access; stage not ready')
    finally: probe.close()
    return {'changed': True, 'objects': len(paths), 'principal': 'Authenticated Users',
            'access': 'read and execute', 'portable_access_verified': True, 'private_data_changed': False}
