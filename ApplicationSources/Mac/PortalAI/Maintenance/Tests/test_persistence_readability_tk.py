"""Readable blank/populated persistence sheets with disposable offline records."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from profile_paths import UID_ENV, EPOCH_ENV
from mission_runner import Missions
from mission_schedule import Schedules
from mission_settings import show_mission_settings, mission_details
from schedule_settings import show_schedule_settings, schedule_details
from test_settings_surfaces_tk import LIGHT, DARK, widgets
from tk_fixture_cleanup import finish_tk_fixture


class PersistenceReadabilityTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1180x720+30+30')
        self.errors=[];self.app.report_callback_exception=lambda *error:self.errors.append(error)
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        (self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.env=patch.dict(os.environ, {}, clear=False);self.env.start()
        os.environ.pop(UID_ENV,None);os.environ.pop(EPOCH_ENV,None)
        self.sheet=None

    def tearDown(self):
        if self.sheet:self.sheet.on_close()
        finish_tk_fixture(self.app);self.env.stop();self.temporary.cleanup()
        self.assertEqual(self.errors,[])

    def texts(self):return [w for w in widgets(self.sheet) if isinstance(w,tk.Text)]

    def test_mission_fields_and_titles_remain_when_no_data(self):
        self.sheet=show_mission_settings(self.app,self.root,LIGHT,embedded=True);self.app.update()
        fields=self.texts();draft=next(w for w in fields if str(w.cget('state'))=='normal')
        details=next(w for w in fields if str(w.cget('state'))=='disabled')
        self.assertEqual(draft.get('1.0','end').strip(),'')
        self.assertIn('No mission selected',details.get('1.0','end'))
        self.assertIn('Action awaiting execution or review:',details.get('1.0','end'))
        self.assertIn('Nothing found to report',details.get('1.0','end'))
        titles=[w.cget('text') for w in widgets(self.sheet) if isinstance(w,tk.Label)]
        for title in ('New mission objective','Saved missions','Selected mission details'):
            self.assertIn(title,titles)
            label=next(w for w in widgets(self.sheet) if isinstance(w,tk.Label) and w.cget('text')==title)
            self.assertGreater(label.winfo_width(),200)
        border=next(b for b in self.sheet.skin.borders if b.widget is self.sheet.heading)
        self.assertTrue(border.canvas.find_withtag('ornate-corner-mask'))
        mission=Missions(self.root).create('Inspect a synthetic report')
        from mission_catalog import MissionCatalog
        MissionCatalog(self.root).mark_origin(mission['id'])
        self.sheet.refresh_records();tree=next(w for w in widgets(self.sheet) if isinstance(w,ttk.Treeview))
        tree.selection_set(mission['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update()
        self.assertIn('Inspect a synthetic report',details.get('1.0','end'))
        self.assertIn('Actions used / allowed:',details.get('1.0','end'))

    def test_schedule_empty_fields_populate_and_clear_without_stale_details(self):
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);self.app.update()
        details=next(w for w in self.texts() if str(w.cget('state'))=='disabled')
        self.assertIn('No schedule selected',details.get('1.0','end'))
        self.assertIn('Next planned run:',details.get('1.0','end'))
        store=Schedules(self.root);s=store.create('Review synthetic input every hour','observe',12,3600,None,3)
        self.sheet.refresh_records();tree=self.sheet.schedule_tree
        tree.selection_set(s['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update()
        text=details.get('1.0','end')
        for phrase in ('Review synthetic input','Every 60 minutes','No; paused','Run limit: 3'):self.assertIn(phrase,text)
        tree.selection_remove(s['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update()
        self.assertNotIn(s['id'],details.get('1.0','end'))
        self.assertIn('Nothing found to report',details.get('1.0','end'))
        self.assertFalse(store.enabled(store.load(s['id'])))

    def test_sheet_theme_round_trip_preserves_readable_surfaces_and_drafts(self):
        for factory in (show_mission_settings, show_schedule_settings):
            self.sheet=factory(self.app,self.root,LIGHT,embedded=True);self.app.update()
            draft=next(w for w in self.texts() if str(w.cget('state'))=='normal')
            details=next(w for w in self.texts() if str(w.cget('state'))=='disabled')
            draft.insert('1.0','Keep this draft through both theme changes')
            saved_details=details.get('1.0','end')
            labels=[w for w in widgets(self.sheet.content) if isinstance(w,tk.Label)]
            accent_labels=[w for w in labels if w.cget('fg')==LIGHT['accent']]
            for palette in (DARK,LIGHT):
                self.sheet.apply_palette(palette);self.app.update()
                self.assertEqual(self.sheet.content.cget('bg'),palette['panel'])
                for label in labels:
                    self.assertEqual(label.cget('bg'),palette['panel'])
                    self.assertEqual(label.cget('fg'),palette['accent'] if label in accent_labels else palette['text'])
                for text in (draft,details):
                    self.assertEqual(text.cget('bg'),palette['panel'])
                    self.assertEqual(text.cget('insertbackground'),palette['text'])
                self.assertIn('Keep this draft',draft.get('1.0','end'))
                self.assertEqual(details.get('1.0','end'),saved_details)
            self.sheet.on_close();self.sheet=None

    def test_compact_empty_sheets_fit_all_access_modes_without_page_scroll(self):
        from mission_modes import MODES, profile
        self.app.geometry('1220x668+30+30')
        for factory in (show_mission_settings,show_schedule_settings):
            self.sheet=factory(self.app,self.root,LIGHT,embedded=True);self.app.update()
            mode=next(w for w in widgets(self.sheet) if isinstance(w,ttk.Combobox)
                      and profile('observe')['label'] in w.cget('values'))
            draft=next(w for w in self.texts() if str(w.cget('state'))=='normal')
            for key in MODES:
                mode.set(profile(key)['label']);self.app.update()
                canvas=self.sheet.skin.canvas
                self.assertEqual(canvas.yview(),(0.0,1.0),(factory.__name__,key,canvas.bbox('all'),canvas.winfo_height()))
                bottom=canvas.winfo_rooty()+canvas.winfo_height()
                for control in widgets(self.sheet.content):
                    if isinstance(control,ttk.Button):
                        # Review-only controls deliberately hide without a selected problem.
                        parent=control.master
                        if any(isinstance(w,tk.Label) and w.cget('text')=='Additional instructions for this mission'
                               for w in parent.winfo_children()) and not parent.winfo_ismapped():continue
                        self.assertTrue(control.winfo_ismapped())
                        self.assertLessEqual(control.winfo_rooty()+control.winfo_height(),bottom)
                self.assertEqual(draft.get('1.0','end').strip(),'')
            self.sheet.on_close();self.sheet=None

    def test_completed_runs_are_navigable_and_live_progress_does_not_replace_results(self):
        import time
        from mission_activity import Activity
        schedules=Schedules(self.root)
        schedule=schedules.create('Synthetic daily report',interval_seconds=60,max_runs=2)
        schedules.enable(schedule['id']);now=time.time()
        for index in range(2):
            schedules.tick(now=now+index*120)
            mid=schedules.load(schedule['id'])['active_run']
            def plan(m):
                return {'action':'note','text':f'Finding from run {index+1}'} if not m['steps'] else {'action':'complete','text':f'Report {index+1} complete'}
            schedules.store.run(mid,steps=2,model=plan)
            schedules.tick(now=now+index*120)
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);self.app.update()
        tree=self.sheet.schedule_tree;tree.selection_set(schedule['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update()
        viewer=self.sheet.run_viewer
        self.assertEqual(len(viewer.run_ids),2)
        viewer.section.set('Results');viewer.sections.event_generate('<<ComboboxSelected>>');self.app.update()
        self.assertIn('Finding from run 2',viewer.text.get('1.0','end'))
        viewer.run.set(list(viewer.run_ids)[1]);viewer.runs.event_generate('<<ComboboxSelected>>');self.app.update()
        self.assertIn('Finding from run 1',viewer.text.get('1.0','end'))
        self.assertNotIn('Finding from run 2',viewer.text.get('1.0','end'))
        self.sheet.refresh_records();self.app.update()
        self.assertIn('Finding from run 1',viewer.text.get('1.0','end'))
        m=schedules.store.load(viewer.run_ids[viewer.run.get()])
        before=(schedules.store.folder(m['id'])/'mission.json').read_bytes()
        activity=Activity(schedules.store,m);activity.update('generating','Receiving model output',preview='UNCOMMITTED PREVIEW',generated_chars=19,force=True)
        viewer.section.set('Live activity');viewer.sections.event_generate('<<ComboboxSelected>>');self.app.update()
        self.assertIn('UNCOMMITTED PREVIEW',viewer.text.get('1.0','end'))
        viewer.section.set('Results');viewer.draw(reset=True)
        self.assertNotIn('UNCOMMITTED PREVIEW',viewer.text.get('1.0','end'))
        self.assertEqual(before,(schedules.store.folder(m['id'])/'mission.json').read_bytes())


if __name__ == '__main__':unittest.main()
