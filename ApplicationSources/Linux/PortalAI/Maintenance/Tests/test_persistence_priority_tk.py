"""Exercise real expanding sheets and the schedule toggle with offline records."""
import os,json,sys,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
import test_persistence_readability_tk as fixtures
from test_settings_surfaces_tk import LIGHT,widgets
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from mission_schedule import Schedules
from chat_priority import Foreground

class PriorityLayoutTests(unittest.TestCase):
    setUp=fixtures.PersistenceReadabilityTests.setUp
    tearDown=fixtures.PersistenceReadabilityTests.tearDown
    texts=fixtures.PersistenceReadabilityTests.texts
    def settle(self):
        end=time.monotonic()+.25
        while time.monotonic()<end:self.app.update();time.sleep(.01)
    def test_missions_and_schedules_grow_and_shrink(self):
        self.app.maxsize(3000,3000)
        for factory in (show_mission_settings,show_schedule_settings):
            self.app.geometry('1100x720');self.sheet=factory(self.app,self.root,LIGHT,embedded=True);self.settle()
            tree=next(w for w in widgets(self.sheet) if isinstance(w,ttk.Treeview))
            detail=next(w for w in self.texts() if str(w.cget('state'))=='disabled')
            small=(tree.winfo_height(),detail.winfo_height())
            self.app.geometry('1100x1100');self.settle()
            large=(tree.winfo_height(),detail.winfo_height())
            self.assertGreater(large[0],small[0]+100);self.assertGreater(large[1],small[1]+100)
            self.app.geometry('1100x720');self.settle();self.assertLess(tree.winfo_height(),large[0]-100)
            self.sheet.on_close();self.sheet=None
    def test_toggle_and_saved_state_refresh(self):
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);self.app.update()
        store=Schedules(self.root);s=store.create('Toggle this fixture');self.sheet.refresh_records()
        tree=self.sheet.schedule_tree;tree.selection_set(s['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update()
        button=self.sheet.schedule_toggle;self.assertEqual(button.cget('text'),'Enable')
        with patch('mission_supervisor.ensure_running',return_value={'started':False}):
            # The builder captured ensure_running; replace it via the closure's
            # global object before constructing the next sheet.
            self.sheet.on_close();self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);self.app.update()
            tree=self.sheet.schedule_tree;tree.selection_set(s['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update();button=self.sheet.schedule_toggle
            button.invoke();self.assertTrue(store.enabled(store.load(s['id'])));self.assertEqual(button.cget('text'),'Disable');self.assertEqual(tree.item(s['id'],'values')[1],'scheduled')
            button.invoke();self.assertFalse(store.enabled(store.load(s['id'])));self.assertEqual(button.cget('text'),'Enable');self.assertEqual(tree.item(s['id'],'values')[1],'paused')
            store.enable(s['id']);self.sheet.refresh_records();self.assertEqual(button.cget('text'),'Disable')
            fg=Foreground(self.root)
            try:
                self.assertTrue(fg.acquire(threading.Event(),lambda:None,lambda text:None));self.sheet.refresh_records();self.assertEqual(tree.item(s['id'],'values')[1],'paused for chat');self.assertEqual(button.cget('text'),'Disable')
            finally:fg.close()

    def test_origin_filters_combine_with_removed_state(self):
        store=Schedules(self.root)
        user=store.create('User fixture',origin='user');diagnostic=store.create('Diagnostic fixture',origin='diagnostic')
        legacy=store.create('Old unclassified fixture');removed=store.create('Removed user fixture',origin='user');store.remove(removed['id'])
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);self.settle()
        for state,source,expected in [('Active and paused','User created',user),('Active and paused','Diagnostic',diagnostic),
                                      ('Active and paused','Legacy / unclassified',legacy),('Removed schedules','User created',removed)]:
            self.sheet.schedule_state_filter.set(state);self.sheet.schedule_origin_filter.set(source);self.sheet.refresh_records();self.settle()
            tree=self.sheet.schedule_tree;self.assertEqual(tree.get_children(),(expected['id'],))
            tree.selection_set(expected['id']);tree.event_generate('<<TreeviewSelect>>');self.app.update()
            if state=='Removed schedules':self.assertEqual(str(self.sheet.schedule_toggle.cget('state')),'disabled')
        self.assertFalse(store.any_enabled())

if __name__=='__main__':unittest.main()
