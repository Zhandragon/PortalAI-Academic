from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import csv
import os
import subprocess
import time
import urllib.request
from pathlib import Path

from service_manager import stop as service_stop


def pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    cp = subprocess.run(
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


def interrupt_comfyui():
    req = urllib.request.Request(
        _instance_url('comfyui', '/interrupt'),
        data=b"",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-pid", type=int, required=True)
    ap.add_argument("--target", choices=["comfyui", "acestep"], required=True)
    ap.add_argument("--marker", required=True)
    args = ap.parse_args()

    marker = Path(args.marker)

    # Give the parent a chance to create/finish normally. The watchdog itself was
    # launched outside OpenGUI's shell process tree.
    while pid_alive(args.owner_pid):
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
            return
        time.sleep(0.75)

    # Parent vanished without writing the completion marker: this is the pattern
    # produced when OpenGUI aborts/kills the active shell tool.
    if marker.exists():
        try:
            marker.unlink()
        except OSError:
            pass
        return

    if args.target == "comfyui":
        # Graceful generation interrupt first, then stop the worker so GPU memory
        # is not left loaded after the user explicitly pressed Stop.
        interrupt_comfyui()
        time.sleep(1.0)
        try:
            service_stop("comfyui")
        except Exception:
            pass

    elif args.target == "acestep":
        # ACE-Step 1.5's documented HTTP API has task submit/query/download but no
        # documented per-task cancellation endpoint. A user abort therefore uses
        # a hard worker stop to actually halt GPU generation.
        try:
            service_stop("acestep")
        except Exception:
            pass


if __name__ == "__main__":
    main()
