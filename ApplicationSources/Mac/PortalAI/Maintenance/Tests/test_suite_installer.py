"""Offline suite boundary, download, archive and publication regression tests."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
import suite_installer as suite


class Response(io.BytesIO):
    def __init__(self,data,status=200,headers=None):
        super().__init__(data);self.status=status;self.headers=headers or {}


class Opener:
    def __init__(self,data,status=200,headers=None):
        self.data,self.status,self.headers=data,status,headers;self.requests=[]
    def open(self,request,timeout=None):
        self.requests.append(request)
        return Response(self.data,self.status,self.headers)


def asset(data=b'archive',edition='Academic',platform='Windows',kind='installer',id='test'):
    return dict(id=id,edition=edition,platform=platform,kind=kind,file=id+'.zip',bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),expanded_bytes=1024*1024,
                url='https://example.invalid/'+id+'.zip',private=False,utility='projection')


class SuiteInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.package=self.root/'package';self.package.mkdir();self.target=self.root/'target';self.stop=threading.Event()
        self.catalog=dict(schema=1,catalog_version='test',assets=[asset(),asset(edition='Full',id='full'),asset(kind='utility',id='projection')])
    def tearDown(self):self.temp.cleanup()
    def download(self,a,opener=None):
        return suite.download(a,self.package,self.target,self.stop,lambda *args:None,opener=opener)
    def test_academic_filters_every_full_choice(self):
        rows=suite.choices(self.catalog,'Academic','Windows','Academic')
        self.assertTrue(all(r['asset']['edition']!='Full' for r in rows))
        with self.assertRaises(suite.SuiteError):suite.plan(self.catalog,['copy:full'],'Academic','Windows')
    def test_full_can_select_both_and_other_os_copy(self):
        self.catalog['assets'].append(asset(id='mac',platform='Mac'))
        rows=suite.choices(self.catalog,'Full','Windows','Full');ids={r['id'] for r in rows}
        self.assertIn('app:Academic',ids);self.assertIn('copy:mac',ids)
        self.assertNotIn('app:Full',ids)
    def test_utility_filtered_to_native_os(self):
        self.assertFalse(any(r['action']=='utility' for r in suite.choices(self.catalog,'Full','Linux')))
    def test_duplicate_and_unknown_rejected(self):
        for selection in (['copy:test']*2,['bad']):
            with self.assertRaises(suite.SuiteError):suite.plan(self.catalog,selection,'Academic','Windows')
    def test_download_deduplicated_for_copy_and_application(self):
        p=suite.plan(self.catalog,['copy:test','app:Academic'],'Full','Windows','Full')
        self.assertEqual(p['download_bytes'],len(b'archive'))
        self.assertGreater(p['working_bytes'],p['installed_bytes'])
    def test_space_rejects_before_mutation(self):
        with patch.object(shutil,'disk_usage',return_value=shutil._ntuple_diskusage(100,99,1)):
            with self.assertRaises(suite.SuiteError):suite.space_check(self.target,100)
        self.assertFalse(self.target.exists())
    def test_local_verified_asset_needs_no_token(self):
        a=asset();a['private']=True;(self.package/a['file']).write_bytes(b'archive')
        self.assertTrue(self.download(a).samefile(self.package/a['file']));self.assertFalse(self.target.exists())
    def test_download_pinned_and_cache_reused(self):
        op=Opener(b'archive');p=self.download(asset(),op)
        self.assertEqual(p.read_bytes(),b'archive');self.assertEqual(self.download(asset(),op),p);self.assertEqual(len(op.requests),1)
    def test_wrong_hash_cannot_be_published(self):
        with self.assertRaises(suite.SuiteError):self.download(asset(),Opener(b'badfile'))
        self.assertFalse(list(self.target.rglob('*.download')))
    def test_oversized_download_bounded(self):
        with self.assertRaises(suite.SuiteError):self.download(asset(),Opener(b'archiveX'))
    def test_resume_valid_range(self):
        a=asset();cache=self.target/'Utilities/.suite-downloads';cache.mkdir(parents=True)
        (cache/(a['sha256']+'.partial')).write_bytes(b'arc')
        op=Opener(b'hive',206,{'Content-Range':'bytes 3-6/7'})
        self.assertEqual(self.download(a,op).read_bytes(),b'archive');self.assertEqual(op.requests[0].get_header('Range'),'bytes=3-')
    def test_bad_resume_range_rejected(self):
        with self.assertRaises(suite.SuiteError):self.download(asset(),Opener(b'archive',206,{'Content-Range':'bytes 1-7/8'}))
    def test_cancellation_retains_no_completed_asset(self):
        self.stop.set()
        with self.assertRaises(suite.SuiteError):self.download(asset(),Opener(b'archive'))
        self.assertFalse(list(self.target.rglob('*.download')))
    def test_redirect_strips_authorization(self):
        request=urllib.request.Request('https://api.github.com/repos/a/b/releases/assets/1',headers={'Authorization':'Bearer secret'})
        result=suite.SafeRedirect().redirect_request(request,None,302,'Found',{},'https://release-assets.githubusercontent.com/a')
        self.assertNotIn('Authorization',result.headers);self.assertNotIn('Authorization',result.unredirected_hdrs)
        with self.assertRaises(suite.SuiteError):suite.SafeRedirect().redirect_request(request,None,302,'Found',{},'http://example.invalid')
    def test_error_does_not_echo_credential_or_url(self):
        class Fail:
            def open(self,*args,**kw):raise OSError('secret-token https://signed.invalid/private')
        with self.assertRaises(suite.SuiteError) as caught:self.download(asset(),Fail())
        self.assertNotIn('secret',str(caught.exception));self.assertNotIn('signed',str(caught.exception))
    def test_private_rejects_non_github_api(self):
        a=asset();a.update(private=True,api_url='https://example.invalid/repos/a/b')
        with self.assertRaises(suite.SuiteError):suite.download(a,self.package,self.target,self.stop,lambda *a:None,token='secret')
    def archive(self,names):
        p=self.package/'test.zip'
        with zipfile.ZipFile(p,'w') as z:
            for name,data in names:z.writestr(name,data)
        return p
    def test_archive_traversal_rejected(self):
        with self.assertRaises(suite.SuiteError):suite.unpack(self.archive([('../escape',b'x')]),self.target,asset(),self.stop)
        self.assertFalse((self.root/'escape').exists())
    def test_archive_link_rejected(self):
        i=zipfile.ZipInfo('link');i.external_attr=(stat.S_IFLNK|0o777)<<16
        with self.assertRaises(suite.SuiteError):suite.unpack(self.archive([(i,b'target')]),self.target,asset(),self.stop)
    def test_archive_size_cap(self):
        a=asset();a['expanded_bytes']=1
        with self.assertRaises(suite.SuiteError):suite.unpack(self.archive([('file',b'big')]),self.target,a,self.stop)
    def test_copy_installer_verified_and_repeatable(self):
        a=asset();(self.package/a['file']).write_bytes(b'archive')
        with patch.object(suite,'space_check'):
            for _ in range(2):
                suite.execute(self.catalog,['copy:test'],'Academic','Windows',self.package,self.target,primary='Academic')
        self.assertEqual((self.target/'Utilities/Installers/Academic/Windows/test.zip').read_bytes(),b'archive')
    def test_existing_copy_never_overwritten(self):
        (self.package/'test.zip').write_bytes(b'archive')
        dest=self.target/'Utilities/Installers/Academic/Windows/test.zip';dest.parent.mkdir(parents=True);dest.write_bytes(b'owner')
        with patch.object(suite,'space_check'),self.assertRaises(suite.SuiteError):
            suite.execute(self.catalog,['copy:test'],'Academic','Windows',self.package,self.target,primary='Academic')
        self.assertEqual(dest.read_bytes(),b'owner')
    def test_projection_publication_has_no_process_launch(self):
        p=self.archive([('Utilities/PortalAI-Projection/app/projection_ui.py',b'#public')]);a=asset(p.read_bytes(),kind='utility');self.catalog['assets']=[a]
        with patch.object(suite,'space_check'),patch.object(suite.subprocess,'Popen') as spawn:
            suite.execute(self.catalog,['utility:test'],'Academic','Windows',self.package,self.target,primary='Academic')
        spawn.assert_not_called();self.assertTrue((self.target/'Utilities/PortalAI-Projection/app/projection_ui.py').is_file())
    def test_private_state_projection_archive_refused(self):
        p=self.archive([('Utilities/PortalAI-Projection/Connections/private',b'secret')]);self.catalog['assets']=[asset(p.read_bytes(),kind='utility')]
        with patch.object(suite,'space_check'),self.assertRaises(suite.SuiteError):
            suite.execute(self.catalog,['utility:test'],'Academic','Windows',self.package,self.target,primary='Academic')
        self.assertFalse((self.target/'Utilities/PortalAI-Projection').exists())
    def test_sidecar_resolves_exact_release_without_network(self):
        a=self.catalog['assets'][0];a.update(resolve_release=True,repository='Zhandragon/PortalAI-Academic',tag='vtest')
        (self.package.parent/'suite-release-catalog.json').write_text(json.dumps(self.catalog))
        result=suite.resolve_catalog(self.catalog,['copy:test'],'Academic','Windows',self.package,'Academic')
        self.assertFalse(result['assets'][0]['resolve_release'])
    def test_sidecar_cannot_change_identity(self):
        a=self.catalog['assets'][0];a.update(resolve_release=True,repository='Zhandragon/PortalAI-Academic',tag='vtest')
        wrong=json.loads(json.dumps(self.catalog));wrong['assets'][0]['file']='other.zip'
        (self.package.parent/'suite-release-catalog.json').write_text(json.dumps(wrong))
        with self.assertRaises(suite.SuiteError):suite.resolve_catalog(self.catalog,['copy:test'],'Academic','Windows',self.package,'Academic')
    def test_release_requires_digest_not_only_filename(self):
        a=self.catalog['assets'][0];a.update(resolve_release=True,repository='Zhandragon/PortalAI-Academic',tag='vtest')
        op=Opener(json.dumps({'assets':[{'name':'test.zip','size':7}]}).encode())
        with self.assertRaises(suite.SuiteError):suite.resolve_catalog(self.catalog,['copy:test'],'Academic','Windows',self.package,'Academic',opener=op)


if __name__=='__main__':unittest.main()
