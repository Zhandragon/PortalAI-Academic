"""Exercise real persistence controls against synthetic records, never owner work."""
import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
import test_persistence_readability_tk as fixtures
from test_settings_surfaces_tk import LIGHT,DARK
from record_refresh_fixture import settle_records
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from mission_catalog import MissionCatalog
from mission_runner import Missions
from mission_schedule import Schedules
from mission_supervisor import disarm

class OrganizationTkTests(unittest.TestCase):
    setUp=fixtures.PersistenceReadabilityTests.setUp
    tearDown=fixtures.PersistenceReadabilityTests.tearDown
    def search(self,text):
        self.sheet.record_search.query.set(text);self.sheet.record_search.run();settle_records(self.app);settle_records(self.app)
    def test_mission_search_classify_filter_and_refresh_preserve_draft(self):
        store=Missions(self.root);m=store.create('Business revenue playbook')
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        tree=self.sheet.mission_tree;self.assertEqual(tree.get_children(),())
        self.search(m['id'][3:16].upper());self.assertEqual(tree.selection(),(m['id'],))
        control=self.sheet.record_classification;control.value.set('User')
        self.sheet.refresh_records();settle_records(self.app);self.assertEqual(control.value.get(),'User')
        control.button.invoke();settle_records(self.app);self.search('')
        self.assertEqual(tree.get_children(),(m['id'],))
        self.search('REVEN play');self.assertEqual(tree.get_children(),(m['id'],))
        self.search('absent');self.assertEqual(tree.get_children(),())
        self.assertEqual(str(control.button.cget('state')),'disabled')
        self.search('business');self.sheet.apply_palette(DARK);self.sheet.refresh_records();settle_records(self.app);settle_records(self.app)
        self.assertEqual(self.sheet.record_search.query.get(),'business')
        self.assertEqual(MissionCatalog(self.root).rows('User missions only')[0]['mission']['id'],m['id'])
    def test_schedule_search_by_active_id_policy_and_blocked_enable(self):
        schedules=Schedules(self.root);s=schedules.create('Weekly business revenue',first_run_at=0)
        schedules.enable(s['id']);schedules.tick();s=schedules.load(s['id']);mid=s['active_run']
        m=schedules.store.load(mid);m.update(status='needs_review',error='Repeated planning');schedules.store.save(m)
        schedules.disable(s['id'])
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        self.search(mid[2:14]);self.assertEqual(self.sheet.schedule_tree.selection(),(s['id'],))
        self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'disabled')
        self.assertIn(mid,self.sheet.recovery_note.get())
        self.sheet.recovery_toggle.invoke();settle_records(self.app)
        self.assertTrue(schedules.load(s['id'])['autonomous_recovery'])
        self.assertFalse(schedules.any_enabled());self.assertTrue(schedules.store.stopped(m))
        control=self.sheet.record_classification;control.value.set('User');control.button.invoke();settle_records(self.app)
        self.assertEqual(schedules.load(s['id'])['classification']['kind'],'user')
        self.search('week REVEN');self.assertEqual(self.sheet.schedule_tree.get_children(),(s['id'],))
        self.sheet.apply_palette(DARK);self.sheet.refresh_records();settle_records(self.app);settle_records(self.app)
        self.assertTrue(self.sheet.autonomous_recovery.get())
        schedules.store.resume(mid);self.sheet.refresh_records();settle_records(self.app);settle_records(self.app)
        self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'normal')

if __name__=='__main__':unittest.main()
