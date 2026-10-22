"""Deterministic test worker. Production supervision never selects this file."""
from pathlib import Path
import os
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
import mission_runner


def model(self, m):
    if m["objective"] == "wait-restart":
        return {"action": "wait", "seconds": 10} if not m["steps"] else {"action": "complete", "text": "resumed"}
    if m["objective"] == "delayed-plan":
        (self.folder(m["id"])/"planning-started").touch()
        time.sleep(6)
    return {"action": "note", "text": "test effect"}


original_execute = mission_runner.Missions.execute
def execute(self, m, action):
    folder = self.folder(m["id"])
    if m["objective"] == "uncertain-effect":
        count = folder/"effect-count.txt"
        count.write_text(str(int(count.read_text())+1 if count.exists() else 1))
        os._exit(73)  # Effect happened, completion checkpoint did not.
    if m["objective"] == "controller-crash":
        subprocess.Popen([sys.executable, "-B", "-c",
                          "import time,sys;from pathlib import Path;time.sleep(5);Path(sys.argv[1]).write_text('late effect')",
                          str(folder/"late-effect.txt")], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (folder/"worker-started").touch()
        time.sleep(60)
    return original_execute(self, m, action)


mission_runner.Missions.model_action = model
mission_runner.Missions.execute = execute
mission_runner.main()
