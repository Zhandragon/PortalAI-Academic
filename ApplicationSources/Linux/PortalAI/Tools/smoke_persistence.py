"""Real process restart/crash tests in isolated SSD folders; no live model needed."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_runner import Missions
from mission_supervisor import arm, disarm
from runtime_policy import atomic_json, portable_env


def wait_for(predicate, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if predicate(): return
        time.sleep(.05)
    raise TimeoutError("Persistence smoke condition timed out")


def main():
    base = ROOT/"Maintenance/Reports/persistence-tests"/uuid.uuid4().hex
    base.mkdir(parents=True)
    report = {"test_root": str(base), "checks": [], "uses_test_worker": True}
    processes = []; logs = []
    def case(name):
        root = base/name; (root/"Agent").mkdir(parents=True)
        atomic_json(root/"Agent/hardware_profiles.json", {"storage": {"minimum_free_gib": 1, "minimum_free_fraction": .01, "output_reserve_gib": 0}})
        store = Missions(root); m = store.create(name, max_steps=4); arm(root, m["id"])
        return root, store, m["id"]
    def launch(root, seconds):
        log = (root/("controller-"+uuid.uuid4().hex[:8]+".log")).open("wb"); logs.append(log)
        p = subprocess.Popen([sys.executable, "-B", str(ROOT/"Maintenance/Tests/supervisor_process_fixture.py"), str(root), str(seconds)],
                             cwd=ROOT, env=portable_env(root), stdout=log, stderr=log,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        processes.append(p); return p
    def check(name, passed, **evidence):
        report["checks"].append({"name": name, "passed": bool(passed), **evidence})
        atomic_json(ROOT/"Maintenance/Reports/persistence-smoke.json", report)
        print(json.dumps(report["checks"][-1]), flush=True)
        if not passed: raise AssertionError(name)
    try:
        root, store, mid = case("wait-restart")
        p = launch(root, 3)
        wait_for(lambda: store.load(mid)["steps"] == 1)
        due = store.load(mid)["next_run_at"]
        duplicate = launch(root, 1); duplicate.wait(timeout=5)
        check("second supervisor cannot dispatch", duplicate.returncode != 0, exit_code=duplicate.returncode)
        p.wait(timeout=10)
        check("scheduled wait survives supervisor exit", store.load(mid)["status"] == "waiting" and store.load(mid)["steps"] == 1)
        p = launch(root, 20); p.wait(timeout=25); m = store.load(mid)
        check("fresh supervisor resumes when due", m["status"] == "complete" and m["steps"] == 2 and m["history"][-1]["at"] >= due,
              mission=mid, completed_at=m["history"][-1]["at"], scheduled_at=due)

        root, store, mid = case("uncertain-effect")
        p = launch(root, 10); p.wait(timeout=15)
        p = launch(root, 2); p.wait(timeout=5)
        m = store.load(mid); effects = int((store.folder(mid)/"effect-count.txt").read_text())
        check("crashed action effect is not replayed", m["status"] == "needs_review" and effects == 1 and bool(m["pending_action"]), effects=effects)

        root, store, mid = case("controller-crash")
        p = launch(root, 60)
        wait_for(lambda: (store.folder(mid)/"worker-started").exists())
        p.kill(); p.wait(timeout=10)
        time.sleep(6)  # Beyond the descendant's scheduled write, bounded test wait.
        p = launch(root, 3); p.wait(timeout=6)
        check("controller crash kills its worker tree", not (store.folder(mid)/"late-effect.txt").exists() and store.load(mid)["status"] == "needs_review")

        root, store, mid = case("delayed-plan")
        p = launch(root, 20)
        wait_for(lambda: (store.folder(mid)/"planning-started").exists())
        disarm(root, mid); p.wait(timeout=8)
        check("stop prevents late planning effects", store.load(mid)["status"] == "paused" and not (store.folder(mid)/"notes.txt").exists())
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        for p in processes:
            if p.poll() is None: p.kill(); p.wait(timeout=10)
        for log in logs: log.close()
        atomic_json(ROOT/"Maintenance/Reports/persistence-smoke.json", report)


if __name__ == "__main__": main()
