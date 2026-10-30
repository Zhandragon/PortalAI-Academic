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
