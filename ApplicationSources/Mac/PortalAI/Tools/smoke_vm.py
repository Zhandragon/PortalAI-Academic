"""Exercise actual hardware-backed VM execution, persistence and cancellation."""
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import atomic_json
from vm_runner import preflight, run_command
from mission_runner import Missions

def main():
    folder = ROOT / "Data/VMTests" / uuid.uuid4().hex
    report = {"preflight": preflight(), "state_folder": str(folder), "checks": []}
    def check(name, condition, evidence):
        report["checks"].append({"name": name, "passed": bool(condition), "evidence": evidence})
        atomic_json(ROOT / "Maintenance/Reports/vm-smoke.json", report)
        if not condition:
            raise AssertionError(name)
    r = run_command("printf 42 > answer.txt; id; uname -s", folder)
    check("hardware-backed unprivileged guest", r["exit_code"] == 0 and "uid=1000" in r["output"] and "Linux" in r["output"], r)
    r = run_command("test \"$(cat answer.txt)\" = 42 && echo WORKSPACE_RESTORED", folder)
    check("workspace survives a fresh guest", r["exit_code"] == 0 and "WORKSPACE_RESTORED" in r["output"], r)
    r = run_command("test \"$(ls /sys/class/net)\" = lo && echo OFFLINE; test ! -e /mnt/c && test ! -e /mnt/d && echo NO_DRIVE_MOUNTS; if (echo bad > /init) 2>/dev/null; then exit 9; else echo ROOT_WRITE_DENIED; fi", folder)
    check("network, mounts and guest permissions", r["exit_code"] == 0 and all(s in r["output"] for s in ("OFFLINE", "NO_DRIVE_MOUNTS", "ROOT_WRITE_DENIED")), r)
    r = run_command("if dd if=/dev/zero of=too-large.bin bs=1M count=12 2>/dev/null; then rm too-large.bin; exit 9; else rm -f too-large.bin; echo WORKSPACE_CAPPED; fi", folder)
    check("guest filesystem has a hard capacity", r["exit_code"] == 0 and "WORKSPACE_CAPPED" in r["output"], r)
    before = hashlib.sha256((folder / "workspace.tar").read_bytes()).hexdigest()
    stop = folder / "STOP"
    timer = threading.Timer(2.5, stop.touch)
    timer.start()
    started = time.monotonic()
    try:
        run_command("sleep 30; echo should-not-finish > late.txt", folder, stop=stop)
        cancelled = False
    except RuntimeError as e:
        cancelled = "stopped by user" in str(e)
    finally:
        timer.cancel()
        timer.join()
        stop.unlink(missing_ok=True)
    check("cancellation preserves prior workspace", cancelled and time.monotonic()-started < 12 and
          hashlib.sha256((folder / "workspace.tar").read_bytes()).hexdigest() == before,
          {"cancelled": cancelled, "elapsed_seconds": round(time.monotonic()-started, 2)})
    store = Missions()
    m = store.create("Self-test the offline VM. Use shell to check id and uname, write the text portal-vm-ok to /workspace/probe.txt. In a SEPARATE later shell action read probe.txt to verify it persisted across a guest reboot, and check that only lo exists in /sys/class/net. Then complete with the actual findings. Do not use host tools.", "vm", max_steps=6)
    m = store.run(m["id"], steps=6)
    check("local model independently uses the VM", m["status"] == "complete" and
          sum(h["action"]["action"] == "shell" for h in m["history"]) >= 2,
          {"mission": m["id"], "status": m["status"], "steps": m["steps"], "history": m["history"], "error": m.get("error")})
    report["passed"] = True
    atomic_json(ROOT / "Maintenance/Reports/vm-smoke.json", report)
    print(json.dumps({"passed": True, "checks": len(report["checks"]), "mission": m["id"]}))

if __name__ == "__main__":
    main()
