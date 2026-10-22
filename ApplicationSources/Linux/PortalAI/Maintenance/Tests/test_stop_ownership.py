"""A stale PID marker must not turn Stop-all into an unrelated process killer."""
from contextlib import redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
spec = importlib.util.spec_from_file_location("portable_stop_test", ROOT/"Launchers/Stop_PortableAI.py")
stop = importlib.util.module_from_spec(spec); spec.loader.exec_module(stop)


class StopOwnershipTests(unittest.TestCase):
    def test_reused_marker_pid_is_not_killed(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            rows = [{"ProcessId": 43210, "ExecutablePath": "C:\\OtherApp\\worker.exe", "CommandLine": "worker.exe"}]
            with patch.object(sys, "argv", ["stop", "--root", str(root)]), \
                 patch.object(stop, "marker_pids", return_value={43210}), \
                 patch.object(stop, "portable_process_pids", return_value=(set(), [])), \
                 patch.object(stop, "cim_processes", return_value=rows), \
                 patch.object(stop, "port_pids", return_value=[]), \
                 patch.object(stop, "gpu_processes", return_value=[]), \
                 patch("service_manager.stop"), patch("mission_supervisor.pause_all"), \
                 patch.object(stop, "kill") as kill, redirect_stdout(io.StringIO()):
                self.assertEqual(stop.main(), 0)
                kill.assert_not_called()


if __name__ == "__main__": unittest.main()
