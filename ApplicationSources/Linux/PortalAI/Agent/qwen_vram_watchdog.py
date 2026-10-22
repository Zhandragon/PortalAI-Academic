from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

VERSION = "15.134c"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            cp = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, errors="replace", timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
            out = (cp.stdout or "").strip()
            return cp.returncode == 0 and out and "No tasks are running" not in out
        except Exception:
            return False
    try:
        state=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]
        return state!='Z'
    except (OSError,IndexError):
        return False


def _log(root: Path, message: str) -> None:
    p = root / "Agent" / ".runtime" / "qwen_handoff.log"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8", errors="replace") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} WATCHDOG v{VERSION} {message}\n")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI hardened Qwen VRAM recovery watchdog")
    ap.add_argument("--owner-pid", type=int, required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--marker", required=True)
    ap.add_argument("--generation", default="")
    ap.add_argument("--ready", help="Linux acknowledgement after leaving the owner's worker cgroup")
    ap.add_argument("--poll", type=float, default=1.0)
    ap.add_argument("--ttl", type=float, default=21600.0, help="Maximum watchdog lifetime; default 6 h")
    ns = ap.parse_args()
    owner_start = None
    if os.name!='nt':
        try:owner_start=Path(f'/proc/{ns.owner_pid}/stat').read_text().rsplit(')',1)[1].split()[19]
        except OSError:pass

    state_path = Path(ns.state).resolve()
    marker = Path(ns.marker).resolve()
    root = state_path.parents[2] if len(state_path.parents) >= 3 else Path.cwd()
    if os.name!='nt':
        sys.path.insert(0,str(root/'Agent'))
        from linux_job import move_to_guardians
        from linux_process import identity
        from runtime_policy import atomic_json
        group=move_to_guardians()
        if ns.ready:
            ready=Path(ns.ready).resolve()
            if ready!=state_path.with_suffix('.ready'):
                raise RuntimeError('Unexpected Linux watchdog acknowledgement path')
            row=identity(os.getpid())
            atomic_json(ready,{'pid':row['pid'],'start_ticks':row['start_ticks'],
                'group':str(group),'generation':ns.generation})
    started = time.monotonic()
    _log(root, f"armed owner={ns.owner_pid} state={state_path.name} generation={ns.generation or '?'}")

    while True:
        if marker.exists():
            _log(root, "disarmed by completion marker")
            return 0
        same_owner = _pid_alive(ns.owner_pid)
        if os.name!='nt' and same_owner:
            try:same_owner=owner_start is not None and Path(f'/proc/{ns.owner_pid}/stat').read_text().rsplit(')',1)[1].split()[19]==owner_start
            except OSError:same_owner=False
        if not same_owner:
            break
        if time.monotonic() - started >= max(300.0, float(ns.ttl)):
            _log(root, "TTL reached while owner still alive; exiting without restoring Qwen")
            return 4
        time.sleep(max(0.25, float(ns.poll)))

    # The owner disappeared without completing its normal finally path. Ask the
    # service manager to perform exactly one generation-gated recovery. That
    # function owns the cross-process mutex and refuses to launch a duplicate
    # when anything is already listening on :8080.
    try:
        sys.path.insert(0, str(root / "Agent"))
        import service_manager  # type: ignore
        result = service_manager.qwen_gpu_handoff_recover(state_path, timeout=300.0)
        _log(root, "owner exited; recovery result=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if bool(result.get("restored")) or bool(result.get("already_running")) or bool(result.get("stale_generation")) else 3
    except Exception as exc:
        _log(root, f"recovery exception {type(exc).__name__}: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
