"""Aoostar merge regression: retain connection deletion and portable root discovery."""
from pathlib import Path
import tempfile,unittest
from unittest.mock import patch,Mock
from test_projection_ui import WindowTests
import host_runtime

class MergeTests(unittest.TestCase):
    setUp=WindowTests.setUp
    tearDown=WindowTests.tearDown
    def test_selected_delete_still_requires_confirmation_and_preserves_other_files(self):
        self.app.deiconify();self.app.update()
        selected=self.root/'Connections'/('a'*32+'.enc');selected.write_bytes(b'fixture')
        other=self.root/'Connections'/('b'*32+'.enc');other.write_bytes(b'keep')
        self.w.refresh();self.w.saved.current(0);self.w.saved.event_generate('<<ComboboxSelected>>');self.app.update()
        self.assertEqual(str(self.w.delete_button.cget('state')),'normal')
        with patch.object(self.w,'confirm_delete',return_value=False):self.w.delete_selected()
        self.assertTrue(selected.exists())
        with patch.object(self.w,'confirm_delete',return_value=True):self.w.delete_selected()
        self.assertFalse(selected.exists());self.assertEqual(other.read_bytes(),b'keep')
        self.assertEqual(str(self.w.delete_button.cget('state')),'disabled')
    def test_live_projection_refuses_delete_before_confirmation(self):
        selected=self.root/'Connections'/('a'*32+'.enc');selected.write_bytes(b'fixture')
        self.w.refresh();self.w.saved.current(0);self.w.worker=Mock();self.w.worker.poll.return_value=None
        with patch.object(self.w,'confirm_delete') as confirmation:self.w.delete_selected();confirmation.assert_not_called()
        self.assertTrue(selected.exists())
    def test_utilities_discovery_finds_windows_named_root(self):
        module=self.root/'Utilities/PortalAI-Projection';module.mkdir(parents=True)
        target=self.root/'PortalAI Windows';(target/'Agent').mkdir(parents=True)
        (target/'PortalAI.exe').write_bytes(b'fixture');(target/'Agent/profile_shutdown.py').write_text('# fixture')
        with patch.object(host_runtime,'MODULE',module):self.assertEqual(host_runtime.default_target(),target)

if __name__=='__main__':unittest.main()
