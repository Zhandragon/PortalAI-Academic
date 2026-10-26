"""Execute the install scripts' actual default-path expressions without installing."""
import os
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
BASH = str(Path('C:/Program Files/Git/bin/bash.exe')) if os.name == 'nt' else shutil.which('bash')

@unittest.skipUnless(BASH and Path(BASH).is_file(), 'Shell expression check requires Bash')
class PortablePlacementTests(unittest.TestCase):
    def check_script(self, source, variable, folder):
        if not source.exists():
            self.skipTest('Platform installer source is excluded from this distribution')
        lines = source.read_text().splitlines()
        # Exercise the source expressions, not a second implementation of them.
        directory = next(line for line in lines if line.startswith(variable+'='))
        destination = next(line for line in lines if line.startswith('DEST='))
        with tempfile.TemporaryDirectory(prefix='PortalAI placement ') as temp:
            parent = Path(temp)
            package = parent/'Nested package with spaces';package.mkdir()
            elsewhere = parent/'Different working directory';elsewhere.mkdir()
            probe = package/'path-probe.sh'
            probe.write_text(directory+'\n'+destination+'\nprintf "%s\\n" "$DEST"\n', encoding='utf-8', newline='\n')
            env = os.environ.copy();env.pop('PORTALAI_INSTALL_DIR', None)
            def run(args=(), environment=env):
                return subprocess.run([BASH, str(probe), *args], cwd=elsewhere, env=environment,
                                      check=True, capture_output=True, text=True, timeout=15).stdout.strip()
            default = run()
            self.assertTrue(default.endswith('/Nested package with spaces/'+folder), default)
            self.assertNotIn('Different working directory', default)
            self.assertEqual(run(environment={**env, 'PORTALAI_INSTALL_DIR':'/chosen/from-env'}), '/chosen/from-env')
            self.assertEqual(run(('/chosen/explicit',), {**env,'PORTALAI_INSTALL_DIR':'/chosen/from-env'}), '/chosen/explicit')
            self.assertFalse((package/folder).exists())

    def test_linux_follows_installer_location_and_explicit_overrides(self):
        self.check_script(ROOT/'Installer/Linux/install.sh', 'SCRIPT_DIR', 'PortalAI Linux')

    def test_mac_follows_installer_location_and_explicit_overrides(self):
        self.check_script(ROOT/'Installer/Mac/install-macos.sh', 'SELF_DIR', 'PortalAI Mac')

class LinuxPayloadOverlayTests(unittest.TestCase):
    def builder(self):
        source = ROOT/'Tools/build_linux_installer.py'
        if not source.exists():self.skipTest('Linux builder source not included')
        spec=importlib.util.spec_from_file_location('placement_linux_builder',source)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module

    def test_updated_docs_in_source_are_replaced_once_by_local_overlays(self):
        builder=self.builder()
        with tempfile.TemporaryDirectory(prefix='PortalAI payload fixture ') as temp:
            root=Path(temp);(root/'Documentation').mkdir()
            files=['README.md','Documentation/Linux_Clean_Installer_20261017.txt',
                   'Documentation/Mac_Compatibility_Review_20261017.txt']
            for name in files:(root/name).write_text('Current '+name,encoding='utf-8')
            script=root/'install.py';script.write_text('# synthetic public installer')
            launcher=root/'run-python';launcher.write_text('# synthetic launcher')
            source=root/'source.zip'
            with zipfile.ZipFile(source,'w') as archive:
                for name in files:archive.writestr('PortalAI/'+name,'Previous version')
                archive.writestr('PortalAI/Agent/example.py','# unchanged')
            with patch.object(builder,'ROOT',root),patch.object(builder,'LAUNCHER',launcher):
                entries,_,_=builder.code_payload_entries(source,'synthetic','synthetic',[],[],[],script)
            names=[row[0] for row in entries]
            self.assertEqual(len(names),len(set(names)))
            by_name={row[0]:row[1] for row in entries}
            for name in files:self.assertEqual(by_name['PortalAI/'+name],(root/name).read_bytes())
            self.assertEqual(by_name['PortalAI/Agent/example.py'],b'# unchanged')

if __name__ == '__main__':unittest.main()
