"""Real Tk widgets with synthetic accounts; no private state, models or services."""
import json
import gc
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import tkinter as tk
from tkinter import ttk

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent')]
import account_ui as ui
from account_presentation import lock_account_surfaces, refresh_account_theme
from tk_fixture_cleanup import finish_tk_fixture

LIGHT={'bg':'#EFE8DC','panel':'#F8F3EA','panel2':'#E9E0D2','text':'#202224','muted':'#6E665E',
       'accent':'#3E91A2','button':'#E6DCCB','border':'#7B5A22','gold_mid':'#A87D32','gold_shine':'#D9BE78','shadow':'#2B2419'}
DARK={**LIGHT,'bg':'#101214','panel':'#181B1E','panel2':'#23272B','text':'#EEE7DA','muted':'#AAA39B','button':'#2C3034'}


def fixture_controller(root):
    backend=Mock()
    users=[{'user_id':'a'*32,'username':'FixtureAdmin','role':'admin','pending':False},
           {'user_id':'b'*32,'username':'KNO3','role':'user','pending':True},
           {'user_id':'c'*32,'username':'FixtureMember','role':'user','pending':False},
           {'user_id':'d'*32,'username':'Guest','role':'guest','pending':False}]
    backend.status.return_value={'state':'locked','users':users}
    backend.list_users.return_value=users
    session=SimpleNamespace(user_id='a'*32,username='FixtureAdmin',role='admin',active=True)
    def login(name,password):
        if password!='synthetic-password':raise ValueError('incorrect synthetic credential')
        return session
    backend.login.side_effect=login
    return ui.AccountController(root,backend),session


def button(dialog,label):return next(widget for widget,_ in dialog.buttons if widget.cget('text')==label)
def newest(app):return next(d for d in reversed(app._portalai_account_dialogs) if not d.closed)

def enter_key(entry, sequence):
    # Invoke Tk's widget-bound callback without stealing the user's OS focus.
    script=entry.bind(sequence)
    if not script:raise AssertionError('Missing entry key binding: '+sequence)
    command=script.split('[',1)[1].split()[0]
    entry.tk.call(command,'synthetic-key-event')


class AccountPresentationTests(unittest.TestCase):
    def setUp(self):
        try:self.app=tk.Tk()
        except tk.TclError as exc:raise unittest.SkipTest('Tk display unavailable: '+str(exc))
        self.app.geometry('1000x780-10000-10000')
        self.app.update()
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.controller,self.session=fixture_controller(Path(self.tmp.name))
        self.colors=dict(LIGHT)
        self.host=tk.Frame(self.app,bg=LIGHT['bg']);self.host.place(x=10,y=80,relwidth=1,width=-20,relheight=1,height=-90)
        self.app._portalai_account_host=self.host
        self.app._portalai_account_root=ROOT
        self.app.update()

    def tearDown(self):
        remaining=finish_tk_fixture(self.app, jobs=(self.controller.jobs,))
        self.app=None;self.host=None;self.controller=None
        gc.collect()  # Drop the final destroyed Tcl interpreter on this thread.
        self.assertEqual(remaining,0,'Fixture left Tk variables for a later worker to collect')

    def pump(self,predicate,timeout=4):
        end=time.monotonic()+timeout
        while not predicate() and time.monotonic()<end:
            self.app.update();time.sleep(.01)
        self.assertTrue(predicate())

    def accounts(self):
        return ui.show_accounts(self.host,self.controller,self.session,self.colors,
            lock_application=lambda:lock_account_surfaces(self.app,self.colors),
            stop_and_seal=Mock(),exit_application=Mock(),on_session_changed=Mock())

    def test_nested_member_panel_stays_inside_root_and_includes_pending(self):
        parent=self.accounts();self.app.update()
        button(parent,'Set/reset member password…').invoke();child=newest(self.app);self.app.update()
        self.assertNotIsInstance(child.win,tk.Toplevel)
        self.assertIs(child.win.winfo_toplevel(),self.app)
        self.assertFalse(any(isinstance(w,tk.Toplevel) for w in self.app.winfo_children()))
        picker=next(w for w in child.body.winfo_children() if isinstance(w,ttk.Combobox))
        self.assertEqual(tuple(picker['values']),('KNO3','FixtureMember'))
        self.assertTrue(any(isinstance(w,tk.Label) and 'Pending account' in w.cget('text') for w in child.body.winfo_children()))
        self.assertGreater(child.surface.card.winfo_width(),400)
        child.close();self.app.update()
        self.assertIs(self.app.grab_current(),self.app)
        self.assertIs(self.app._portalai_modal_guard.surface,parent.surface)

    def test_drag_and_resize_keep_panel_inside_launcher(self):
        dialog=self.accounts();self.app.update()
        dialog.surface._drag_start(SimpleNamespace(x_root=1,y_root=1))
        dialog.surface._drag_move(SimpleNamespace(x_root=99999,y_root=99999))
        self.app.geometry('500x400-10000-10000');self.app.update()
        card=dialog.surface.card;overlay=dialog.win
        self.assertGreaterEqual(card.winfo_x(),0);self.assertGreaterEqual(card.winfo_y(),0)
        self.assertLessEqual(card.winfo_x()+card.winfo_width(),overlay.winfo_width())
        self.assertLessEqual(card.winfo_y()+card.winfo_height(),overlay.winfo_height())

    def test_light_dark_theme_reaches_panel_inputs_and_border(self):
        dialog=self.accounts();button(dialog,'Set/reset member password…').invoke();child=newest(self.app)
        self.colors.clear();self.colors.update(DARK);refresh_account_theme(self.app,self.colors);self.app.update()
        entry=next(w for w in child.body.winfo_children() if isinstance(w,(tk.Entry,ttk.Entry)) and not isinstance(w,ttk.Combobox))
        self.assertEqual(ttk.Style(entry).lookup(entry.cget('style'),'fieldbackground'),DARK['panel2'])
        self.assertEqual(child.surface.border.palette['panel'],DARK['panel'])
        self.assertEqual(child.bg,DARK['panel'])
        self.assertTrue(child.surface.border.canvas.find_withtag('ornate'))

    def test_account_buttons_do_not_inherit_move_cursor(self):
        dialog=self.accounts();button(dialog,'Set/reset member password…').invoke();child=newest(self.app)
        self.assertEqual(str(child.surface.head.cget('cursor')),'fleur')
        self.assertEqual(str(child.surface.overlay.cget('cursor')),'arrow')
        self.assertEqual(str(child.surface.close_button.cget('cursor')),'hand2')
        self.assertTrue(all(str(widget.cget('cursor'))=='hand2' for widget,_ in child.buttons))
        picker=next(w for w in child.body.winfo_children() if isinstance(w,ttk.Combobox))
        self.assertEqual(str(picker.cget('cursor')),'arrow')

    def test_progress_coalesces_and_cannot_delay_terminal_result(self):
        dialog=ui._Dialog(self.app,'Progress',self.colors,jobs=self.controller.jobs)
        for index in range(10000):
            dialog.progress.publish({'stage':'restore','message':'Opening verified files','completed':index,'total':10000})
        success=Mock();dialog.busy=True
        dialog.results.put((True,'ready',success));dialog._poll()
        success.assert_called_once_with('ready')
        self.assertIn('9,999 / 10,000',dialog.status.get())
        self.assertIsNone(dialog.progress.latest())

    def test_retained_login_keeps_shell_and_releases_only_after_main_ready(self):
        from account_gate import GUIAccountGate
        self.app._portalai_shell_ready=True;self.app._portalai_login_host=self.host
        before=(self.app.winfo_id(),self.app.geometry(),self.app.title())
        def sign_in():
            dialog=newest(self.app)
            entry=next(w for w in dialog.body.winfo_children() if isinstance(w,(tk.Entry,ttk.Entry)) and not isinstance(w,ttk.Combobox))
            entry.insert(0,'synthetic-password');button(dialog,'Sign in').invoke()
        self.app.after(20,sign_in)
        session=ui.show_login(self.app,self.controller,self.colors,
                             prepare_session=lambda _:{'ready':True,'user_id':self.session.user_id},
                             retain_until_ready=True)
        self.assertIs(session,self.session);dialog=self.app._portalai_login_dialog
        self.assertTrue(dialog.busy);self.assertFalse(dialog.closed)
        self.assertIs(dialog.surface.host,self.host)
        self.assertEqual(before,(self.app.winfo_id(),self.app.geometry(),self.app.title()))
        dialog.surface.on_close();self.assertFalse(dialog.closed)
        # The main controller's safe shutdown protocol must not be overwritten
        # by closing the retained login panel after successful construction.
        final_close=Mock();self.app.protocol('WM_DELETE_WINDOW',final_close)
        gate=GUIAccountGate.__new__(GUIAccountGate);gate.app=self.app;gate.application_ready()
        self.assertTrue(dialog.closed);self.assertIsNone(self.app._portalai_login_dialog)
        self.app.tk.call(self.app.protocol('WM_DELETE_WINDOW'));final_close.assert_called_once()

    def test_lock_covers_private_root_and_preserves_internal_progress(self):
        self.app._portalai_login_host=self.host
        dialog=self.accounts();self.app.update()
        lock_account_surfaces(self.app,self.colors);self.app.update()
        self.assertTrue(self.app._portalai_account_lock_cover.winfo_ismapped())
        self.assertFalse(dialog.surface.full_window)
        self.assertEqual(dialog.win.winfo_width(),self.host.winfo_width())
        self.assertEqual(dialog.win.winfo_height(),self.host.winfo_height())
        self.assertEqual(dialog.win.winfo_rooty(),self.host.winfo_rooty())
        self.assertIs(self.app._portalai_modal_guard.surface,dialog.surface)

    def test_startup_close_and_escape_refuse_busy_nested_worker(self):
        original=self.app.protocol('WM_DELETE_WINDOW')
        parent=ui._Dialog(self.app,'Login',self.colors,startup=True,jobs=self.controller.jobs)
        child=ui._Dialog(parent.win,'Recovery',self.colors,jobs=self.controller.jobs);child.busy=True
        self.app.tk.call(self.app.protocol('WM_DELETE_WINDOW'))
        self.assertFalse(parent.closed);self.assertFalse(child.closed)
        self.assertIn('Wait',child.status.get())
        child.surface._escape(None)
        self.assertFalse(child.closed)
        child.busy=False;child.close();parent.close()
        self.assertEqual(self.app.protocol('WM_DELETE_WINDOW'),original)

    def test_login_wrong_then_correct_waits_for_ready_workspace(self):
        state={'phase':0,'errors':[]};prepare=Mock(return_value={'ready':True,'user_id':self.session.user_id})
        def tick():
            try:
                dialog=newest(self.app)
                entry=next(w for w in dialog.body.winfo_children() if isinstance(w,(tk.Entry,ttk.Entry)) and not isinstance(w,ttk.Combobox))
                if state['phase']==0:
                    entry.insert(0,'wrong-password');enter_key(entry,'<Return>')
                    enter_key(entry,'<Return>');state['phase']=1
                elif state['phase']==1 and not dialog.busy:
                    self.assertIn('failed',dialog.status.get().lower());prepare.assert_not_called()
                    self.assertEqual(self.controller.backend.login.call_count,1)
                    # A nested recovery sheet can retain this field's focus.
                    child=ui._Dialog(dialog.win,'Recovery',self.colors,jobs=self.controller.jobs)
                    entry.insert(0,'synthetic-password');enter_key(entry,'<Return>')
                    self.assertFalse(dialog.busy);self.assertEqual(self.controller.backend.login.call_count,1)
                    child.close()
                    button(dialog,'Sign in').configure(state='disabled');enter_key(entry,'<Return>')
                    self.assertFalse(dialog.busy);self.assertEqual(self.controller.backend.login.call_count,1)
                    button(dialog,'Sign in').configure(state='normal');enter_key(entry,'<KP_Enter>');state['phase']=2
            except Exception as exc:
                state['errors'].append(exc)
                for dialog in getattr(self.app,'_portalai_account_dialogs',[]):dialog.busy=False;dialog.close()
                return
            if state['phase']<2:self.app.after(20,tick)
        self.app.after(30,tick)
        self.app.after(4000,lambda:[d.close() for d in list(getattr(self.app,'_portalai_account_dialogs',())) if not d.busy])
        session=ui.show_login(self.app,self.controller,self.colors,prepare_session=prepare)
        if state['errors']:raise state['errors'][0]
        self.assertIs(session,self.session);prepare.assert_called_once_with(self.session)
        self.assertEqual(self.controller.backend.login.call_count,2)


if __name__=='__main__':unittest.main()
