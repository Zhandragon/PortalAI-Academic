"""Real Tk input and synthetic records; no owner mission or model is started."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch,Mock
from pathlib import Path
import tempfile
from confirmation_dialog import ask_yes_no
from account_presentation import refresh_account_theme
from record_context_menu import RecordContextMenu
THEMES = {'light': {'bg': '#EEE7DC',
           'panel': '#F8F3EA',
           'panel2': '#E9E0D2',
           'panel3': '#DED1BC',
           'card': '#FFFDF8',
           'card_hover': '#F7F0E5',
           'text': '#202224',
           'muted': '#625E59',
           'muted2': '#7C725F',
           'accent': '#3E91A2',
           'accent2': '#1F6F82',
           'good': '#2E8062',
           'warn': '#9D7027',
           'bad': '#A9514C',
           'button': '#E6DCCB',
           'button_hover': '#D9CBB3',
           'danger': '#7C403E',
           'danger_hover': '#66312F',
           'border': '#7B5A22',
           'gold_mid': '#A87D32',
           'gold_shine': '#D9BE78',
           'outline': '#343638',
           'border_soft': '#6E6E6B',
           'shadow': '#1E2022',
           'model_bg': '#F3ECE1'},
 'dark': {'bg': '#111315',
          'panel': '#1C1E20',
          'panel2': '#252729',
          'panel3': '#302D27',
          'card': '#242628',
          'card_hover': '#2D3032',
          'text': '#F2ECE2',
          'muted': '#B7AFA4',
          'muted2': '#9D9282',
          'accent': '#58AFC1',
          'accent2': '#7CC4D3',
          'good': '#63B88E',
          'warn': '#C89B4A',
          'bad': '#D17770',
          'button': '#2A2D2F',
          'button_hover': '#363A3D',
          'danger': '#6C3534',
          'danger_hover': '#83423F',
          'border': '#806027',
          'gold_mid': '#B0863A',
          'gold_shine': '#D6BA70',
          'outline': '#070809',
          'border_soft': '#4B4E50',
          'shadow': '#000000',
          'model_bg': '#101214'}}

from tk_fixture_cleanup import finish_tk_fixture


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('900x720');self.errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
        self.host=tk.Frame(self.app);self.host.pack(fill='both',expand=True);self.app.update()
    def tearDown(self):
        finish_tk_fixture(self.app);self.assertFalse(self.errors)
    def choose(self,yes):
        dialog=self.app._portalai_account_dialogs[-1]
        self.assertIs(dialog.win.winfo_toplevel(),self.app)
        self.assertFalse(any(isinstance(w,tk.Toplevel) for w in self.app.winfo_children()))
        refresh_account_theme(self.app,THEMES['dark'])
        self.assertEqual(dialog.surface.card.cget('bg'),THEMES['dark']['panel'])
        next(b for b,_ in dialog.buttons if b.cget('text').startswith('Yes' if yes else 'No')).invoke()
    def test_yes_and_no_are_explicit_internal_choices(self):
        for yes in (False,True):
            self.app.after(80,lambda answer=yes:self.choose(answer))
            with patch('tkinter.messagebox.askyesno',side_effect=AssertionError('Native popup forbidden')):
                self.assertEqual(ask_yes_no('Delete?','Retained records.\n\nNo files erased.',parent=self.host,colors=THEMES['light']),yes)
            self.assertFalse(self.app._portalai_account_dialogs)
    def test_tcl_only_dropdown_focus_does_not_block_confirmation(self):
        self.app.after(80,lambda:self.choose(False))
        with patch.object(self.app,'focus_get',side_effect=KeyError('popdown')):
            self.assertFalse(ask_yes_no('Delete?','Synthetic dropdown focus.',parent=self.host,colors=THEMES['dark']))

    def test_parent_close_cancels(self):
        self.app.after(80,self.host.destroy)
        self.assertFalse(ask_yes_no('Delete?','Synthetic.',parent=self.host,colors=THEMES['dark']))
    def test_revoked_account_cannot_confirm(self):
        self.app.after(80,lambda:self.choose(True))
        with self.assertRaises(PermissionError):
            ask_yes_no('Delete?','Synthetic.',parent=self.host,colors=THEMES['dark'],validate=Mock(side_effect=PermissionError('Account changed')))
    def test_remote_confirmation_keeps_native_workflow_adapter(self):
        self.app._portalai_native_workflow=Mock(active=object())
        with patch('tkinter.messagebox.askyesno',return_value=False) as remote:
            self.assertFalse(ask_yes_no('Delete?','Synthetic.',parent=self.host,colors=THEMES['dark']))
            remote.assert_called_once()


class ContextTests(unittest.TestCase):
    def test_actions_bind_clicked_record_and_blank_area_does_nothing(self):
        app=tk.Tk();app.geometry('700x400')
        frame=tk.Frame(app);frame.skin=Mock(colors=THEMES['dark']);frame.pack(fill='both',expand=True)
        tree=ttk.Treeview(frame);tree.pack(fill='both',expand=True)
        tree.insert('','end',iid='first');tree.insert('','end',iid='second');tree.selection_set('first');app.update()
        calls=[]
        menu=RecordContextMenu(frame,tree,lambda row:[dict(label='Stop',command=lambda:calls.append(tree.selection()[0]))],title='Missions')
        with patch.object(menu.menu,'show') as shown:
            menu.show('second',20,20);self.assertEqual(tree.selection(),('second',))
            callback=shown.call_args.args[2][0]['command']
            tree.selection_set('first');callback();self.assertEqual(calls,['second'])
            tree.delete('second');callback();self.assertEqual(calls,['second'])
        menu.close();finish_tk_fixture(app)

    def test_mission_actions_obey_pending_review_and_deletion_guards(self):
        from test_mission_catalog_tk import MissionCatalogTkTests
        case=MissionCatalogTkTests('test_default_view_shows_only_user_work_and_other_views_preserve_old_records')
        case.setUp()
        try:
            menu=case.window.record_context_menu
            def actions():return {v['label']:v for v in menu.items(case.user['id']) if v}
            initial=actions();self.assertFalse(initial['Delete…']['enabled']);self.assertFalse(initial['Review: retry']['enabled'])
            from mission_supervisor import disarm
            disarm(case.root,case.user['id']);case.refresh.invoke()
            self.assertTrue(actions()['Delete…']['enabled'])
            record=case.store.load(case.user['id']);record.update(status='needs_review',pending_action={'action':'recall','query':'probe'});case.store.save(record)
            values=actions();self.assertTrue(values['Review: retry']['enabled']);self.assertTrue(values['Review: skip']['enabled']);self.assertFalse(values['Run']['enabled']);self.assertFalse(values['Resume']['enabled'])
        finally:case.doCleanups()


    def test_schedule_review_is_bound_to_stable_active_run(self):
        from test_mission_organization_tk import OrganizationTkTests, Schedules, show_schedule_settings, LIGHT
        case=OrganizationTkTests('test_schedule_search_by_active_id_policy_and_blocked_enable')
        case.setUp()
        try:
            store=Schedules(case.root);s=store.create('Synthetic context menu probe',first_run_at=0)
            store.enable(s['id']);store.tick();s=store.load(s['id']);mid=s['active_run']
            store.disable(s['id']);m=store.store.load(mid)
            m.update(status='needs_review',pending_action={'action':'recall','query':'probe'});store.store.save(m)
            case.sheet=show_schedule_settings(case.app,case.root,LIGHT,embedded=True);case.app.update()
            case.sheet.schedule_tree.selection_set(s['id'])
            def actions():return {v['label']:v for v in case.sheet.record_context_menu.items(s['id']) if v}
            rows=actions();self.assertFalse(rows['Run / enable schedule']['enabled'])
            self.assertTrue(rows['Review: skip']['enabled']);self.assertFalse(rows['Resume active mission']['enabled'])
            # A changed record invalidates a menu's previously captured review.
            m=store.store.load(mid);m['error']='new review information';store.store.save(m)
            rows['Review: skip']['command']();self.assertIsNotNone(store.store.load(mid)['pending_action'])
            actions()['Review: skip']['command']();self.assertIsNone(store.store.load(mid)['pending_action'])
            self.assertFalse(store.enabled(store.load(s['id'])))
            self.assertTrue(actions()['Run / enable schedule']['enabled'])
        finally:case.tearDown();case.doCleanups()

if __name__=='__main__':unittest.main()
