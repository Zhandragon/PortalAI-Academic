"""Unmanaged host/desktop entry points must see restored historical paths."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT / 'ControlCenter')]
from mission_runner import Missions
import media_devices


class HostBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_full_mission_restores_before_launch_and_rechecks_stop(self):
        missions = Missions(self.root)
        mission = missions.create('synthetic file task', 'full')
        def hydrate(*args, **kwargs):
            (missions.folder(mission['id']) / 'STOP').touch()
        with patch('profile_hydration.materialize', side_effect=hydrate) as restore, \
             patch('mission_runner.require_space'), \
             patch('mission_runner.subprocess.Popen') as process:
            with self.assertRaisesRegex(RuntimeError, 'Mission stopped'):
                missions.execute(mission, {'action': 'shell', 'command': 'echo synthetic'})
        restore.assert_called_once_with(self.root, None, recursive=True)
        process.assert_not_called()

    def test_observe_and_vm_actions_never_restore_host_data(self):
        missions = Missions(self.root)
        observe = missions.create('synthetic observer')
        with patch('profile_hydration.materialize') as restore:
            with self.assertRaises(PermissionError):
                missions.execute(observe, {'action': 'shell', 'command': 'echo synthetic'})
            with patch('vm_runner.preflight', return_value={}):
                guest = missions.create('synthetic guest', 'vm')
            with patch('vm_runner.run_command', return_value={'exit_code': 0}):
                missions.execute(guest, {'action': 'shell', 'command': 'echo synthetic'})
        restore.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows file opener fixture')
    def test_external_file_open_hydrates_before_os_opener(self):
        context = ('a' * 32, 'b' * 32)
        workspace = self.root / 'Workspace'
        path = workspace / 'Outputs/file.txt'
        def hydrate(*args, **kwargs):
            path.parent.mkdir(parents=True)
            path.write_text('synthetic')
        with patch('profile_paths.capture', return_value=context), \
             patch('profile_paths.workspace_root', return_value=workspace), \
             patch('profile_hydration.materialize', side_effect=hydrate) as restore, \
             patch('media_devices.os.startfile') as open_file:
            media_devices.open_external(self.root, path)
        restore.assert_called_once_with(self.root, 'Outputs/file.txt', recursive=True)
        open_file.assert_called_once_with(str(path))

    @unittest.skipUnless(os.name == 'nt', 'Windows file opener fixture')
    def test_revoked_login_blocks_os_opener_after_hydration(self):
        context = ('a' * 32, 'b' * 32)
        workspace = self.root / 'Workspace'
        path = workspace / 'Outputs/file.txt'
        with patch('profile_paths.capture', side_effect=[context, None]), \
             patch('profile_paths.workspace_root', return_value=workspace), \
             patch('profile_hydration.materialize'), patch('media_devices.os.startfile') as open_file:
            with self.assertRaises(PermissionError):
                media_devices.open_external(self.root, path)
        open_file.assert_not_called()


if __name__ == '__main__':
    unittest.main()
