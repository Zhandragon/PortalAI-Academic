import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('gui_stop_contract',ROOT/'Launchers/Stop_PortableAI.py')
stop=importlib.util.module_from_spec(spec);spec.loader.exec_module(stop)


class StopContractTests(unittest.TestCase):
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


if __name__=='__main__':unittest.main()
