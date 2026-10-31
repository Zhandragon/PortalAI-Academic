"""Temporary compact voice views preserve the normal composer and transcript."""
import threading,tkinter as tk,unittest
from types import SimpleNamespace
from unittest.mock import Mock
from test_account_presentation_tk import LIGHT
from tk_fixture_cleanup import finish_tk_fixture
from voice_activity import VoiceActivity
from voice_layout import install_compact_voice,sync_voice_view
from voice_visualizer import VoiceVisualizer


class CompactVoiceTests(unittest.TestCase):
    def setUp(self):
        app=self.app=tk.Tk();app.withdraw();self.addCleanup(finish_tk_fixture,app)
        palette={**LIGHT,'gold':LIGHT['gold_mid'],'cyan':LIGHT['accent']}
        parent=tk.Frame(app);parent.pack()
        full=tk.Frame(parent);full.grid(row=1,column=0);full.grid_remove()
        event=threading.Event()
        self.panel=p=SimpleNamespace(app=app,COL=palette,conversation_active=event,
            _conversation_io=SimpleNamespace(activity=VoiceActivity()),voice_host=full,
            voice_visualizer=VoiceVisualizer(full,palette),toggle_conversation_mode=Mock(),stop_conversation_mode=Mock())
        p.composer_shell=tk.Frame(parent);p.composer_shell.grid(row=2,column=0)
        bar=tk.Frame(app);bar.pack()
        row=tk.Frame(bar);row.pack(fill='x',padx=5,pady=(0,4))
        entry=tk.Entry(row);entry.insert(0,'Preserved compact draft');entry.pack()
        transcript=tk.Text(app);transcript.insert('1.0','Earlier history\nYou: recognized speech\nNice: visible spoken reply');transcript.pack()
        class Controller:
            active=False;expanded=False
            def enter(self):self.active=True
            def exit(self):self.active=False;self.expanded=False
            def toggle_chat(self):self.expanded=not self.expanded
            def _refresh_colors(self):pass
            def _collapsed_geometry(self):return 860,104
            def _button_action(self,*names):return lambda:None
            def _set_size(self,expanded):self.last_size=self._collapsed_geometry() if not expanded else (1120,680)
        self.ctl=c=Controller();c.app=app;c.native_chat_panel=p;c._compact_bar=bar;c._composer_row=row
        app._portalai_compact_controller=c;install_compact_voice(c)
        self.entry,self.transcript=entry,transcript
        self.pack_before=row.pack_info().copy()

    def activate(self):
        self.panel.conversation_active.set();sync_voice_view(self.panel)

    def test_normal_compact_is_unchanged_until_voice_starts(self):
        c=self.ctl;c.enter()
        self.assertEqual(c._composer_row.pack_info(),self.pack_before)
        self.assertIsNone(c._voice_layout.view)
        self.assertEqual(c._collapsed_geometry(),(860,104))

    def test_compact_voice_replaces_only_entry_and_restores_exact_draft(self):
        c=self.ctl;c.enter();before=self.transcript.get('1.0','end')
        self.activate();self.app.update()
        self.assertFalse(c._composer_row.winfo_manager())
        self.assertFalse(self.panel.composer_shell.winfo_manager())
        self.assertTrue(c._voice_layout.view._visible)
        self.assertIsNone(self.panel.voice_visualizer._after)
        self.assertGreater(c._collapsed_geometry()[1],104)
        c.toggle_chat();self.assertTrue(c.expanded)
        self.assertEqual(self.transcript.get('1.0','end'),before)
        self.panel.conversation_active.clear();sync_voice_view(self.panel)
        self.assertEqual(c._composer_row.pack_info(),self.pack_before)
        self.assertEqual(self.panel.composer_shell.winfo_manager(),'grid')
        self.assertEqual(self.entry.get(),'Preserved compact draft')
        self.assertIsNone(c._voice_layout.view._after)

    def test_layout_switch_keeps_session_and_runs_only_one_visualizer(self):
        self.activate();activity=self.panel._conversation_io.activity
        self.assertIs(self.panel.voice_visualizer.activity,activity)
        self.ctl.enter();compact=self.ctl._voice_layout.view
        self.assertIs(compact.activity,activity);self.assertIsNone(self.panel.voice_visualizer._after)
        self.ctl.toggle_chat();self.assertIs(self.ctl._voice_layout.view,compact)
        self.ctl.exit();self.assertIs(self.panel.voice_visualizer.activity,activity)
        self.assertIsNone(compact._after);self.assertIsNone(compact.activity)

    def test_compact_handsfree_action_remains_available_after_button_rename(self):
        self.ctl._button_action('Hands-free','Hands free')()
        self.panel.toggle_conversation_mode.assert_called_once_with()


if __name__=='__main__':unittest.main()
