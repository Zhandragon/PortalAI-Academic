"""Saved installer choices must recreate the current complete bundle, not r75 kits."""
from pathlib import Path
import hashlib,io,json,sys,tempfile,unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'InstallerSources/Windows'))
from current_bundle_catalog import current_catalog
import suite_installer as suite

class Opener:
    def __init__(self,assets):self.assets=assets
    def open(self,request,timeout=None):return io.BytesIO(json.dumps(dict(assets=self.assets)).encode())

class CurrentCopies(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.package=self.root/'unpacked/Platforms/Windows';self.package.mkdir(parents=True)
        assets=[]
        for owner in ('Full','Academic'):
            for platform in ('Windows','Mac','Linux'):
                assets.append(dict(id='installer-'+owner.lower()+'-'+platform.lower(),kind='installer',edition=owner,platform=platform,
                    file='old-'+owner+'-'+platform+'.zip',bytes=1,sha256='0'*64,expanded_bytes=1,repository='Zhandragon/PortalAI'+('-Academic' if owner=='Academic' else ''),tag='old',resolve_release=True))
        self.raw=json.dumps(dict(schema=1,catalog_version='old',assets=assets))
    def catalog(self,edition='Full'):
        (self.package/'suite-catalog.json').write_bytes(current_catalog(self.raw,edition,'2026.11.27-bundle8'))
        return suite.read_catalog(self.package)
    def test_all_eight_full_copies_are_current_zip_bundles(self):
        rows=suite.choices(self.catalog(),'Full','Windows','Full');copies=[r for r in rows if r['action']=='copy']
        self.assertEqual(len(copies),8)
        self.assertEqual({r['asset']['platform'] for r in copies},{'Windows','Mac','Linux','Universal'})
        for row in copies:
            self.assertIn('-Bundle-2026.11.27-bundle8.zip',row['asset']['file'])
            self.assertEqual(row['asset']['tag'],'v2026.11.27-bundle8')
            self.assertTrue(row['asset']['resolve_release'])
    def test_academic_has_four_copies_and_no_full_assets(self):
        catalog=self.catalog('Academic');rows=suite.choices(catalog,'Academic','Windows','Academic')
        self.assertEqual(len([r for r in rows if r['action']=='copy']),4)
        self.assertTrue(all(r['asset']['edition']=='Academic' for r in rows))
        with self.assertRaises(suite.SuiteError):suite.plan(catalog,['copy:installer-full-windows'],'Academic','Windows')
    def test_secondary_windows_application_uses_r87_and_cannot_be_saved_as_an_old_copy(self):
        rows=suite.choices(self.catalog(),'Full','Windows','Full')
        app=next(r for r in rows if r['id']=='app:Academic')
        self.assertEqual(app['asset']['tag'],'v2026.11.27-Desktop-r87')
        self.assertTrue(app['asset']['application_only'])
        self.assertNotIn('copy:'+app['asset']['id'],[r['id'] for r in rows])
    def test_resolved_universal_copy_is_verified_and_saved_at_selected_root(self):
        catalog=self.catalog();selected=['copy:installer-full-universal'];row=suite.plan(catalog,selected,'Full','Windows','Full')['rows'][0]['asset']
        data=b'fixture current bundle';sha=hashlib.sha256(data).hexdigest()
        (self.package/row['file']).write_bytes(data)
        published=dict(name=row['file'],digest='sha256:'+sha,size=len(data),url='https://api.github.com/repos/Zhandragon/PortalAI/releases/assets/1',browser_download_url=row['url'])
        resolved=suite.resolve_catalog(catalog,selected,'Full','Windows',self.package,'Full',token='fixture',opener=Opener([published]))
        with patch.object(suite,'space_check'):
            suite.execute(resolved,selected,'Full','Windows',self.package,self.root/'drive',primary='Full')
        target=self.root/'drive/Utilities/Installers/Full/Universal'/row['file']
        self.assertEqual(target.read_bytes(),data)
        self.assertFalse((self.package/'Utilities').exists())
    def test_missing_current_release_asset_never_falls_back_to_old_kit(self):
        with self.assertRaises(suite.SuiteError):
            suite.resolve_catalog(self.catalog(),['copy:installer-full-universal'],'Full','Windows',self.package,'Full',token='fixture',opener=Opener([]))
    def test_unresolved_estimate_cannot_be_downloaded_or_published(self):
        with patch.object(suite,'space_check'),patch.object(suite,'download',side_effect=AssertionError('Must resolve first')),self.assertRaises(suite.SuiteError):
            suite.execute(self.catalog(),['copy:installer-full-universal'],'Full','Windows',self.package,self.root/'drive',primary='Full')
        self.assertFalse((self.root/'drive').exists())

if __name__=='__main__':unittest.main()
