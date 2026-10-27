"""The live web harness uses private, revocation-aware fixtures and reports."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
import smoke_web
from smoke_profile import SmokeProfile
from profile_paths import UID_ENV,EPOCH_ENV,ProfileLocked


class WebSmokeProfileTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal web smoke ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        (self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{
            'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        (self.root/'Private').mkdir()
        self.uid,self.epoch='c'*32,'d'*32
        self.active={'user_id':self.uid,'epoch':self.epoch,'state':'open'}
        self.marker=self.root/'Private/active-session.json'
        self.marker.write_text(json.dumps(self.active))
        environment=patch.dict(os.environ,{UID_ENV:self.uid,EPOCH_ENV:self.epoch})
        environment.start();self.addCleanup(environment.stop)
        self.profile=SmokeProfile(self.root)

    def revoke(self):self.marker.write_text(json.dumps({**self.active,'state':'closed'}))

    def test_synthetic_cache_does_not_inherit_login_and_cannot_outlive_outer_profile(self):
        state=smoke_web._fixture_state(self.profile,'test')
        self.assertIsNone(state.context)
        self.assertEqual(dict(state._environ),{})
        self.assertEqual(os.environ[UID_ENV],self.uid)
        self.assertTrue(state.path.is_relative_to(self.profile.path('fixtures')))
        self.revoke()
        with self.assertRaises(ProfileLocked):state.save('late',3,{'provider':'fixture','results':[]})
        self.assertFalse(state.path.parent.exists())

    def test_harness_checks_actual_fallback_and_image_bytes_without_global_writes(self):
        result=[{'title':'Python','url':'https://www.python.org/doc/','snippet':'Python docs'}]
        searches=[]
        def search(query,limit,*,lite=False):
            self.assertEqual(os.environ[UID_ENV],self.uid)
            searches.append((query,lite))
            return result
        def page(url,**kwargs):
            return {'text':'Public documentation','title':'Python Wikimedia','url':url}
        def download(url,*,query,output_root):
            self.assertEqual(os.environ[UID_ENV],self.uid)
            folder=Path(output_root);folder.mkdir(parents=True)
            path=folder/(query+'.png');path.write_bytes(b'\x89PNG\r\n\x1a\n'+b'synthetic fixture')
            return {'path':str(path),'source_url':url,'content_type':'image/png'}
        with patch.object(smoke_web.web,'search_bing',side_effect=smoke_web.web.WebAccessError('fixture')),\
             patch.object(smoke_web.web,'search_duckduckgo',side_effect=search),\
             patch.object(smoke_web.web,'fetch_url',side_effect=page),\
             patch.object(smoke_web.web,'image_search',return_value={'provider':'fixture','images':[{'image_url':'https://example.com/image.png'}]}),\
             patch.object(smoke_web.web,'download_public_image',side_effect=download),\
             patch.object(smoke_web,'ROOT',self.root),patch('builtins.print'):
            self.assertEqual(smoke_web.main(),0)
        reports=list((self.root/'Private/Users'/self.uid/'Workspace/Data/Maintenance/Smoke').glob('*/web-smoke.json'))
        self.assertEqual(len(reports),1)
        report=json.loads(reports[0].read_text())
        self.assertTrue(report['passed']);self.assertEqual(len(report['checks']),6)
        self.assertTrue(report['checks'][1]['html_403_injected'])
        self.assertEqual(searches,[('Python official documentation',False),('Python pathlib documentation',True)])
        self.assertFalse((self.root/'Maintenance/Reports').exists())
        self.assertFalse((self.root/'Cache').exists())

    def test_locked_harness_does_not_start_network_or_create_shared_reports(self):
        self.revoke()
        with patch.object(smoke_web,'ROOT',self.root),patch.object(smoke_web,'run_checks') as run:
            with self.assertRaises(ProfileLocked):smoke_web.main()
        run.assert_not_called()
        self.assertFalse((self.root/'Private/Users').exists())

    def test_signature_check_rejects_html_named_as_image(self):
        self.assertFalse(smoke_web._image_signature(b'<html><title>403'))
        self.assertTrue(smoke_web._image_signature(b'RIFF'+b'\x00'*4+b'WEBP'))


if __name__=='__main__':unittest.main()
