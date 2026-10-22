"""Mac setup/recovery preparation without a native Mac or real HA deployment."""
from pathlib import Path
import hashlib,importlib.util,io,json,sys,tempfile,threading,types,unittest,zipfile
from unittest.mock import Mock,patch
MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'app'),str(MODULE/'Runtime/packages')]
import host_runtime,recovery_runtime
spec=importlib.util.spec_from_file_location('setup_macos',MODULE.parent/'PortalAI HA Setup/Setup Files/setup_macos.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)

class SetupTests(unittest.TestCase):
    def test_prepared_package_matches_current_HA_manifest(self):
        with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder:
            archive=setup.prepare(Path(folder)/'ha.zip')
            with zipfile.ZipFile(archive) as z:
                manifest=json.loads(z.read('HomeAssistant/SHA256SUMS.json'))
                self.assertEqual(set(z.namelist()),{'HomeAssistant/'+n for n in [*manifest,'SHA256SUMS.json']})
                for name,digest in manifest.items():self.assertEqual(hashlib.sha256(z.read('HomeAssistant/'+name)).hexdigest(),digest)
            with self.assertRaises(ValueError):setup.prepare(archive)
    def test_destination_inside_payload_refused(self):
        with self.assertRaises(ValueError):setup.prepare(setup.PACKAGE/'bad.zip')
    def test_mac_recovery_selects_bundled_runtime_and_refuses_changed_source(self):
        with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as folder:
            base=Path(folder);module=base/'Projection';root=base/'PortalAI Mac'
            for path in (module/'Runtime/MacPython-arm64/bin/python3.12',module/'app/projection_worker.py',
                         root/'Runtime/MacPython/bin/python3.12',root/'Launchers/portalai_gui_macos.py',
                         root/'ControlCenter/control_center_bootstrap.py',root/'Agent/profile_shutdown.py'):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture, never executed')
            manager=Mock();manager.root=root
            with patch.object(recovery_runtime.sys,'platform','darwin'),patch.object(host_runtime,'mac_arch',return_value='arm64'):
                controller=recovery_runtime.LaunchController({'target':'../PortalAI Mac'},threading.Event(),module=module,manager=manager,snapshot=Mock(return_value={}),scope=module/'state/input/test')
                self.assertEqual(controller.worker_python,module/'Runtime/MacPython-arm64/bin/python3.12')
                exe=str(controller.worker_python)
                rows={42:{'executable':exe,'argv':[exe,'-B','-I',str(module/'app/projection_worker.py')]}}
                self.assertEqual(len(controller.projection_rows(rows)),1)
                controller.verify()
                (module/'app/projection_worker.py').write_bytes(b'changed')
                with self.assertRaises(ValueError):controller.verify()
                controller.close()

if __name__=='__main__':unittest.main()
