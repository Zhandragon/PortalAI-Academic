"""Manual labels and cross-filter literal search on disposable account records."""
import json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
import test_mission_catalog as fixtures
from mission_catalog import MissionCatalog
from mission_schedule import Schedules
from schedule_catalog import origin,select
from mission_supervisor import arm,disarm,read_policy
from mission_runner import process_lock

class OrganizationTests(unittest.TestCase):
    setUp=fixtures.MissionCatalogTests.setUp
    def test_manual_classification_preserves_checkpoint_origin_and_arming(self):
        m=self.store.create('Bounded schedule regression test Business Research')
        self.catalog.mark_origin(m['id'],'validation','fixture')
        arm(self.root,m['id'])
        before=(self.store.folder(m['id'])/'mission.json').read_bytes()
        self.catalog.classify(m['id'],'user')
        self.assertEqual(self.catalog.rows('User missions only')[0]['mission']['id'],m['id'])
        self.catalog.mark_origin(m['id'],'validation','automatic refresh')
        self.assertEqual(self.catalog.rows()[0]['origin']['kind'],'user')
        self.catalog.classify(m['id'],'unknown')
        self.assertEqual(self.catalog.rows('Diagnostics'),[])
        self.catalog.classify(m['id'],None)
        self.assertEqual(self.catalog.rows('Diagnostics')[0]['mission']['id'],m['id'])
        self.assertEqual((self.store.folder(m['id'])/'mission.json').read_bytes(),before)
        self.assertTrue(read_policy(self.store,m['id'])['enabled'])

    def test_search_finds_hidden_deleted_full_and_partial_ids_keywords_and_links(self):
        m=self.store.create('Quarterly BUSINESS revenue playbook')
        disarm(self.root,m['id']);self.catalog.delete(m['id'])
        before=(self.store.folder(m['id'])/'mission.json').read_bytes()
        for query in (m['id'],m['id'][4:15].upper(),'BUSIN REVEN','business   play'):
            rows=self.catalog.rows('User missions only',query)
            self.assertEqual([r['mission']['id'] for r in rows],[m['id']])
            self.assertTrue(rows[0]['deleted'])
        self.assertEqual(self.catalog.rows('User missions only',''),[])
        self.assertEqual(self.catalog.rows('All records','business missing'),[])
        self.assertEqual(self.catalog.rows('All records','.*'),[])
        self.assertEqual((self.store.folder(m['id'])/'mission.json').read_bytes(),before)
        s=Schedules(self.root).create('Scheduled business',first_run_at=0)
        schedules=Schedules(self.root);schedules.enable(s['id']);schedules.tick();s=schedules.load(s['id'])
        self.assertEqual(self.catalog.rows('User missions only',s['id'][:12])[0]['mission']['id'],s['active_run'])

    def test_schedule_override_survives_execution_and_is_inherited_unless_run_overridden(self):
        schedules=Schedules(self.root);s=schedules.create('Business cycle',first_run_at=0,origin='diagnostic')
        schedules.classify(s['id'],'user');schedules.enable(s['id']);schedules.tick();s=schedules.load(s['id'])
        m=self.store.load(s['active_run'])
        self.assertEqual(origin(s)['kind'],'user')
        self.assertEqual(self.catalog.rows('User missions only')[0]['mission']['id'],m['id'])
        self.catalog.classify(m['id'],'unknown')
        self.assertEqual(self.catalog.rows('User missions only'),[])
        self.catalog.classify(m['id'],None)
        self.assertEqual(self.catalog.rows('User missions only')[0]['origin']['source'],'Inherited manual schedule classification')
        schedules.disable(s['id']);schedules.remove(s['id'])
        for query in (s['id'][2:12],m['id'][2:12],'BUSI CYC'):
            self.assertEqual(select(schedules.list(),'Active and paused','Diagnostic',query)[0]['id'],s['id'])
        schedules.restore(s['id']);schedules.classify(s['id'],None)
        self.assertEqual(origin(schedules.load(s['id']))['kind'],'diagnostic')
        self.assertFalse(schedules.any_enabled())

    def test_invalid_labels_and_scheduler_lock_do_not_write(self):
        s=Schedules(self.root);record=s.create('Fixture')
        before=s.path(record['id']).read_bytes()
        with self.assertRaises(ValueError):s.classify(record['id'],'bogus')
        with process_lock(self.store.base/'schedules.lock'):
            with self.assertRaises(OSError):s.classify(record['id'],'user')
        self.assertEqual(s.path(record['id']).read_bytes(),before)

if __name__=='__main__':unittest.main()
