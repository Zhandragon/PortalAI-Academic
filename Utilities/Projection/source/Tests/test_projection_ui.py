"""Disposable Tk/tray fixtures. Never opens a user connection or PortalAI."""
import ctypes
import json
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch,Mock

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
import projection_ui as ui
import projection_theme as theme
import projection_tray as tray

class FakeTray:
    def __init__(self):self.available=True;self.closed=False
    def show(self):return self.available
    def close(self):self.closed=True

class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        shutil.copytree(MODULE/'app/assets',self.root/'app/assets')
        (self.root/'Connections').mkdir();self.native=FakeTray()
        self.app=tk.Tk();self.app.withdraw();self.errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
        self.patches=[patch.object(ui,'MODULE',self.root),patch.object(ui,'default_target',return_value=self.root/'PortalAI'),patch.object(tray,'create',return_value=self.native)]
        for p in self.patches:p.start()
        self.w=ui.Window(self.app);self.app.after_cancel(self.w.tray_timer);self.app.update_idletasks()
    def tearDown(self):
        try:
            self.w.worker=None;self.w.local_starting=False;self.w.close()
        except tk.TclError:pass
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup();self.assertFalse(self.errors,self.errors)
    def test_minimize_restore_keeps_connection_worker(self):
        connection={'fixture':'public'};worker=Mock();worker.poll.return_value=None
        self.w.connection=connection;self.w.worker=worker
        self.w.minimize();self.assertTrue(self.w.hidden);self.assertEqual(self.app.state(),'withdrawn')
        self.w.restore();self.assertFalse(self.w.hidden);self.assertIs(self.w.connection,connection);worker.terminate.assert_not_called();worker.stdin.close.assert_not_called()
    def test_no_tray_keeps_taskbar_window(self):
        self.native.available=False
        with patch.object(self.app,'iconify') as iconify:
            self.w.minimize();iconify.assert_called_once()
        self.assertFalse(self.w.hidden);self.assertIn('taskbar',self.w.status.get())
    def test_native_minimize_event(self):
        with patch.object(self.app,'state',return_value='iconic'):
            self.w.on_unmap(Mock(widget=self.app))
        self.assertTrue(self.w.hidden)
    def test_tray_failure_reopens(self):
        self.w.minimize();self.w.ui_events.put(('tray_failed',None));self.w.tick()
        self.assertFalse(self.w.hidden);self.assertEqual(self.app.state(),'normal')
    def test_menu_matches_launcher_and_tray_actions(self):
        self.w.skin.menu((20,20));buttons=self.w.skin.menu_buttons
        self.assertEqual(len(buttons),8);self.assertEqual(buttons[2].cget('state'),'disabled');self.assertEqual(buttons[3].cget('state'),'disabled')
        self.assertIn('Start local PortalAI',buttons[4].cget('text'));self.assertIn('leave PortalAI running',buttons[3].cget('text'))
        buttons[6].invoke();self.assertEqual(self.w.skin.tabs.select(),str(self.w.skin.documentation))
    def test_themes_retain_draft_and_unlocked_connection(self):
        self.w.connection={'fixture':'public'};self.w.password.set('disposable draft');self.w.address.set('https://example.invalid')
        self.w.skin.change('mode','light');self.w.skin.change('border','#123ABC');self.w.skin.change('accent','#5599AA');self.app.update_idletasks()
        self.assertEqual(self.w.password.get(),'disposable draft');self.assertEqual(self.w.connection,{'fixture':'public'})
        prefs=theme.read_settings(self.root);self.assertEqual(prefs['border'],'#123ABC');self.assertEqual(prefs['mode'],'light')
        self.assertNotIn('disposable', (self.root/'state/ui-settings.json').read_text());self.assertNotIn('example.invalid',(self.root/'state/ui-settings.json').read_text())
    def test_bad_settings_and_unknown_fields(self):
        p=self.root/'state/ui-settings.json';p.parent.mkdir();p.write_text('[1,2]');self.assertEqual(theme.read_settings(self.root),theme.DEFAULT)
        p.write_text(json.dumps({'mode':'light','accent':'invalid'}));self.assertEqual(theme.read_settings(self.root),theme.DEFAULT)
        theme.save_settings(self.root,{'mode':'light','password':'do-not-store'});self.assertNotIn('password',p.read_text())
        p.write_text('x'*5000);self.assertEqual(theme.read_settings(self.root),theme.DEFAULT)
    def test_start_local_invalid_target_has_no_effect(self):
        with patch.object(ui,'target_valid',return_value=False),patch.object(ui.subprocess,'run') as run:
            self.w.open_portalai();run.assert_not_called()
        self.assertFalse(self.w.local_starting)
    def test_start_local_without_connection_runs_silently_once(self):
        cp=Mock(stdout=json.dumps({'state':'complete','message':'Fixture opened'}))
        with patch.object(ui,'target_valid',return_value=True),patch.object(ui.subprocess,'run',return_value=cp) as run:
            self.w.open_portalai();self.w.open_portalai()
            deadline=time.monotonic()+2
            while self.w.ui_events.empty() and time.monotonic()<deadline:time.sleep(.01)
            self.w.tick();run.assert_called_once();kw=run.call_args.kwargs
            if os.name=='nt':self.assertTrue(kw['creationflags']&ui.subprocess.CREATE_NO_WINDOW)
        self.assertIsNone(self.w.connection);self.assertFalse(self.w.local_starting);self.assertEqual(self.w.status.get(),'Fixture opened')
    def test_stop_only_closes_exact_projection_pipe(self):
        worker=Mock();worker.poll.return_value=None;self.w.worker=worker
        self.w.stop();worker.stdin.close.assert_called_once();worker.terminate.assert_not_called();self.assertIsNotNone(self.w.stop_deadline)
    def test_close_waits_worker_and_cleans_tray(self):
        worker=Mock();worker.poll.return_value=None;self.w.worker=worker
        self.w.close();self.assertFalse(self.native.closed)
        worker.poll.return_value=0;self.w.close();self.assertTrue(self.native.closed)
    def test_minimum_layout_and_docs(self):
        self.app.geometry('720x680');self.app.deiconify();self.app.update()
        self.assertGreater(self.w.instructions.winfo_height(),75)
        for b in (self.w.skin.start_button,self.w.skin.stop_button,self.w.skin.local_button):
            self.assertLess(b.winfo_rootx()+b.winfo_width(),self.app.winfo_rootx()+self.app.winfo_width())
        self.assertIn('MINIMIZE AND TRAY',theme.DOCUMENTATION);self.assertIn('taskbar',theme.DOCUMENTATION)

@unittest.skipUnless(os.name=='nt','Real Win32 tray test')
class NativeTrayTests(unittest.TestCase):
    def test_real_tray_register_event_queue_and_cleanup(self):
        events=queue.Queue();t=tray.WindowsTray(None,events,MODULE/'app/assets/projection-dark.ico')
        try:
            self.assertTrue(t.show(),'Windows tray registration failed');self.assertTrue(t.hwnd)
            user=ctypes.windll.user32
            user.PostMessageW(ctypes.c_void_p(t.hwnd),t.EVENT,1,0x202)
            self.assertEqual(events.get(timeout=3)[0],'restore')
            user.PostMessageW(ctypes.c_void_p(t.hwnd),t.EVENT,1,0x205)
            self.assertEqual(events.get(timeout=3)[0],'menu')
        finally:t.close()
        self.assertFalse(t.thread.is_alive());self.assertFalse(t.visible);self.assertEqual(t.hwnd,0)

class LocalHelperTests(unittest.TestCase):
    def test_local_helper_uses_only_existing_start_contract(self):
        import projection_local as local,portalai_target
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manager=Mock(operation={'state':'complete','message':'PortalAI opened. Sign in through the viewer.'})
            with patch.object(local.sys,'platform','win32'),patch.object(local,'MODULE',root),patch.object(local,'target_valid',return_value=True),patch.object(local,'resolve_target',return_value=root),patch.object(local,'input_owner',return_value='fixture-owner'),patch.object(portalai_target,'configure') as configure,patch.object(portalai_target,'Manager',return_value=manager):
                result=local.start_local(str(root));configure.assert_called_once_with(root)
                self.assertEqual(manager._operate.call_args.args[0],'start');self.assertEqual(len(manager._operate.call_args.args[1]),32)
                self.assertTrue(manager.endpoint_dir.is_dir());self.assertIn('PortalAI window',result['message'])

if __name__=='__main__':unittest.main()
