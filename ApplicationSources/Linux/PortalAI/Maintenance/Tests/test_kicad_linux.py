"""Synthetic root path/ownership tests; actual exports run in the Linux guest."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Scientific')]
import kicad_linux as kicad
import profile_paths
import science_core


class LinuxKiCad(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve()
        env=patch.dict(os.environ,{},clear=True);env.start();self.addCleanup(env.stop)

    def payload(self):
        base=self.root/'Runtime/LinuxSystem/kicad'
        for relative in ('usr/lib/kicad/ld-linux-x86-64.so.2','usr/bin/kicad-cli',
                         'usr/lib/kicad/_eeschema.kiface','usr/lib/kicad/_pcbnew.kiface'):
            path=base/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
        return base

    def active(self,state='open'):
        uid='a'*32;epoch='b'*32
        marker=self.root/'Private/active-session.json';marker.parent.mkdir(exist_ok=True)
        marker.write_text(json.dumps({'user_id':uid,'epoch':epoch,'state':state}))
        os.environ.update(PORTALAI_PROFILE_ID=uid,PORTALAI_PROFILE_EPOCH=epoch)
        return self.root/'Private/Users'/uid/'Workspace'

    def test_legacy_env_only_uses_bundled_libs_resources_private_state(self):
        payload=self.payload()
        os.environ.update(LD_LIBRARY_PATH='/host/libs',LD_PRELOAD='/host/hook.so',LD_AUDIT='/host/audit',
                          KICAD_RUN_FROM_BUILD_DIR='1',PYTHONHOME='/host/python')
        command,env=kicad.command_environment(self.root)
        self.assertEqual(Path(command[-1]),payload/'usr/bin/kicad-cli')
        self.assertEqual(Path(command[0]),payload/'usr/lib/kicad/ld-linux-x86-64.so.2')
        for key in ('LD_LIBRARY_PATH','LD_PRELOAD','LD_AUDIT','KICAD_RUN_FROM_BUILD_DIR'):
            self.assertNotIn(key,env)
        self.assertEqual(env['PYTHONHOME'],str(payload/'usr'))
        self.assertEqual(env['KICAD_STOCK_DATA_HOME'],str(payload/'usr/share/kicad'))
        self.assertTrue(Path(env['TMPDIR']).is_relative_to(self.root/'Data/Science/KiCad'))
        self.assertNotIn('/usr/share/fonts</dir>',Path(env['FONTCONFIG_FILE']).read_text())

    def test_active_vendor_state_and_fonts_follow_profile(self):
        self.payload();workspace=self.active()
        _,env=kicad.command_environment(self.root)
        for key in ('HOME','XDG_CONFIG_HOME','KICAD_CONFIG_HOME','KICAD_DOCUMENTS_HOME','FONTCONFIG_FILE','TMPDIR'):
            self.assertTrue(Path(env[key]).is_relative_to(workspace/'Data/Science/KiCad'),key)
        self.assertFalse((self.root/'Data').exists())

    def test_locked_is_refused_before_any_vendor_state(self):
        self.payload();self.active('closed')
        with self.assertRaises(profile_paths.ProfileLocked):kicad.command_environment(self.root)
        self.assertFalse((self.root/'Data').exists())
        self.assertFalse((self.root/'Private/Users').exists())

    def test_missing_native_payload_refused_before_configuration_write(self):
        with self.assertRaisesRegex(RuntimeError,'incomplete'):kicad.command_environment(self.root)
        self.assertFalse((self.root/'Data').exists())

    def test_linux_export_uses_owned_worker_and_ram_cap(self):
        import linux_owned_run
        out=self.root/'Outputs/out';out.mkdir(parents=True)
        with patch.object(science_core,'os',SimpleNamespace(name='posix')), \
             patch.object(science_core,'_find_kicad',return_value='/portable/kicad'), \
             patch.object(science_core,'_outdir',return_value=out), \
             patch.object(science_core,'media_reference',return_value=self.root/'input.kicad_sch'), \
             patch.object(linux_owned_run,'run',return_value=subprocess.CompletedProcess([],0,'exported','')) as run:
            result=science_core.op_electrical_kicad_export({'input':'input.kicad_sch'},self.root)
        self.assertEqual(run.call_args.kwargs['memory_bytes'],2*1024**3)
        self.assertEqual(run.call_args.kwargs['cwd'],self.root)
        self.assertEqual(result['stdout'],'exported')


if __name__=='__main__':unittest.main()
