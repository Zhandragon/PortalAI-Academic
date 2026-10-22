"""Cached web results cannot outlive their captured account workspace."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import web_state
from profile_paths import UID_ENV,EPOCH_ENV,ProfileLocked


class WebProfileStateTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='Portal web profile ')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        (self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{
            'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        (self.root/'Private').mkdir()
        self.marker=self.root/'Private/active-session.json'
        self.uid,self.epoch='a'*32,'b'*32
        self.active={'user_id':self.uid,'epoch':self.epoch,'state':'open'}
        self.marker.write_text(json.dumps(self.active))
        environment=patch.dict(os.environ,{UID_ENV:self.uid,EPOCH_ENV:self.epoch})
        environment.start();self.addCleanup(environment.stop)
        self.result={'provider':'fixture','results':[{'title':'Public source','url':'https://example.com/'}]}
        self.state=web_state.WebState(self.root)

    def revoke(self):
        self.marker.write_text(json.dumps({**self.active,'state':'closed'}))

    def test_active_cache_is_private_and_reconstructed_with_same_epoch(self):
        self.state.save('one',3,self.result)
        self.state.block('fixture',60,'HTTP 403')
        replacement=web_state.WebState(self.root)
        self.assertEqual(replacement.cached('one',3)['results'],self.result['results'])
        self.assertEqual(replacement.cooling('fixture')['message'],'HTTP 403')
        self.assertTrue(replacement.path.is_relative_to(self.root/'Private/Users'/self.uid/'Workspace/Cache/Web'))
        self.assertFalse((self.root/'Cache').exists())

    def test_all_stale_entry_points_reject_before_recreating_cache(self):
        self.revoke()
        actions=(lambda:self.state.save('one',3,self.result),
                 lambda:self.state.block('fixture',60,'denied'),
                 lambda:self.state.cached('one',3),lambda:self.state.cooling('fixture'))
        for action in actions:
            with self.assertRaises(ProfileLocked):action()
        with self.assertRaises(ProfileLocked):
            with self.state.connection():self.fail('A stale database was opened')
        self.assertFalse((self.root/'Private/Users').exists())
        with self.assertRaises(ProfileLocked):web_state.WebState(self.root)

    def test_revocation_during_space_admission_does_not_create_directory(self):
        with patch.object(web_state,'require_space',side_effect=lambda *a,**kw:self.revoke()):
            with self.assertRaises(ProfileLocked):self.state.save('late',3,self.result)
        self.assertFalse(self.state.path.parent.exists())

    def test_replaced_login_cannot_reuse_old_instance_even_with_same_user(self):
        self.state.save('existing',3,self.result)
        epoch='c'*32
        self.marker.write_text(json.dumps({**self.active,'epoch':epoch}))
        with patch.dict(os.environ,{EPOCH_ENV:epoch}):
            with self.assertRaises(ProfileLocked):self.state.cached('existing',3)
            with self.assertRaises(ProfileLocked):self.state.save('late',3,self.result)
            self.assertTrue(web_state.WebState(self.root).cached('existing',3)['cached'])

    def test_revoked_write_transaction_rolls_back_save_and_cooldown(self):
        self.state.save('existing',3,self.result)
        original_connect=sqlite3.connect
        owner=self
        class RevokeOnPrune(sqlite3.Connection):
            def execute(self,sql,*args,**kwargs):
                value=super().execute(sql,*args,**kwargs)
                if 'NOT IN (SELECT' in sql:owner.revoke()
                return value
        for kind in ('save','block'):
            self.marker.write_text(json.dumps(self.active))
            with patch.object(web_state.sqlite3,'connect',side_effect=lambda *a,**kw:original_connect(*a,**kw,factory=RevokeOnPrune)):
                with self.assertRaises(ProfileLocked):
                    if kind=='save':self.state.save('late',3,self.result)
                    else:self.state.block('late-provider',60,'refused')
            with closing(original_connect(self.state.path)) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM cache').fetchone()[0],1)
                self.assertEqual(db.execute('SELECT count(*) FROM cooldown').fetchone()[0],0)

    def test_decoding_cached_value_rechecks_login_before_return(self):
        self.state.save('existing',3,self.result)
        original_loads=json.loads
        def loads(value,*args,**kwargs):
            result=original_loads(value,*args,**kwargs)
            if isinstance(result,dict) and result.get('provider')=='fixture':self.revoke()
            return result
        with patch.object(web_state.json,'loads',side_effect=loads):
            with self.assertRaises(ProfileLocked):self.state.cached('existing',3)

    def test_explicit_fixture_environment_is_copied_and_never_authorizes_private_root(self):
        with self.assertRaises(ProfileLocked):web_state.WebState(self.root,environ={})
        with self.assertRaises(ValueError):web_state.WebState(self.root,environ={UID_ENV:self.uid,EPOCH_ENV:self.epoch})
        fixture=self.root/'isolated';fixture.mkdir()
        (fixture/'Agent').mkdir()
        (fixture/'Agent/hardware_profiles.json').write_bytes((self.root/'Agent/hardware_profiles.json').read_bytes())
        environment={}
        state=web_state.WebState(fixture,environ=environment)
        environment[UID_ENV]=self.uid
        state.save('fixture',3,self.result)
        self.assertEqual(state.context,None)
        self.assertTrue(state.path.is_relative_to(fixture/'Cache/Web'))
        self.assertTrue(state.cached('fixture',3)['cached'])

    def test_legacy_cache_does_not_survive_account_activation(self):
        fixture=self.root/'legacy';fixture.mkdir()
        with patch.dict(os.environ,{},clear=True):state=web_state.WebState(fixture)
        (fixture/'Private').mkdir()
        (fixture/'Private/active-session.json').write_text(json.dumps(self.active))
        with self.assertRaises(ProfileLocked):state.save('late',3,self.result)
        self.assertFalse((fixture/'Cache').exists())


if __name__=='__main__':unittest.main()
