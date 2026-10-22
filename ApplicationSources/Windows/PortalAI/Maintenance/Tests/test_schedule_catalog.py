"""Read-only origin/state classification over disposable saved schedules."""
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
import test_mission_schedule as fixtures
from schedule_catalog import origin,select

class ScheduleCatalogTests(unittest.TestCase):
    setUp=fixtures.ScheduleTests.setUp
    def test_recorded_user_and_diagnostic_origins_survive_transitions(self):
        for kind in ('user','diagnostic'):
            s=self.schedules.create('A fixture objective',origin=kind)
            for change in (self.schedules.enable,self.schedules.disable,self.schedules.remove,self.schedules.restore):
                change(s['id']);self.assertEqual(origin(self.schedules.load(s['id']))['kind'],kind)
            self.assertFalse(self.schedules.enabled(self.schedules.load(s['id'])))
    def test_legacy_is_unclassified_except_known_self_test_wording(self):
        plain=self.schedules.create('Check my report')
        known=self.schedules.create('Bounded schedule regression test fixture')
        self.assertEqual(origin(plain)['kind'],'legacy');self.assertFalse(origin(plain)['confirmed'])
        self.assertEqual(origin(known)['kind'],'diagnostic');self.assertFalse(origin(known)['confirmed'])
        explicit=self.schedules.create(known['objective'],origin='user')
        self.assertEqual(origin(explicit)['kind'],'user')
    def test_source_and_removed_filters_combine_without_writing_or_enabling(self):
        user=self.schedules.create('User fixture',origin='user')
        diagnostic=self.schedules.create('Test fixture',origin='diagnostic')
        legacy=self.schedules.create('Older unknown fixture')
        removed=self.schedules.create('Removed user',origin='user');self.schedules.remove(removed['id'])
        before={p.name:p.read_bytes() for p in self.schedules.base.glob('*.json')}
        rows=self.schedules.list()
        def ids(state,source):return {s['id'] for s in select(rows,state,source)}
        self.assertEqual(ids('Active and paused','User created'),{user['id']})
        self.assertEqual(ids('Removed schedules','User created'),{removed['id']})
        self.assertEqual(ids('All schedules','Diagnostic'),{diagnostic['id']})
        self.assertEqual(ids('All schedules','Legacy / unclassified'),{legacy['id']})
        self.assertEqual(len(select(rows,'All schedules')),4)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.schedules.base.glob('*.json')})
        self.assertFalse(self.schedules.any_enabled());self.assertEqual(self.store.list(),[])
    def test_invalid_origin_is_rejected_before_writing(self):
        with self.assertRaises(ValueError):self.schedules.create('Invalid',origin='invented')
        self.assertEqual(self.schedules.list(),[])
    def test_corrupt_records_remain_visible_as_unclassified_for_review(self):
        bad={'id':'broken','status':'needs_review','error':'Invalid record','objective':'Unreadable schedule'}
        self.assertEqual(select([bad],source='Legacy / unclassified'),[bad])

if __name__=='__main__':unittest.main()
