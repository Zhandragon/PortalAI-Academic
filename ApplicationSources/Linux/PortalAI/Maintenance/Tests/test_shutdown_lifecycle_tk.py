"""Real Tk close/retry/timer tests with synthetic services and no profile data."""
import ast
import gc
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
from account_presentation import lock_account_surfaces
from account_ui import _Dialog
from native_chat import NativeChat
from writer_jobs import WriterJobs
from test_account_presentation_tk import LIGHT
from tk_fixture_cleanup import finish_tk_fixture


def gui_callbacks(context):
    """Execute the real nested close/event callbacks without starting services."""
    tree = ast.parse((ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8'))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    names = {'begin_exit_portableai', 'retry_account_shutdown', 'lock_account_application',
             'minimize_to_tray', 'restore_from_tray', 'pump', '_menu_item',
             '_show_launcher_context', '_show_full_launcher_menu', 'show_tray_context_menu',
             'stop_components'}
    class BindFixture(ast.NodeTransformer):
        def visit_Nonlocal(self, node):
            return ast.copy_location(ast.Global(names=node.names), node)
    body = [BindFixture().visit(n) for n in main.body if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.fix_missing_locations(ast.Module(body=body, type_ignores=[])), '<real-gui-close-callbacks>', 'exec'), context)
    return context


class ShutdownLifecycleTests(unittest.TestCase):
    def setUp(self):
        try: self.app = tk.Tk()
        except tk.TclError as exc: raise unittest.SkipTest('Tk display unavailable: '+str(exc))
        self.app.geometry('840x700-10000-10000')
        self.app.update()
        self.app._portalai_account_root = ROOT
        self.errors = []
        self.workers = []
        self.worker_releases = []
        self.app.report_callback_exception = lambda *args:self.errors.append(args)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def tearDown(self):
        for release in self.worker_releases: release.set()
        # Tests assert recorded callback errors before teardown. Their traceback
        # frames otherwise retain the synthetic callback globals and Tk vars.
        self.errors.clear()
        remaining=finish_tk_fixture(self.app, threads=self.workers)
        self.app=None;self.workers.clear()
        gc.collect()  # Final root cycles belong to the fixture's Tk thread.
        self.assertEqual(remaining,0,'Fixture left Tk variables for a later worker to collect')

    def spin(self, predicate, timeout=3):
        deadline = time.monotonic()+timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)
        self.assertTrue(predicate())

    def context(self):
        def thread(**kwargs):
            worker=threading.Thread(**kwargs);self.workers.append(worker);return worker
        gate = SimpleNamespace(locked=False, close=Mock(), lock=Mock())
        def lock():
            gate.locked = True
            lock_account_surfaces(self.app, LIGHT)
        gate.lock.side_effect = lock
        context = dict(app=self.app, account_gate=gate, COLORS=dict(LIGHT),
            shutdown_status=None, exit_in_progress=False, tray_hidden=True,
            use_custom_chrome=False, ensure_windows_chrome=Mock(),
            startup_gate=Mock(), control_progress=Mock(), stop_worker=threading.Event(),
            close_native_chat_frontend=Mock(), portal_chat_frontend=None,
            _portableai_popup=Mock(),
            native_chat_panel=Mock(), tray=Mock(), event_q=queue.Queue(),
            root=Path(self.tmp.name), log=Mock(), threading=SimpleNamespace(Thread=thread),
            queue=queue, sys=sys, os=SimpleNamespace(name='nt'))
        gui_callbacks(context)
        self.app.protocol('WM_DELETE_WINDOW', context['begin_exit_portableai'])
        return context

    def test_stop_all_cancels_delayed_preview_before_process_cleanup(self):
        c = self.context()
        late_playback = []
        pending = self.app.after_idle(lambda: late_playback.append('restarted'))
        c['native_chat_panel']._stop_embedded_media.side_effect = lambda: self.app.after_cancel(pending)
        def cleanup():
            # Pump the event queue at the cleanup boundary, when a completed
            # duration probe could otherwise recreate its killed player.
            self.app.update()
            self.assertFalse(late_playback)
        c.update(_release_chat_audio_before_process_cleanup=cleanup,
                 _stop_legacy_openwebui_quiet=Mock(), Path=Path,
                 bootstrap_python=lambda _root: str(ROOT/'Runtime/BootstrapPython/python.exe'))
        c['stop_components']()
        self.app.update()
        c['native_chat_panel']._stop_embedded_media.assert_called_once()
        self.assertFalse(late_playback)

    def test_delayed_shutdown_stays_visible_and_locked_tray_actions_do_not_run_tools(self):
        c = self.context(); done = threading.Event(); entered = threading.Event()
        self.worker_releases.append(done)
        def close(): entered.set(); done.wait(3)
        c['account_gate'].close.side_effect = close
        self.app.withdraw(); c['begin_exit_portableai'](); self.app.update()
        self.assertTrue(entered.wait(1)); self.assertNotEqual(self.app.state(), 'withdrawn')
        status = c['shutdown_status']
        self.assertFalse(status.failed)
        self.assertEqual(str(status.retry_button.cget('state')), 'disabled')
        c['start_components'] = Mock(); c['show_tab'] = Mock()
        for kind, data in [('tray_action','startup'),('tray_action','chat'),('tray_action','restore'),('tray_context',{})]:
            self.app.withdraw(); c['event_q'].put((kind,data)); c['pump']()
            self.assertNotEqual(self.app.state(), 'withdrawn')
        c['start_components'].assert_not_called(); c['show_tab'].assert_not_called()
        self.app.tk.call(self.app.protocol('WM_DELETE_WINDOW'))
        self.assertTrue(c['exit_in_progress']); self.assertFalse(status.dialog.closed)
        self.assertEqual(c['account_gate'].close.call_count,1)
        done.set()

    def test_context_menus_and_previously_queued_actions_are_blocked_after_lock(self):
        c=self.context(); action=Mock()
        item=c['_menu_item']('New chat',action)
        item['command'](); action.assert_called_once(); action.reset_mock()
        # Simulate a menu click whose after_idle callback was queued before lock.
        self.app.after_idle(item['command'])
        c['lock_account_application'](); self.app.update()
        action.assert_not_called(); c['_portableai_popup'].close.assert_called_once()
        event=SimpleNamespace(widget=self.app,x_root=0,y_root=0)
        self.assertEqual(c['_show_launcher_context'](event),'break')
        c['_show_full_launcher_menu'](0,0); c['show_tray_context_menu'](0,0)
        c['_portableai_popup'].show.assert_not_called()

    def test_synchronous_lock_failure_is_visible_and_retry_closes_only_after_verified_success(self):
        c = self.context(); calls = [0]
        def lock():
            c['account_gate'].locked = True
            lock_account_surfaces(self.app,LIGHT)
            calls[0] += 1
            if calls[0] == 1: raise RuntimeError('synthetic cleanup failure')
        c['account_gate'].lock.side_effect = lock
        self.app.withdraw(); c['begin_exit_portableai'](); c['pump'](); self.app.update()
        self.assertFalse(c['exit_in_progress']); self.assertTrue(c['shutdown_status'].failed)
        self.assertNotEqual(self.app.state(),'withdrawn')
        c['account_gate'].close.assert_not_called(); c['tray'].close.assert_not_called()
        closed = []
        self.app.destroy = lambda:closed.append(True)
        c['shutdown_status'].retry_button.invoke()
        self.spin(lambda:c['account_gate'].close.called)
        c['pump'](); self.spin(lambda:bool(closed))
        self.assertEqual(calls[0],2); c['tray'].close.assert_called_once()
        self.assertFalse(self.errors)
        del self.app.destroy

    def test_failed_background_verification_never_exits_and_queue_survives_bad_events(self):
        c = self.context(); c['account_gate'].close.side_effect=RuntimeError('synthetic verification failure')
        c['begin_exit_portableai'](); self.spin(lambda:not c['event_q'].empty()); c['pump']()
        self.assertFalse(c['exit_in_progress']); self.assertTrue(c['shutdown_status'].failed)
        c['tray'].close.assert_not_called()
        c['account_gate'].locked=False
        c['event_q'].put(('unexpected',{})); c['pump']()
        self.assertEqual(len(self.errors),1)
        self.assertTrue(self.app.tk.call('after','info'))
        c['account_gate'].locked=True
        self.app.withdraw(); c['event_q'].put(('tray_action','restore')); c['pump']()
        self.assertNotEqual(self.app.state(),'withdrawn')

    def test_active_logout_worker_prevents_second_seal(self):
        c = self.context(); c['account_gate'].locked=True
        dialog=_Dialog(self.app,'Synthetic logout',LIGHT)
        dialog.busy=True
        self.app.withdraw(); c['begin_exit_portableai']()
        self.assertNotEqual(self.app.state(),'withdrawn')
        c['account_gate'].lock.assert_not_called(); c['account_gate'].close.assert_not_called()
        dialog.busy=False;dialog.close()

    def test_progress_construction_error_happens_after_account_admission_is_locked(self):
        c=self.context()
        with patch('shutdown_ui.ShutdownStatus.begin',side_effect=tk.TclError('synthetic widget failure')):
            c['begin_exit_portableai']()
        self.assertTrue(c['account_gate'].locked)
        c['account_gate'].lock.assert_called_once();c['account_gate'].close.assert_not_called()
        c['pump']();self.app.update()
        self.assertTrue(c['shutdown_status'].failed)
        self.assertNotEqual(self.app.state(),'withdrawn')

    def chat(self):
        chat = NativeChat.__new__(NativeChat)
        chat.app=self.app; chat._writer_jobs=WriterJobs(); chat._closing=False
        chat._memory_after=None; chat._model_probe_running=False; chat._model_probe_due=0
        chat.memory=Mock(); chat._stop_embedded_media=Mock(); chat.release_audio_capture=Mock()
        chat.busy=True; chat.stop_generation=Mock(); chat.drop_target=Mock()
        chat._pai128e_timer={'active':True}
        return chat

    def test_status_timer_does_not_submit_after_writer_gate_closes(self):
        chat=self.chat()
        chat._status_after=self.app.after(20,chat._status_tick)
        timer=chat._status_after
        chat.shutdown()
        self.assertNotIn(timer,self.app.tk.call('after','info'))
        # Also exercise an already-dispatched callback, including a forced probe.
        chat._status_tick(); chat._schedule_model_probe(force=True)
        self.app.update()
        self.assertIsNone(chat._status_after); self.assertFalse(chat._model_probe_running)
        self.assertTrue(chat.wait_for_writers(0)['stopped'])
        self.assertFalse(self.errors)

    def test_locked_cover_takes_focus_and_queued_chat_commands_cannot_write(self):
        prompt=tk.Entry(self.app);prompt.pack();self.app.focus_force();prompt.focus_set();self.app.update()
        self.assertIs(self.app.focus_get(),prompt)
        chat=self.chat();chat.store=Mock();chat._check_login=Mock()
        self.app.after_idle(chat.submit)
        chat.shutdown();lock_account_surfaces(self.app,LIGHT);self.app.update()
        self.assertIsNot(self.app.focus_get(),prompt)
        chat.new_chat();chat.new_isolated_chat();chat.regenerate_last()
        self.assertEqual(chat._history_context_menu(None),'break')
        self.assertEqual(chat._chat_context_menu(None),'break')
        chat.store.assert_not_called();self.assertEqual(chat.store.mock_calls,[])
        chat._check_login.assert_not_called();self.assertFalse(self.errors)

    def test_cleanup_failure_still_cancels_inference_and_all_other_resources(self):
        chat=self.chat(); chat.memory.cancel_active.side_effect=RuntimeError('synthetic')
        with self.assertRaisesRegex(RuntimeError,'cleanup needs retry'):chat.shutdown()
        self.assertTrue(chat._closing); chat.stop_generation.assert_called_once()
        chat._stop_embedded_media.assert_called_once(); chat.release_audio_capture.assert_called_once()
        chat.drop_target.close.assert_called_once()
        with self.assertRaisesRegex(RuntimeError,'closing'):
            chat._writer_jobs.thread(target=lambda:None).start()
        chat.memory.cancel_active.side_effect=None
        chat.shutdown(); self.assertTrue(chat.wait_for_writers(0)['stopped'])


if __name__=='__main__': unittest.main()
