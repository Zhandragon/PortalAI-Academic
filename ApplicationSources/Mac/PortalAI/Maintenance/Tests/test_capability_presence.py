"""Installed means the current platform's payload exists, not just a dispatcher."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
import capability_registry as registry


class CapabilityPresence(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        for relative in ('Scientific/science_core.py','Agent/scientific_tool_bridge.py',
                         'Runtime/ScientificPython/packages/openmm/__init__.py',
                         'Runtime/LinuxPackages/science/openmm/__init__.py'):
            self.put(relative)
        self.put('Agent/ai_tools.py',"sub.add_parser('science')")
        self.put('Agent/service_manager.py',"science_workload='openmm-cuda'")

    def put(self,relative,contents='fixture'):
        path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(contents)

    def rows(self,linux=False):
        with patch.object(registry,'os',SimpleNamespace(name='posix' if linux else 'nt')), patch.object(registry,'_port',return_value=False):
            return {row['key']:row for row in registry.detect(self.root)['capabilities']}

    def test_cuda_lease_without_plugin_is_not_installed(self):
        for linux in (False,True):
            with self.subTest(linux=linux):
                rows=self.rows(linux)
                self.assertTrue(rows['science_electrical']['installed'])
                self.assertFalse(rows['science_cuda']['installed'])
                self.assertFalse(rows['science_opencl']['installed'])

    def test_plugin_inventory_is_platform_specific(self):
        self.put('Runtime/ScientificPython/packages/OpenMM.libs/lib/plugins/OpenMMOpenCL.dll')
        self.put('Runtime/LinuxPackages/science/OpenMM.libs/lib/plugins/libOpenMMCUDA.so')
        windows,linux=self.rows(),self.rows(True)
        self.assertTrue(windows['science_opencl']['installed'])
        self.assertFalse(windows['science_cuda']['installed'])
        self.assertTrue(linux['science_cuda']['installed'])
        self.assertFalse(linux['science_opencl']['installed'])

    def test_linux_kicad_launcher_requires_payload_and_does_not_satisfy_windows(self):
        self.put('Runtime/KiCad/linux-x64/bin/kicad-cli')
        self.assertFalse(self.rows(True)['science_kicad']['installed'])
        self.put('Runtime/LinuxSystem/kicad/usr/bin/kicad-cli')
        self.assertTrue(self.rows(True)['science_kicad']['installed'])
        self.assertFalse(self.rows()['science_kicad']['installed'])


if __name__=='__main__':unittest.main()
