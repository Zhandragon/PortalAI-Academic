#!/usr/bin/env python3
"""Focused post-install checks that must run on the recipient Mac."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "Runtime/MacPackages/gui"),
               str(ROOT / "Runtime/AccountPython/macos-packages"), str(ROOT / "Agent")]


def main() -> int:
    if sys.platform != "darwin" or sys.version_info[:2] != (3, 12):
        raise RuntimeError("The PortalAI Mac smoke suite requires its bundled macOS Python 3.12")
    import tkinter
    import PIL
    import psutil
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from local_accounts import _crypto
    from mission_accounts import activate
    import mission_schedule
    import mission_supervisor
    import runtime_policy
    from mission_supervisor import WorkerJob
    from platform_runtime import python_path, worker_process_options

    total, available = runtime_policy.memory_info()
    if total <= 0 or available <= 0:
        raise RuntimeError("macOS memory accounting did not return positive values")
    if not Path(python_path(ROOT)).is_file():
        raise RuntimeError("Bundled macOS Python path is invalid")
    if hasattr(mission_schedule, "Schedules") is False:
        raise RuntimeError("Mission schedule API is not available")
    if hasattr(mission_supervisor, "Supervisor") is False:
        raise RuntimeError("Mission supervisor API is not available")
    aes, _ = _crypto()
    activate(ROOT)
    if aes is not AESGCM:
        raise RuntimeError("Account cryptography did not load from the local Mac runtime")
    if tkinter.Tcl().eval("info patchlevel") == "":
        raise RuntimeError("Tcl runtime did not initialize")
    if not PIL.__version__ or not psutil.__version__:
        raise RuntimeError("Portable GUI dependencies did not initialize")

    server = ROOT / "LLM/backends/macos-metal/bin/llama-server"
    if not server.is_file():
        raise RuntimeError("Compiled Metal-capable llama-server is missing")
    check = subprocess.run([str(server), "--version"], cwd=ROOT,
                           capture_output=True, text=True, timeout=45)
    if check.returncode:
        raise RuntimeError("llama-server did not pass its version smoke check")

    child = subprocess.Popen([str(python_path(ROOT)), "-I", "-c", "import time; time.sleep(90)"],
                             cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **worker_process_options())
    job = None
    try:
        job = WorkerJob(child)
        job.limit_memory(512 * 1024**2)
        job.check()
        time.sleep(0.4)
        job.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise RuntimeError("macOS worker Stop left its process group running")
        if child.returncode == 0:
            raise RuntimeError("macOS worker lifetime test completed without cancellation")
    finally:
        if job and job.handle:
            job.close()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)

    result = {"passed": True, "macOS": platform.mac_ver()[0], "architecture": platform.machine(),
              "python": platform.python_version(), "available_memory_bytes": available,
              "tcl": tkinter.Tcl().eval("info patchlevel"), "pillow": PIL.__version__,
              "psutil": psutil.__version__, "llama_server": (check.stdout or check.stderr).strip(),
              "worker_stop": "passed", "physical_install_tested": True}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        print(f"PortalAI macOS smoke test: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
