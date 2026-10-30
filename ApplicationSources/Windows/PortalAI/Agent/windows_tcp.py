"""Windows listener PIDs from the native, listener-filtered TCP owner tables.

GetExtendedTcpTable with TCP_TABLE_OWNER_PID_LISTENER filters in the OS. Do not
parse netstat's rendered state: some hosts omit listeners with an unknown state.
https://learn.microsoft.com/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
"""
import ctypes
import os
import socket

DWORD = ctypes.c_uint32


class Tcp4Row(ctypes.Structure):
    _fields_ = [(name, DWORD) for name in
                ('state', 'local_address', 'local_port', 'remote_address', 'remote_port', 'pid')]


class Tcp6Row(ctypes.Structure):
    _fields_ = [('local_address', ctypes.c_ubyte * 16), ('local_scope', DWORD),
                ('local_port', DWORD), ('remote_address', ctypes.c_ubyte * 16),
                ('remote_scope', DWORD), ('remote_port', DWORD), ('state', DWORD), ('pid', DWORD)]


def _listener_rows(api, family, row_type):
    size = DWORD(0)
    buffer = None
    for _ in range(4):
        result = api(buffer, ctypes.byref(size), False, family, 3, 0)
        if result == 122:  # ERROR_INSUFFICIENT_BUFFER, also the initial size query
            if not 4 <= size.value <= 64 * 1024 * 1024:
                raise OSError('Invalid Windows TCP owner table size')
            buffer = ctypes.create_string_buffer(size.value)
            continue
        if result:
            raise OSError(result, 'Windows TCP listener ownership query failed')
        if buffer is None or len(buffer) < 4:
            raise OSError('Missing Windows TCP owner table')
        count = DWORD.from_buffer_copy(buffer).value
        if 4 + count * ctypes.sizeof(row_type) > min(size.value, len(buffer)):
            raise OSError('Truncated Windows TCP owner table')
        return (row_type * count).from_buffer_copy(buffer, 4)
    raise OSError('Windows TCP owner table kept changing size')


def listener_pids(port):
    if os.name != 'nt':
        raise OSError('Windows TCP ownership requires Windows')
    api = ctypes.WinDLL('iphlpapi', use_last_error=True).GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(DWORD), ctypes.c_int,
                    DWORD, ctypes.c_int, DWORD]
    api.restype = DWORD
    pids = set()
    for family, row_type in ((socket.AF_INET, Tcp4Row), (socket.AF_INET6, Tcp6Row)):
        for row in _listener_rows(api, family, row_type):
            # Port is network-order in the low 16 bits. Table class 3 already
            # excludes established/closing connections, independent of dwState.
            if socket.ntohs(row.local_port & 0xffff) == int(port) and row.pid:
                pids.add(int(row.pid))
    return sorted(pids)
