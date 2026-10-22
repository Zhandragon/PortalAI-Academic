"""Verify explicit Stop pauses armed work across a normal native restart."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_runner import Missions, ACTIVE
from mission_supervisor import arm, disarm, ensure_running, read_policy, running
from runtime_policy import atomic_json, portable_env
from mission_schedule import Schedules


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--voice-smoke',action='store_true');args=ap.parse_args()
    store = Missions()
    schedules=Schedules()
    if running() or schedules.any_enabled() or any(m["status"] in ACTIVE for m in store.list()):
        raise RuntimeError("Finish or pause other missions before this Stop-all test")
    m = store.create("Stop lifecycle test: do not execute any model actions", max_steps=2)
    m = store.run(m["id"], model=lambda _: {"action": "wait", "seconds": 3600})
    schedule=schedules.create('Stop lifecycle: future schedule must remain paused',first_run_at=time.time()+3600,max_runs=1)
    schedules.enable(schedule['id'])
    arm(ROOT, m["id"]); ensure_running()
    def invoke(name):
        cp = subprocess.run([sys.executable, "-B", str(ROOT/"Launchers"/name), "--root", str(ROOT)],
                            cwd=ROOT, env=portable_env(ROOT), capture_output=True, text=True, errors="replace", timeout=180,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(cp.stdout)
        if cp.returncode: raise RuntimeError(json.dumps(data))
        return data
    stop=start=None;voice=None
    try:
        stop = invoke("Stop_PortableAI.py")
        if args.voice_smoke:
            with (ROOT/'Maintenance/Reports/repair-voice-stopped.txt').open('wb') as log:
                cp=subprocess.run([sys.executable,'-B','-I',str(ROOT/'Tools/smoke_voice.py')],cwd=ROOT,env=portable_env(ROOT),
                                  stdout=log,stderr=log,timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            voice={'returncode':cp.returncode,'log':'Maintenance/Reports/repair-voice-stopped.txt'}
        start = invoke("Start_PortableAI_Native_v15_133.py")
        m = store.load(m["id"])
        report = {"passed": stop["success"] and start["success"] and m["status"] == "paused" and
                  m["steps"] == 1 and not read_policy(store, m["id"])["enabled"] and not running() and
                  not schedules.enabled(schedules.load(schedule['id'])) and (voice is None or voice['returncode']==0),
                  "mission": m["id"], "status": m["status"], "stop": stop,
                  "future_schedule_paused":not schedules.enabled(schedules.load(schedule['id'])),"voice_smoke":voice,
                  "startup": {"success": start["success"], "qwen_ready": start["qwen"]["ready"], "missions": start["missions"]}}
        atomic_json(ROOT/"Maintenance/Reports/persistence-lifecycle.json", report)
        print(json.dumps(report))
        if not report["passed"]: raise AssertionError("Stop lifecycle")
    finally:
        if stop and start is None:invoke("Start_PortableAI_Native_v15_133.py")
        schedules.disable(schedule['id'])
        disarm(ROOT, m["id"])


if __name__ == "__main__": main()
