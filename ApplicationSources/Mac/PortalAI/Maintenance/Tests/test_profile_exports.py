import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent')); sys.path.insert(0,str(ROOT/'ControlCenter'))
from profile_exports import export_profile


class ProfileExportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.uid='1'*32; self.epoch='2'*32
        self.workspace=self.root/'Private/Users'/self.uid/'Workspace'
        self.workspace.mkdir(parents=True)
        (self.root/'Private/active-session.json').write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'open'}))
        self.env=patch.dict(os.environ,{'PORTALAI_PROFILE_ID':self.uid,'PORTALAI_PROFILE_EPOCH':self.epoch}); self.env.start()
        self.session=SimpleNamespace(user_id=self.uid,profile_key=b'x'*32)
        self.space=patch('runtime_policy.require_space'); self.space.start()
        for name,text in [('Data/Chat/session.json','chat'),('Data/Memory/facts.json','memory'),
                          ('Outputs/image.txt','output'),('Benchmarks/run/result.json','benchmark'),
                          ('Patch/Videos/render.mp4','video'),('Cache/tmp/temp.txt','scratch')]:
            path=self.workspace/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_text(text)

    def tearDown(self):
        self.space.stop(); self.env.stop(); self.temp.cleanup()

    def test_history_and_outputs_have_separate_verified_manifest(self):
        for kind,expected in [('history',{'Data/Chat/session.json','Data/Memory/facts.json'}),
                              ('outputs',{'Outputs/image.txt','Benchmarks/run/result.json','Patch/Videos/render.mp4'}),
                              ('both',{'Data/Chat/session.json','Data/Memory/facts.json','Outputs/image.txt','Benchmarks/run/result.json','Patch/Videos/render.mp4'})]:
            target=self.root/(kind+'.zip')
            self.assertTrue(export_profile(self.root,self.session,kind,target)['verified'])
            with zipfile.ZipFile(target) as archive:
                manifest=json.loads(archive.read('PortalAI-export-manifest.json'))
                self.assertEqual({row['path'] for row in manifest['files']},expected)
                self.assertEqual(set(archive.namelist()),expected|{'PortalAI-export-manifest.json'})

    def test_export_refuses_overwrite_and_private_destination(self):
        target=self.root/'existing.zip'; target.write_text('keep')
        for path in (target,self.workspace/'export.zip'):
            with self.assertRaises(ValueError): export_profile(self.root,self.session,'outputs',path)
        self.assertEqual(target.read_text(),'keep')

    def test_ended_login_and_other_profile_cannot_export(self):
        other=SimpleNamespace(user_id='3'*32,profile_key=b'x'*32)
        with self.assertRaises(PermissionError): export_profile(self.root,other,'history',self.root/'x.zip')
        (self.root/'Private/active-session.json').write_text(json.dumps({'user_id':self.uid,'epoch':self.epoch,'state':'closed'}))
        with self.assertRaises(PermissionError): export_profile(self.root,self.session,'history',self.root/'x.zip')
        self.assertFalse((self.root/'x.zip').exists())


if __name__=='__main__': unittest.main()
