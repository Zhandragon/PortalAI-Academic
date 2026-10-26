"""The setup entry must retain ordinary preflight, instance and diagnostics."""
from pathlib import Path
import contextlib
import importlib.util
import io
import sys
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('setup_bootstrap_under_test',ROOT/'ControlCenter/control_center_bootstrap.py')
bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)


class SetupBootstrapTests(unittest.TestCase):
    def test_default_launch_unchanged(self):
        self.assertEqual(bootstrap.gui_arguments(ROOT,[]),[str(ROOT/'ControlCenter/PortableAI_GUI.py'),'--root',str(ROOT)])

    def test_explicit_paths_are_literal_data(self):
        request='folder with spaces/setup request.json'
        receipt='folder with spaces/setup receipt.json'
        result=bootstrap.gui_arguments(ROOT,['--account-setup',request,'--account-setup-receipt',receipt])
        self.assertEqual(result[-4:],['--account-setup',request,'--account-setup-receipt',receipt])

    def test_receipt_requires_setup_and_unknown_arguments_fail(self):
        for arguments in (['--account-setup-receipt','receipt.json'],['--root','elsewhere'],['--account-setup']):
            with self.subTest(arguments=arguments),contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit) as exc:
                bootstrap.gui_arguments(ROOT,arguments)
            self.assertEqual(exc.exception.code,2)

    def test_setup_uses_normal_startup_and_cleanup(self):
        events=[]
        runtime=types.ModuleType('account_runtime');runtime.AccountRuntimeUnavailable=RuntimeError
        runtime.preflight=lambda:events.append('preflight')
        instance=types.ModuleType('instance_runtime')
        class Instance:
            def __init__(self,root):pass
            def start(self):events.append('start');return self
            def close(self):events.append('close')
        instance.InstanceSession=Instance
        diagnostics=types.ModuleType('profile_diagnostics')
        diagnostics.prepare=lambda root:events.append('prepare')
        diagnostics.suspend=lambda:events.append('suspend')
        diagnostics.record=lambda text:None
        diagnostics.stderr=lambda text:None
        tk=types.ModuleType('tkinter');tk.Tk=type('Tk',(),{'report_callback_exception':lambda *args:None})
        argv=['bootstrap.py','--account-setup','request.json','--account-setup-receipt','receipt.json']
        def launch(path,run_name):
            events.append('gui')
            self.assertEqual(sys.argv,bootstrap.gui_arguments(ROOT,argv[1:]))
            self.assertIn(str(ROOT/'ControlCenter'),sys.path)
            self.assertEqual(run_name,'__main__')
            raise SystemExit(0)
        with patch.dict(sys.modules,{'account_runtime':runtime,'instance_runtime':instance,'profile_diagnostics':diagnostics,'tkinter':tk}),patch.object(sys,'argv',argv),patch.object(sys,'path',sys.path.copy()),patch.object(bootstrap.threading,'excepthook'),patch.object(bootstrap.runpy,'run_path',side_effect=launch):
            self.assertEqual(bootstrap.main(),0)
            self.assertEqual(sys.argv,argv)
        self.assertEqual(events,['preflight','start','prepare','gui','suspend','close'])


if __name__=='__main__':unittest.main()
