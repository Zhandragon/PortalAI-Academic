"""Real encrypted sealing/lazy restore for artifact and API persistent state."""
import sys
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from test_workspace_profiles import ProfileTests as Fixture
import test_profile_hydration as fixtures
from artifacts import Artifacts
from application_api import APIState
from profile_paths import ProfileLocked

class IntegrationProfiles(unittest.TestCase):
    setUp=Fixture.setUp
    tearDown=Fixture.tearDown
    def test_sealed_history_tokens_receipts_and_stale_login(self):
        store=Artifacts(self.root);a=store.save('Private','html','<p>private synthetic contents</p>');state=APIState(self.root)
        grant=state.issue('Synthetic',['artifacts:read']);token=state.authenticate('Bearer '+grant['token'])
        state.receipt(token,'private-request-1','POST','/synthetic',{},lambda:{'saved':True})
        version=store.path('Versions/'+a['id']+'/'+a['head']+'.json');catalog=store.path('Catalog/'+a['id']+'.json')
        self.runtime.close(self.session,writers_stopped=True);self.assertFalse(version.exists());self.assertFalse(catalog.exists())
        with self.assertRaises(ProfileLocked):state.tokens()
        self.session=self.backend.login(fixtures.OWNER);self.runtime.prepare(self.session)
        self.assertFalse(version.exists());reopened=Artifacts(self.root);self.assertEqual(reopened.list()[0]['id'],a['id'])
        self.assertFalse(version.exists());self.assertIn('private synthetic',reopened.read(a['id'])['content'])
        restored=APIState(self.root);restored.authenticate('Bearer '+grant['token'])
        self.assertEqual(restored.receipt(token,'private-request-1','POST','/synthetic',{},lambda:self.fail('Must not replay')),{'saved':True})
        with self.assertRaises(ProfileLocked):store.read(a['id'])

if __name__=='__main__':unittest.main()
