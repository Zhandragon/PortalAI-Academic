"""Verify actual watchdog recovery when a handoff owner exits before restoration."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from ai_tools import acquire_gpu_lease, release_gpu_lease, quiesce_gpu_workers
from runtime_policy import atomic_json, portable_env
from service_manager import _listener_identity, _qwen_health_ready, qwen_gpu_handoff_recover


def main():
    before = _listener_identity()
    if not before["portable_qwen"]: raise RuntimeError("Start the owned chat server first")
    lease = acquire_gpu_lease("watchdog-recovery-smoke")
    state = None; report = {"before": before}; started = time.monotonic()
    try:
        quiesce_gpu_workers(None)
        code = "import os,json,sys; sys.path.insert(0,'Agent'); from service_manager import qwen_gpu_handoff_begin; print(json.dumps(qwen_gpu_handoff_begin('watchdog-recovery-smoke')),flush=True); os._exit(23)"
        child = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=portable_env(ROOT),
                               text=True, capture_output=True, timeout=60,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        state = json.loads(child.stdout)
        if child.returncode != 23 or not state.get("active"):
            raise RuntimeError("Fixture failed to exit after its owned handoff: " + child.stderr)
        report["state"] = state
        marker = Path(state["marker_path"])
        deadline = time.monotonic()+360
        while time.monotonic() < deadline and not marker.exists(): time.sleep(.5)
        after = _listener_identity()
        ready = _qwen_health_ready()
        report.update(after=after, ready_at_marker=ready,
                      marker=marker.read_text() if marker.exists() else None,
                      elapsed_seconds=round(time.monotonic()-started, 2))
        report["passed"] = bool(ready and report["marker"] == "watchdog-restored" and
                                 before["listeners"][0]["pid"] in state.get("killed_pids", []) and
                                 after["listeners"] and before["listeners"][0]["command_line"] == after["listeners"][0]["command_line"])
    except Exception as exc:
        report.update(passed=False, error=f"{type(exc).__name__}: {exc}")
    finally:
        if state and not Path(state["marker_path"]).exists():
            report["cleanup_recovery"] = qwen_gpu_handoff_recover(state["state_path"])
        release_gpu_lease(lease)
        atomic_json(ROOT/"Maintenance/Reports/handoff-watchdog-recovery.json", report)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
