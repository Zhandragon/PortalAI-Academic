"""Linux Kornia precedence/integrity without importing any native ML dependency."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import linux_ml


class LinuxCompatibilityTests(unittest.TestCase):
    def setUp(self):
        directory=tempfile.TemporaryDirectory(prefix='Portal Linux compatibility ')
        self.addCleanup(directory.cleanup);self.root=Path(directory.name).resolve()
        self.layer=self.root/'Runtime/LinuxPackages/kornia_compat'
        package=self.layer/'kornia_rs';package.mkdir(parents=True)
        (package/'__init__.py').write_text('# native import intentionally not executed')
        (package/'kornia_rs.so').write_bytes(b'fixture native bytes')
        imports=self.root/'Maintenance/Imports';imports.mkdir(parents=True)
        self.receipt=imports/'linux-kornia_compat-lock.json'
        self.lock={'verified':True,'assets':[{'name':'kornia_rs','version':'0.1.10',
            'sha256':'f332a2a034cc791006f25c2d85e342a060887145e9236e8e43562badcadededf'}],
            'files':[{'path':p.relative_to(self.layer).as_posix(),'bytes':p.stat().st_size,
                'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in package.iterdir()]}
        self.write_lock()
        for backend in linux_ml.BACKENDS.values():
            torch=self.root/'Runtime/LinuxTorch'/backend/'torch';torch.mkdir(parents=True)
            (torch/'__init__.py').touch()
            (imports/f'linux-torch-{backend}.json').write_text('{"verified":true}')
        self.addCleanup(patch.stopall)
        patch.object(sys,'platform','linux').start()
        patch.object(sys,'path',list(sys.path)).start()
        patch.dict(os.environ,{},clear=True).start()
        patch.dict(sys.modules).start()
        for name in ('torch','torchvision','torchaudio','kornia_rs'):sys.modules.pop(name,None)
        patch('runtime_policy.portable_env',return_value={'PATH':''}).start()

    def write_lock(self):self.receipt.write_text(json.dumps(self.lock))

    def test_all_backends_place_only_kornia_override_before_media(self):
        for backend in linux_ml.BACKENDS:
            with self.subTest(backend=backend):
                linux_ml.activate(self.root,backend)
                self.assertLess(sys.path.index(str(self.layer)),sys.path.index(str(self.root/'Runtime/LinuxPackages/media')))
                self.assertNotIn(str(self.root/'Runtime/LinuxPackages/comfyextras'),sys.path)
                self.assertEqual(sys.path[0],str(self.root/'Runtime/LinuxTorch'/linux_ml.BACKENDS[backend]))

    def test_missing_receipt_fails_before_native_imports(self):
        self.receipt.unlink()
        with self.assertRaisesRegex(RuntimeError,'missing'):linux_ml.activate(self.root,'cpu')
        self.assertNotIn('torch',sys.modules)

    def test_changed_native_binary_is_rejected(self):
        (self.layer/'kornia_rs/kornia_rs.so').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'integrity'):linux_ml.activate(self.root,'cpu')

    def test_wrong_version_or_publisher_checksum_is_rejected(self):
        for key,value in (('version','0.1.14'),('sha256','unreviewed')):
            with self.subTest(key=key):
                original=self.lock['assets'][0][key];self.lock['assets'][0][key]=value;self.write_lock()
                with self.assertRaisesRegex(RuntimeError,'reviewed wheel'):linux_ml.activate(self.root,'cpu')
                self.lock['assets'][0][key]=original

    def test_package_path_must_remain_inside_isolated_layer(self):
        self.lock['files'][0]['path']='../outside';self.write_lock()
        with self.assertRaisesRegex(RuntimeError,'path is invalid'):linux_ml.activate(self.root,'cpu')

    def test_old_already_loaded_native_module_cannot_be_silently_reused(self):
        sys.modules['kornia_rs']=SimpleNamespace(__version__='0.1.14',__file__=str(self.root/'Runtime/LinuxPackages/media/kornia_rs/__init__.py'))
        with self.assertRaisesRegex(RuntimeError,'already loaded'):linux_ml.activate(self.root,'cpu')

    def test_repeated_activation_accepts_shared_or_comfy_copy_of_same_version(self):
        for folder in ('kornia_compat','comfyextras'):
            sys.modules['kornia_rs']=SimpleNamespace(__version__='0.1.10',__file__=str(self.root/'Runtime/LinuxPackages'/folder/'kornia_rs/__init__.py'))
            linux_ml.activate(self.root,'cpu')

    def test_matching_version_from_host_packages_is_rejected(self):
        sys.modules['kornia_rs']=SimpleNamespace(__version__='0.1.10',__file__=str(self.root.parent/'host-packages/kornia_rs/__init__.py'))
        with self.assertRaisesRegex(RuntimeError,'already loaded'):linux_ml.activate(self.root,'cpu')


if __name__=='__main__':unittest.main()
