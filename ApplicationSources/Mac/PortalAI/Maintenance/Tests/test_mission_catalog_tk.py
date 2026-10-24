"""Real Tk filtering/refresh against synthetic missions; no live user window."""
import json
import os
from pathlib import Path
import sys
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
from mission_runner import Missions
from mission_supervisor import disarm
from mission_catalog import MissionCatalog, VIEWS
from profile_paths import UID_ENV, EPOCH_ENV
import mission_settings


def children(widget):
    for child in widget.winfo_children():
        yield child
        yield from children(child)


class MissionCatalogTkTests(unittest.TestCase):
    def setUp(self):
        try: self.app = tk.Tk()
        except tk.TclError as exc: self.skipTest(str(exc))
        self.app.withdraw(); self.addCleanup(self.app.destroy)
        temporary = tempfile.TemporaryDirectory(prefix='Portal mission Tk ')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{
            'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        environment = patch.dict(os.environ, {}, clear=False); environment.start(); self.addCleanup(environment.stop)
        os.environ.pop(UID_ENV, None); os.environ.pop(EPOCH_ENV, None)
        self.store = Missions(self.root); self.catalog = MissionCatalog(self.root, store=self.store)
        self.user = self.store.create('A user project')
        self.unknown = self.store.create('Old plan without origin')
        self.legacy = self.store.create('Stop lifecycle test: do not execute any model actions')
        self.validation = self.store.create('Explicit fixture')
        self.catalog.mark_origin(self.user['id'])
        self.catalog.mark_origin(self.validation['id'], 'validation', 'Tools/fixture.py')
        self.window = mission_settings.show_mission_settings(self.app, self.root,
                            {'panel':'#efe8dc','bg':'#efe8dc','text':'#202020','accent':'#886620'})
        self.assertIs(self.window.winfo_toplevel(), self.app)
        self.addCleanup(self.close_window)
        controls = list(children(self.window))
        self.tree = next(item for item in controls if isinstance(item, ttk.Treeview))
        self.picker = next(item for item in controls if isinstance(item, ttk.Combobox) and tuple(item.cget('values')) == VIEWS)
        self.refresh = next(item for item in controls if isinstance(item, ttk.Button) and item.cget('text') == 'Refresh')
        self.delete = next(item for item in controls if isinstance(item, ttk.Button) and item.cget('text') == 'Delete…')

    def close_window(self):
        if self.window.winfo_exists():
            self.window.on_close()
        self.app.update_idletasks()

    def select_view(self, value):
        self.picker.set(value)
        self.picker.event_generate('<<ComboboxSelected>>')
        self.app.update()

    def test_default_view_shows_only_user_work_and_other_views_preserve_old_records(self):
        self.assertEqual(self.picker.get(), 'User missions only')
        self.assertEqual(set(self.tree.get_children()), {self.user['id']})
        self.assertEqual(self.tree.item(self.user['id'], 'values')[0], 'User mission')
        self.select_view('Diagnostics')
        self.assertEqual(set(self.tree.get_children()), {self.validation['id'], self.legacy['id']})
        self.assertEqual(self.tree.item(self.legacy['id'], 'values')[0], 'Legacy diagnostic')
        self.select_view('User & unclassified')
        self.assertEqual(set(self.tree.get_children()), {self.user['id'], self.unknown['id'], self.legacy['id']})
        self.select_view('All records')
        self.assertEqual(len(self.tree.get_children()), 4)
        self.select_view(VIEWS[0])
        created = self.store.create('New unclassified user mission')
        self.refresh.invoke()
        self.assertNotIn(created['id'], self.tree.get_children())
        self.catalog.mark_origin(created['id'])
        self.refresh.invoke()
        self.assertIn(created['id'], self.tree.get_children())

    def test_deleted_filter_restore_and_revised_record_refresh(self):
        disarm(self.root, self.user['id'])
        self.catalog.delete(self.user['id'])
        self.refresh.invoke()
        self.assertNotIn(self.user['id'], self.tree.get_children())
        self.select_view('Deleted (recoverable)')
        self.assertEqual(self.tree.get_children(), (self.user['id'],))
        changed = self.store.load(self.user['id']); changed['objective'] = 'Changed while hidden'; self.store.save(changed)
        self.refresh.invoke()
        self.assertEqual(self.tree.get_children(), ())
        self.select_view(VIEWS[0])
        self.assertIn(self.user['id'], self.tree.get_children())

    def test_delete_requires_confirmation_and_refuses_active_work_before_prompt(self):
        self.tree.selection_set(self.user['id'])
        with patch.object(mission_settings.messagebox, 'askyesno', return_value=False) as confirm:
            self.delete.invoke()
            confirm.assert_not_called()
            disarm(self.root, self.user['id'])
            self.refresh.invoke()
            self.delete.invoke()
            confirm.assert_called_once()
        self.assertEqual(self.catalog.rows('Deleted (recoverable)'), [])
        self.assertTrue((self.store.folder(self.user['id'])/'mission.json').is_file())


if __name__ == '__main__': unittest.main()
