from pathlib import Path
import hashlib,importlib.util,io,subprocess,sys,tarfile,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]/'Mac'
spec=importlib.util.spec_from_file_location('cmake_helper',ROOT/'mac-cmake.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
class CMakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def archive(self,name='cmake/CMake.app/Contents/bin/cmake'):
        p=self.root/'archive.tar.gz'
        with tarfile.open(p,'w:gz') as z:
            i=tarfile.TarInfo(name);data=b'fixture executable';i.size=len(data);z.addfile(i,io.BytesIO(data))
        return p
    def test_corrupt_download_never_creates_destination(self):
        p=self.archive();target=self.root/'tools'
        with self.assertRaisesRegex(ValueError,'SHA-256'):helper.install(p,target,'0'*64,p.stat().st_size)
        self.assertFalse(target.exists())
    def test_verified_extract_publishes_receipt(self):
        p=self.archive();target=self.root/'tools';h=helper.digest(p)
        executable=helper.install(p,target,h,p.stat().st_size)
        self.assertEqual(executable.read_bytes(),b'fixture executable');self.assertTrue((target/'portalai-cmake.json').is_file())
    def test_existing_tools_are_never_overwritten(self):
        p=self.archive();target=self.root/'tools';target.mkdir();(target/'keep').write_text('keep')
        with self.assertRaisesRegex(ValueError,'already exists'):helper.install(p,target,helper.digest(p),p.stat().st_size)
        self.assertEqual((target/'keep').read_text(),'keep')
    def test_archive_escape_is_rejected(self):
        p=self.archive('../escape')
        with self.assertRaisesRegex(ValueError,'Unsafe'):helper.install(p,self.root/'tools',helper.digest(p),p.stat().st_size)
        self.assertFalse((self.root.parent/'escape').exists())
class ShellTests(unittest.TestCase):
    def run_script(self,body):
        script='source "'+(ROOT/'mac-prerequisites.sh').as_posix()+'"\n'+body
        return subprocess.run([r'C:\Program Files\Git\bin\bash.exe','-c',script],capture_output=True,text=True)
    def test_present_tools_do_not_request_download(self):
        p=self.run_script('cmake() { return 0; }; xcode-select() { return 0; }; xcrun() { return 0; }; portalai_apple_permission() { echo UNEXPECTED; return 1; }; portalai_mac_prerequisites ignored /tmp/fixture ignored')
        self.assertEqual(p.returncode,0,p.stderr);self.assertNotIn('UNEXPECTED',p.stdout)
    def test_missing_clt_starts_apple_dialog_and_returns_pending(self):
        p=self.run_script('cmake() { return 0; }; xcode-select() { if [ "$1" = -p ]; then return 1; fi; echo APPLE_DIALOG; }; portalai_apple_permission() { return 0; }; portalai_mac_prerequisites ignored /tmp/fixture ignored')
        self.assertEqual(p.returncode,3,p.stderr);self.assertIn('APPLE_DIALOG',p.stdout)
    def test_declining_apple_setup_runs_no_download(self):
        p=self.run_script('cmake() { return 0; }; xcode-select() { return 1; }; portalai_apple_permission() { return 1; }; xcodebuild() { echo UNEXPECTED; }; portalai_mac_prerequisites ignored /tmp/fixture ignored')
        self.assertEqual(p.returncode,2,p.stderr);self.assertNotIn('UNEXPECTED',p.stdout)
    def test_missing_metal_download_is_rechecked(self):
        p=self.run_script('cmake() { return 0; }; xcode-select() { return 0; }; ready=0; xcrun() { [ "$ready" = 1 ]; }; portalai_apple_permission() { return 0; }; xcodebuild() { if [ "$1" = -downloadComponent ]; then ready=1;echo METAL_DOWNLOAD; fi; }; portalai_mac_prerequisites ignored /tmp/fixture ignored')
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('METAL_DOWNLOAD',p.stdout)
    def test_failed_metal_download_stops(self):
        p=self.run_script('cmake() { return 0; }; xcode-select() { return 0; }; xcrun() { return 1; }; portalai_apple_permission() { return 0; }; xcodebuild() { [ "$1" = -version ]; }; portalai_mac_prerequisites ignored /tmp/fixture ignored')
        self.assertEqual(p.returncode,2,p.stderr)
if __name__=='__main__':unittest.main(verbosity=2)
