from __future__ import annotations

import argparse
import csv
import os
import subprocess
import time
from pathlib import Path

CREATE_NO_WINDOW = getattr(
    subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0
)


def run_hidden(args, **kwargs):
    if os.name == "nt":
        kwargs.setdefault("creationflags", CREATE_NO_WINDOW)
    return subprocess.run(args, **kwargs)


def pid_alive(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    cp = run_hidden(
        ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
        capture_output=True, text=True, errors="replace"
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
            except Exception:
                pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-pid", type=int, required=True)
    ap.add_argument("--child-pid", type=int, required=True)
    ap.add_argument("--marker", required=True)
    args = ap.parse_args()
    marker = Path(args.marker)

    while pid_alive(args.owner_pid):
        if marker.exists():
            try:
                marker.unlink()
            except OSError:
                pass
            return
        time.sleep(0.5)

    if marker.exists():
        try:
            marker.unlink()
        except OSError:
            pass
        return

    # OpenGUI killed the active ai_tools command. Terminate the isolated TTS
    # worker so it does not keep the GPU occupied in the background.
    if os.name == "nt" and pid_alive(args.child_pid):
        run_hidden(
            ["taskkill", "/PID", str(args.child_pid), "/T", "/F"],
            capture_output=True, text=True, errors="replace"
        )


if __name__ == "__main__":
    main()
