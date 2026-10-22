from __future__ import annotations

import ctypes
import csv
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200 if os.name == "nt" else 0)
CREATE_BREAKAWAY_FROM_JOB = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000 if os.name == "nt" else 0)


def runtime_dir(root: Path) -> Path:
    p = root / "Agent" / ".runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_line(path: Path, message: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + message + "\n")
    except Exception:
        pass


def port_open(port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def http_bytes(url: str, timeout: float = 1.0) -> bytes | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.read()
    except Exception:
        return None


def http_json(url: str, timeout: float = 1.0):
    raw = http_bytes(url, timeout)
    if raw is None:
        return None
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except Exception:
        return None


def http_text(url: str, timeout: float = 1.0) -> str | None:
    raw = http_bytes(url, timeout)
    return raw.decode("utf-8", errors="replace") if raw is not None else None


def hidden_popen(args, *, cwd: Path | str | None = None, stdin=None, stdout=None, stderr=None, text=False):
    """Create a detached-looking Windows child without a console or shell scripting.

    BREAKAWAY is attempted first to preserve the old worker independence when a
    parent application happens to be inside a Windows Job Object. Some jobs do not
    permit breakaway, so we retry without it; this is the same compatibility model
    used by the earlier direct-launch fallback.
    """
    kwargs = dict(
        cwd=str(cwd) if cwd else None,
        stdin=stdin if stdin is not None else subprocess.DEVNULL,
        stdout=stdout if stdout is not None else subprocess.DEVNULL,
        stderr=stderr if stderr is not None else subprocess.DEVNULL,
        close_fds=True,
        text=text,
    )
    if os.name != "nt":
        return subprocess.Popen(args, **kwargs)

    base = CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    try:
        return subprocess.Popen(args, creationflags=base | CREATE_BREAKAWAY_FROM_JOB, **kwargs)
    except OSError as exc:
        # ERROR_ACCESS_DENIED is normal if the parent's Job Object disallows breakaway.
        if getattr(exc, "winerror", None) not in (5, 87, None):
            raise
        return subprocess.Popen(args, creationflags=base, **kwargs)


def hidden_run(args, *, timeout: float | None = None, cwd: Path | str | None = None):
    flags = CREATE_NO_WINDOW if os.name == "nt" else 0
    return subprocess.run(
        args,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=flags,
    )


def pythonw_executable() -> str:
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return str(exe)


def find_opengui() -> Path | None:
    candidates = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        candidates.extend([
            Path(local) / "Programs" / "OpenGUI" / "OpenGUI.exe",
            Path(local) / "OpenGUI" / "OpenGUI.exe",
        ])
    pf = os.environ.get("ProgramFiles")
    if pf:
        candidates.append(Path(pf) / "OpenGUI" / "OpenGUI.exe")
    pf86 = os.environ.get("ProgramFiles(x86)")
    if pf86:
        candidates.append(Path(pf86) / "OpenGUI" / "OpenGUI.exe")
    for p in candidates:
        if p.exists():
            return p.resolve()

    if os.name == "nt":
        try:
            import winreg
            locations = [
                (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe"),
            ]
            for hive, key_name in locations:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        value, _ = winreg.QueryValueEx(key, None)
                    p = Path(value)
                    if p.exists():
                        return p.resolve()
                except OSError:
                    pass
        except Exception:
            pass
    return None


# ----- Native Windows process inspection (no shell-management runtime) -----
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_COMMAND_LINE_INFORMATION = 60
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


def iter_processes():
    if os.name != "nt":
        return []
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32FirstW.restype = wintypes.BOOL
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    result = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            result.append((int(entry.th32ProcessID), str(entry.szExeFile)))
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return result


def process_image_path(pid: int) -> str | None:
    if os.name != "nt":
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        try:
            n = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(n.value)
            if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                return None
            return buf.value or None
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def process_command_line(pid: int) -> str | None:
    """Read the command line with NtQueryInformationProcess; fail closed if unavailable."""
    if os.name != "nt":
        return None
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        ntdll.NtQueryInformationProcess.restype = ctypes.c_long
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, int(pid))
        if not h:
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return None
        try:
            needed = wintypes.ULONG(0)
            ntdll.NtQueryInformationProcess(h, PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(needed))
            if needed.value < ctypes.sizeof(UNICODE_STRING):
                return None
            raw = ctypes.create_string_buffer(needed.value)
            status = ntdll.NtQueryInformationProcess(h, PROCESS_COMMAND_LINE_INFORMATION, raw, needed.value, ctypes.byref(needed))
            if int(status) < 0:
                return None
            us = UNICODE_STRING.from_buffer(raw)
            byte_len = int(us.Length)
            ptr = int(us.Buffer or 0)
            if not ptr or byte_len <= 0 or byte_len % 2:
                return None
            base = ctypes.addressof(raw)
            end = base + ctypes.sizeof(raw)
            if base <= ptr and ptr + byte_len <= end:
                return ctypes.wstring_at(ptr, byte_len // 2)
            # Some Windows builds return a remote pointer. Read it if access permits.
            k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
            k32.ReadProcessMemory.restype = wintypes.BOOL
            out = ctypes.create_string_buffer(byte_len + 2)
            got = ctypes.c_size_t(0)
            if k32.ReadProcessMemory(h, ctypes.c_void_p(ptr), out, byte_len, ctypes.byref(got)) and got.value >= byte_len:
                return out.raw[:byte_len].decode("utf-16le", errors="replace")
            return None
        finally:
            k32.CloseHandle(h)
    except Exception:
        return None


def process_named(name: str, expected_path: Path | None = None) -> bool:
    wanted = name.lower()
    expected = os.path.normcase(os.path.abspath(str(expected_path))) if expected_path else None
    for pid, exe in iter_processes():
        if exe.lower() != wanted:
            continue
        if not expected:
            return True
        p = process_image_path(pid)
        if not p:  # access denied/path unavailable: process presence is safer than false shutdown
            return True
        if os.path.normcase(os.path.abspath(p)) == expected:
            return True
    return False


def listening_pids(port: int) -> list[int]:
    try:
        cp = hidden_run(["netstat.exe", "-ano", "-p", "tcp"], timeout=3)
    except Exception:
        return []
    pat = re.compile(r"^\s*TCP\s+\S+:" + re.escape(str(int(port))) + r"\s+\S+\s+LISTENING\s+(\d+)\s*$", re.I)
    pids = set()
    for line in cp.stdout.splitlines():
        m = pat.match(line)
        if m:
            pids.add(int(m.group(1)))
    return sorted(pids)


def kill_tree(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        cp = hidden_run(["taskkill.exe", "/PID", str(int(pid)), "/T", "/F"], timeout=15)
        return cp.returncode == 0
    except Exception:
        return False


def parse_prom_metric(text: str | None, metric: str) -> float | None:
    if not text:
        return None
    pat = re.compile(r"^" + re.escape(metric) + r"(?:\{[^\r\n]*\})?\s+([-+0-9.eE]+)\s*$", re.M)
    m = pat.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None
