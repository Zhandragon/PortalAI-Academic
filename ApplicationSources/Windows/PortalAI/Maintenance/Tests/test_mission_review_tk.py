"""Real Tk review entry, draft retention and schedule re-enable controls."""
import sys,time
from pathlib import Path
from unittest.mock import patch
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
import test_persistence_readability_tk as fixtures
from test_settings_surfaces_tk import LIGHT,DARK,widgets
from record_refresh_fixture import settle_records
from tkinter import ttk
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from mission_runner import Missions
from mission_schedule import Schedules
from mission_catalog import MissionCatalog

class ReviewTkTests(unittest.TestCase):
    setUp=fixtures.PersistenceReadabilityTests.setUp
    tearDown=fixtures.PersistenceReadabilityTests.tearDown
    def select(self,mid):
        self.sheet.mission_tree.selection_set(mid);self.sheet.mission_tree.event_generate('<<TreeviewSelect>>');settle_records(self.app)
        self.sheet.review_panel.set_open();settle_records(self.app)
    def wait(self,predicate):
        until=time.monotonic()+5
        while not predicate() and time.monotonic()<until:settle_records(self.app);time.sleep(.02)
        self.assertTrue(predicate());settle_records(self.app)
    def test_entry_submit_uncertainty_and_drafts_survive_refresh_theme_selection(self):
        store=Missions(self.root);missions=[store.create('Synthetic '+str(i)) for i in range(2)]
        for m in missions:
            m.update(status='needs_review',pending_action={'action':'note','text':'Uncertain'},error='Inspect output');store.save(m)
            MissionCatalog(self.root).mark_origin(m['id'])
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app);self.select(missions[0]['id'])
        self.assertTrue(self.sheet.review_submit.winfo_ismapped())
        self.sheet.review_instructions.insert('1.0','Inspect the CSV header.')
        self.sheet.refresh_records();settle_records(self.app);self.sheet.apply_palette(DARK);settle_records(self.app)
        self.select(missions[1]['id']);self.assertEqual(self.sheet.review_instructions.get('1.0','end-1c'),'')
        self.sheet.review_instructions.insert('1.0','Second draft');self.select(missions[0]['id'])
        self.assertEqual(self.sheet.review_instructions.get('1.0','end-1c'),'Inspect the CSV header.')
        self.sheet.review_submit.invoke()
        self.wait(lambda:'pending action is still unresolved' in self.sheet.review_status.get())
        self.assertIsNotNone(store.load(missions[0]['id'])['pending_action'])
        self.sheet.review_resolution.set('Reviewed: skip pending action');self.sheet.review_submit.invoke()
        self.wait(lambda:store.load(missions[0]['id'])['status']=='queued')
        self.assertEqual(store.load(missions[0]['id'])['review_instructions'],'Inspect the CSV header.')
        self.select(missions[1]['id']);self.assertEqual(self.sheet.review_instructions.get('1.0','end-1c'),'Second draft')
    def test_stale_decision_is_not_applied_to_new_problem(self):
        store=Missions(self.root);m=store.create('Changing problem');m.update(status='needs_review',error='First');store.save(m);MissionCatalog(self.root).mark_origin(m['id'])
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app);self.select(m['id'])
        self.sheet.review_instructions.insert('1.0','My answer')
        m.update(error='New problem',pending_action={'action':'note','text':'New action'});store.save(m)
        self.sheet.review_submit.invoke();settle_records(self.app)
        self.assertIn('mission changed',self.sheet.review_status.get());self.assertNotIn('review_instructions',store.load(m['id']))
        self.assertEqual(self.sheet.review_instructions.get('1.0','end-1c'),'My answer')
    def test_reviewed_scheduled_run_can_be_enabled_again(self):
        schedules=Schedules(self.root);s=schedules.create('Scheduled fixture',first_run_at=0)
        schedules.enable(s['id']);schedules.tick();s=schedules.load(s['id']);m=schedules.store.load(s['active_run'])
        m.update(status='needs_review',error='Needs answer');schedules.store.save(m);schedules.tick()
        with patch('mission_supervisor.ensure_running',return_value={'started':False}):
            self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
            self.sheet.schedule_tree.selection_set(s['id']);self.sheet.schedule_tree.event_generate('<<TreeviewSelect>>');settle_records(self.app)
            self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'disabled')
            schedules.store.review(m['id'],'Use the new input');self.sheet.refresh_records();settle_records(self.app);settle_records(self.app)
            self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'normal')
            self.sheet.schedule_toggle.invoke();self.assertTrue(schedules.enabled(schedules.load(s['id'])))
    def test_compact_schedule_keeps_all_actions_visible_in_each_mode(self):
        from mission_modes import MODES,profile
        self.app.geometry('1220x668+30+30')
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        mode=next(w for w in widgets(self.sheet) if isinstance(w,ttk.Combobox) and profile('observe')['label'] in w.cget('values'))
        for palette in (LIGHT,DARK):
            self.sheet.apply_palette(palette)
            for key in MODES:
                mode.set(profile(key)['label']);settle_records(self.app)
                canvas=self.sheet.skin.canvas;self.assertEqual(canvas.yview(),(0.0,1.0))
                bottom=canvas.winfo_rooty()+canvas.winfo_height()
                for control in widgets(self.sheet.content):
                    folded={w for panel in (self.sheet.creation_panel,self.sheet.options_panel,self.sheet.filters_panel) if not panel.expanded for w in widgets(panel.body)}
                    if isinstance(control,ttk.Button) and control not in folded:
                        self.assertTrue(control.winfo_ismapped())
                        self.assertLessEqual(control.winfo_rooty()+control.winfo_height(),bottom)
        self.assertEqual(self.sheet.schedule_state_filter.get(),'Active and paused')
        self.assertEqual(self.sheet.schedule_origin_filter.get(),'All origins')

if __name__=='__main__':unittest.main()
