"""Exercise the actual fresh-install engine on synthetic, data-free payloads."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
core=None
if (ROOT/'Installer/Windows/installer_core.py').is_file():
    spec=importlib.util.spec_from_file_location('windows_installer_core', ROOT/'Installer/Windows/installer_core.py')
    core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)

@unittest.skipIf(core is None,'Windows installer source is excluded from native Linux/Mac packages')
class WindowsInstallerLayoutTests(unittest.TestCase):
    def make_package(self, parent):
        package = parent/'Nested installer with spaces'
        package.mkdir()
        data = b'Synthetic public source'
        row = {'member': 'PortalAI/Agent/example.py', 'dest': 'PortalAI Windows/Agent/example.py',
               'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        payload = package/'payload.zip'
        with zipfile.ZipFile(payload, 'w') as archive:
            archive.writestr(row['member'], data)
        manifest = {'schema': 1, 'status': 'RELEASED', 'release': 'in-place-fixture',
                    'components': [], 'payload': {'file': 'payload.zip',
                    'bytes': payload.stat().st_size, 'sha256': core.sha256(payload), 'members': [row]}}
        (package/'release.json').write_text(json.dumps(manifest), encoding='utf-8')
        return package, data, row

    def test_in_place_install_preserves_package_and_unrelated_files(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI installer ') as tmp:
            package, data, row = self.make_package(Path(tmp))
            (package/'Personal notes.txt').write_text('Preserve this')
            before = core.sha256(package/'payload.zip')
            report = core.install(package, package, [])
            self.assertEqual(report['verified_files'], 1)
            self.assertEqual((package/row['dest']).read_bytes(), data)
            self.assertEqual((package/'Personal notes.txt').read_text(), 'Preserve this')
            self.assertEqual(core.sha256(package/'payload.zip'), before)
            self.assertFalse(list(package.glob('.PortalAI-installing-*')))
            with self.assertRaisesRegex(core.InstallError, 'already exists beside'):
                core.install(package, package, [])
            self.assertEqual((package/row['dest']).read_bytes(), data)

    def test_in_place_refuses_existing_app_before_extraction(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI installer ') as tmp:
            package, _, _ = self.make_package(Path(tmp))
            existing = package/'PortalAI Windows'; existing.mkdir()
            (existing/'Owner.txt').write_text('Private fixture')
            with patch.object(core, 'extract_allowlist') as extract:
                with self.assertRaisesRegex(core.InstallError, 'already exists beside'):
                    core.install(package, package, [])
                extract.assert_not_called()
            self.assertEqual((existing/'Owner.txt').read_text(), 'Private fixture')

    def test_cancellation_publishes_nothing(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI installer ') as tmp:
            package, _, _ = self.make_package(Path(tmp))
            stop = threading.Event()
            extract = core.extract_allowlist
            def cancel_after_extract(*args):
                extract(*args); stop.set()
            with patch.object(core, 'extract_allowlist', side_effect=cancel_after_extract):
                with self.assertRaises(core.Cancelled):core.install(package, package, [], stop)
            self.assertFalse((package/'PortalAI Windows').exists())
            self.assertFalse((package/'INSTALL_RECEIPT.json').exists())

    def test_destination_appearing_during_install_is_preserved(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI installer ') as tmp:
            package, _, _ = self.make_package(Path(tmp))
            extract = core.extract_allowlist
            def create_competing_destination(*args):
                extract(*args)
                (package/'PortalAI Windows').mkdir()
                (package/'PortalAI Windows/Owner.txt').write_text('Concurrent owner')
            with patch.object(core, 'extract_allowlist', side_effect=create_competing_destination):
                with self.assertRaisesRegex(core.InstallError, 'Destination appeared'):
                    core.install(package, package, [])
            self.assertEqual((package/'PortalAI Windows/Owner.txt').read_text(), 'Concurrent owner')
            self.assertFalse((package/'INSTALL_RECEIPT.json').exists())

    def test_legacy_and_current_private_paths_are_both_rejected(self):
        for root in ('PortalAI', 'PortalAI Windows'):
            self.assertEqual(core.public_destination(root+'/Agent/example.py'), root+'/Agent/example.py')
            for suffix in ('Private', 'Private/Accounts/registry.json', 'Outputs/chat.txt', 'Cache/token',
                           'Generative/ComfyUI_windows_portable/ComfyUI/input/photo.png',
                           'Generative/ComfyUI_windows_portable/ComfyUI/user/session.json'):
                with self.subTest(root=root, suffix=suffix), self.assertRaises(core.InstallError):
                    core.public_destination(root+'/'+suffix)

    @unittest.skipUnless(os.name == 'nt', 'Windows extended-path regression')
    def test_deep_payload_destination_exceeds_legacy_windows_limit(self):
        # Give TemporaryDirectory an extended root so cleanup uses the same API.
        with tempfile.TemporaryDirectory(prefix='PortalAI long ', dir=core.native_path(tempfile.gettempdir())) as tmp:
            package, data, row = self.make_package(Path(tmp))
            row['dest'] = 'PortalAI Windows/' + '/'.join(['Long public module directory'] * 9) + '/example.py'
            manifest = json.loads((package/'release.json').read_text())
            manifest['payload']['members'] = [row]
            (package/'release.json').write_text(json.dumps(manifest), encoding='utf-8')
            report = core.install(package, package, [])
            installed = core.checked_path(package, row['dest'])
            self.assertGreater(len(str(installed)), 260)
            self.assertEqual(installed.read_bytes(), data)
            self.assertEqual(report['verified_files'], 1)

    def test_new_layout_and_private_paths(self):
        for path in ('PortalAI Windows/Agent/runtime_policy.py','Start PortalAI Windows.cmd',
                     'Start PortalAI Linux.sh','Start PortalAI Mac.command','PortalAI.exe'):
            self.assertEqual(core.public_destination(path),path)
        for path in ('PortalAI Windows/Private/Accounts/registry.json',
                     'PortalAI Windows/Outputs/chat.txt','PortalAI Windows/Cache/token',
                     'PortalAI Windows/Generative/ComfyUI_windows_portable/ComfyUI/user/secret',
                     'Utilities/PortalAI-Projection/Connections/private.json',
                     'PortalAI Windows/../secret','arbitrary.cmd'):
            with self.assertRaises(core.InstallError):core.public_destination(path)

    def test_install_to_new_portable_folder_and_preserve_existing_destination(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI installer fixture ') as tmp:
            parent=Path(tmp);package=parent/'Package';package.mkdir()
            data=b'Synthetic public application source only'
            row={'member':'PortalAI/Agent/example.py','dest':'PortalAI Windows/Agent/example.py',
                 'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
            payload=package/'payload.zip'
            with zipfile.ZipFile(payload,'w') as archive:archive.writestr(row['member'],data)
            manifest={'schema':1,'status':'RELEASED','release':'synthetic-test',
                      'components':[{'id':'app','required':True,'artifacts':[]}],
                      'payload':{'file':'payload.zip','bytes':payload.stat().st_size,
                                 'sha256':core.sha256(payload),'members':[row]}}
            (package/'release.json').write_text(json.dumps(manifest),encoding='utf-8')
            destination=parent/'Portable install'
            core.install(package,destination,[])
            self.assertEqual((destination/row['dest']).read_bytes(),data)
            self.assertFalse((destination/'PortalAI Windows/Private').exists())
            with self.assertRaises(core.InstallError):core.install(package,destination,[])
            self.assertEqual((destination/row['dest']).read_bytes(),data)

if __name__=='__main__':unittest.main()
