"""Windows KiCad may not use host state or initialize a locked account."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import kicad_windows
from profile_paths import ProfileLocked


class KiCadWindowsTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name).resolve()
        env=patch.dict(os.environ,{},clear=True);env.start();self.addCleanup(env.stop)

    def payload(self):
        base=self.root/'Tools/KiCad'
        for rel in ('bin/kicad-cli.exe','share/kicad/symbols/Device.kicad_sym',
                    'share/kicad/footprints/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod'):
            file=base/rel;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'fixture')
        return base

    def active(self,state='open'):
        uid='a'*32;epoch='b'*32
        marker=self.root/'Private/active-session.json';marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'user_id':uid,'epoch':epoch,'state':state}))
        os.environ.update(PORTALAI_PROFILE_ID=uid,PORTALAI_PROFILE_EPOCH=epoch)
        return self.root/'Private/Users'/uid/'Workspace'

    def test_bundled_resources_and_private_configuration(self):
        base=self.payload();workspace=self.active()
        os.environ.update(APPDATA='C:/host/config',LOCALAPPDATA='C:/host/cache',PYTHONPATH='C:/host/python',
                          PYTHONHOME='C:/host/python',KICAD_RUN_FROM_BUILD_DIR='1',PORTALAI_ACCOUNT_UNLOCK='secret')
        command,env=kicad_windows.command_environment(self.root)
        self.assertEqual(command,[str(base/'bin/kicad-cli.exe')])
        for key in ('APPDATA','LOCALAPPDATA','HOME','USERPROFILE','TMP','KICAD_CONFIG_HOME'):
            self.assertTrue(Path(env[key]).is_relative_to(workspace/'Data/Science/KiCad'),key)
        for key in ('PYTHONHOME','PYTHONPATH','KICAD_RUN_FROM_BUILD_DIR','PORTALAI_ACCOUNT_UNLOCK'):
            self.assertNotIn(key,env)
        self.assertEqual(Path(env['KICAD9_3DMODEL_DIR']),base/'share/kicad/3dmodels')
        self.assertFalse((self.root/'Data').exists())

    def test_locked_refused_before_vendor_writes(self):
        self.payload();self.active('closed')
        with self.assertRaises(ProfileLocked):kicad_windows.command_environment(self.root)
        self.assertFalse((self.root/'Private/Users').exists())
        self.assertFalse((self.root/'Data').exists())

    def test_incomplete_payload_refused_before_configuration(self):
        with self.assertRaisesRegex(RuntimeError,'incomplete'):kicad_windows.command_environment(self.root)
        self.assertFalse((self.root/'Data').exists())

    def test_vendor_bytecode_is_not_a_first_party_cleanup_candidate(self):
        sys.path.insert(0,str(ROOT/'Tools'))
        from storage_current import safe_candidates
        from storage_audit import find_safe_candidates
        for rel in ('Tools/KiCad/lib/__pycache__/vendor.pyc',
                    'Tools/KiCad.staging-9.0.2/lib/__pycache__/vendor.pyc',
                    'Tools/__pycache__/owned.pyc'):
            file=self.root/rel;file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'cache fixture')
        self.assertEqual([row['path'] for row in safe_candidates(self.root)],['Tools/__pycache__/owned.pyc'])
        self.assertEqual([row.path for row in find_safe_candidates(self.root)],[str(self.root/'Tools/__pycache__')])


if __name__=='__main__':unittest.main()
