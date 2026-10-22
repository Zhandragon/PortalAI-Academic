"""Best-effort macOS worker lifetime ownership using isolated process groups.

This is cancellation and sampled memory monitoring, not an OS sandbox. A
process that deliberately leaves its process group can escape these controls.
"""
from __future__ import annotations

import errno
import os
import select
import signal
import subprocess
import sys
import time
from pathlib import Path


def _kill_group(pgid: int) -> None:
    if type(pgid) is not int or pgid <= 1:
        raise RuntimeError("Refusing an invalid macOS worker process group")
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _group_rss(pgid: int) -> int:
    root = Path(__file__).resolve().parents[1]
    packages = root / "Runtime/MacPackages/gui"
    if packages.is_dir() and str(packages) not in sys.path:
        sys.path.insert(0, str(packages))
    import psutil

    total = 0
    for proc in psutil.process_iter(("pid",)):
        try:
            if os.getpgid(proc.info["pid"]) == pgid:
                total += proc.memory_info().rss
        except (OSError, ProcessLookupError, psutil.Error):
            continue
    return total


def guardian(pgid: int) -> None:
    """Stay outside the worker group and kill it if its controller disappears."""
    if pgid <= 1 or pgid == os.getpgrp():
        raise RuntimeError("Refusing to monitor this process group")
    limit = None
    print("READY", flush=True)
    stream = sys.stdin.buffer
    while True:
        readable, _, _ = select.select([stream], [], [], 0.25)
        if readable:
            line = stream.readline(128)
            if not line:
                _kill_group(pgid)
                return
            if line == b"release\n":
                return
            if line == b"cancel\n":
                _kill_group(pgid)
                return
            if line.startswith(b"limit "):
                value = line[6:].strip()
                if not value.isdigit() or not 256 * 1024**2 <= int(value) <= 1024**5:
                    raise ValueError("Invalid macOS worker memory ceiling")
                limit = int(value)
            else:
                raise ValueError("Unexpected macOS guardian command")
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return
        except PermissionError:
            return
        if limit is not None and _group_rss(pgid) > limit:
            _kill_group(pgid)
            return


class MacJob:
    """Own one start_new_session worker and monitor it from an EOF guardian."""

    def __init__(self, process: subprocess.Popen):
        if sys.platform != "darwin":
            raise RuntimeError("macOS worker ownership requires Darwin")
        if process.poll() is not None:
            raise RuntimeError("Worker exited before macOS lifetime ownership")
        try:
            pgid = os.getpgid(process.pid)
        except OSError as exc:
            raise RuntimeError("Cannot identify the worker process group") from exc
        if pgid != process.pid:
            raise RuntimeError("macOS workers must start in a new session before their start gate opens")
        self.process = process
        self.pgid = pgid
        self.guardian = None
        self.handle = True
        try:
            root = Path(__file__).resolve().parents[1]
            self.guardian = subprocess.Popen(
                [str(root / "Runtime/MacPython/bin/python3.12"), "-B", "-I",
                 str(Path(__file__).resolve()), "guard", str(pgid)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True,
                env={**os.environ, "PORTALAI_ROOT": str(root)},
            )
            if not select.select([self.guardian.stdout], [], [], 8)[0] or self.guardian.stdout.readline() != b"READY\n":
                raise RuntimeError("macOS worker guardian did not become ready")
            self.guardian.stdout.close()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        if self.handle and self.guardian and self.guardian.poll() is not None:
            raise RuntimeError("macOS worker guardian exited unexpectedly")

    def limit_memory(self, size: int) -> None:
        if type(size) is not int or size < 256 * 1024**2:
            raise ValueError("Invalid worker memory ceiling")
        if not self.handle or not self.guardian or self.guardian.poll() is not None:
            raise RuntimeError("macOS worker guardian is unavailable")
        self.guardian.stdin.write(f"limit {size}\n".encode("ascii"))
        self.guardian.stdin.flush()

    def close(self, completed: bool = False) -> None:
        if not self.handle:
            return
        try:
            if self.guardian and self.guardian.poll() is None:
                try:
                    self.guardian.stdin.write(b"release\n" if completed else b"cancel\n")
                    self.guardian.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                finally:
                    self.guardian.stdin.close()
                try:
                    self.guardian.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    if not completed:
                        _kill_group(self.pgid)
                    self.guardian.kill()
                    self.guardian.wait(timeout=5)
            if not completed:
                _kill_group(self.pgid)
        finally:
            self.handle = False


def preflight() -> dict:
    if sys.platform != "darwin":
        raise RuntimeError("macOS worker ownership requires Darwin")
    if os.geteuid() == 0:
        raise RuntimeError("Run PortalAI as a regular macOS user, not root")
    return {"backend": "macos-process-group", "sampled_memory_monitor": True,
            "os_sandbox": False, "strict_memory_limit": False}


if __name__ == "__main__" and len(sys.argv) == 3 and sys.argv[1] == "guard":
    guardian(int(sys.argv[2]))
