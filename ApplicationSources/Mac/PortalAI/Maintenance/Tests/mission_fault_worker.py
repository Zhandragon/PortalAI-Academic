"""Synthetic process failures; selected only by the crash-recovery tests."""
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
import mission_runner


def model(self, mission):
    folder = self.folder(mission['id'])
    if mission['objective'] == 'stall-once':
        marker = folder/'first-worker-pid.txt'
        if not marker.exists():
            marker.write_text(str(os.getpid()))
            while True:
                time.sleep(1)
        (folder/'recovered-worker-pid.txt').write_text(str(os.getpid()))
        return {'action':'complete', 'text':'A new Python worker resumed automatically'}
    return {'action':'note', 'text':'effect before crash'}


def execute(self, mission, action):
    if mission['objective'] == 'crash-after-effect':
        path = self.folder(mission['id'])/'effect-count.txt'
        path.write_text(str(int(path.read_text())+1 if path.exists() else 1))
        os._exit(73)
    return original_execute(self, mission, action)


original_execute = mission_runner.Missions.execute
mission_runner.Missions.model_action = model
mission_runner.Missions.execute = execute
mission_runner.main()
