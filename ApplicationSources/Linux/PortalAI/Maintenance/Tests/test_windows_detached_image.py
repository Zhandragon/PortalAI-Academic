"""Lost-mount image proof; no real processes or files are terminated."""
import ctypes
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'Agent'))
import windows_detached_image as image
import profile_shutdown as shutdown


@unittest.skipUnless(os.name == 'nt', 'Windows handle API fixture')
class DetachedImageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.row = {'pid': 101, 'start': 1000, 'executable': str(self.root/'Runtime/model.exe')}
        self.native = r'\Device\HarddiskVolume8' + self.row['executable'][2:]
        self.lib = MagicMock()
        self.lib.OpenProcess.return_value = 123
        self.lib.WaitForSingleObject.return_value = 258
        self.lib.GetProcessTimes.side_effect = self.times
        self.lib.QueryFullProcessImageNameW.side_effect = self.query
        self.lib.TerminateProcess.return_value = True
        self.error = 21
        self.created = 1000
        self.native_result = self.native
        mock = patch.object(ctypes, 'WinDLL', return_value=self.lib)
        mock.start(); self.addCleanup(mock.stop)

    def times(self, handle, created, *unused):
        created._obj.dwLowDateTime = self.created
        created._obj.dwHighDateTime = 0
        return True

    def query(self, handle, flags, buffer, size):
        self.assertEqual(handle, 123)
        if flags == 0:
            ctypes.set_last_error(self.error)
            return False
        buffer.value = self.native_result
        return True

    def pin(self):
        self.row['detached_image'] = image.capture(self.row, self.root)

    def test_capture_binds_original_cim_path_to_same_handle_native_image_and_time(self):
        self.pin()
        self.assertEqual(self.row['detached_image'], {
            'pid': 101, 'start': 1000, 'original': self.row['executable'], 'native': self.native})
        self.lib.TerminateProcess.assert_not_called()
        self.lib.CloseHandle.assert_called_once_with(123)

    def test_access_denied_other_errors_and_foreign_roots_have_no_fallback(self):
        for error in (5, 2, 31, 87, 0):
            self.error = error
            self.assertIsNone(image.capture(self.row, self.root))
        self.error = 21
        self.assertIsNone(image.capture(self.row, self.root/'different'))
        self.lib.TerminateProcess.assert_not_called()

    def test_capture_rejects_pid_reuse_and_native_path_mismatch(self):
        self.created = 2000
        self.assertIsNone(image.capture(self.row, self.root))
        self.created = 1000
        self.native_result = r'\Device\HarddiskVolume8\unrelated\model.exe'
        self.assertIsNone(image.capture(self.row, self.root))

    def test_exact_captured_identity_is_rechecked_before_same_handle_stop(self):
        self.pin()
        self.lib.reset_mock()
        self.lib.WaitForSingleObject.side_effect = [258, 0]
        shutdown._windows_stop(self.row, self.root)
        self.lib.TerminateProcess.assert_called_once_with(123, 1)
        self.lib.CloseHandle.assert_called_once_with(123)

    def test_changed_native_volume_or_creation_time_never_terminates(self):
        self.pin()
        self.native_result = self.native.replace('Volume8', 'Volume10')
        with self.assertRaises(shutdown.QuiescenceError):
            shutdown._windows_stop(self.row, self.root)
        self.native_result = self.native
        self.created = 1001  # Exact 100ns pin is stricter than the CIM timestamp.
        with self.assertRaises(shutdown.QuiescenceError):
            shutdown._windows_stop(self.row, self.root)
        self.lib.TerminateProcess.assert_not_called()

    def test_missing_or_changed_original_proof_never_terminates(self):
        with self.assertRaises(shutdown.QuiescenceError):
            shutdown._windows_stop(self.row, self.root)
        self.pin()
        self.row['detached_image']['original'] = str(self.root/'Other/model.exe')
        with self.assertRaises(shutdown.QuiescenceError):
            shutdown._windows_stop(self.row, self.root)
        self.lib.TerminateProcess.assert_not_called()

    def test_valid_proof_does_not_override_another_error_or_successful_identity_mismatch(self):
        self.pin()
        self.error = 5
        with self.assertRaises(shutdown.QuiescenceError):
            shutdown._windows_stop(self.row, self.root)
        def wrong(handle, flags, buffer, size):
            buffer.value = str(self.root/'Other/model.exe'); return True
        self.lib.QueryFullProcessImageNameW.side_effect = wrong
        with self.assertRaises(shutdown.QuiescenceError):
            shutdown._windows_stop(self.row, self.root)
        self.lib.TerminateProcess.assert_not_called()


class NativeSuffixTests(unittest.TestCase):
    def test_full_directory_and_local_drive_required(self):
        self.assertTrue(image.matching_suffix(r'\Device\HarddiskVolume8\PortalAI\LLM\model.exe', r'D:\PortalAI\LLM\model.exe'))
        for native, original in [
            (r'\Device\HarddiskVolume8\other\model.exe', r'D:\PortalAI\LLM\model.exe'),
            (r'\Device\HarddiskVolume8\PortalAI\LLM\model.exe', r'\\server\share\PortalAI\LLM\model.exe'),
            (r'\Device\Mup\PortalAI\LLM\model.exe', r'D:\PortalAI\LLM\model.exe'),
            (r'\Device\HarddiskVolume8\PortalAI\..\model.exe', r'D:\PortalAI\..\model.exe')]:
            self.assertFalse(image.matching_suffix(native, original))


if __name__ == '__main__': unittest.main()
