"""Owned endpoint identity checks, synthetic roots only; no production discovery."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
from native_state_client import NativeStateClient, PROTOCOL


@unittest.skipUnless(os.name=='nt','Windows process/window identity fixture')
class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.scope=self.root/'input';self.scope.mkdir()
        self.row={'pid':42,'start':10000,'executable':str(self.root/'Runtime/BootstrapPython/python.exe'),
                  'argv':[str(self.root/'ControlCenter/PortableAI_GUI.py')]}
        self.desktop=Mock();self.desktop.windows.return_value=[{'pid':42,'start':10000,'hwnd':123,'class':'TkTopLevel'}]
        self.manager=SimpleNamespace(root=self.root,endpoint_dir=self.scope,desktop=self.desktop,inventory=Mock(return_value={42:self.row}))
        self.endpoint={'version':2,'protocol':PROTOCOL,'scope':'native.state.read','pid':42,'start':10000,'hwnd':123,'port':54321,'token':'x'*43}
        self.path=self.scope/'native-gui-42.json';self.write()
        self.client=NativeStateClient(self.manager)
    def tearDown(self): self.temp.cleanup()
    def write(self):self.path.write_text(json.dumps(self.endpoint))

    def test_exact_owned_process_and_window_are_revalidated(self):
        self.assertEqual(self.client.discover(),self.endpoint)
        self.desktop.validate.assert_called_once()
        self.assertEqual(self.desktop.validate.call_args.args[0]['executable'],self.row['executable'])

    def test_changed_creation_time_scope_or_window_refuses_endpoint(self):
        for key,value in [('start',20000),('pid',44),('scope','projection'),('hwnd',999),('port',True),('token','short')]:
            previous=self.endpoint[key];self.endpoint[key]=value;self.write()
            with self.subTest(key=key),self.assertRaises(RuntimeError):self.client.discover()
            self.endpoint[key]=previous
        self.write()

    def test_foreign_executable_or_script_is_not_an_owned_GUI(self):
        for change in [{'executable':str(self.root/'unowned/python.exe')},{'argv':['-c','print(1)']}]:
            self.manager.inventory.return_value={42:{**self.row,**change}}
            with self.assertRaises(RuntimeError):self.client.discover()
        self.desktop.validate.assert_not_called()

    def test_missing_or_malformed_endpoint_does_not_fall_back_to_projection(self):
        self.endpoint['unexpected']='anything';self.write()
        with self.assertRaises(RuntimeError):self.client.discover()
        self.path.unlink()
        with self.assertRaises(RuntimeError):self.client.discover()
        self.desktop.validate.assert_not_called()

    def test_bound_reads_check_kernel_identity_without_repeating_full_inventory(self):
        self.client.endpoint=self.client.discover()
        self.manager.inventory.reset_mock();self.desktop.validate.reset_mock()
        self.client.discover()
        self.manager.inventory.assert_not_called();self.desktop.validate.assert_called_once()
        # Reused PIDs, changed executables, closed HWNDs or changed creation times
        # must fail in the production kernel identity validator on every read.
        self.desktop.validate.side_effect=RuntimeError('Window process was replaced')
        with self.assertRaises(RuntimeError):self.client.discover()
        self.assertEqual(self.desktop.validate.call_count,2)

    def test_bound_reads_still_refuse_a_replaced_endpoint(self):
        self.client.endpoint=self.client.discover()
        self.endpoint['start']+=10000;self.write()
        with self.assertRaises(RuntimeError):self.client.discover()


if __name__=='__main__':unittest.main()
