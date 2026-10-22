from __future__ import annotations
import argparse, sys, time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--opengui-path", required=True)
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    opengui = Path(ns.opengui_path).resolve()
    sys.path.insert(0, str(root / "ControlCenter"))
    from portableai_common import hidden_popen, log_line, process_named, pythonw_executable, runtime_dir

    log = runtime_dir(root) / "portableai_lifecycle.log"
    log_line(log, "Lifecycle watcher AV-clean Python version started.")
    deadline = time.time() + 90
    seen = False
    while time.time() < deadline:
        if process_named("OpenGUI.exe", opengui):
            seen = True; break
        time.sleep(1)
    if not seen:
        log_line(log, "OpenGUI was not detected within 90 seconds. Failsafe: leaving backends running.")
        return 0

    log_line(log, "OpenGUI detected; waiting for it to close.")
    misses = 0
    while True:
        if process_named("OpenGUI.exe", opengui):
            misses = 0
        else:
            misses += 1
            if misses >= 5: break
        time.sleep(1)

    log_line(log, "OpenGUI absent for 5 consecutive checks; stopping PortableAI backends.")
    stop = root / "Launchers" / "Stop_PortableAI.py"
    if stop.exists():
        try:
            p = hidden_popen([pythonw_executable(), str(stop), "--root", str(root), "--quiet"], cwd=root)
            p.wait(timeout=60)
        except Exception as exc:
            log_line(log, f"Stop helper failed: {exc}")
    log_line(log, "Lifecycle watcher finished.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
