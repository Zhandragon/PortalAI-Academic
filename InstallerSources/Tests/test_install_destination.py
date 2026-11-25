"""Offline installs into chosen roots preserve unrelated files and reject collisions."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,threading,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Windows'))
import installer_core as core
import installer_storage as storage

class Destinations(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='PortalAI-destination-test-')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.package=self.root/'package';self.package.mkdir()
        files={'PortalAI Windows/Agent/executable_recovery.py':b'def register(*args): pass\n',
               'PortalAI Windows/app.txt':b'clean fixture', 'Start PortalAI Windows.cmd':b'fixture, never run'}
        rows=[];payload=self.package/'payload.zip'
        with zipfile.ZipFile(payload,'w') as z:
            for name,data in files.items():
                z.writestr(name,data);rows.append(dict(member=name,dest=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        manifest=dict(schema=1,status='RELEASED',release='synthetic',components=[],payload=dict(file='payload.zip',bytes=payload.stat().st_size,sha256=core.sha256(payload),members=rows))
        (self.package/'release.json').write_text(json.dumps(manifest),encoding='utf-8')
    def install(self,target,**kwargs):return core.install(self.package,target,[],**kwargs)
    def test_existing_selected_folder_preserves_unrelated_data(self):
        target=self.root/'destination with spaces';target.mkdir();(target/'keep.txt').write_text('untouched')
        self.install(target)
        self.assertEqual((target/'PortalAI Windows/app.txt').read_bytes(),b'clean fixture')
        self.assertEqual((target/'keep.txt').read_text(),'untouched')
        self.assertFalse((self.package/'PortalAI Windows').exists())
    def test_new_destination_and_beside_installer_still_work(self):
        self.install(self.root/'new');self.install(self.package)
        self.assertTrue((self.root/'new/INSTALL_RECEIPT.json').is_file())
        self.assertTrue((self.package/'PortalAI Windows/app.txt').is_file())
    def test_existing_application_is_never_overwritten(self):
        target=self.root/'used';(target/'PortalAI Windows').mkdir(parents=True)
        (target/'PortalAI Windows/owner.txt').write_text('owner')
        with self.assertRaisesRegex(core.InstallError,'Update existing'):self.install(target)
        self.assertEqual((target/'PortalAI Windows/owner.txt').read_text(),'owner')
        self.assertFalse((target/'INSTALL_RECEIPT.json').exists())
    def test_root_launcher_collision_is_not_overwritten(self):
        target=self.root/'used';target.mkdir();p=target/'Start PortalAI Windows.cmd';p.write_text('owner')
        with self.assertRaises(core.InstallError):self.install(target)
        self.assertEqual(p.read_text(),'owner')
    def test_cancellation_does_not_publish(self):
        target=self.root/'empty';target.mkdir();stop=threading.Event();stop.set()
        with self.assertRaises(core.Cancelled):self.install(target,stop=stop)
        self.assertFalse((target/'PortalAI Windows').exists())
    def test_file_destination_is_rejected(self):
        target=self.root/'file';target.write_text('keep')
        with self.assertRaisesRegex(core.InstallError,'not a folder'):self.install(target)
        self.assertEqual(target.read_text(),'keep')
    @unittest.skipUnless(os.name=='nt','Windows drive-root acceptance')
    def test_drive_root_via_disposable_subst(self):
        folder=self.root/'drive';folder.mkdir()
        drive=next((c+':' for c in 'ZYXWVUTSRQP' if not Path(c+':/').exists()),None)
        if drive is None:self.skipTest('No unused test drive letter')
        subprocess.run(['subst',drive,str(folder)],check=True)
        try:
            # SUBST is not a volume mount point; query the actual backing volume.
            unit=storage.allocation_unit(folder)
            with patch.object(storage,'allocation_unit',return_value=unit):self.install(drive+'/')
            self.assertEqual((folder/'PortalAI Windows/app.txt').read_bytes(),b'clean fixture')
        finally:subprocess.run(['subst',drive,'/D'],check=True)

if __name__=='__main__':unittest.main()
