import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import os

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gui_stop_contract',ROOT/'Launchers/Stop_PortableAI.py')
stop=importlib.util.module_from_spec(spec);spec.loader.exec_module(stop)


class StopContractTests(unittest.TestCase):
    def test_external_descendants_are_owned_only_with_valid_parent_creation(self):
        parent={'ProcessId':424242,'ParentProcessId':0,'StartTicks':'10','ExecutablePath':str(ROOT/'Runtime/python.exe'),'CommandLine':'owned hook'}
        child={'ProcessId':424243,'ParentProcessId':424242,'StartTicks':'20','ExecutablePath':'C:/Windows/System32/cmd.exe','CommandLine':'cmd /c owned job'}
        unrelated={**child,'ProcessId':424244,'StartTicks':'5'}
        pids,_=stop.portable_process_pids(ROOT,[parent,child,unrelated])
        self.assertEqual(pids,{424242,424243})
        pids,_=stop.portable_process_pids(ROOT,[child],known={424243:child})
        self.assertEqual(pids,{424243})
        pids,_=stop.portable_process_pids(ROOT,[{**child,'StartTicks':'30'}],known={424243:child})
        self.assertFalse(pids)
    def test_unknown_owned_worker_is_a_component(self):
        worker={'ProcessId':424242,'ParentProcessId':0,'StartTicks':'1',
                'ExecutablePath':str(ROOT/'Runtime/BootstrapPython/python.exe'),
                'CommandLine':'python newly_installed_custom_hook.py'}
        with patch.object(stop,'cim_processes',return_value=[worker]):
            pids,_=stop.portable_process_pids(ROOT)
        self.assertIn(424242,pids)

    def test_host_python_direct_owned_script_is_a_component(self):
        worker={'ExecutablePath':'C:/HostPython/python.exe',
                'CommandLine':subprocess.list2cmdline(['python','-B',str(ROOT/'Tools/new_hook.py')])}
        self.assertTrue(stop.owned_process(ROOT,worker))
        worker['CommandLine']=subprocess.list2cmdline(['python','-c','print('+repr(str(ROOT))+')'])
        self.assertFalse(stop.owned_process(ROOT,worker))

    def test_owned_child_path(self):
        self.assertTrue(stop.owned_process(ROOT,{'ExecutablePath':str(ROOT/'Runtime/python.exe')}))

    def test_prefix_sibling_not_owned(self):
        self.assertFalse(stop.owned_process(ROOT,{'ExecutablePath':str(ROOT)+'-other/Runtime/python.exe'}))

    def test_argument_mention_not_ownership(self):
        self.assertFalse(stop.owned_process(ROOT,{'ExecutablePath':'C:/Other/worker.exe','CommandLine':'worker --read '+str(ROOT)}))

    def test_explicit_owned_powershell_file(self):
        row={'ExecutablePath':'C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe',
             'CommandLine':subprocess.list2cmdline(['powershell.exe','-NoProfile','-File',str(ROOT/'Launchers/Start_Qwen_Hidden.ps1')])}
        self.assertTrue(stop.owned_process(ROOT,row))
        row['CommandLine']=subprocess.list2cmdline(['powershell.exe','-File',str(ROOT/'Launchers/../../Other/Start_Qwen_Hidden.ps1')])
        self.assertFalse(stop.owned_process(ROOT,row))
        row['CommandLine']='powershell -Command "Write-Output '+str(ROOT)+'"'
        self.assertFalse(stop.owned_process(ROOT,row))

    def test_unknown_identity_not_owned(self):
        self.assertFalse(stop.owned_process(ROOT,{'CommandLine':str(ROOT/'Agent/mission_runner.py')}))

    def test_failed_inventory_cannot_report_clean_shutdown(self):
        with patch.object(stop,'run',return_value=subprocess.CompletedProcess([],1,'','failed')):
            with self.assertRaises(RuntimeError):stop.cim_processes()

    def test_gui_and_its_launch_ancestors_are_never_components(self):
        gui={'ProcessId':101,'ParentProcessId':100,'StartTicks':'20',
             'ExecutablePath':str(ROOT/'Runtime/pythonw.exe'),
             'CommandLine':subprocess.list2cmdline(['pythonw',str(ROOT/'ControlCenter/control_center_bootstrap.py')])}
        parent={'ProcessId':100,'ParentProcessId':0,'StartTicks':'10',
                'ExecutablePath':str(ROOT/'Runtime/python.exe'),'CommandLine':'start_portableai_controller'}
        helper={'ProcessId':os.getpid(),'ParentProcessId':101,'StartTicks':'30'}
        with patch.object(stop,'cim_processes',return_value=[gui,parent,helper]):
            pids,_=stop.portable_process_pids(ROOT)
        self.assertFalse(pids)
        self.assertTrue({100,101,os.getpid()} <= stop.protected_pids({100:parent,101:gui,os.getpid():helper}))

    def test_reused_parent_is_not_adopted_as_gui_ancestor(self):
        rows={101:{'ParentProcessId':100,'StartTicks':'20','CommandLine':'python PortableAI_GUI.py'},
              100:{'ParentProcessId':0,'StartTicks':'30'}}
        self.assertNotIn(100,stop.protected_pids(rows))

    def test_stop_binds_to_creation_identity_and_never_taskkills_a_tree(self):
        row={'StartTicks':'123456','ExecutablePath':str(ROOT/'LLM/llama-server.exe')}
        with patch('profile_shutdown._windows_stop') as terminate, patch.object(stop,'run',side_effect=AssertionError('no taskkill')):
            self.assertTrue(stop.kill(1234,ROOT,row)[0])
            terminate.assert_called_once_with({'pid':1234,'start':123456,'executable':row['ExecutablePath']},ROOT)
            terminate.reset_mock()
            self.assertFalse(stop.kill(1234,ROOT,{'ExecutablePath':row['ExecutablePath']})[0])
            terminate.assert_not_called()


if __name__=='__main__':unittest.main()
