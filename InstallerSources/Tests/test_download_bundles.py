"""Exercise setup without running an installer, downloading, or activating utilities."""
from pathlib import Path
import hashlib, json, shutil, subprocess, tempfile, unittest, zipfile
SOURCE=Path(__file__).resolve().parents[1]/'Bundle'
BASH=Path('C:/Program Files/Git/bin/bash.exe')
class BundlePreparation(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='portalai bundle test ')
        self.root=Path(self.tmp.name)
        for p in SOURCE.iterdir():shutil.copy2(p,self.root/p.name)
        (self.root/'Packages').mkdir()
        self.assets=[]
        for platform in ('Windows','Mac','Linux'):
            p=self.root/'Packages'/f'{platform}.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('PortalAI-Install.exe',b'fixture - must never execute')
            self.assets.append(dict(platform=platform,file=p.name,bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),url='https://example.invalid/no-download'))
        self.manifest=dict(schema=1,version='test',assets=self.assets,windows_installer='PortalAI-Install.exe')
        self.save()
    def tearDown(self):self.tmp.cleanup()
    def save(self):
        (self.root/'bundle.json').write_text(json.dumps(self.manifest))
        (self.root/'assets.tsv').write_text(''.join(f"{a['platform']}\t{a['file']}\t{a['bytes']}\t{a['sha256']}\t{a['url']}\n" for a in self.manifest['assets']))
    def ps(self,*args):
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'prepare-setup.ps1'),*args],cwd=self.root,capture_output=True,text=True,timeout=30)
    def sh(self,*args):
        return subprocess.run([str(BASH),'prepare-setup.sh',*args],cwd=self.root,capture_output=True,text=True,timeout=30)
    def test_three_packages_verify_without_installing(self):
        before=sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        r=self.ps('-VerifyOnly');self.assertEqual(r.returncode,0,r.stderr)
        r=self.sh('--verify-only');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(before,sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*')))
    def test_single_package_prepare_keeps_utilities_optional(self):
        self.manifest['assets']=self.assets[:1];self.save()
        r=self.ps('-PrepareOnly');self.assertEqual(r.returncode,0,r.stderr)
        self.assertFalse((self.root/'Platforms').exists())
        self.assertFalse((self.root/'Utilities').exists())
    def test_extract_only_uses_windows_entry_without_launch(self):
        r=self.ps('-ExtractOnly');self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual((self.root/'Platforms/Windows-test/PortalAI-Install.exe').read_bytes(),b'fixture - must never execute')
    def test_academic_entrypoint(self):
        p=self.root/'Packages/Windows.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('PortalAI-Academic-Install.exe',b'Academic fixture')
        a=self.assets[0];a['bytes']=p.stat().st_size;a['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest['windows_installer']='PortalAI-Academic-Install.exe';self.save()
        r=self.ps('-ExtractOnly');self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((self.root/'Platforms/Windows-test/PortalAI-Academic-Install.exe').is_file())
    def test_corrupt_package_rejected_in_both_shells(self):
        (self.root/'Packages/Windows.zip').write_bytes(b'corrupt')
        for r in [self.ps('-VerifyOnly'),self.sh('--verify-only')]:self.assertNotEqual(r.returncode,0)
        self.assertFalse((self.root/'Platforms').exists())
    def test_missing_package_rejected_without_network(self):
        (self.root/'Packages/Windows.zip').unlink()
        for r in [self.ps('-PrepareOnly'),self.sh('--prepare-only')]:self.assertNotEqual(r.returncode,0)
    def test_duplicate_platform_rejected(self):
        self.manifest['assets'][1]['platform']='Windows';self.save()
        for r in [self.ps('-VerifyOnly'),self.sh('--verify-only')]:self.assertNotEqual(r.returncode,0)
    def test_existing_extraction_preserved(self):
        p=self.root/'Platforms/Windows-test';p.mkdir(parents=True);(p/'keep.txt').write_text('keep')
        r=self.ps('-ExtractOnly');self.assertNotEqual(r.returncode,0)
        self.assertEqual((p/'keep.txt').read_text(),'keep')
    def test_wrong_os_bundle_rejected(self):
        self.manifest['assets']=self.assets[1:2];self.save()
        r=self.ps('-ExtractOnly');self.assertNotEqual(r.returncode,0)
        self.assertFalse((self.root/'Platforms').exists())
if __name__=='__main__':unittest.main()

