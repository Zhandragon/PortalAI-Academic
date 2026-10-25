"""Real heading callbacks reorder synthetic records across refresh/filter changes."""
import json
import unittest
from tkinter import ttk

import test_persistence_readability_tk as fixtures
from test_settings_surfaces_tk import LIGHT, DARK
from record_refresh_fixture import settle_records
from mission_runner import Missions
from mission_catalog import MissionCatalog
from mission_schedule import Schedules
from mission_supervisor import disarm
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from record_controls import RecordSort


class SortingTkTests(unittest.TestCase):
    setUp = fixtures.PersistenceReadabilityTests.setUp
    tearDown = fixtures.PersistenceReadabilityTests.tearDown

    def click(self, tree, key):
        tree.tk.call(tree.heading(key, 'command'))
        settle_records(self.app)

    def test_mission_headings_sort_full_text_counts_dates_and_preserve_review_draft(self):
        store = Missions(self.root); catalog = MissionCatalog(self.root)
        a = store.create('# zebra\n' + 'x'*180 + ' a', max_steps=12)
        b = store.create('# Alpha\n' + 'x'*180 + ' z', max_steps=12)
        for m, steps, created in ((a, 2, 1700000000), (b, 10, 1600000000)):
            disarm(self.root, m['id']); m = store.load(m['id'])
            m.update(steps=steps, created_at=created); store.save(m); catalog.mark_origin(m['id'])
        self.sheet = show_mission_settings(self.app, self.root, LIGHT, embedded=True); settle_records(self.app)
        tree = self.sheet.mission_tree
        tree.selection_set(a['id']); settle_records(self.app)
        review = self.sheet.review_instructions
        review.insert('end', 'Keep this unsaved strategy')
        for key, expected in (('name', (b['id'],a['id'])), ('steps', (a['id'],b['id'])),
                              ('created', (b['id'],a['id'])), ('updated', (a['id'],b['id']))):
            self.click(tree,key); self.assertEqual(tree.get_children(),expected)
            self.click(tree,key); self.assertEqual(tree.get_children(),expected[::-1])
            self.assertIn('▼',tree.heading(key,'text'))
            self.sheet.refresh_records();settle_records(self.app); self.assertEqual(tree.get_children(),expected[::-1])
            self.assertEqual(tree.selection(),(a['id'],))
            self.assertIn('Keep this unsaved strategy',review.get('1.0','end'))
        # Description compares the complete objective, even beyond its table preview.
        a=store.load(a['id']); b=store.load(b['id'])
        a['objective']='same '+'x'*180+' z'; b['objective']='same '+'x'*180+' a'
        store.save(a);store.save(b)
        self.click(tree,'objective');self.assertEqual(tree.get_children(),(b['id'],a['id']))
        self.sheet.record_search.query.set(a['id'][5:16]);self.sheet.record_search.run();settle_records(self.app)
        self.assertEqual(tree.get_children(),(a['id'],))
        self.sheet.record_search.query.set('');self.sheet.record_search.run();settle_records(self.app)
        self.assertEqual(tree.get_children(),(b['id'],a['id']))
        self.sheet.apply_palette(DARK);self.sheet.refresh_records();settle_records(self.app);settle_records(self.app)
        self.assertEqual(tree.get_children(),(b['id'],a['id']))
        self.assertIn('▲',tree.heading('objective','text'))
        self.assertTrue(all(tree.heading(k,'command') for k in tree['columns']))

    def test_schedule_sorting_dates_numeric_runs_category_and_selection(self):
        store=Schedules(self.root)
        a=store.create('zeta revenue',max_runs=10,first_run_at=1900000000)
        b=store.create('Alpha revenue',max_runs=2,first_run_at=1800000000)
        a.update(runs_completed=2,runs_started=2,created_at=1700000000,updated_at=1700000000)
        b.update(runs_completed=10,runs_started=10,created_at=1600000000,updated_at=1600000000)
        for s in (a,b):store.path(s['id']).write_text(json.dumps(s))
        store.classify(a['id'],'user');store.classify(b['id'],'diagnostic')
        self.sheet=show_schedule_settings(self.app,self.root,LIGHT,embedded=True);settle_records(self.app)
        tree=self.sheet.schedule_tree;tree.selection_set(a['id']);settle_records(self.app)
        for key,expected in (('name',(b['id'],a['id'])),('runs',(a['id'],b['id'])),
                             ('limit',(b['id'],a['id'])),('next',(b['id'],a['id'])),
                             ('created',(b['id'],a['id'])),('origin',(b['id'],a['id']))):
            self.click(tree,key);self.assertEqual(tree.get_children(),expected)
            self.click(tree,key);self.assertEqual(tree.get_children(),expected[::-1])
            self.sheet.refresh_records();settle_records(self.app);self.assertEqual(tree.get_children(),expected[::-1])
            self.assertEqual(tree.selection(),(a['id'],))
        control=self.sheet.record_classification;control.value.set('Diagnostic');control.button.invoke();settle_records(self.app)
        self.assertEqual(tree.selection(),(a['id'],))
        self.assertEqual(tree.get_children(),tuple(sorted((a['id'],b['id']))))
        self.assertTrue(all(tree.heading(k,'command') for k in tree['columns']))

    def test_generic_heading_sort_has_stable_id_ties_and_missing_values_last(self):
        tree=ttk.Treeview(self.app,columns=('status','date'),show='headings')
        for key in tree['columns']:tree.heading(key,text=key)
        records={'b':{'status':'Paused','date':None},'a':{'status':'paused','date':2},'c':{'status':'Complete','date':10}}
        for key in records:tree.insert('','end',iid=key)
        sort=RecordSort(tree,lambda:sort.apply(records))
        self.click(tree,'status');self.assertEqual(tree.get_children(),('c','a','b'))
        self.click(tree,'status');self.assertEqual(tree.get_children(),('a','b','c'))
        self.click(tree,'date');self.assertEqual(tree.get_children(),('a','c','b'))
        self.click(tree,'date');self.assertEqual(tree.get_children(),('c','a','b'))


if __name__=='__main__':unittest.main()
