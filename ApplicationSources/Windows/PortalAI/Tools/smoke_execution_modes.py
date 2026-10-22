"""Exercise real host/VM routing and restricted-mode rejection in test missions."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_runner import Missions, ACTIVE
from mission_supervisor import running
from runtime_policy import atomic_json


def main():
    if running(): raise RuntimeError("Finish active supervision before this test")
    store = Missions(); created = []
    report = {"checks": [], "planner": "fixed bounded test actions; real host/guest execution"}
    def create(mode):
        m = store.create("Bounded execution-mode routing self-test", mode, 3)
        created.append(m["id"]); return m
    def check(name, condition, **evidence):
        report["checks"].append({"name": name, "passed": bool(condition), **evidence})
        atomic_json(ROOT/"Maintenance/Reports/execution-mode-smoke.json", report)
        print(json.dumps(report["checks"][-1]), flush=True)
        if not condition: raise AssertionError(name)
    previous = os.environ.get("PORTALAI_MODE_TEST_SENTINEL")
    os.environ["PORTALAI_MODE_TEST_SENTINEL"] = "HOST_TEST_VALUE"
    try:
        m = create("observe")
        try:
            store.execute(m, {"action": "shell", "mode": "full", "command": "echo must-not-execute"})
            refused = False
        except PermissionError: refused = True
        check("observe refuses host shell despite requested mode override", refused, mission=m["id"])
        try:
            store.execute(m, {"action": "account", "mode": "full", "operation": "profiles"})
            refused = False
        except PermissionError: refused = True
        check("observe refuses dedicated account access despite mode override", refused, mission=m["id"])
        store.run(m["id"], model=lambda _: {"action": "complete", "text": "Restriction verified"})

        m = create("full")
        proof = store.folder(m["id"])/"host-proof.txt"
        code = ("import json,os,sys;from pathlib import Path;"
                "assert os.environ.get('PORTALAI_MODE_TEST_SENTINEL')=='HOST_TEST_VALUE';"
                "Path(sys.argv[1]).write_text('FULL_HOST_OK',encoding='utf-8');"
                "print(json.dumps({'platform':sys.platform,'proof':'FULL_HOST_OK'}))")
        command = subprocess.list2cmdline([sys.executable, "-B", "-c", code, str(proof)])
        def host_action(m):
            return {"action": "shell", "command": command} if not m["steps"] else {"action": "complete", "text": "Host proof checked by test controller"}
        m = store.run(m["id"], 2, model=host_action)
        r = json.loads(m["history"][0]["result"])
        check("full mode executes on this host", m["status"] == "complete" and r["exit_code"] == 0 and proof.read_text() == "FULL_HOST_OK" and json.loads(r["output"])["platform"] == sys.platform,
              mission=m["id"], result=r)

        m = create("vm")
        command = "test -z \"${PORTALAI_MODE_TEST_SENTINEL+x}\" && test \"$(id -u)\" = 1000 && test \"$(ls /sys/class/net)\" = lo && printf 'VM_ONLY_OK\\n'; uname -s"
        def guest_action(m):
            return {"action": "shell", "mode": "full", "command": command} if not m["steps"] else {"action": "complete", "text": "Guest proof checked by test controller"}
        m = store.run(m["id"], 2, model=guest_action)
        r = json.loads(m["history"][0]["result"])
        check("VM shell stays in guest and omits host environment", m["status"] == "complete" and r["exit_code"] == 0 and "VM_ONLY_OK" in r["output"] and "Linux" in r["output"] and r["network"] is False and r["host_mounts"] == [],
              mission=m["id"], result=r)
        denied = []
        for kind in ("read_file", "diagnostics", "account"):
            try: store.execute(m, {"action": kind, "path": "Agent/mission_runner.py", "mode": "full"})
            except PermissionError: denied.append(kind)
        check("VM mission cannot invoke host reads, diagnostics or accounts", denied == ["read_file", "diagnostics", "account"], denied=denied)
        report["passed"] = True
    finally:
        if previous is None: os.environ.pop("PORTALAI_MODE_TEST_SENTINEL", None)
        else: os.environ["PORTALAI_MODE_TEST_SENTINEL"] = previous
        for mid in created:
            m = store.load(mid)
            if m["status"] in ACTIVE:
                store.stop(mid); m.update(status="paused"); store.save(m)
        atomic_json(ROOT/"Maintenance/Reports/execution-mode-smoke.json", report)


if __name__ == "__main__": main()
