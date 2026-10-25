"""Native compact/resizing and review navigation with synthetic data only."""
import json
import unittest
from unittest.mock import patch
import test_persistence_readability_tk as fixtures
from test_settings_surfaces_tk import LIGHT,DARK,widgets
from record_refresh_fixture import settle_records
from mission_runner import Missions
from mission_schedule import Schedules
from mission_catalog import MissionCatalog
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from mission_review_issue import SECTION


class ReviewLayoutTests(unittest.TestCase):
    setUp=fixtures.PersistenceReadabilityTests.setUp
    tearDown=fixtures.PersistenceReadabilityTests.tearDown

    def test_default_reading_area_is_large_and_creation_drafts_survive_folding(self):
        self.app.maxsize(3000,3000)
        for factory in (show_mission_settings,show_schedule_settings):
            self.app.geometry('1220x668');self.sheet=factory(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
            viewer=self.sheet.run_viewer
            self.assertFalse(self.sheet.creation_panel.expanded)
            self.assertFalse(self.sheet.options_panel.expanded)
            self.assertGreater(viewer.text.winfo_height(),250)
            self.assertGreater(viewer.winfo_width(),600)
            initial=viewer.text.winfo_height()
            self.app.geometry('1500x1000');settle_records(self.app);self.assertGreater(viewer.text.winfo_height(),initial+200)
            self.app.geometry('800x720');settle_records(self.app)
            table=(getattr(self.sheet,'mission_tree',None) or self.sheet.schedule_tree).master
            self.assertLess(table.winfo_rooty(),viewer.winfo_rooty())
            self.app.geometry('1220x668');settle_records(self.app);self.assertGreater(viewer.text.winfo_height(),250)
            self.sheet.creation_panel.set_open();settle_records(self.app)
            draft=next(w for w in widgets(self.sheet.creation_panel.body) if w.winfo_class()=='Text')
            draft.insert('1.0','Retain this draft')
            self.sheet.creation_panel.set_open(False);self.sheet.refresh_records();settle_records(self.app);self.sheet.apply_palette(DARK);settle_records(self.app)
            self.sheet.creation_panel.set_open();settle_records(self.app);self.assertEqual(draft.get('1.0','end-1c'),'Retain this draft')
            self.sheet.on_close();self.sheet=None

    def test_review_issue_opens_on_selection_and_does_not_override_manual_view(self):
        store=Missions(self.root);m=store.create('Synthetic review')
        m.update(status='needs_review',error='Repeated identical actions without progress');store.save(m);MissionCatalog(self.root).mark_origin(m['id'])
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        tree=self.sheet.mission_tree;tree.selection_set(m['id']);settle_records(self.app)
        viewer=self.sheet.run_viewer;self.assertEqual(viewer.section.get(),SECTION)
        self.assertIn('same action',viewer.text.get('1.0','end'))
        self.assertIn(SECTION,viewer.sections.cget('values'))
        viewer.section.set('Details');viewer.sections.event_generate('<<ComboboxSelected>>')
        self.sheet.refresh_records();settle_records(self.app);settle_records(self.app);self.assertEqual(viewer.section.get(),'Details')
        self.sheet.review_panel.set_open();settle_records(self.app)
        self.assertTrue(self.sheet.review_submit.winfo_ismapped())
        self.sheet.review_instructions.insert('end','A different strategy')
        self.sheet.review_panel.set_open(False);self.sheet.refresh_records();settle_records(self.app);self.sheet.review_panel.set_open()
        self.assertIn('different strategy',self.sheet.review_instructions.get('1.0','end'))

    def test_schedule_issue_context_and_recovery_control_remain_readable(self):
        schedules=Schedules(self.root);s=schedules.create('Synthetic schedule issue')
        s.update(status='needs_review',error='Missing model file');schedules.save(s)
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        tree=self.sheet.schedule_tree;tree.selection_set(s['id']);settle_records(self.app)
        viewer=self.sheet.run_viewer
        self.assertEqual(viewer.section.get(),SECTION);self.assertIn('could not prepare',viewer.text.get('1.0','end'))
        self.assertEqual(viewer.run.get(),'Schedule issue')
        self.sheet.options_panel.set_open();settle_records(self.app)
        control=self.sheet.recovery_toggle
        self.assertTrue(control.winfo_ismapped());self.assertEqual(int(control.cget('wraplength')),0)
        self.assertGreater(control.winfo_width(),130);self.assertLess(control.winfo_height(),50)
        before=schedules.path(s['id']).read_bytes()
        viewer.draw();self.sheet.refresh_records();settle_records(self.app);self.assertEqual(schedules.path(s['id']).read_bytes(),before)

    def test_missing_linked_mission_still_has_plain_review_explanation(self):
        schedules=Schedules(self.root);s=schedules.create('Missing linked run')
        s.update(status='needs_review',active_run='d'*32,error='Active run requires review');schedules.save(s)
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        self.sheet.schedule_tree.selection_set(s['id']);settle_records(self.app)
        text=self.sheet.run_viewer.text.get('1.0','end')
        self.assertIn('could not be read',text);self.assertIn('d'*32,text)

    def test_new_blocker_resets_overview_scroll_and_leaves_history_selection_independent(self):
        store=Missions(self.root);m=store.create('Long objective '*500);MissionCatalog(self.root).mark_origin(m['id'])
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        self.sheet.mission_tree.selection_set(m['id']);settle_records(self.app)
        viewer=self.sheet.run_viewer;viewer.text.yview_moveto(1)
        m.update(status='needs_review',error='Repeated identical actions without progress');store.save(m)
        self.sheet.refresh_records();settle_records(self.app);settle_records(self.app)
        self.assertEqual(viewer.section.get(),SECTION);self.assertEqual(viewer.text.yview()[0],0)
        viewer.section.set('Action history');viewer.draw(reset=True)
        self.sheet.refresh_records();settle_records(self.app);self.assertEqual(viewer.section.get(),'Action history')


if __name__=='__main__':unittest.main()
