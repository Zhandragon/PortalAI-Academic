"""Portable certificate assets must accompany every web-enabled installer."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'Tools'))
from web_installer_assets import certificate_files, native_web_path

class CertificateAssets(unittest.TestCase):
    def fixture(self,root):
        data=b'public certificate fixture'
        (root/'Agent').mkdir()
        (root/'Runtime/Certificates').mkdir(parents=True)
        (root/'Runtime/Certificates/cacert.pem').write_bytes(data)
        (root/'Runtime/Certificates/LICENSE.certifi').write_text('Fixture license')
        (root/'Agent/web_tls.py').write_text("BUNDLE_RELATIVE='Runtime/Certificates/cacert.pem'\nBUNDLE_BYTES="+str(len(data))+"\nBUNDLE_SHA256="+repr(hashlib.sha256(data).hexdigest())+'\n')
    def test_exact_pinned_assets_on_each_platform(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            rows=list(certificate_files(root));self.assertEqual(len(rows),2)
            for platform in ('Windows','Linux','Mac'):
                self.assertTrue(all(native_web_path(name,platform) for name,path in rows))
    def test_corrupt_bundle_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            (root/'Runtime/Certificates/cacert.pem').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'differs'):list(certificate_files(root))
    def test_missing_license_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);self.fixture(root)
            (root/'Runtime/Certificates/LICENSE.certifi').unlink()
            with self.assertRaisesRegex(RuntimeError,'missing'):list(certificate_files(root))

if __name__=='__main__':unittest.main()
