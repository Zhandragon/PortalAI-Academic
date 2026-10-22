"""macOS process identity and managed service helpers for PortalAI-owned jobs."""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import signal
import subprocess
import time

from runtime_policy import ROOT, atomic_json, portable_env


def _psutil():
    packages = ROOT / "Runtime/MacPackages/gui"
    import sys
    if packages.is_dir() and str(packages) not in sys.path:
        sys.path.insert(0, str(packages))
    import psutil
    return psutil


def identity(pid: int) -> dict:
    psutil = _psutil()
    proc = psutil.Process(int(pid))
    return {"pid": proc.pid, "create_time": proc.create_time(),
            "uid": proc.uids().real, "executable": str(Path(proc.exe()).resolve()),
            "argv": proc.cmdline(), "process_group": os.getpgid(proc.pid)}


def owned(row: dict, root=ROOT) -> bool:
    try:
        return int(row["uid"]) == os.getuid() and Path(row["executable"]).resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError, KeyError, TypeError):
        return False


def is_llama(row: dict, root=ROOT) -> bool:
    if not owned(row, root):
        return False
    executable = Path(row["executable"]).resolve()
    return executable.name == "llama-server" and executable.is_relative_to((Path(root).resolve() / "LLM"))


def stop(row: dict, root=ROOT) -> None:
    if int(row.get("pid", -1)) == os.getpid():
        raise RuntimeError("Refusing to stop the PortalAI controller")
    current = identity(int(row["pid"]))
    if current != row or not owned(current, root):
        raise RuntimeError("macOS process identity changed; refusing to stop it")
    pgid = int(current["process_group"])
    if pgid != int(current["pid"]):
        raise RuntimeError("Managed macOS service no longer owns its process group")
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return


def listeners(port: int) -> list[int]:
    psutil = _psutil()
    result = set()
    try:
        rows = psutil.net_connections(kind="tcp")
    except psutil.AccessDenied as exc:
        raise RuntimeError("macOS denied access to local TCP listener ownership") from exc
    for row in rows:
        if row.status != psutil.CONN_LISTEN or not row.laddr or row.laddr.port != int(port) or not row.pid:
            continue
        try:
            if int(identity(row.pid)["uid"]) == os.getuid():
                result.add(int(row.pid))
        except (psutil.Error, OSError, ValueError):
            continue
    return sorted(result)


def launch(command, cwd=ROOT, name=None, extra_env=None) -> int:
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    if not argv or not Path(argv[0]).resolve().is_relative_to(Path(ROOT).resolve()):
        raise RuntimeError("Service executable is outside the portable root")
    env = portable_env(ROOT)
    env.pop("DYLD_LIBRARY_PATH", None)
    if extra_env:
        env.update(extra_env)
    from media_paths import media_runtime
    log = media_runtime(ROOT) / f"macos-{name or 'worker'}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as output:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=output, close_fds=True,
                                   start_new_session=True)
    deadline = time.monotonic() + 8
    while True:
        try:
            row = identity(process.pid)
            if owned(row, ROOT) and row["process_group"] == process.pid:
                break
        except (OSError, ValueError):
            pass
        if process.poll() is not None or time.monotonic() >= deadline:
            raise RuntimeError("PortalAI service did not establish an owned macOS process group")
        time.sleep(0.05)
    if name:
        atomic_json(ROOT / "Agent/.runtime" / f"macos-{name}.json", row)
    return process.pid
