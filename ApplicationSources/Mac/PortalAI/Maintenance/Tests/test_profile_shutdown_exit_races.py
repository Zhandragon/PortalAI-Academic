"""Same-handle Windows exit races; mocked ABI, no real process termination."""
import ctypes
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'Agent'))
import profile_shutdown as shutdown


class WindowsExitRaces(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.row = {'pid': 101, 'start': 1000, 'executable': str(self.root / 'Runtime/python.exe')}
        self.lib = MagicMock()
        self.lib.OpenProcess.return_value = 123
        self.lib.TerminateProcess.return_value = True
        def times(handle, created, *unused):
            self.assertEqual(handle, 123)
            created._obj.dwLowDateTime = 1000
            created._obj.dwHighDateTime = 0
            return True
        def image(handle, flags, buffer, size):
            self.assertEqual(handle, 123)
            buffer.value = self.row['executable']
            return True
        self.lib.GetProcessTimes.side_effect = times
        self.lib.QueryFullProcessImageNameW.side_effect = image
        mock = patch.object(ctypes, 'WinDLL', return_value=self.lib, create=True)
        mock.start()
        self.addCleanup(mock.stop)

    def stop(self):
        shutdown._windows_stop(self.row, self.root)

    def assert_closed_original_handle(self):
        self.lib.OpenProcess.assert_called_once()
        self.lib.CloseHandle.assert_called_once_with(123)
        self.assertTrue(all(call.args[0] == 123 for call in self.lib.WaitForSingleObject.call_args_list))

    def test_exit_between_initial_wait_and_times_query(self):
        self.lib.WaitForSingleObject.side_effect = [258, 0]
        self.lib.GetProcessTimes.side_effect = None
        self.lib.GetProcessTimes.return_value = False
        self.stop()
        self.lib.QueryFullProcessImageNameW.assert_not_called()
        self.lib.TerminateProcess.assert_not_called()
        self.assert_closed_original_handle()

    def test_exit_between_times_and_image_query(self):
        self.lib.WaitForSingleObject.side_effect = [258, 0]
        self.lib.QueryFullProcessImageNameW.side_effect = None
        self.lib.QueryFullProcessImageNameW.return_value = False
        self.stop()
        self.lib.TerminateProcess.assert_not_called()
        self.assert_closed_original_handle()

    def test_unreadable_live_identity_remains_fail_closed(self):
        self.lib.WaitForSingleObject.side_effect = [258, 258]
        self.lib.QueryFullProcessImageNameW.side_effect = None
        self.lib.QueryFullProcessImageNameW.return_value = False
        with self.assertRaisesRegex(shutdown.QuiescenceError, 'identity cannot be rechecked'):
            self.stop()
        self.lib.TerminateProcess.assert_not_called()
        self.assert_closed_original_handle()

    def test_wait_failure_never_proves_exit_after_identity_failure(self):
        self.lib.WaitForSingleObject.side_effect = [258, 0xFFFFFFFF]
        self.lib.GetProcessTimes.side_effect = None
        self.lib.GetProcessTimes.return_value = False
        with self.assertRaisesRegex(shutdown.QuiescenceError, 'identity cannot be rechecked'):
            self.stop()
        self.lib.TerminateProcess.assert_not_called()
        self.assert_closed_original_handle()

    def test_exit_during_failed_termination_uses_same_handle(self):
        self.lib.WaitForSingleObject.side_effect = [258, 0]
        self.lib.TerminateProcess.return_value = False
        self.stop()
        self.lib.TerminateProcess.assert_called_once_with(123, 1)
        self.assert_closed_original_handle()

    def test_failed_termination_of_still_live_process_is_rejected(self):
        self.lib.WaitForSingleObject.side_effect = [258, 258]
        self.lib.TerminateProcess.return_value = False
        with self.assertRaisesRegex(shutdown.QuiescenceError, 'did not exit'):
            self.stop()
        self.lib.TerminateProcess.assert_called_once_with(123, 1)
        self.assert_closed_original_handle()

    def test_failed_termination_with_failed_wait_is_rejected(self):
        self.lib.WaitForSingleObject.side_effect = [258, 0xFFFFFFFF]
        self.lib.TerminateProcess.return_value = False
        with self.assertRaisesRegex(shutdown.QuiescenceError, 'did not exit'):
            self.stop()
        self.assert_closed_original_handle()

    def test_exit_at_end_of_bounded_wait_is_accepted_only_when_signaled(self):
        self.lib.WaitForSingleObject.side_effect = [258, 258, 0]
        self.stop()
        self.assertEqual([call.args[1] for call in self.lib.WaitForSingleObject.call_args_list], [0, 8000, 0])
        self.assert_closed_original_handle()

    def test_identity_mismatch_is_never_terminated_or_excused(self):
        self.row['start'] = 2000
        self.lib.WaitForSingleObject.side_effect = [258, 0]
        with self.assertRaisesRegex(shutdown.QuiescenceError, 'identity changed'):
            self.stop()
        self.lib.WaitForSingleObject.assert_called_once_with(123, 0)
        self.lib.TerminateProcess.assert_not_called()
        self.assert_closed_original_handle()


if __name__ == '__main__':
    unittest.main()
