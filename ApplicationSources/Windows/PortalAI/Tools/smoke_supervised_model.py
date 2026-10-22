"""Real local-model supervision, recursion, diagnostics and nested VM jobs."""
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_runner import Missions, ACTIVE
from mission_supervisor import arm, disarm, ensure_running, running
from runtime_policy import atomic_json


def main():
    store = Missions()
    report = {"checks": [], "real_model": True, "started_at": time.time()}
    if running(): raise RuntimeError("Another supervisor is active; finish that work before this live test")
    def run(name, objective, mode, check, budget):
        m = store.create(objective, mode, budget)
        try:
            arm(ROOT, m["id"])
            launch = ensure_running()
            deadline = time.monotonic()+300
            while time.monotonic() < deadline:
                m = store.load(m["id"])
                if m["status"] not in ACTIVE: break
                time.sleep(.5)
            children = [store.load(cid) for cid in m["children"]]
            passed = m["status"] == "complete" and check(m, children)
            item = {"name": name, "passed": passed, "launch": launch, "mission": m, "children": children}
            report["checks"].append(item)
            atomic_json(ROOT/"Maintenance/Reports/supervised-model-smoke.json", report)
            print(json.dumps({"name": name, "passed": passed, "mission": m["id"], "status": m["status"], "steps": m["steps"]}), flush=True)
            if not passed: raise AssertionError(name)
        finally:
            disarm(ROOT, m["id"])
            deadline = time.monotonic()+15
            while running() and time.monotonic() < deadline: time.sleep(.2)
            if m["status"] == "complete" and store.load(m["id"])["status"] != "complete":
                raise AssertionError("Disarming changed a completed mission")
    run("scheduled recursive installation self-test",
        "Perform this exact bounded installation self-test. First create ONE subtask with objective: Save a note containing exactly CHILD_OK, then complete. "
        "After that child completes, wait exactly 10 seconds ONCE. Then use diagnostics once, save a note summarizing the actual PASS/WARN/FAIL counts, "
        "and complete. Check your history so no step is repeated. Never create more than one subtask.", "observe",
        lambda m, children: len(children) == 1 and children[0]["status"] == "complete" and
            "CHILD_OK" in (store.folder(children[0]["id"])/"notes.txt").read_text() and
            [h["action"]["action"] for h in m["history"]] == ["subtask", "wait", "diagnostics", "note", "complete"], 8)
    run("supervised VM shell and guest persistence",
        "Self-test the offline VM. First shell: run id and write SUPERVISED_VM_OK into /workspace/check.txt. "
        "In a SEPARATE second shell, read /workspace/check.txt and list /sys/class/net. "
        "Then complete with the actual results. Do not repeat a successful shell action.", "vm",
        lambda m, _: len([h for h in m["history"] if h["action"]["action"] == "shell"]) == 2 and
            "SUPERVISED_VM_OK" in m["history"][1]["result"], 5)
    report["passed"] = True
    atomic_json(ROOT/"Maintenance/Reports/supervised-model-smoke.json", report)


if __name__ == "__main__": main()
