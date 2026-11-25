"""Exercise setup without running an installer, downloading, or activating utilities."""
from pathlib import Path
import hashlib, json, shutil, subprocess, tempfile, unittest, zipfile, time, tarfile, io, os
SOURCE=Path(__file__).resolve().parents[1]/'Bundle'
BASH=Path('C:/Program Files/Git/bin/bash.exe')
@unittest.skipUnless(os.name=='nt' and BASH.exists(), 'Requires Windows PowerShell and Git Bash; verified locally before publication')
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
        (self.root/'Setup').mkdir()
        self.launcher=b'updated fixture - must never execute'
        (self.root/'Setup/PortalAI-Setup.exe').write_bytes(self.launcher)
        self.manifest['windows_launcher']=dict(file='Setup/PortalAI-Setup.exe',bytes=len(self.launcher),sha256=hashlib.sha256(self.launcher).hexdigest())
        data=b'{"fixture":"optional model catalog"}'
        p=self.root/'Setup/Windows/model-overlay.json';p.parent.mkdir();p.write_bytes(data)
        self.manifest['setup_files']=[dict(file='Setup/Windows/model-overlay.json',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())]
        self.save()
    def tearDown(self):self.tmp.cleanup()
    def save(self):
        (self.root/'bundle.json').write_text(json.dumps(self.manifest))
        (self.root/'assets.tsv').write_text(''.join(f"{a['platform']}\t{a['file']}\t{a['bytes']}\t{a['sha256']}\t{a['url']}\n" for a in self.manifest['assets']))
        (self.root/'setup.tsv').write_text(''.join(f"{r['file']}\t{r['bytes']}\t{r['sha256']}\n" for r in self.manifest.get('setup_files',[])),newline='\n')
    def ps(self,*args,answer=None):
        return subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(self.root/'prepare-setup.ps1'),*args],cwd=self.root,capture_output=True,text=True,input=answer,timeout=30)
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
        self.assertEqual((self.root/'Platforms/Windows-test/PortalAI-Install.exe').read_bytes(),self.launcher)
        self.assertEqual((self.root/'Platforms/Windows-test/model-overlay.json').read_bytes(),(self.root/'Setup/Windows/model-overlay.json').read_bytes())
        self.assertFalse((self.root/'Platforms/Windows-test/PortalAI Windows').exists())
    def test_corrupt_model_catalog_rejected_before_extraction(self):
        (self.root/'Setup/Windows/model-overlay.json').write_bytes(b'corrupt')
        for r in [self.ps('-VerifyOnly'),self.sh('--verify-only')]:self.assertNotEqual(r.returncode,0)
        self.assertFalse((self.root/'Platforms').exists())
    def test_bundle4_requires_model_catalog(self):
        self.manifest['version']='2026.11.25-bundle4';self.save()
        self.assertNotEqual(self.ps('-VerifyOnly').returncode,0)
    def test_academic_entrypoint(self):
        p=self.root/'Packages/Windows.zip'
        with zipfile.ZipFile(p,'w') as z:z.writestr('PortalAI-Academic-Install.exe',b'Academic fixture')
        a=self.assets[0];a['bytes']=p.stat().st_size;a['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
        self.manifest['windows_installer']='PortalAI-Academic-Install.exe';self.save()
        r=self.ps('-ExtractOnly');self.assertEqual(r.returncode,0,r.stderr)
        self.assertTrue((self.root/'Platforms/Windows-test/PortalAI-Academic-Install.exe').is_file())
        self.assertEqual((self.root/'Platforms/Windows-test/PortalAI-Academic-Install.exe').read_bytes(),self.launcher)
    def test_corrupt_setup_launcher_rejected_before_extraction(self):
        (self.root/'Setup/PortalAI-Setup.exe').write_bytes(b'bad')
        self.assertNotEqual(self.ps('-ExtractOnly').returncode,0)
        self.assertFalse((self.root/'Platforms').exists())
    def test_missing_setup_launcher_rejected_before_extraction(self):
        (self.root/'Setup/PortalAI-Setup.exe').unlink()
        self.assertNotEqual(self.ps('-VerifyOnly').returncode,0)
        self.assertFalse((self.root/'Platforms').exists())
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
    def test_start_setup_passes_drive_root_to_windows_installer(self):
        source=self.root/'capture.cs';source.write_text('using System; using System.IO; class Capture { static void Main(string[] args) { File.WriteAllLines(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"received-args.txt"),args); } }')
        output=self.root/'Setup/PortalAI-Setup.exe'
        r=subprocess.run(['C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe','/nologo','/target:winexe','/out:'+str(output),str(source)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.manifest['windows_launcher'].update(bytes=output.stat().st_size,sha256=hashlib.sha256(output.read_bytes()).hexdigest());self.save()
        result=self.ps(answer='y\n');self.assertEqual(result.returncode,0,result.stderr)
        received=self.root/'Platforms/Windows-test/received-args.txt'
        deadline=time.monotonic()+5
        while not received.exists() and time.monotonic()<deadline:time.sleep(.05)
        self.assertEqual(received.read_text().strip(),'--destination='+self.root.anchor)
    def test_native_start_setup_uses_chosen_root_not_extracted_package(self):
        for platform,script in [('Linux','install.sh'),('Mac','install-macos.sh')]:
            with self.subTest(platform=platform):
                data=b'#!/bin/bash\nprintf "%s\\n" "$1" > "$(dirname -- "$0")/received-dest.txt"\n'
                archive=self.root/'Packages'/(platform+'.tar.gz')
                with tarfile.open(archive,'w:gz') as tar:
                    member=tarfile.TarInfo('installer/'+script);member.size=len(data);member.mode=0o755;tar.addfile(member,io.BytesIO(data))
                index=1 if platform=='Mac' else 2
                self.assets[index].update(file=archive.name,bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest())
                fixture={'Setup/Models/complete_models.py':b'# fixture, never run\n',
                    'Setup/'+platform+'/'+script:data,'Setup/'+platform+'/SHA256SUMS':b'# fixture\n',
                    'Setup/'+platform+'/suite-local.json':b'{"assets":[]}\n',
                    'Utilities/'+platform+'/fixture.txt':b'companion fixture'}
                content=fixture['Utilities/'+platform+'/fixture.txt']
                fixture['Setup/'+platform+'/suite-copy.tsv']=(f'Utilities/{platform}/fixture.txt\tSuiteAssets/fixture.txt\t{len(content)}\t{hashlib.sha256(content).hexdigest()}\n').encode()
                for name,body in fixture.items():
                    p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(body)
                    if name.startswith('Setup/') and not any(r['file']==name for r in self.manifest['setup_files']):self.manifest['setup_files'].append(dict(file=name,bytes=len(body),sha256=hashlib.sha256(body).hexdigest()))
                self.save()
                mock=self.root/'mock-uname.sh';mock.write_text('uname() { echo '+('Darwin' if platform=='Mac' else 'Linux')+'; }\n',newline='\n')
                env=dict(os.environ,BASH_ENV='/'+mock.drive[0].lower()+mock.as_posix()[2:])
                r=subprocess.run([str(BASH),'prepare-setup.sh'],cwd=self.root,env=env,capture_output=True,input=b'y\n/chosen drive root\n',timeout=30)
                self.assertEqual(r.returncode,0,r.stderr)
                received=self.root/'Platforms'/platform/'received-dest.txt'
                self.assertTrue(received.is_file(),r.stdout+b'\n'+r.stderr)
                self.assertEqual(received.read_text().strip(),'/chosen drive root/PortalAI '+platform)
if __name__=='__main__':unittest.main()

