"""Account action intent and Help navigation on synthetic Tk surfaces."""
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from test_settings_surfaces_tk import LIGHT,DARK,button
from tk_fixture_cleanup import finish_tk_fixture
from account_ui import show_accounts
from writer_jobs import WriterJobs


class AccountUXTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1000x760+30+30');self.errors=[]
        self.app.report_callback_exception=lambda *error:self.errors.append(error)
    def tearDown(self):
        for dialog in reversed(list(getattr(self.app,'_portalai_account_dialogs',[]))):
            dialog.busy=False;dialog.close()
        finish_tk_fixture(self.app)
        self.assertEqual(self.errors,[])
    def until(self,predicate):
        deadline=time.monotonic()+4
        while not predicate() and time.monotonic()<deadline:self.app.update();time.sleep(.02)
        self.assertTrue(predicate())
    def test_reset_needs_final_confirmation_and_cancel_never_executes(self):
        from account_reset_ui import show_start_fresh
        adapter=Mock();adapter.prepare.return_value={'users':[{},{}],'files':[],'bytes':0}
        adapter.execute.return_value={'reset':True,'login_required':True}
        gate=SimpleNamespace(locked=False,runtime=SimpleNamespace(session=None))
        exited=Mock()
        with patch('account_reset_ui.ResetAdapter',return_value=adapter):
            dialog=show_start_fresh(self.app,gate,LIGHT,lock_application=lambda:setattr(gate,'locked',True),exit_application=exited)
            button(dialog.win,'Stop, seal and review').invoke()
            self.until(lambda:not dialog.busy)
            button(dialog.win,'Reset reviewed private profiles and close').invoke()
            confirm=self.app._portalai_account_dialogs[-1]
            self.assertIsNot(confirm,dialog);adapter.execute.assert_not_called()
            button(confirm.win,'Cancel — keep data').invoke();adapter.execute.assert_not_called()
            button(dialog.win,'Reset reviewed private profiles and close').invoke()
            confirm=self.app._portalai_account_dialogs[-1]
            button(confirm.win,'Yes, reset reviewed private data').invoke()
            self.until(lambda:exited.called);adapter.execute.assert_called_once()
    def test_export_data_choices_and_tones_persist_after_theme_changes(self):
        jobs=WriterJobs();controller=SimpleNamespace(jobs=jobs,backend=Mock())
        session=SimpleNamespace(username='Fixture',role='admin',user_id='fixture')
        factories={name:Mock(return_value=lambda:{'verified':True,'path':'synthetic.zip'}) for name in ('history','outputs','both')}
        page=show_accounts(self.app,controller,session,LIGHT,page=True,change_user=Mock(),
            export_history=factories['history'],export_outputs=factories['outputs'],export_both=factories['both'])
        for palette in (DARK,LIGHT):
            page.apply_palette(palette);self.app.update()
            self.assertEqual(button(page.win,'Change current user').cget('bg'),palette['gold_shine'])
            self.assertEqual(button(page.win,'Start fresh…').cget('fg'),'#FFFFFF')
        button(page.win,'Export Data…').invoke();dialog=self.app._portalai_account_dialogs[-1]
        choices=next(w for w in dialog.body.winfo_children() if isinstance(w,ttk.Combobox))
        self.assertEqual(list(choices.cget('values')),['Chat history','Outputs','Both'])
        choices.set('Both');button(dialog.win,'Choose destination and export…').invoke()
        self.until(lambda:not page.busy)
        factories['both'].assert_called_once();factories['history'].assert_not_called();factories['outputs'].assert_not_called()
        jobs.close();self.assertTrue(jobs.wait(2)['stopped'])
    def test_help_search_keyboard_and_quiet_titles(self):
        from ui_extensions import DocumentationPanel
        panel=DocumentationPanel(self.app,LIGHT);self.app.update()
        panel.listbox._select(0);panel.listbox._move(1)
        self.assertEqual(panel.listbox.curselection(),(1,))
        panel.search_var.set('persistent memory');self.app.update()
        self.assertTrue(panel.keys)
        panel.listbox._select(0);self.app.update()
        self.assertGreater(panel.title_rule.winfo_width(),300)
        panel.apply_palette(DARK)
        self.assertEqual(panel.text.tag_cget('title','foreground'),DARK['muted'])
        self.assertEqual(len(panel.listbox.bounds),len(panel.keys))

if __name__=='__main__':unittest.main()
