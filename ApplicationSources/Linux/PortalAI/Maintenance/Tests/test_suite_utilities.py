import contextlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(ROOT/'Tools')]
import suite_utilities as suite
import portalai_full_reset as reset


def put(root, name, data=b'fixture'):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data);return p


class UtilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'PortalAI Windows';self.root.mkdir()
        suite._pending=None

    def tearDown(self):
        suite._pending=None;self.temp.cleanup()

    def test_full_and_academic_choices_are_distinct(self):
        self.assertEqual(suite.editions(self.root),('Full','Academic'))
        put(self.root,'Agent/academic_policy.py')
        self.assertEqual(suite.editions(self.root),('Academic',))
        with self.assertRaises(PermissionError):suite.installer_folder(self.root,'Full','Mac')

    def test_academic_policy_wins_over_inconsistent_receipt(self):
        put(self.root,'Agent/academic_policy.py')
        put(self.root,'Maintenance/Imports/distribution-version.json',b'{"edition":"Full"}')
        self.assertEqual(suite.edition(self.root),'Academic')

    def test_corrupt_edition_is_not_promoted_to_full(self):
        put(self.root,'Maintenance/Imports/distribution-version.json',b'{"edition":"unknown"}')
        with self.assertRaises(RuntimeError):suite.editions(self.root)

    def test_os_matched_projection_launchers(self):
        home=self.base/'Utilities/PortalAI-Projection'
        put(home,'Runtime/Python/pythonw.exe');put(home,'app/projection_ui.py')
        put(home,'Start Projection.command');put(home,'Start Projection.sh')
        for system,first in [('Windows',str(home/'Runtime/Python/pythonw.exe')),('Mac','/bin/bash'),('Linux','/bin/sh')]:
            command,cwd=suite.utility_command(self.root,'projection',system)
            self.assertEqual(command[0],first);self.assertEqual(cwd,home)

    def test_windows_abliterator_is_not_run_on_mac(self):
        put(self.base,'Utilities/Portable Abliterator/Abliterator.exe')
        self.assertTrue(suite.utility_command(self.root,'abliterator','Windows')[0][0].endswith('.exe'))
        with self.assertRaises(FileNotFoundError):suite.utility_command(self.root,'abliterator','Mac')

    def test_academic_denies_abliterator_before_launch(self):
        put(self.root,'Agent/academic_policy.py',b'# Academic')
        put(self.base,'Utilities/Portable Abliterator/Abliterator.exe')
        with patch.object(suite,'spawn') as start:
            with self.assertRaises(PermissionError):suite.launch(self.root,'abliterator')
            start.assert_not_called()

    def test_optional_utility_missing_does_not_launch(self):
        with patch.object(suite,'spawn') as start:
            with self.assertRaises(FileNotFoundError):suite.launch(self.root,'projection')
            start.assert_not_called()

    def test_installer_locator_selects_edition_and_os(self):
        for edition in ('Full','Academic'):
            for system in suite.PLATFORMS:
                p=put(self.base,'Utilities/Installers/'+edition+'/'+system+'/installer.zip')
                self.assertEqual(suite.installer_folder(self.root,edition,system),p.parent)

    def test_installer_locator_does_not_invent_missing_folders(self):
        with self.assertRaises(FileNotFoundError):suite.installer_folder(self.root,'Full','Linux')
        self.assertFalse((self.base/'Utilities').exists())

    def test_maintenance_request_waits_for_bootstrap_exit_dispatch(self):
        put(self.root,'Tools/recover_profile_login.py')
        with patch.object(suite,'spawn',return_value='child') as start:
            suite.request_after_exit(self.root,'recover');start.assert_not_called()
            self.assertEqual(suite.launch_after_exit(),'child')
            self.assertIsNone(suite.launch_after_exit());self.assertEqual(start.call_count,1)
            argv=start.call_args.args[0];self.assertIn('--parent',argv);self.assertIn('recover',argv)

    def test_missing_maintenance_tool_does_not_queue(self):
        with self.assertRaises(FileNotFoundError):suite.request_after_exit(self.root,'reset')
        self.assertIsNone(suite._pending)

    def test_independent_program_does_not_inherit_account_environment(self):
        with patch.dict(os.environ,{'PORTALAI_PROFILE_KEY':'secret','PYTHONPATH':'host-injection','DISPLAY':':1'}):
            env=suite.clean_environment()
        self.assertNotIn('PORTALAI_PROFILE_KEY',env);self.assertNotIn('PYTHONPATH',env)
        self.assertEqual(env['DISPLAY'],':1')


class ResetBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.root=self.base/'PortalAI Windows';self.root.mkdir()
        for n in ('ControlCenter/control_center_bootstrap.py','Agent/local_accounts.py',
                  'PortalAI.exe','Runtime/BootstrapPython/pythonw.exe',
                  'Runtime/LinuxPython/bin/python3','Runtime/MacPython/bin/python3.12'):
            put(self.root,n)
        put(self.root,'Private/Users/account/Vault/data.enc',b'encrypted-fixture')
        put(self.root,'LLM/models/keep.gguf',b'keep-model')
        self.engine=reset.FactoryReset(self.root)
        self.stack=contextlib.ExitStack()
        self.stack.enter_context(patch.object(reset,'processes',return_value=[]))
        self.stack.enter_context(patch('instance_runtime.host_directory',return_value=self.base/'coordination'))

    def tearDown(self):
        self.stack.close();self.temp.cleanup()

    def test_platform_name_and_missing_optional_companion_are_supported(self):
        self.engine.validate_roots();self.assertIsNone(self.engine.peer)

    def test_no_confirmation_no_deletion(self):
        for value in ('','confirm','CONFIRM ',' CONFIRM','RESET'):
            with self.assertRaises(reset.ResetError):self.engine.reset(value)
        self.assertTrue((self.root/'Private/Users/account/Vault/data.enc').exists())
        self.assertFalse(self.engine.guard.exists())

    def test_explicit_fixture_reset_keeps_source_and_models(self):
        result=self.engine.reset('CONFIRM')
        self.assertTrue(result['fresh'])
        self.assertFalse((self.root/'Private/Users/account/Vault/data.enc').exists())
        self.assertEqual((self.root/'LLM/models/keep.gguf').read_bytes(),b'keep-model')
        self.assertTrue((self.root/'ControlCenter/control_center_bootstrap.py').exists())
        self.assertFalse(self.engine.guard.exists())

    def test_existing_companion_connections_are_included_and_public_code_kept(self):
        peer=self.base/'Utilities/PortalAI-Projection'
        put(peer,'app/projection_ui.py');put(peer,'Connections/pair.enc',b'fixture-key')
        self.engine.reset('CONFIRM')
        self.assertFalse((peer/'Connections/pair.enc').exists())
        self.assertTrue((peer/'app/projection_ui.py').exists())

    def test_duplicate_companions_stop_before_deletion(self):
        for n in ('Utilities/PortalAI-Projection','PortalAI-Projection'):put(self.base,n+'/app/projection_ui.py')
        with self.assertRaises(reset.ResetError):self.engine.reset('CONFIRM')
        self.assertTrue((self.root/'Private/Users/account/Vault/data.enc').exists())

    def test_incomplete_installation_cannot_be_reset(self):
        (self.root/'Agent/local_accounts.py').unlink()
        with self.assertRaises(reset.ResetError):self.engine.reset('CONFIRM')

    def test_running_owned_process_stops_reset_without_killing_it(self):
        with patch.object(reset,'processes',return_value=[(98765,str(self.root/'Runtime/worker.exe'),'worker.exe')]):
            with self.assertRaises(reset.ResetError):self.engine.reset('CONFIRM')
        self.assertTrue((self.root/'Private/Users/account/Vault/data.enc').exists())

    def test_hardlinked_private_file_is_refused(self):
        target=self.root/'Private/Users/account/Vault/data.enc'
        os.link(target,self.base/'outside-copy.enc')
        with self.assertRaises(reset.ResetError):self.engine.reset('CONFIRM')
        self.assertEqual(target.read_bytes(),b'encrypted-fixture')

    def test_companion_arrival_after_inventory_stops_reset(self):
        self.engine.validate_roots()
        put(self.base,'Utilities/PortalAI-Projection/app/projection_ui.py')
        with self.assertRaises(reset.ResetError):self.engine.validate_roots()


if __name__=='__main__':unittest.main()
