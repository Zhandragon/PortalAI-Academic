"""Optional companions use reviewed local files and the selected root layout."""
from pathlib import Path
import hashlib,json,sys,tempfile,threading,unittest
from unittest.mock import patch
from collections import namedtuple
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Windows'))
import suite_installer as suite
import installer_core as core

class Companions(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.package=self.root/'Unzipped Bundle/Platforms/Windows';self.package.mkdir(parents=True)
        asset=dict(id='projection-windows',kind='utility',utility='projection',edition='Any',platform='Windows',
            file='fixture.zip',bytes=1,sha256='0'*64,expanded_bytes=1,private=False,resolve_release=True)
        raw=json.dumps(dict(schema=1,catalog_version='fixture',assets=[asset])).encode();(self.package/'suite-catalog.json').write_bytes(raw)
        self.rows=[]
        for name,data in [('Utilities/PortalAI-Projection/app/fixture.txt',b'projection'),('Utilities/PortalAI HA Setup/Setup Files/HomeAssistant/fixture.yaml',b'public yaml')]:
            relative='SuiteAssets/projection/'+name;p=self.package/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
            self.rows.append(dict(file=relative,dest=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
        (self.package/'suite-local.json').write_text(json.dumps(dict(schema=1,base_catalog_sha256=hashlib.sha256(raw).hexdigest(),assets=[dict(id='projection-windows',platform='Windows',files=self.rows)])))
    def test_selection_uses_local_companions_at_drive_root(self):
        catalog=suite.read_catalog(self.package)
        with patch.object(suite,'download',side_effect=AssertionError('No companion network download')),patch.object(suite,'space_check'):
            catalog=suite.resolve_catalog(catalog,['utility:projection-windows'],'Full','Windows',self.package,'Full')
            suite.execute(catalog,['utility:projection-windows'],'Full','Windows',self.package,self.root,primary='Full')
        self.assertEqual((self.root/self.rows[0]['dest']).read_bytes(),b'projection')
        self.assertEqual((self.root/self.rows[1]['dest']).read_bytes(),b'public yaml')
        self.assertFalse((self.package/'Utilities').exists())
        self.assertFalse((self.root/'Utilities/PortalAI-Projection/Connections').exists())
    def test_unselected_companions_stay_uninstalled(self):
        suite.execute(suite.read_catalog(self.package),[],'Full','Windows',self.package,self.root,primary='Full')
        self.assertFalse((self.root/'Utilities').exists())
    def test_corrupt_local_companion_is_not_published(self):
        (self.package/self.rows[0]['file']).write_bytes(b'corrupt')
        with patch.object(suite,'space_check'),self.assertRaises(suite.SuiteError):
            suite.execute(suite.read_catalog(self.package),['utility:projection-windows'],'Full','Windows',self.package,self.root,primary='Full')
        self.assertFalse((self.root/'Utilities/PortalAI-Projection').exists())
    def test_existing_projection_settings_are_preserved(self):
        target=self.root/'Utilities/PortalAI-Projection';target.mkdir(parents=True);(target/'owner.txt').write_text('keep')
        with patch.object(suite,'space_check'),self.assertRaises(suite.SuiteError):
            suite.execute(suite.read_catalog(self.package),['utility:projection-windows'],'Full','Windows',self.package,self.root,primary='Full')
        self.assertEqual((target/'owner.txt').read_text(),'keep')
    def test_abliterator_runtime_can_join_only_its_verified_example_model(self):
        target=self.root/'Utilities/Portable Abliterator';model=target/'models/example.bin';model.parent.mkdir(parents=True);model.write_bytes(b'model')
        row=dict(dest='Utilities/Portable Abliterator/models/example.bin',bytes=5,sha256=hashlib.sha256(b'model').hexdigest())
        component=dict(id='abliterator-example-model',artifacts=[dict(members=[row])])
        source=self.root/'staging';source.mkdir();(source/'fixture.txt').write_text('runtime')
        with patch.object(core,'read_manifest',return_value=dict(components=[component])):
            suite.publish_abliterator(source,target,self.package,['abliterator-example-model'],core)
        self.assertEqual(model.read_bytes(),b'model');self.assertEqual((target/'fixture.txt').read_text(),'runtime')
        source.mkdir(exist_ok=True);(source/'second.txt').write_text('new')
        with patch.object(core,'read_manifest',return_value=dict(components=[component])),self.assertRaises(suite.SuiteError):
            suite.publish_abliterator(source,target,self.package,['abliterator-example-model'],core)
        self.assertFalse((target/'second.txt').exists())
    def test_full_install_temporary_download_peak_preserves_final_reserve(self):
        usage=namedtuple('usage','total used free')(920*suite.GIB,2*suite.GIB,918*suite.GIB)
        with patch.object(suite.shutil,'disk_usage',return_value=usage):
            with self.assertRaises(suite.SuiteError):suite.space_check(self.root,840*suite.GIB)
            result=suite.space_check(self.root,840*suite.GIB,completed_downloads=390*suite.GIB)
            self.assertEqual(result['reserve_bytes'],92*suite.GIB)
            self.assertEqual(result['temporary_reserve_bytes'],suite.GIB)

if __name__=='__main__':unittest.main()
