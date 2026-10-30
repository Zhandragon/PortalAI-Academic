from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import csv
import json
import os
import re
import socket
import sys
import uuid
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from contextlib import contextmanager

from _common import root_dir
from runtime_policy import tool_plan, require_space

SERVICE_MANAGER_VERSION = "2026.10.10-owned-windows-linux+cuda-rocm+healthy-handoff"


def launcher_metadata(system: str | None = None) -> dict:
    """Describe packaged launch routes without probing hardware or processes."""
    selected = system or ("Windows" if os.name == "nt" else
                          "Linux" if sys.platform.startswith("linux") else "unsupported")
    launchers = {
        "Windows": "direct subprocess CREATE_NO_WINDOW with owned process identity",
        "Linux": "direct subprocess with verified portable Linux executable and start-time identity",
    }
    return {
        "platform": selected,
        "worker_launcher": launchers.get(selected, "No packaged worker launcher for this platform"),
        "worker_launchers": launchers,
        "worker_launch_requires": "Existing ownership, backend, free-memory and storage admission checks",
        "hardware_probed": False,
    }

CREATE_NO_WINDOW = getattr(
    subprocess,
    "CREATE_NO_WINDOW",
    0x08000000 if os.name == "nt" else 0,
)

SERVICES = {
    "comfyui": {
        "port": _instance_port('comfyui'),
        "cwd": Path("Generative/ComfyUI_windows_portable"),
        # v13 launches the actual long-lived ComfyUI Python process directly.
        # Tracking the wrapper BAT/CMD PID caused false startup failures when the
        # wrapper exited before port 8188 had finished coming online.
        "python": Path("python_embeded/python.exe"),
        "main": Path("ComfyUI/main.py"),
        "start_timeout": 600,
    },
    "acestep": {
        "port": _instance_port('acestep'),
        "cwd": Path("Music/ACE-Step-1.5"),
        # The PortableAI ACE-Step bundle uses python_embeded\python.exe.
        # Current upstream start_api_server.bat probes python_embedded\python.exe
        # and otherwise falls back to uv/.venv, which breaks this portable bundle.
        # v14.9 bypasses that BAT and launches the embedded runtime directly.
        "python_candidates": [
            Path("python_embeded/python.exe"),
            Path("python_embedded/python.exe"),
        ],
        "entry": Path("Agent/acestep_embedded_entry.py"),
        "start_timeout": 900,
    },
    "qwen": {
        "port": _instance_port('qwen'),
    },
}

ALIASES = {
    "comfy": "comfyui",
    "comfyui": "comfyui",
    "ace": "acestep",
    "ace-step": "acestep",
    "acestep": "acestep",
    "qwen": "qwen",
    "llm": "qwen",
}


def normalize_service(name: str) -> str:
    key = name.strip().lower()
    if key == "all":
        return "all"
    if key not in ALIASES:
        raise ValueError(f"Unknown service: {name}")
    return ALIASES[key]


def port_open(port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _runtime_dir() -> Path:
    p = root_dir() / "Agent" / ".runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# GPU serialization / VRAM custodianship
# ---------------------------------------------------------------------------
# PortableAI has one primary CUDA device. ComfyUI, ACE-Step, Qwen3-TTS and
# MuseTalk must not be allowed to initialize concurrently on a 24 GB card.
# The lock is process-wide and cross-process so simultaneous OpenGUI tool calls
# cannot race each other into loading multiple model stacks.

def _gpu_lock_path() -> Path:
    from instance_runtime import host_directory
    return host_directory() / 'gpu_exclusive.lock'


def _gpu_owner_path() -> Path:
    return _runtime_dir() / "gpu_exclusive_owner.json"


def _try_lock_file(handle) -> bool:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    else:
        import fcntl
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False


def _unlock_file(handle) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass


def acquire_gpu_lease(owner: str, timeout: float = 7200.0):
    """Acquire the single-GPU lease used by every heavy PortableAI task."""
    path = _gpu_lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if _try_lock_file(handle):
            try:
                _gpu_owner_path().write_text(json.dumps({
                    "owner": owner,
                    "pid": os.getpid(),
                    "acquired_at": time.time(),
                }, indent=2), encoding="utf-8")
            except Exception:
                pass
            return handle
        time.sleep(0.25)
    handle.close()
    raise TimeoutError(f"Timed out waiting for the PortableAI GPU lease ({owner}).")


def release_gpu_lease(handle) -> None:
    if handle is None:
        return
    _unlock_file(handle)
    try:
        handle.close()
    except Exception:
        pass
    try:
        _gpu_owner_path().unlink(missing_ok=True)
    except Exception:
        pass


def quiesce_gpu_workers(target: str | None = None) -> dict:
    """
    Stop persistent GPU peers before another GPU-heavy stage starts.

    target may be 'comfyui' or 'acestep'. For one-shot workers such as
    Qwen3-TTS/MuseTalk, pass anything else (or None) and both persistent
    workers are stopped first.
    """
    result = {}
    for peer in ("comfyui", "acestep"):
        if peer == target:
            continue
        try:
            result[peer] = stop(peer)
        except Exception as exc:
            result[peer] = {"error": str(exc)}
    return result


# PORTABLEAI_SCIENCE_LIFECYCLE_v15_130a_BEGIN
SCIENCE_LIFECYCLE_VERSION = "15.130a"
SCIENCE_WORKLOAD_POLICY = {
    "kind": "tool-workload",
    "lifecycle": "on-demand",
    "persistent": False,
    "default_compute": "cpu",
    "gpu_policy": "explicit-openmm-cuda-or-opencl-lease",
    "persistent_server": False,
}


def _science_activity_path(pid: int | None = None) -> Path:
    return _runtime_dir() / f"science_activity_{int(pid or os.getpid())}.json"


def _portable_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError, PermissionError):
        return False


def _write_science_activity(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _active_science_activities() -> list[dict]:
    active: list[dict] = []
    for marker in _runtime_dir().glob("science_activity_*.json"):
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
            pid = int(data.get("pid") or 0)
        except Exception:
            try:
                marker.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        if not _portable_pid_alive(pid):
            try:
                marker.unlink(missing_ok=True)
            except Exception:
                pass
            continue
        active.append(data)
    active.sort(key=lambda x: float(x.get("started_at") or 0.0))
    return active


def science_lifecycle_metadata(*, include_activity: bool = True) -> dict:
    activities = _active_science_activities() if include_activity else []
    return {
        "version": SCIENCE_LIFECYCLE_VERSION,
        **SCIENCE_WORKLOAD_POLICY,
        "activity_checked": include_activity,
        "active": bool(activities) if include_activity else None,
        "active_count": len(activities) if include_activity else None,
        "activities": activities,
        "activity_marker": "Agent/.runtime/science_activity_<pid>.json",
    }


@contextmanager
def science_workload(
    operation: str,
    *,
    gpu_requested: bool = False,
    gpu_backend: str | None = None,
    timeout: float = 7200.0,
):
    """Foreground Science scope: CPU by default; explicit OpenMM CUDA/OpenCL leases the GPU."""
    op = str(operation or "").strip().lower()
    backend = str(gpu_backend).strip().lower() if gpu_backend else None
    use_gpu = bool(gpu_requested)
    if use_gpu and (op != "protein.minimize" or backend not in ("openmm-cuda", "openmm-opencl")):
        raise ValueError(
            "Science GPU leasing is restricted to an explicit protein.minimize "
            "request using the OpenMM CUDA or OpenCL backend."
        )

    from workload_request import request_guard
    check = request_guard(root_dir())
    check()
    marker = _science_activity_path()
    activity = {
        "pid": os.getpid(),
        "tool": "science",
        "operation": op or str(operation),
        "kind": "tool-workload",
        "lifecycle": "on-demand",
        "persistent": False,
        "compute": backend.removeprefix("openmm-") if use_gpu else "cpu",
        "gpu_requested": use_gpu,
        "gpu_backend": backend if use_gpu else None,
        "state": "waiting-for-gpu" if use_gpu else "running",
        "started_at": time.time(),
    }
    _write_science_activity(marker, activity)

    lease = None
    qwen_state = None
    try:
        if use_gpu:
            lease = acquire_gpu_lease(f"science:{op}:{backend}", timeout=timeout)
            check()
            quiesce_gpu_workers(None)
            qwen_state = qwen_gpu_handoff_begin(f"science:{op}:{backend}", start_guard=check)
            check()
            activity["state"] = "running"
            activity["gpu_lease"] = "acquired"
            _write_science_activity(marker, activity)
        check()
        yield {
            "lifecycle": "on-demand",
            "persistent": False,
            "compute": activity["compute"],
            "gpu_requested": use_gpu,
            "gpu_backend": activity["gpu_backend"],
            "activity_marker": str(marker.relative_to(root_dir())).replace("\\", "/"),
        }
    finally:
        try:
            if use_gpu:
                qwen_gpu_handoff_end(qwen_state)
        finally:
            if use_gpu:
                release_gpu_lease(lease)
            try:
                marker.unlink(missing_ok=True)
            except Exception:
                pass
# PORTABLEAI_SCIENCE_LIFECYCLE_v15_130a_END


def _state_path() -> Path:
    return _runtime_dir() / "service_pids.json"


def _load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(data: dict) -> None:
    _state_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def _run_hidden(args, **kwargs):
    """Run a short-lived console helper without flashing a Windows console."""
    if os.name == "nt":
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)


def _worker_launch_log(message: str) -> None:
    """Best-effort diagnostics for worker-launch fallback/recovery behavior."""
    try:
        path = _runtime_dir() / "worker_launch.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def _launch_direct_hidden(command_line: str, cwd: Path | str) -> int:
    """Start a long-lived worker directly with the Windows process API.

    This deliberately avoids PowerShell, EncodedCommand, CIM/WMI process
    creation, and shell wrappers. CREATE_NO_WINDOW preserves the previous
    no-console behavior. When Windows allows job breakaway we also detach the
    worker from a restrictive parent job; if breakaway is not permitted we
    immediately retry with the same flags PortableAI's prior direct fallback used.
    """
    if os.name != "nt":
        raise RuntimeError("Hidden direct worker launch is Windows-only.")

    cwd_resolved = str(Path(cwd).resolve())
    base_flags = CREATE_NO_WINDOW | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)

    kwargs = dict(
        cwd=cwd_resolved,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )

    try:
        proc = subprocess.Popen(
            command_line,
            creationflags=base_flags | breakaway_flag,
            **kwargs,
        )
        mode = "breakaway"
    except OSError as exc:
        # CREATE_BREAKAWAY_FROM_JOB is rejected when the caller's job does not
        # permit breakaway. Retrying without it is the same launch mode that was
        # already present as PortableAI's v15.26 direct fallback.
        _worker_launch_log(f"DIRECT_BREAKAWAY_RETRY error={exc!r}")
        proc = subprocess.Popen(
            command_line,
            creationflags=base_flags,
            **kwargs,
        )
        mode = "standard"

    _worker_launch_log(
        f"DIRECT_OK pid={proc.pid} mode={mode} cwd={cwd_resolved!r} command={command_line!r}"
    )
    return int(proc.pid)


def _pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name!='nt':
        try:os.kill(pid,0);return True
        except OSError:return False
    cp = _run_hidden(
        ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if cp.returncode != 0:
        return False
    try:
        rows = list(csv.reader(cp.stdout.splitlines()))
    except Exception:
        return False
    for row in rows:
        if len(row) >= 2:
            try:
                if int(row[1]) == int(pid):
                    return True
            except (ValueError, TypeError):
                pass
    return False


def _managed_pid(name: str) -> int | None:
    state = _load_state()
    raw = (state.get(name) or {}).get("launcher_pid")
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return None
    if _pid_alive(pid):
        return pid

    # Clean stale PID records.
    if name in state:
        state.pop(name, None)
        _save_state(state)
    return None


def _remember_pid(name: str, pid: int, log_path: str | None = None) -> None:
    state = _load_state()
    entry = {
        "launcher_pid": int(pid),
        "launched_at": time.time(),
    }
    if log_path:
        entry["log_path"] = str(log_path)
    state[name] = entry
    _save_state(state)


def _forget_pid(name: str) -> None:
    state = _load_state()
    if name in state:
        state.pop(name, None)
        _save_state(state)


def _log_path(name: str) -> Path:
    from media_paths import media_runtime
    path = media_runtime(root_dir()) / f"{name}_service.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _state_log_path(name: str) -> Path | None:
    state = _load_state()
    raw = (state.get(name) or {}).get("log_path")
    if not raw:
        return None
    try:
        return Path(raw)
    except Exception:
        return None


def _tail_text(path: Path | None, max_chars: int = 6000) -> str:
    if not path or not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            text = path.read_text(errors="replace")
        except Exception:
            return ""
    return text[-max_chars:]


def _listening_pids(port: int) -> list[int]:
    if os.name != "nt":
        from linux_process import listeners
        return listeners(port)
    from windows_tcp import listener_pids
    return listener_pids(port)



def qwen_props() -> dict | None:
    """
    Read llama.cpp /props without waking a sleeping model.
    Current llama.cpp documents GET /props as sleep-safe.
    """
    if not port_open(SERVICES["qwen"]["port"]):
        return None
    try:
        with urllib.request.urlopen(_instance_url('qwen', '/props'), timeout=2) as r:
            raw = r.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except Exception:
        return None



def _qwen_handoff_log(message: str) -> None:
    try:
        path = _runtime_dir() / "qwen_vram_handoff.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def _qwen_launch_command_path() -> Path:
    return _runtime_dir() / "qwen_launch_command.txt"


def _qwen_launch_executable_path() -> Path:
    return _runtime_dir() / "qwen_launch_executable.txt"


def _remember_qwen_launch(command_line: str, executable: str | Path | None = None) -> None:
    """Persist the exact Qwen launch command as a recovery-only fallback."""
    try:
        _qwen_launch_command_path().write_text(command_line.strip() + "\n", encoding="utf-8")
        if executable:
            _qwen_launch_executable_path().write_text(
                str(Path(executable).resolve()) + "\n", encoding="utf-8"
            )
    except Exception as exc:
        _worker_launch_log(f"QWEN_LAUNCH_STATE_WRITE_FAILED error={exc!r}")


def _process_image_path(pid: int) -> str | None:
    """Return the executable path for a PID using documented Win32 APIs."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL

        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            size = wintypes.DWORD(32768)
            buf = ctypes.create_unicode_buffer(size.value)
            if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return None
            return buf.value or None
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None


def _registered_qwen_command_line(pid: int) -> str | None:
    """Use saved launcher state only when it matches the live listener executable."""
    try:
        command_path = _qwen_launch_command_path()
        exe_path = _qwen_launch_executable_path()
        if not command_path.exists() or not exe_path.exists():
            return None
        command_line = command_path.read_text(encoding="utf-8").strip()
        expected_exe = exe_path.read_text(encoding="utf-8").strip()
        live_exe = _process_image_path(pid)
        if not command_line or not expected_exe or not live_exe:
            return None
        if os.path.normcase(os.path.abspath(live_exe)) != os.path.normcase(os.path.abspath(expected_exe)):
            _worker_launch_log(
                f"QWEN_REGISTERED_CMD_REJECTED pid={pid} live_exe={live_exe!r} expected={expected_exe!r}"
            )
            return None
        _worker_launch_log(f"QWEN_REGISTERED_CMD_FALLBACK pid={pid}")
        return command_line
    except Exception as exc:
        _worker_launch_log(f"QWEN_REGISTERED_CMD_FAILED pid={pid} error={exc!r}")
        return None


def _process_command_line(pid: int) -> str | None:
    """Read a process command line without spawning PowerShell.

    Preferred path: Windows' native NtQueryInformationProcess
    ProcessCommandLineInformation query. Recovery path: a launch command recorded
    by PortableAI itself, but only after validating that the live listener PID's
    executable matches the recorded llama-server executable. If both paths fail,
    qwen_gpu_handoff_begin() fails closed and leaves Qwen running.
    """
    if os.name != "nt":
        import shlex
        from linux_process import identity
        try:return shlex.join(identity(pid)['argv'])
        except OSError:return None

    try:
        import ctypes
        from ctypes import wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_VM_READ = 0x0010
        PROCESS_COMMAND_LINE_INFORMATION = 60

        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [
                ("Length", wintypes.USHORT),
                ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        ntdll = ctypes.WinDLL("ntdll")

        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.ReadProcessMemory.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        kernel32.ReadProcessMemory.restype = wintypes.BOOL

        ntdll.NtQueryInformationProcess.argtypes = [
            wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]
        ntdll.NtQueryInformationProcess.restype = ctypes.c_long

        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, int(pid)
        )
        can_read_remote = bool(handle)
        if not handle:
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
            can_read_remote = False
        if not handle:
            return _registered_qwen_command_line(pid)

        try:
            required = wintypes.ULONG(0)
            ntdll.NtQueryInformationProcess(
                handle, PROCESS_COMMAND_LINE_INFORMATION, None, 0, ctypes.byref(required)
            )
            if required.value < ctypes.sizeof(UNICODE_STRING):
                return _registered_qwen_command_line(pid)

            raw = ctypes.create_string_buffer(required.value)
            status = ntdll.NtQueryInformationProcess(
                handle, PROCESS_COMMAND_LINE_INFORMATION, raw, required.value, ctypes.byref(required)
            )
            if int(status) < 0:
                return _registered_qwen_command_line(pid)

            value = UNICODE_STRING.from_buffer(raw)
            byte_len = int(value.Length)
            max_len = int(value.MaximumLength)
            ptr = int(value.Buffer or 0)
            if not ptr or byte_len <= 0 or byte_len % 2 or byte_len > max_len:
                return _registered_qwen_command_line(pid)

            start_addr = ctypes.addressof(raw)
            end_addr = start_addr + ctypes.sizeof(raw)
            if start_addr <= ptr and ptr + byte_len <= end_addr:
                text = ctypes.wstring_at(ptr, byte_len // 2)
            elif can_read_remote:
                copy = ctypes.create_string_buffer(byte_len)
                got = ctypes.c_size_t(0)
                if not kernel32.ReadProcessMemory(
                    handle, ctypes.c_void_p(ptr), ctypes.cast(copy, ctypes.c_void_p), byte_len, ctypes.byref(got)
                ) or got.value != byte_len:
                    return _registered_qwen_command_line(pid)
                text = copy.raw.decode("utf-16le", errors="strict")
            else:
                return _registered_qwen_command_line(pid)

            text = text.strip()
            return text or _registered_qwen_command_line(pid)
        finally:
            kernel32.CloseHandle(handle)
    except Exception as exc:
        _worker_launch_log(f"NATIVE_CMDLINE_FAILED pid={pid} error={exc!r}")
        return _registered_qwen_command_line(pid)


def _qwen_health_ready(timeout: float = 2.0) -> bool:
    if not port_open(SERVICES["qwen"]["port"]):
        return False
    try:
        with urllib.request.urlopen(_instance_url('qwen', '/health'), timeout=timeout) as r:
            return int(getattr(r, "status", 0)) == 200
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False


def _wait_qwen_ready(timeout: float = 300.0) -> None:
    deadline = time.time() + float(timeout)
    while time.time() < deadline:
        if _qwen_health_ready(timeout=2.0):
            return
        time.sleep(0.5)
    raise TimeoutError(("Qwen did not become healthy on port 8080 after VRAM handoff.").replace('port 8080', 'port '+str(_instance_port('qwen'))))


def _stop_qwen_listener() -> list[int]:
    """Recheck executable ownership before stopping any listener on port 8080."""
    pids = _listening_pids(SERVICES["qwen"]["port"])
    root = root_dir().resolve()
    if os.name != 'nt':
        from linux_process import identity, owned, is_llama, stop
        rows=[identity(pid) for pid in pids]
        if any(not is_llama(row,root) for row in rows):
            raise RuntimeError('Refusing to stop an unowned Linux listener')
        for row in rows:stop(row,root)
        return pids
    def owned(pid):
        image = _process_image_path(pid)
        if not image: return False
        path = Path(image).resolve()
        return path.name.lower() == "llama-server.exe" and path.is_relative_to(root)
    # Another app can claim an IPv4/IPv6 listener after the earlier handoff probe.
    # Reject a mixed/changed listener set before affecting any of its processes.
    if any(not owned(pid) for pid in pids):
        raise RuntimeError("Refusing to stop a Qwen-port listener outside this portable root")
    killed: list[int] = []
    for pid in pids:
        if not owned(pid):
            raise RuntimeError("Qwen listener ownership changed before stop")
        cp = _run_hidden(
            ["taskkill", "/PID", str(pid), "/F"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if cp.returncode == 0:
            killed.append(pid)

    deadline = time.time() + 20
    while time.time() < deadline and port_open(SERVICES["qwen"]["port"]):
        time.sleep(0.25)

    if port_open(SERVICES["qwen"]["port"]):
        raise RuntimeError(("Qwen is still listening on port 8080 after VRAM handoff stop.").replace('port 8080', 'port '+str(_instance_port('qwen'))))
    return killed


# PORTABLEAI_QWEN_HANDOFF_HARDENING_v15_134a_BEGIN
QWEN_HANDOFF_HARDENING_VERSION = "15.134a"








# PORTABLEAI_QWEN_HANDOFF_HARDENING_v15_134a_END

# PORTABLEAI_QWEN_HANDOFF_HARDENING_v15_134c_BEGIN
QWEN_HANDOFF_HARDENING_VERSION = "15.134c"

def _qwen_generation_path() -> Path:
    return _runtime_dir() / "qwen_handoff_generation.json"

def _read_qwen_generation() -> dict | None:
    p=_qwen_generation_path()
    if not p.exists(): return None
    try:
        d=json.loads(p.read_text(encoding="utf-8",errors="replace")); return d if isinstance(d,dict) else None
    except Exception: return None

def _write_qwen_generation(state: dict) -> None:
    p=_qwen_generation_path();p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(state,indent=2),encoding="utf-8");os.replace(tmp,p)

def _generation_current(state: dict) -> bool:
    cur=_read_qwen_generation();return bool(cur and str(cur.get("token"))==str(state.get("generation_token")))

def _clear_generation_if_current(state: dict) -> None:
    if _generation_current(state):
        try:_qwen_generation_path().unlink(missing_ok=True)
        except Exception:pass

def _mark_handoff_done(state: dict, value: str="restored") -> None:
    raw=state.get("marker_path")
    if raw:
        try:Path(raw).write_text(value,encoding="utf-8")
        except Exception:pass

def _listener_identity() -> dict:
    port = SERVICES["qwen"]["port"]
    pids = _listening_pids(port)
    opened = bool(pids)
    if not pids:
        opened = port_open(port)
        # The child can bind after the PID snapshot but before the socket
        # probe. Refresh OS ownership instead of treating that race as a
        # foreign listener. An unidentified open socket still fails closed.
        for attempt in range(3):
            if not opened:
                break
            if attempt:
                time.sleep(.05)
            pids = _listening_pids(port)
            if pids:
                break
            opened = port_open(port)
    rows=[]
    for pid in pids:
        cmd=_process_command_line(int(pid)) or ""
        image = _process_image_path(int(pid)) if os.name=='nt' else None
        ok=bool(image and Path(image).name.lower()=='llama-server.exe' and Path(image).resolve().is_relative_to(root_dir().resolve()))
        if os.name!='nt':
            from linux_process import identity, owned, is_llama
            try:
                row=identity(pid);ok=is_llama(row,root_dir())
            except OSError:ok=False
        rows.append({"pid":int(pid),"command_line":cmd,"portable_qwen":ok})
    return {"open":bool(pids) or opened,
            "portable_qwen":bool(rows) and all(row["portable_qwen"] for row in rows),
            "listeners":rows}

@contextmanager
def _qwen_lifecycle_mutex(timeout: float=30.0):
    if os.name!="nt":
        from mission_runner import process_lock
        deadline=time.monotonic()+timeout
        while True:
            lock=process_lock(_runtime_dir()/'linux-qwen-lifecycle.lock')
            try:lock.__enter__();break
            except OSError:
                if time.monotonic()>=deadline:raise TimeoutError('Linux lifecycle lock timed out')
                time.sleep(.05)
        try:yield
        finally:lock.__exit__(None,None,None)
        return
    import ctypes
    k=ctypes.WinDLL("kernel32",use_last_error=True);k.CreateMutexW.restype=ctypes.c_void_p
    h=k.CreateMutexW(None,False,"Local\\PortalAI.QwenLifecycle." + __import__("instance_runtime").instance_key(root_dir()))
    if not h: raise OSError(ctypes.get_last_error(),"CreateMutexW failed")
    wait=k.WaitForSingleObject(h,int(max(0.1,float(timeout))*1000))
    if wait not in (0,0x80): k.CloseHandle(h);raise TimeoutError("Timed out waiting for PortableAI Qwen lifecycle mutex")
    try: yield
    finally:
        try:k.ReleaseMutex(h)
        finally:k.CloseHandle(h)
# PORTABLEAI_QWEN_HANDOFF_HARDENING_v15_134c_END

def _start_qwen_command(command_line: str, cwd: str | Path, timeout: float = 300.0, state: dict | None = None) -> int:
    """Restore the captured Qwen command exactly once; adopt an existing PortableAI listener."""
    with _qwen_lifecycle_mutex(timeout=30.0):
        if state is not None and not _generation_current(state):
            raise RuntimeError("Qwen handoff was superseded before restoration")
        ident=_listener_identity()
        if ident["open"]:
            if ident["portable_qwen"]:
                rows=ident["listeners"]; return int(rows[0]["pid"]) if rows else 0
            raise RuntimeError((f"Port 8080 is occupied by a non-PortableAI listener: {ident['listeners']}").replace('Port 8080', 'Port '+str(_instance_port('qwen'))))
        pid=launch_detached(command_line,cwd)
        deadline=time.time()+float(timeout)
        while time.time()<deadline:
            ident=_listener_identity()
            if ident["open"]:
                if ident["portable_qwen"]:
                    rows=ident["listeners"]; return int(rows[0]["pid"]) if rows else int(pid or 0)
                raise RuntimeError((f"Port 8080 was claimed by another process while restoring Qwen: {ident['listeners']}").replace('Port 8080', 'Port '+str(_instance_port('qwen'))))
            time.sleep(.25)
        raise TimeoutError(("Qwen did not bind port 8080 after VRAM handoff restore.").replace('port 8080', 'port '+str(_instance_port('qwen'))))


def _wait_handoff_ready(state: dict, timeout: float = 300.0) -> bool:
    """A listening port can still return HTTP 503 while model weights load.

    Keep the generation alive until health is ready. A Stop/new generation cancels
    this wait without relaunching the server or clearing the newer generation.
    """
    deadline = time.monotonic()+float(timeout)
    while time.monotonic() < deadline:
        if not _generation_current(state): return False
        if _qwen_health_ready(timeout=2.0):
            if not _generation_current(state): return False
            identity = _listener_identity()
            if not identity["portable_qwen"]:
                raise RuntimeError("Qwen readiness came from a listener not owned by this portable root")
            return True
        time.sleep(.5)
    raise TimeoutError("Qwen port opened but the model did not become ready after handoff")

def _wait_linux_handoff_watchdog(state: dict, timeout: float=8.0) -> None:
    """The model stays running until recovery survives cancellation of its owner."""
    from linux_job import delegated_root,MOUNT
    from linux_process import identity,owned
    group=delegated_root()/'portalai-guardians'
    ready=Path(state['watchdog_ready_path'])
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if ready.exists():
            data=json.loads(ready.read_text(encoding='utf-8'))
            row=identity(state['watchdog_pid'])
            membership=next(x[3:] for x in Path(f"/proc/{row['pid']}/cgroup").read_text().splitlines() if x.startswith('0::'))
            actual=(MOUNT/membership.lstrip('/')).resolve()
            expected_script=str(root_dir()/'Agent/qwen_vram_watchdog.py')
            if (data.get('pid')!=row['pid'] or data.get('start_ticks')!=row['start_ticks'] or
                data.get('generation')!=state['generation_token'] or data.get('group')!=str(group) or
                actual!=group or not owned(row,root_dir()) or expected_script not in row['argv'] or
                state['state_path'] not in row['argv']):
                raise RuntimeError('Linux watchdog did not establish independent recovery ownership; Qwen was left running')
            return
        time.sleep(.05)
    raise TimeoutError('Linux watchdog did not acknowledge recovery ownership; Qwen was left running')


def qwen_gpu_handoff_begin(reason: str = "media", *, start_guard=None) -> dict:
    """Generation-gated Qwen VRAM handoff. Startup command/profile is captured, never rewritten."""
    with _qwen_lifecycle_mutex(timeout=30.0):
        if start_guard is not None:
            start_guard()
        ident=_listener_identity()
        if not ident["open"]: return {"active":False,"reason":"Qwen was not running"}
        if not ident["portable_qwen"]: return {"active":False,"reason":(f"Port 8080 is not owned by PortableAI Qwen: {ident['listeners']}").replace('Port 8080', 'Port '+str(_instance_port('qwen')))}
        listener_pid=int(ident["listeners"][0]["pid"]);command_line=_process_command_line(listener_pid)
        if not command_line:
            _qwen_handoff_log(f"SKIP reason={reason!r}: unable to capture command line for PID {listener_pid}")
            return {"active":False,"reason":"Could not capture Qwen command line; left Qwen running","listener_pid":listener_pid}
        token=uuid.uuid4().hex;state_path=_runtime_dir()/f"qwen_handoff_{os.getpid()}_{token}.json";marker_path=_runtime_dir()/f"qwen_handoff_{os.getpid()}_{token}.done"
        state={"active":True,"reason":reason,"listener_pid":listener_pid,"command_line":command_line,"cwd":str(root_dir()),"state_path":str(state_path),"marker_path":str(marker_path),"owner_pid":os.getpid(),"started_at":time.time(),"generation_token":token,"lifecycle_version":QWEN_HANDOFF_HARDENING_VERSION}
        state_path.write_text(json.dumps(state,indent=2),encoding="utf-8");_write_qwen_generation({"token":token,"owner_pid":os.getpid(),"state_path":str(state_path),"started_at":state["started_at"],"reason":reason})
        watchdog=root_dir()/"Agent"/"qwen_vram_watchdog.py"
        if not watchdog.exists(): _clear_generation_if_current(state);state_path.unlink(missing_ok=True);raise RuntimeError("Hardened qwen_vram_watchdog.py is missing; Qwen was left running.")
        from platform_runtime import python_path
        command=[str(python_path(root_dir())),str(watchdog),"--owner-pid",str(os.getpid()),"--state",str(state_path),"--marker",str(marker_path),"--generation",token]
        if os.name=='nt':command=subprocess.list2cmdline(command)
        else:
            state['watchdog_ready_path']=str(state_path.with_suffix('.ready'))
            command+=['--ready',state['watchdog_ready_path']]
        try:
            watchdog_pid=launch_detached(command,root_dir());state["watchdog_pid"]=int(watchdog_pid);state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
            if os.name!='nt':_wait_linux_handoff_watchdog(state)
        except Exception:
            if os.name!='nt':_mark_handoff_done(state,'watchdog-start-failed')
            _clear_generation_if_current(state);state_path.unlink(missing_ok=True);raise
        killed=_stop_qwen_listener();time.sleep(.75);state["killed_pids"]=killed;state_path.write_text(json.dumps(state,indent=2),encoding="utf-8")
        _qwen_handoff_log(f"BEGIN v15.134c generation={token} reason={reason!r} pid={listener_pid} killed={killed}")
        return state

def qwen_gpu_handoff_end(state: dict | None, timeout: float = 300.0) -> dict:
    if not state or not state.get("active"): return {"restored":False,"reason":(state or {}).get("reason","handoff inactive")}
    if not _generation_current(state):
        _mark_handoff_done(state,"stale-generation");return {"restored":False,"stale_generation":True,"reason":"newer Qwen handoff generation owns restoration"}
    try:
        pid=_start_qwen_command(str(state.get("command_line") or ""),str(state.get("cwd") or root_dir()),timeout=timeout,state=state)
        if not _wait_handoff_ready(state, timeout):
            _mark_handoff_done(state,"stale-generation");return {"restored":False,"stale_generation":True}
        _mark_handoff_done(state,"restored");_clear_generation_if_current(state);_qwen_handoff_log(f"END v15.134c restored/adopted Qwen pid={pid}")
        return {"restored":True,"ready":True,"pid":pid}
    except Exception as e:
        _qwen_handoff_log(f"RESTORE FAILED v15.134c: {e}");raise

def qwen_gpu_handoff_recover(state_file: str | Path, timeout: float = 300.0) -> dict:
    path=Path(state_file)
    try:state=json.loads(path.read_text(encoding="utf-8",errors="replace"))
    except Exception as e:return {"restored":False,"error":f"cannot read handoff state: {e}"}
    if not _generation_current(state):
        _mark_handoff_done(state,"stale-generation");return {"restored":False,"stale_generation":True}
    try:
        pid=_start_qwen_command(str(state.get("command_line") or ""),str(state.get("cwd") or root_dir()),timeout=timeout,state=state)
        if not _wait_handoff_ready(state, timeout):
            _mark_handoff_done(state,"stale-generation");return {"restored":False,"stale_generation":True}
        _mark_handoff_done(state,"watchdog-restored");_clear_generation_if_current(state);_qwen_handoff_log(f"RECOVERY v15.134c restored/adopted Qwen pid={pid}")
        return {"restored":True,"ready":True,"pid":pid,"already_running":bool(_listener_identity().get("open"))}
    except Exception as e:
        _qwen_handoff_log(f"RECOVERY FAILED v15.134c: {e}");return {"restored":False,"error":str(e)}

def _one_status(name: str) -> dict:
    port = SERVICES[name]["port"]
    ready = port_open(port)
    managed_pid = _managed_pid(name) if name != "qwen" else None
    process_running = ready or bool(managed_pid)

    sleeping = False
    if name == "qwen" and ready:
        props = qwen_props()
        if isinstance(props, dict):
            sleeping = bool(props.get("is_sleeping", False))

    if name == "qwen" and sleeping:
        state = "sleeping"
    elif ready:
        state = "ready"
    elif process_running:
        state = "starting"
    else:
        state = "stopped"

    result = {
        "state": state,
        "running": ready,
        "ready": ready and not sleeping,
        "healthy": ready,
        "process_running": process_running,
        "port": port,
    }

    if name == "qwen":
        result["sleeping"] = sleeping

    if managed_pid:
        result["launcher_pid"] = managed_pid
    lp = _state_log_path(name) if name != "qwen" else None
    if lp:
        result["log_path"] = str(lp)
    return result


def status(name: str | None = None) -> dict:
    # PORTABLEAI_SCIENCE_STATUS_v15_130a_BEGIN
    if isinstance(name, str) and name.strip().lower() == "science":
        return {"science": science_lifecycle_metadata()}
    # PORTABLEAI_SCIENCE_STATUS_v15_130a_END
    names = ["qwen", "comfyui", "acestep"] if name in (None, "all") else [normalize_service(name)]
    return {n: _one_status(n) for n in names}



def launch_detached(command_line: str, cwd: Path | str) -> int:
    """Start a long-lived PortableAI worker without PowerShell or WMI.

    v15.28 promotes the already-tested direct Windows subprocess path to the
    primary launcher. This removes the AV-hostile chain of hidden PowerShell +
    the legacy shell-wrapper process-launch chain. The worker
    still receives the same command line, working directory, hidden-console
    behavior, PID tracking, readiness checks, and watchdog recovery semantics.
    """
    if os.name!='nt':
        from linux_process import launch
        return launch(command_line,cwd)
    return _launch_direct_hidden(command_line, cwd)


def _launch_comfyui_direct() -> int:
    """Launch and track the actual ComfyUI Python worker, not run_nvidia_gpu.bat."""
    from profile_paths import enabled, private_path
    directory_args = []
    if enabled(root_dir()):
        for label in ('input', 'output', 'temp', 'user'):
            path = private_path(root_dir(), 'Generative/ComfyUI_windows_portable/ComfyUI/' + label)
            path.mkdir(parents=True, exist_ok=True)
            directory_args += ['--' + label + '-directory', str(path)]
    if os.name != "nt":
        from platform_runtime import python_path
        from linux_process import launch
        root=root_dir();policy=tool_plan('comfyui');work=root/'Generative/ComfyUI_windows_portable'
        require_space(root,for_outputs=True)
        pid=launch([str(python_path(root)),'-B','-I',str(root/'Agent/comfy_amd_entry.py'),
                    '--disable-auto-launch','--listen','127.0.0.1',*policy['args'],*directory_args],work,
                   name='comfyui',extra_env={'PORTALAI_TORCH_BACKEND':policy['backend']})
        _remember_pid('comfyui',pid,str(_log_path('comfyui')))
        return pid

    name = "comfyui"
    svc = SERVICES[name]
    root = root_dir()
    work = (root / svc["cwd"]).resolve()
    python_exe = (work / svc["python"]).resolve()
    main_py = (work / svc["main"]).resolve()
    policy = tool_plan("comfyui")
    if policy["backend"] == "rocm":
        python_exe = root/"Runtime/BootstrapPython/python.exe"
        main_py = root/"Agent/comfy_amd_entry.py"

    if not python_exe.exists():
        raise FileNotFoundError(f"ComfyUI embedded Python not found: {python_exe}")
    if not main_py.exists():
        raise FileNotFoundError(f"ComfyUI main.py not found: {main_py}")

    log = _log_path(name)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"=== PortableAI {name} direct service start {time.ctime()} [service-manager v14.9] ===\n"
            f"cwd: {work}\n"
            f"python: {python_exe}\n"
            f"main: {main_py}\n"
            "launch: native subprocess CREATE_NO_WINDOW -> embedded python -> ComfyUI/main.py --windows-standalone-build --disable-auto-launch\n\n"
            "Note: v13 launches ComfyUI directly so the tracked PID is the real "
            "long-lived Python process. Console output is not redirected by the "
            "Windows detached launcher; use the service state/port for readiness.\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    # Direct subprocess launch returns the PID of python.exe itself here, so
    # wait_ready() watches the real worker rather than a transient wrapper.
    command_line = (
        f'"{python_exe}" -s "{main_py}" --windows-standalone-build --disable-auto-launch'
    )
    require_space(root, for_outputs=True)
    command_line += " " + subprocess.list2cmdline([*policy["args"], *directory_args])
    pid = launch_detached(command_line, work)
    _remember_pid(name, pid, str(log))
    return pid



def _launch_acestep_direct() -> int:
    """Launch ACE-Step with its bundled embedded Python; never require uv/.venv."""
    if os.name != "nt":
        raise RuntimeError("PortableAI service launch management is currently configured for Windows.")
    policy = tool_plan("acestep")
    if policy["backend"] == "unavailable":
        raise RuntimeError(policy["warning"])
    require_space(root_dir(), for_outputs=True)

    name = "acestep"
    svc = SERVICES[name]
    root = root_dir()
    work = (root / svc["cwd"]).resolve()

    python_exe = None
    checked = []
    for rel in svc.get("python_candidates", []):
        cand = (work / rel).resolve()
        checked.append(str(cand))
        if cand.exists():
            python_exe = cand
            break

    if python_exe is None:
        raise FileNotFoundError(
            "ACE-Step embedded Python was not found. Checked: " + "; ".join(checked)
        )

    entry = (root / svc["entry"]).resolve()
    if not entry.exists():
        raise FileNotFoundError(f"PortableAI ACE-Step entry helper not found: {entry}")

    api_py = work / "acestep" / "api_server.py"
    if not api_py.exists():
        raise FileNotFoundError(f"ACE-Step api_server.py not found: {api_py}")

    log = _log_path(name)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"=== PortableAI ACE-Step direct service start {time.ctime()} "
            f"[service-manager {SERVICE_MANAGER_VERSION}] ===\\n"
            f"cwd: {work}\\n"
            f"python: {python_exe}\\n"
            "launch: native subprocess CREATE_NO_WINDOW -> ACE-Step embedded Python -> "
            "Agent/acestep_embedded_entry.py -> acestep.api_server\\n"
            "uv/.venv: intentionally bypassed\\n\\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    command_line = subprocess.list2cmdline([
        str(python_exe),
        "-u",
        str(entry),
        "--work", str(work),
        "--log", str(log),
        "--host", "127.0.0.1",
        "--port", str(SERVICES[name]["port"]),
    ])
    pid = launch_detached(command_line, work)
    _remember_pid(name, pid, str(log))
    return pid


def _launch_bat(name: str) -> int:
    """Generic detached BAT launcher retained for ACE-Step."""
    if os.name != "nt":
        raise RuntimeError("PortableAI service launch management is currently configured for Windows.")

    svc = SERVICES[name]
    root = root_dir()
    work = (root / svc["cwd"]).resolve()
    bat = work / svc["launcher"]

    if not bat.exists():
        raise FileNotFoundError(f"Launcher not found: {bat}")

    log = _log_path(name)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            f"=== PortableAI {name} service start {time.ctime()} ===\n"
            f"cwd: {work}\nlauncher: {bat}\n\n",
            encoding="utf-8",
        )
    except Exception:
        pass

    command_line = (
        f'cmd.exe /d /s /c "call ""{bat}"" >> ""{log}"" 2>&1"'
    )
    pid = launch_detached(command_line, work)
    _remember_pid(name, pid, str(log))
    return pid


def _launch_service(name: str) -> int:
    if name == "comfyui":
        return _launch_comfyui_direct()
    if name == "acestep":
        return _launch_acestep_direct()
    return _launch_bat(name)


def start(name: str) -> dict:
    """
    Launch a worker if necessary and RETURN QUICKLY.

    This intentionally does not block through model initialization. Media commands
    call wait_ready() themselves, so OpenGUI does not sit on a long 'service start'
    command that looks frozen.
    """
    name = normalize_service(name)

    if name == "all":
        raise RuntimeError(
            "Starting all GPU workers simultaneously is disabled. PortableAI uses "
            "serialized GPU activation; start only the worker you need."
        )

    if name in ("comfyui", "acestep"):
        # Enforce exclusivity even for Control Center/manual starts. Starting one
        # persistent GPU service always evicts the other first.
        quiesce_gpu_workers(name)

    if name == "qwen":
        raise RuntimeError(
            "Qwen is the active chat model. Start it with the PortableAI launcher, "
            "not from media service management."
        )

    current = _one_status(name)
    if current["ready"]:
        return {
            "service": name,
            "state": "ready",
            "running": True,
            "already_running": True,
        }

    pid = _managed_pid(name)
    if pid:
        return {
            "service": name,
            "state": "starting",
            "running": False,
            "process_running": True,
            "launcher_pid": pid,
            "already_starting": True,
        }

    pid = _launch_service(name)

    # Give very fast services a moment to bind, but never make start() a long wait.
    time.sleep(0.75)
    now = _one_status(name)
    return {
        "service": name,
        "state": now["state"],
        "running": now["ready"],
        "process_running": now["process_running"],
        "launcher_pid": pid,
        "already_running": False,
    }


def wait_ready(name: str, timeout: float | None = None) -> dict:
    """
    Wait until the service's localhost API port is actually listening.

    If the service is stopped, launch it first. If it is already starting, attach
    to that existing launch instead of creating a duplicate process.
    """
    name = normalize_service(name)
    if name == "all":
        return {n: wait_ready(n, timeout=timeout) for n in ("comfyui", "acestep")}

    if name == "qwen":
        deadline = time.time() + float(timeout or 300)
        while time.time() < deadline:
            if port_open(SERVICES[name]["port"]):
                return {"service": name, "state": "ready", "running": True}
            time.sleep(1)
        raise TimeoutError(("Qwen did not become ready on port 8080 before timeout.").replace('port 8080', 'port '+str(_instance_port('qwen'))))

    if not port_open(SERVICES[name]["port"]):
        start(name)

    svc = SERVICES[name]
    limit = float(timeout if timeout is not None else svc.get("start_timeout", 600))
    deadline = time.time() + limit

    while time.time() < deadline:
        if port_open(svc["port"]):
            return {
                "service": name,
                "state": "ready",
                "running": True,
                "port": svc["port"],
            }

        # v13 tracks the real ComfyUI python.exe PID. If that PID dies before the
        # API opens, the worker itself really exited; this is no longer a false
        # failure caused by run_nvidia_gpu.bat/cmd.exe ending.
        managed = _managed_pid(name)
        if not managed:
            log = _state_log_path(name) or _log_path(name)
            tail = _tail_text(log)
            subject = "worker" if name == "comfyui" else "launcher"
            msg = (
                f"{name} {subject} exited before port {svc['port']} became ready. "
                f"Startup log: {log}"
            )
            if tail:
                msg += "\n\nStartup metadata/log output:\n" + tail
            raise RuntimeError(msg)

        time.sleep(2)

    st = _one_status(name)
    log = _state_log_path(name) or _log_path(name)
    tail = _tail_text(log)
    msg = (
        f"{name} did not open port {svc['port']} within {int(limit)} seconds. "
        f"Current state: {st['state']}. Startup log: {log}"
    )
    if tail:
        msg += "\n\nLast startup log output:\n" + tail
    raise TimeoutError(msg)


def stop(name: str) -> dict:
    name = normalize_service(name)

    if name == "all":
        return {n: stop(n) for n in ("comfyui", "acestep")}

    if name == "qwen":
        raise RuntimeError(
            "Refusing to stop Qwen from an active agent session. "
            "Stop it externally after the chat is finished."
        )

    port = SERVICES[name]["port"]
    pids = set(_listening_pids(port))

    managed = _managed_pid(name)
    if managed:
        pids.add(managed)

    if not pids:
        _forget_pid(name)
        return {
            "service": name,
            "state": "stopped",
            "running": False,
            "already_stopped": True,
        }

    killed = []
    for pid in sorted(pids):
        if os.name!='nt':
            from linux_process import identity, owned, stop as stop_owned
            try:
                row=identity(pid)
                record_path=root_dir()/'Agent/.runtime'/f'linux-{name}.json'
                record=json.loads(record_path.read_text()) if record_path.is_file() else None
                if not owned(row,root_dir()) or row!=record:
                    raise RuntimeError('Refusing to stop an unregistered Linux service listener')
                stop_owned(row,root_dir());killed.append(pid)
            except (FileNotFoundError,ProcessLookupError):pass
            continue
        cp = _run_hidden(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            errors="replace",
        )
        if cp.returncode == 0:
            killed.append(pid)

    deadline = time.time() + 25
    while time.time() < deadline and port_open(port):
        time.sleep(0.5)

    _forget_pid(name)

    if port_open(port):
        raise RuntimeError(f"{name} is still listening on port {port} after taskkill.")

    return {
        "service": name,
        "state": "stopped",
        "running": False,
        "killed_pids": killed,
    }
