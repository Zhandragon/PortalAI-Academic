"""Read-only disk-space accounting for clean PortalAI installations."""
import ctypes
import math
import os
from pathlib import Path
import shutil

GIB = 1024 ** 3


def existing_directory(path):
    path = Path(path).absolute()
    while not path.exists():
        if path == path.parent:
            raise OSError('Cannot locate the destination volume')
        path = path.parent
    if not path.is_dir():
        raise OSError('Installation destination is not a directory')
    return path


def allocation_unit(path):
    path = existing_directory(path)
    if os.name != 'nt':
        info = os.statvfs(path)
        return info.f_frsize or info.f_bsize
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    volume = ctypes.create_unicode_buffer(32768)
    if not kernel.GetVolumePathNameW(w.LPCWSTR(str(path)), volume, len(volume)):
        raise ctypes.WinError(ctypes.get_last_error())
    values = [w.DWORD() for _ in range(4)]
    if not kernel.GetDiskFreeSpaceW(volume, *[ctypes.byref(x) for x in values]):
        raise ctypes.WinError(ctypes.get_last_error())
    return values[0].value * values[1].value


def requirement(files, artifacts, unit=4096, extra_bytes=0):
    if type(unit) is not int or not 0 < unit <= 2**31:
        raise ValueError('Invalid filesystem allocation unit')
    downloads = {}
    for artifact in artifacts:
        key = artifact['sha256']
        size = artifact['bytes']
        if key in downloads and downloads[key] != size:
            raise ValueError('Conflicting download sizes')
        downloads[key] = size
    installed = sum(row['bytes'] for row in files)
    downloaded = sum(downloads.values())
    # Conservative slack for every file, including empty/small files and downloads.
    allocation = (len(files) + len(downloads)) * (unit - 1)
    need = installed + downloaded + allocation + extra_bytes + GIB
    return dict(installed_bytes=installed, download_bytes=downloaded,
                allocation_allowance_bytes=allocation, working_allowance_bytes=GIB,
                required_bytes=need)


def check_space(destination, files, artifacts, extra_bytes=0):
    probe = existing_directory(destination)
    result = requirement(files, artifacts, allocation_unit(probe), extra_bytes)
    result.update(destination=str(destination), available_bytes=shutil.disk_usage(probe).free)
    result['shortfall_bytes'] = max(0, result['required_bytes'] - result['available_bytes'])
    message = (f"Disk space at {destination}: required {result['required_bytes']/GIB:.2f} GiB "
               f"(installed files, retained downloads, filesystem allocation and working space); "
               f"available {result['available_bytes']/GIB:.2f} GiB.")
    if result['shortfall_bytes']:
        raise OSError(message + f" Need {result['shortfall_bytes']/GIB:.2f} GiB more. "
                      "Choose another destination, free space, or select fewer optional components.")
    result['message'] = message
    return result
