"""Isolated real-process supervisor fixture using the deterministic test worker."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_supervisor import Supervisor
root = Path(sys.argv[1])
Supervisor(root, worker_command=[sys.executable, "-B", str(ROOT/"Maintenance/Tests/mission_worker_fixture.py"), "--root", str(root)],
           model_ready=lambda: True).run(float(sys.argv[2]))
