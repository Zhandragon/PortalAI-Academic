"""Real settings widgets with synthetic inventory and an in-memory chat store."""
import copy
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
import settings_page
from settings_style import SettingsSkin
from native_chat import NativeChat, DEFAULT_SETTINGS
from ornate_ui import FiligreeScrollbar
from tk_fixture_cleanup import finish_tk_fixture

LIGHT = {'bg':'#EFE8DC','panel':'#F8F3EA','panel2':'#E9E0D2','text':'#202224','muted':'#6E665E',
         'accent':'#3E91A2','button':'#E6DCCB','border':'#7B5A22','gold_mid':'#A87D32',
         'gold_shine':'#D9BE78','shadow':'#2B2419','good':'#237B66','bad':'#B14B4B'}
DARK = {**LIGHT,'bg':'#101214','panel':'#181B1E','panel2':'#23272B','text':'#EEE7DA',
        'muted':'#AAA39B','button':'#2C3034'}
INVENTORY = {'policy':{'selection':'auto','backend':'auto','context_tokens':8192},
             'models':[{'label':'Compact text · 4B · Q4','id':'fixture-small','installed':True,'bytes':2*1024**3},
                       {'label':'Large vision · 27B · Q4','id':'fixture-large','installed':True,'bytes':16*1024**3}],
             'storage':{'free_bytes':180*1024**3,'output_reserve_bytes':60*1024**3,
                        'minimum_free_bytes':30*1024**3,'download_budget_bytes':90*1024**3}}


def widgets(parent):
    yield parent
    for child in parent.winfo_children(): yield from widgets(child)


def hardware_fixture(app, palette=LIGHT, admin=True):
    shell = tk.Frame(app, bg=palette['bg']); shell.pack(fill='both', expand=True)
    session = SimpleNamespace(role='admin' if admin else 'user')
    with patch.object(settings_page, 'inventory', return_value=copy.deepcopy(INVENTORY)), \
         patch.object(settings_page, 'can_user', return_value=True), \
         patch.object(settings_page, 'load_effective_policy', return_value=copy.deepcopy(INVENTORY['policy'])):
        page = settings_page.SettingsPage(shell, ROOT, palette, missions=Mock(), session=session)
    page.pack(fill='both', expand=True)
    return page, page.skin


def chat_fixture(app, palette=LIGHT):
    # Bypass production construction: no profile consumers, status/model probes,
    # microphones, tool runtimes or writers are started by this UI fixture.
    panel = object.__new__(NativeChat)
    panel.host = tk.Frame(app, bg=palette['bg']); panel.host.pack(fill='both', expand=True)
    panel.app = app
    panel.COL = {**palette, 'gold':palette['gold_mid'], 'cyan':palette['accent']}
    panel._sheet_overlay = None
    panel._stop_embedded_media = Mock()
    panel.settings = copy.deepcopy(DEFAULT_SETTINGS)
    panel.store = SimpleNamespace(save_settings=Mock())
    panel._request_output_tokens = lambda: 4096
    panel.render_history = Mock(); panel.update_token_label = Mock()
    panel.compact_context_now = Mock(); panel.reset_context_summary = Mock()
    panel.discover_mic_entries = Mock(return_value=[{'name':'Synthetic microphone'}])
    panel.open_settings()
    return panel


def button(host, title):
    return next(w for w in widgets(host) if isinstance(w, ttk.Button) and str(w.cget('text')) == title)


def entry_for(panel, title):
    label = next(w for w in widgets(panel._sheet_overlay) if isinstance(w, tk.Label) and w.cget('text') == title)
    return next(w for w in label.master.winfo_children() if isinstance(w, tk.Entry))


class SettingsSurfaceTests(unittest.TestCase):
    def setUp(self):
        try: self.app = tk.Tk()
        except tk.TclError as exc: raise unittest.SkipTest(str(exc))
        self.app.geometry('1080x760+30+30')
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.page = self.panel = self.skin = None

    def tearDown(self):
        if self.panel: self.panel._close_sheet()
        if self.page: self.page.destroy()
        self.page = self.panel = self.skin = None
        finish_tk_fixture(self.app)
        self.assertEqual(self.errors, [])

    def test_tool_budget_and_rolling_controls_save_and_reopen(self):
        self.panel = chat_fixture(self.app)
        for label, value in [('Tool calls per request (0 = unlimited)', '175'),
                             ('Recent tool exchanges kept verbatim', '6'),
                             ('Checkpoint after this many older exchanges', '10')]:
            entry = entry_for(self.panel, label)
            entry.delete(0, 'end'); entry.insert(0, value)
        button(self.panel._sheet_overlay, 'Save settings').invoke()
        self.panel.store.save_settings.assert_called_once()
        self.assertEqual(self.panel.settings['tool_call_limit'], 175)
        self.assertEqual(self.panel.settings['context_keep_recent_tool_rounds'], 6)
        self.assertEqual(self.panel.settings['context_checkpoint_interval'], 10)
        self.panel.open_settings()
        entry = entry_for(self.panel, 'Tool calls per request (0 = unlimited)')
        self.assertEqual(entry.get(), '175')
        entry.delete(0, 'end'); entry.insert(0, '0')
        button(self.panel._sheet_overlay, 'Save settings').invoke()
        self.assertEqual(self.panel.settings['tool_call_limit'], 0)

    def test_hardware_dark_theme_covers_fields_popups_and_corner_masks(self):
        self.page, self.skin = hardware_fixture(self.app)
        self.app.update()
        initial = self.page.values()
        self.page.apply_palette(DARK); self.skin.apply_palette(DARK); self.app.update()
        self.assertEqual(self.page.values(), initial)
        style = ttk.Style(self.app)
        for combo in self.page.selectors.values():
            self.assertEqual(style.lookup(combo.cget('style'), 'fieldbackground', ('readonly',)), DARK['panel2'])
            popup = combo.tk.call('ttk::combobox::PopdownWindow', str(combo))
            self.assertEqual(combo.tk.call(str(popup)+'.f.l', 'cget', '-background'), DARK['panel2'])
        for border in self.page.skin.borders:
            if not border.widget.winfo_ismapped():continue
            self.assertEqual(border.canvas.winfo_width(), border.widget.winfo_width())
            self.assertEqual(border.canvas.winfo_height(), border.widget.winfo_height())
            masks = border.canvas.find_withtag('ornate-corner-mask')
            self.assertTrue(masks)
            self.assertEqual(border.canvas.itemcget(masks[0], 'fill'),border.widget.master.cget('bg'))

    def test_hardware_permission_and_setting_values_are_preserved(self):
        self.page, self.skin = hardware_fixture(self.app, admin=False)
        self.app.update()
        self.assertFalse(self.page.save_button.instate(['disabled']))
        self.assertFalse(self.page.section_buttons['media'][1].instate(['disabled']))
        with patch.object(settings_page, 'load_effective_policy', return_value=INVENTORY['policy']), patch.object(settings_page, 'save_settings') as save:
            self.page.save_button.invoke()
            save.assert_called_once()
        self.page.destroy(); self.page = None
        for child in self.app.winfo_children(): child.destroy()
        self.page, self.skin = hardware_fixture(self.app, admin=True)
        self.page.variables['backend'].set('vulkan')
        self.page.variables['context_tokens'].set('4096')
        with patch.object(settings_page, 'load_effective_policy', return_value=INVENTORY['policy']), patch.object(settings_page, 'save_settings') as save:
            self.page.save_button.invoke()
            self.assertEqual(save.call_args.args[1]['backend'], 'vulkan')
            self.assertEqual(save.call_args.args[1]['context_tokens'], '4096')
            self.assertIs(save.call_args.kwargs['session'], self.page.account_session)

    def test_hardware_rows_stack_without_clipped_controls_at_narrow_width(self):
        self.app.geometry('420x760+30+30')
        self.page, self.skin = hardware_fixture(self.app)
        self.app.update()
        for scope in ('chat','media'):
            self.page.tabs.select(scope); self.app.update()
            for key,combo in self.page.selectors.items():
                if (key in settings_page.CHAT_KEYS) != (scope == 'chat'):continue
                self.assertEqual(int(combo.grid_info()['row']), 1)
                self.assertGreater(combo.winfo_width(), 160)
                self.assertLessEqual(combo.winfo_x()+combo.winfo_width(), combo.master.winfo_width())
                caption = next(w for w in widgets(combo.master) if isinstance(w, tk.Label))
                self.assertLessEqual(caption.winfo_y()+caption.winfo_height(), combo.winfo_y())
        self.assertLessEqual(self.page.probe_button.winfo_x()+self.page.probe_button.winfo_width(),
                             self.page.probe_button.master.winfo_width())

    def test_media_descriptions_map_to_stable_saved_ids_and_refresh_clean_fields(self):
        self.page,self.skin=hardware_fixture(self.app)
        self.page.selectors['music_engine'].current(2)
        self.app.update()
        self.assertEqual(self.page.values('media')['music_engine'],'acestep-scaled')
        self.page._show_media_help('music_engine')
        self.assertIn('10–30 seconds',self.page.media_detail_text.get())
        self.assertTrue(self.page.dirty('media'))
        policy={**INVENTORY['policy'],'media':{'text_video_engine':'sdcpp-cpu'}}
        with patch.object(settings_page,'load_effective_policy',return_value=policy):
            self.page.refresh_saved()
        self.assertEqual(self.page.values('media')['music_engine'],'acestep-scaled')
        self.assertEqual(self.page.values('media')['text_video_engine'],'sdcpp-cpu')
        self.assertIn('very slow',self.page.media_labels['text_video_engine'].get())

    def test_subtabs_keep_drafts_and_media_fits_normal_window_without_scrolling(self):
        self.app.geometry('1080x650+30+30')
        self.page,self.skin=hardware_fixture(self.app)
        self.page.variables['backend'].set('cpu')
        self.page.tabs.select('media');self.app.update()
        self.page.variables['music_engine'].set('musicgen-cpu')
        self.page._show_media_help('music_engine');self.app.update()
        self.assertEqual(self.page.tabs.selected,'media')
        self.assertGreaterEqual(self.skin.canvas.yview()[1], .999)
        top=self.page.tabs.bar.winfo_rooty()
        self.skin.canvas.yview_moveto(1);self.app.update()
        self.assertEqual(self.page.tabs.bar.winfo_rooty(),top)
        self.page.tabs.select('chat');self.app.update()
        self.assertEqual(self.page.values('chat')['backend'],'cpu')
        self.assertEqual(self.page.values('media')['music_engine'],'musicgen-cpu')
        self.assertTrue(self.page.dirty('chat'));self.assertTrue(self.page.dirty('media'))

    def test_chat_edit_values_survive_theme_and_save_uses_existing_validation(self):
        self.panel = chat_fixture(self.app)
        self.app.update()
        field = entry_for(self.panel, 'Memory summary allowance (tokens)')
        field.delete(0, 'end'); field.insert(0, '99999')
        checkpoint = entry_for(self.panel, 'Checkpoints without new tool results (0 = unlimited)')
        checkpoint.delete(0, 'end'); checkpoint.insert(0, '0')
        self.panel._sheet_skin.apply_palette(DARK); self.app.update()
        self.assertEqual(field.get(), '99999')
        self.assertEqual(checkpoint.get(), '0')
        self.assertEqual(ttk.Style(field).lookup(field.cget('style'),'fieldbackground'), DARK['panel2'])
        self.assertEqual(len([w for w in widgets(self.panel._sheet_overlay) if isinstance(w,tk.Entry)]), 20)
        button(self.panel._sheet_overlay, 'Save settings').invoke()
        self.assertEqual(self.panel.settings['context_summary_max_tokens'], 4096)
        self.assertEqual(self.panel.settings['checkpoint_no_tool_limit'], 0)
        self.panel.store.save_settings.assert_called_once()
        self.panel.render_history.assert_called_once()
        self.assertIsNone(self.panel._sheet_overlay)

    def test_chat_cancel_preserves_values_and_save_bar_stays_visible_while_scrolling(self):
        self.app.geometry('560x700+30+30')
        self.panel = chat_fixture(self.app)
        self.app.update()
        field = entry_for(self.panel, 'Fallback reply allowance (tokens)')
        original = self.panel.settings['max_output_tokens']
        field.delete(0, 'end'); field.insert(0, '7000')
        skin = self.panel._sheet_skin
        self.assertIsInstance(skin.scrollbars[0], FiligreeScrollbar)
        self.assertLess(skin.canvas.yview()[1], 1)
        save = button(self.panel._sheet_overlay, 'Save settings')
        top = save.winfo_rooty()
        skin._wheel(SimpleNamespace(delta=-1200, num=0)); self.app.update()
        self.assertGreater(skin.canvas.yview()[0], 0)
        self.assertEqual(save.winfo_rooty(), top)
        self.assertTrue(save.winfo_ismapped())
        self.assertLess(save.winfo_rooty()+save.winfo_height(), self.app.winfo_rooty()+self.app.winfo_height())
        button(self.panel._sheet_overlay, 'Cancel').invoke()
        self.assertEqual(self.panel.settings['max_output_tokens'], original)
        self.panel.store.save_settings.assert_not_called()


if __name__ == '__main__': unittest.main()
