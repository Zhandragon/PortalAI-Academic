"""Same-handle image evidence for a portable executable on a lost mount.

Windows can retain an original DOS image name in CIM while converting the
process image to a current DOS path fails with ERROR_NOT_READY after USB loss.
Capture the kernel-native image and creation time from one handle and bind
them to that CIM row. This never maps an old volume onto the new drive letter,
uses a command-line claim as ownership, or authorizes termination by PID.
"""
from pathlib import Path, PureWindowsPath
import re


def _api():
    import ctypes
    from ctypes import wintypes as w
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.OpenProcess.argtypes = (w.DWORD, w.BOOL, w.DWORD)
    api.OpenProcess.restype = w.HANDLE
    api.CloseHandle.argtypes = (w.HANDLE,)
    api.WaitForSingleObject.argtypes = (w.HANDLE, w.DWORD)
    api.WaitForSingleObject.restype = w.DWORD
    api.GetProcessTimes.argtypes = (w.HANDLE, ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME), ctypes.POINTER(w.FILETIME))
    api.QueryFullProcessImageNameW.argtypes = (w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD))
    return api


def _query(api, handle, flags):
    import ctypes
    from ctypes import wintypes as w
    size = w.DWORD(32768)
    value = ctypes.create_unicode_buffer(size.value)
    ctypes.set_last_error(0)
    if not api.QueryFullProcessImageNameW(handle, flags, value, ctypes.byref(size)):
        return None, ctypes.get_last_error()
    return value.value, 0


def _created(api, handle):
    import ctypes
    from ctypes import wintypes as w
    times = [w.FILETIME() for _ in range(4)]
    if not api.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        return None
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


def matching_suffix(native, original):
    """Only an exact original local-drive image, including its full directory."""
    if not isinstance(native, str) or not isinstance(original, str):
        return False
    match = re.fullmatch(r'\\Device\\HarddiskVolume[0-9]+(\\.+)', native, re.I)
    path = PureWindowsPath(original)
    if (match is None or not re.fullmatch(r'[A-Za-z]:', path.drive)
            or not path.is_absolute() or '..' in path.parts or '/' in original):
        return False
    return match.group(1).casefold() == str(path)[2:].casefold()


def capture(row, root):
    """Read-only: pin only directly owned images with the exact storage error."""
    original = row.get('executable')
    if not original or not Path(original).resolve().is_relative_to(Path(root).resolve()):
        return None
    api = _api()
    handle = api.OpenProcess(0x1000 | 0x00100000, False, row['pid'])
    if not handle:
        return None
    try:
        if api.WaitForSingleObject(handle, 0) != 258:
            return None
        created = _created(api, handle)
        if created is None or created // 10 != row['start'] // 10:
            return None
        image, error = _query(api, handle, 0)
        if image is not None or error != 21:
            return None
        native, error = _query(api, handle, 1)
        if error or not matching_suffix(native, original):
            return None
        return {'pid': row['pid'], 'start': created, 'original': original, 'native': native}
    finally:
        api.CloseHandle(handle)


def verify(row, root, api, handle, created):
    """Recheck the captured image on the exact handle the caller will stop."""
    proof = row.get('detached_image')
    if not isinstance(proof, dict):
        return False
    original = row.get('executable')
    if (proof.get('pid') != row['pid'] or proof.get('start') != created
            or created // 10 != row['start'] // 10 or proof.get('original') != original
            or not Path(original).resolve().is_relative_to(Path(root).resolve())
            or not matching_suffix(proof.get('native'), original)):
        return False
    native, error = _query(api, handle, 1)
    return error == 0 and native == proof['native']
