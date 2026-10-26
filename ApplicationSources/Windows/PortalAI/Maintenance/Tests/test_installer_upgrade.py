"""Exercise the production Windows upgrade entry on an older, private-data fixture."""
from pathlib import Path
import contextlib,hashlib,importlib.util,json,sys,tempfile,unittest,zipfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Installer/Windows'))
import installer_core as core
import portable_update as update

class InstallerUpgrade(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup)
        self.base=Path(self.t.name);self.package=self.base/'package';self.package.mkdir()
        self.target=self.base/'older PortalAI';self.target.mkdir()
        files={update.STAMP:b"RELEASE_VERSION='2026.10.25-Aoostar-r44'\n",update.BOOT:b'# PENDING.json startup guard\n',
            'Agent/profile_workspace.py':b'# fixture new profile implementation\n','Agent/config.json':b'{"default":true}',
            'Tools/new_feature.py':b'# new\n',
            'Agent/executable_recovery.py':b'def register(root, files, release, cancel):\n    cancel()\n'}
        rows=[];payload=self.package/'payload.zip'
        with zipfile.ZipFile(payload,'w') as z:
            for name,data in files.items():
                z.writestr('PortalAI/'+name,data)
                rows.append({'member':'PortalAI/'+name,'dest':'PortalAI Windows/'+name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        self.meta={'schema':1,'status':'RELEASED','release':'PortalAI-2026.10.25-Aoostar-r44-Full-Windows','components':[],
            'payload':{'file':'payload.zip','bytes':payload.stat().st_size,'sha256':core.sha256(payload),'members':rows},
            'upgrade':{'schema':1,'version':'2026.10.25-Aoostar-r44','platform':'Windows','edition':'Full','compatible_versions':[]}}
        (self.package/'release.json').write_text(json.dumps(self.meta))
        for name,data in {update.STAMP:"RELEASE_VERSION='2026.10.24-r17'\n",update.BOOT:'# old bootstrap',
                          'Agent/profile_workspace.py':'# old profiles','Agent/config.json':'{"owner":true}',
                          'Private/Users/fixture/Vault/encrypted':'private fixture','Models/existing.gguf':'existing asset'}.items():
            p=self.target/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
        self.p=patch.object(update,'closed_guard',lambda *a:contextlib.nullcontext());self.p.start();self.addCleanup(self.p.stop)
    def test_entrypoint_inspects_and_updates_existing_version(self):
        p=core.inspect_update(self.package,self.target)
        self.assertEqual(p['from_version'],'2026.10.24-r17');self.assertEqual(p['to_version'],'2026.10.25-Aoostar-r44')
        result=core.install(self.package,self.target,[],mode='upgrade')
        self.assertTrue(result['verified'])
        self.assertEqual((self.target/'Agent/config.json').read_text(),'{"owner":true}')
        self.assertEqual((self.target/'Private/Users/fixture/Vault/encrypted').read_text(),'private fixture')
        self.assertEqual((self.target/'Models/existing.gguf').read_text(),'existing asset')
    def test_new_install_still_works(self):
        destination=self.base/'fresh'
        result=core.install(self.package,destination,[])
        self.assertFalse(result['accounts_created'])
        self.assertEqual(update.version(destination/'PortalAI Windows'),'2026.10.25-Aoostar-r44')
    def test_plain_install_never_overwrites_existing(self):
        with self.assertRaisesRegex(core.InstallError,'Existing folders'):core.install(self.package,self.target,[])
    def test_newer_installation_refused_before_download(self):
        (self.target/update.STAMP).write_text("RELEASE_VERSION='2026.10.26-r99'")
        with patch.object(core,'download_artifact') as fetch,self.assertRaisesRegex(update.UpdateError,'Downgrade'):
            core.install(self.package,self.target,[],mode='upgrade')
        fetch.assert_not_called()
if __name__=='__main__':unittest.main()
