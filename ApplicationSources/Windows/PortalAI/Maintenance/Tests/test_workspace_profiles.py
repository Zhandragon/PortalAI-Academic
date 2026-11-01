"""Workspace data follows real encrypted lazy-profile and login boundaries."""
import json
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
import test_profile_hydration as fixtures
from profile_paths import ProfileLocked
from knowledge_base import Knowledge
from workflows import Workflows
from mcp_client import Connections
from test_workspace import Embedder


class ProfileTests(unittest.TestCase):
    def setUp(self):
        fixtures.HydrationTests.setUp(self)
        (self.root/'Agent').mkdir(exist_ok=True)
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':1,'minimum_free_fraction':.0001,'output_reserve_gib':0}}))
    tearDown=fixtures.HydrationTests.tearDown

    def test_new_project_undo_verification_and_calibration_state_seals(self):
        from types import SimpleNamespace
        from code_projects import CodeProjects,Edits
        from result_verification import Verifications
        from model_calibration import Calibration
        folder=self.root/'synthetic-project';folder.mkdir();path=folder/'result.json';path.write_bytes(b'{"count":3}')
        projects=CodeProjects(self.root);pid=projects.add('Private code',folder)['id'];projects.scan(pid)
        edits=Edits(self.root);edit=edits.prepare(path,b'private before image',path.read_bytes());edits.finish(edit)
        runtime=SimpleNamespace(root=self.root,safe_path=lambda value:Path(value))
        verifier=Verifications(runtime);receipt=verifier.run([{'kind':'json_value','path':str(path),'expected_json':'{"count":3}'}])
        calibration=Calibration(self.root);rid=calibration.new_id();calibration.save('Runs/'+rid+'.json',{'id':rid,'state':'running','created':1})
        image=edits.path('Images/'+edit['id']+'.bin');proof=verifier.path('Runs/'+receipt['id']+'.json')
        self.runtime.close(self.session,writers_stopped=True)
        self.assertFalse(image.exists());self.assertFalse(proof.exists())
        with self.assertRaises(ProfileLocked):edits.before_image(edit)
        self.session=self.backend.login(fixtures.OWNER);self.runtime.prepare(self.session)
        self.assertEqual(CodeProjects(self.root).list()[0]['id'],pid)
        self.assertEqual(Edits(self.root).before_image(edit),b'private before image')
        self.assertTrue(Verifications(runtime).read(receipt['id'],fresh=True)['success'])
        self.assertEqual(Calibration(self.root).read(rid)['state'],'unfinished')

    def test_projects_skills_and_oauth_tokens_seal_and_reopen(self):
        from portable_workspace import Organization,Skills
        from mcp_client import Connections
        org=Organization(self.root);pid=org.put('Private project','Private guidance')['id'];org.assign(['a'*32],pid)
        skills=Skills(self.root);sid=skills.put('Private skill','For tests','Secret synthetic instructions',enabled=True)['id']
        connections=Connections(self.root);cid=connections.create('Fixture','http',url='https://example.org/mcp')['id']
        connections.configure_oauth(cid,{'issuer':'https://auth.example.org','client_id':'fixture'})
        row=connections.load(cid);row['oauth_token']={'access_token':'synthetic-private-access','refresh_token':'synthetic-private-refresh','resource':row['url'],'expires_at':9999999999}
        connections.save('Servers/'+cid+'.json',row)
        paths=[org.path('projects.json'),skills.path('Items/'+sid+'.json'),connections.path('Servers/'+cid+'.json')]
        self.runtime.close(self.session,writers_stopped=True)
        self.assertTrue(all(not p.exists() for p in paths))
        with self.assertRaises(ProfileLocked):skills.read(sid)
        self.session=self.backend.login(fixtures.OWNER);self.runtime.prepare(self.session)
        self.assertEqual(Organization(self.root).for_chat('a'*32)['id'],pid)
        self.assertIn('Secret synthetic',Skills(self.root).read(sid)['instructions'])
        self.assertEqual(Connections(self.root).load(cid)['oauth_token']['refresh_token'],'synthetic-private-refresh')

    def test_sealed_knowledge_lazy_reopen_and_stale_login_fence(self):
        source=self.root/'synthetic-documents';source.mkdir();(source/'notes.txt').write_text('Plants grow towards sunlight.')
        kb=Knowledge(self.root,embedder=Embedder());cid=kb.create('Private research',source)['id'];kb.sync(cid)
        citation=kb.search('plants')['results'][0]['citation'];index=kb._dbpath(cid)
        self.runtime.close(self.session,writers_stopped=True)
        self.assertFalse(index.exists())
        with self.assertRaises(ProfileLocked):kb.search('plants')
        self.session=self.backend.login(fixtures.OWNER);self.runtime.prepare(self.session)
        self.assertFalse(index.exists(),'Login should not decrypt the document index')
        reopened=Knowledge(self.root,embedder=Embedder());self.assertEqual(reopened.list()[0]['id'],cid)
        self.assertFalse(index.exists(),'Listing collection metadata should not decrypt the index')
        self.assertIn('sunlight',reopened.read(citation)['text']);self.assertTrue(index.exists())
        with self.assertRaises(ProfileLocked):kb.list()

    def test_connections_and_workflow_approvals_survive_sealing(self):
        c=Connections(self.root);cid=c.create('Synthetic','http',url='https://example.org/mcp',headers={'Authorization':'synthetic-private-secret'})['id']
        flows=Workflows(self.root);tid=flows.put({'version':1,'name':'Private workflow','inputs':[],'steps':[{'id':'approval','kind':'approval'},{'id':'done','kind':'output','value':42}]})['id']
        rid=flows.start(tid,{})['id'];flows.advance(rid)
        private=c.path('Servers/'+cid+'.json');run=flows.path('Runs/'+rid+'.json')
        self.runtime.close(self.session,writers_stopped=True);self.assertFalse(private.exists());self.assertFalse(run.exists())
        self.session=self.backend.login(fixtures.OWNER);self.runtime.prepare(self.session)
        self.assertEqual(Connections(self.root).load(cid)['headers']['Authorization'],'synthetic-private-secret')
        reopened=Workflows(self.root);self.assertEqual(reopened.run(rid)['state'],'approval');reopened.approve(rid)
        self.assertEqual(reopened.advance(rid)['results']['done'],42)


if __name__=='__main__':unittest.main()
