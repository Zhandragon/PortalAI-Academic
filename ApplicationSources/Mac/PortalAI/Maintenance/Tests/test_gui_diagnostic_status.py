"""Execute real GUI report branches against synthetic events, without a login."""
import ast
from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
from diagnostic_catalog import CHOICES,resolve


def source():
    return ast.parse((ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8-sig'))


def dispatch(kind,data,*,saved=False):
    marker='system_test_complete' if kind=='system_test_complete' else 'diagnostic_complete'
    node=next(node for node in ast.walk(source()) if isinstance(node,ast.If)
              and any(isinstance(part,ast.Constant) and part.value==marker for part in ast.walk(node.test)))
    # This branch normally lives inside the GUI's event queue loop. Keep its
    # actual continue statement and run a single synthetic loop iteration.
    loop=ast.For(target=ast.Name(id='_event',ctx=ast.Store()),iter=ast.Tuple(elts=[ast.Constant(None)],ctx=ast.Load()),
                 body=[deepcopy(node)],orelse=[])
    module=ast.fix_missing_locations(ast.Module(body=[loop],type_ignores=[]))
    namespace={'kind':kind,'data':data,'system_test_state':{'running':True},'log':Mock(),
               '_show_text_report':Mock(),'_show_saved_report':Mock(return_value=saved),'force_scan':Mock()}
    exec(compile(module,'<actual GUI diagnostic event branch>','exec'),namespace)
    return namespace


class ReportEvents(unittest.TestCase):
    def test_zero_exit_warning_and_failure_are_not_green(self):
        for kind in ('system_test_complete','diagnostic_complete','storage_report_complete'):
            for status in ('WARN','FAIL','UNVERIFIED'):
                with self.subTest(kind=kind,status=status):
                    namespace=dispatch(kind,{'returncode':0,'status':status,'text':'fixture'})
                    self.assertFalse(namespace['_show_text_report'].call_args.kwargs['ok'])

    def test_explicit_pass_and_legacy_failure_keep_their_meaning(self):
        for kind in ('system_test_complete','diagnostic_complete','storage_report_complete'):
            passed=dispatch(kind,{'returncode':0,'status':'PASS'})
            self.assertTrue(passed['_show_text_report'].call_args.kwargs['ok'])
            failed=dispatch(kind,{'returncode':2})
            self.assertFalse(failed['_show_text_report'].call_args.kwargs['ok'])

    def test_saved_evidence_is_not_overwritten_by_fallback_success(self):
        for kind in ('diagnostic_complete','storage_report_complete'):
            namespace=dispatch(kind,{'returncode':0,'status':'WARN','report_key':'fixture'},saved=True)
            namespace['_show_saved_report'].assert_called_once_with('fixture','PortableAI Report')
            namespace['_show_text_report'].assert_not_called()

    def test_runtime_selector_uses_same_report_keys_as_cli(self):
        function=next(node for node in ast.walk(source()) if isinstance(node,ast.FunctionDef) and node.name=='_component_diag_info')
        module=ast.fix_missing_locations(ast.Module(body=[deepcopy(function)],type_ignores=[]))
        for choice in CHOICES:
            namespace={'resolve_diagnostic':resolve,'diag_component_var':SimpleNamespace(get=lambda:choice)}
            exec(compile(module,'<actual GUI diagnostic selector>','exec'),namespace)
            argument,label,key,title=namespace['_component_diag_info']()
            expected=resolve(choice)
            self.assertEqual((argument,label,key),(expected['argument'],expected['label'],expected['report_key']))
            self.assertIn(label,title)


if __name__=='__main__':unittest.main()
