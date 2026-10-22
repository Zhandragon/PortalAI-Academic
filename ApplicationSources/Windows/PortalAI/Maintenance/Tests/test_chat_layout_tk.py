"""Real native chat layout with harmless in-memory conversations and no workers."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import tkinter as tk

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ControlCenter'), str(ROOT / 'Agent')]
import native_chat
from chat_layout import stored_width, pane_limits
from tk_fixture_cleanup import finish_tk_fixture

LIGHT = dict(bg='#efe8dc', panel='#e6dccb', panel2='#e9e0d2', card='#f8f3ea',
             text='#202224', muted='#6e665e', thinking='#6e665e', gold='#a87d32',
             tool='#d9be78', cyan='#3e91a2', good='#268e74', bad='#ad4545')
DARK = dict(LIGHT, bg='#101214', panel='#181b1e', panel2='#23272b', card='#181b1e',
            text='#eee7da', muted='#aaa39b', thinking='#aaa39b')


class SyntheticEffort:
    def __init__(self, panel, parent):
        self.widget = tk.Label(parent, text='Chat effort: Balanced  ·  Tools: Balanced',
                               bg=panel.COL['panel'], fg=panel.COL['muted'])


def build_panel(app, *, colors=None, settings=None):
    panel = native_chat.NativeChat.__new__(native_chat.NativeChat)
    panel.app = panel.host = app
    panel.COL = dict(colors or LIGHT)
    panel.settings = {} if settings is None else settings
    panel.store = SimpleNamespace(save_settings=Mock())
    panel._closing = False
    panel._enable_file_drop = Mock()
    panel.history_collapsed = bool(panel.settings.get('history_collapsed', False))
    with patch.object(native_chat, 'ChatEffortControls', SyntheticEffort):
        panel._build_ui()
    return panel


class ChatLayoutPolicyTests(unittest.TestCase):
    def test_preferences_bounded_and_invalid_values_safe(self):
        self.assertEqual(stored_width('bad'), 210)
        self.assertEqual(stored_width(float('inf')), 210)
        self.assertEqual(stored_width(-3), 120)
        self.assertEqual(stored_width(50000), 960)
        for width in (320, 480, 800, 1200):
            minimum, maximum, main = pane_limits(width)
            self.assertLessEqual(minimum, maximum)
            self.assertLessEqual(maximum + main + 11, width)


class ChatLayoutTkTests(unittest.TestCase):
    def setUp(self):
        self.app = tk.Tk()
        self.app.geometry('1100x820+3500+3500')
        self.errors = []
        self.app.report_callback_exception = lambda kind, value, trace: self.errors.append(str(value))
        self.panel = build_panel(self.app)
        self.pump(.2)

    def tearDown(self):
        self.panel.chat_layout.close()
        self.panel.chat_zoom.close()
        finish_tk_fixture(self.app)
        self.assertFalse(self.errors, self.errors)

    def pump(self, seconds=.12):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.app.update(); time.sleep(.01)

    def test_actual_native_layout_has_connected_borders_and_gold_scrollbars(self):
        self.assertFalse(hasattr(self.panel.chat_outer, '_portalai_conversation_border'))
        for widget in (self.panel.composer_shell, self.panel.history_pane, self.panel.conversation_shell):
            border = widget._portalai_conversation_border
            self.assertTrue(border.canvas.find_withtag('ornate'))
        self.assertTrue(self.panel.chat_layout.history_x.winfo_ismapped())
        self.assertTrue(self.panel.chat_layout.history_y.winfo_ismapped())
        self.assertTrue(self.panel.chat_layout.conversation_y.winfo_ismapped())
        self.assertAlmostEqual(self.panel.history_pane.winfo_width(), 210, delta=3)

    def test_saved_history_width_survives_late_child_layout(self):
        self.panel.chat_layout.wanted = 320
        self.panel.chat_layout._schedule()
        self.panel.session_list.insert('end', 'A very long harmless conversation title ' * 8)
        self.pump(.35)
        self.assertAlmostEqual(self.panel.history_pane.winfo_width(), 320, delta=3)
        self.panel.chat_zoom.set_percent(150)
        self.pump()
        self.assertAlmostEqual(self.panel.history_pane.winfo_width(), 320, delta=3)

    def test_horizontal_title_scroll_reveals_complete_title_without_changing_selection(self):
        title = 'A harmless long conversation about planning a weekend museum visit, public transit, opening hours and lunch'
        self.panel.session_list.insert('end', title)
        self.panel.session_list.selection_set(0)
        self.pump()
        self.assertLess(self.panel.session_list.xview()[1], 1)
        self.panel.chat_layout.history_x._move(1)
        self.pump()
        self.assertGreater(self.panel.session_list.xview()[0], 0)
        self.assertEqual(self.panel.session_list.get(0), title)
        self.assertEqual(self.panel.session_list.curselection(), (0,))

    def test_horizontal_scrollbar_actual_drag_moves_title_view(self):
        self.panel.session_list.insert('end', 'Harmless long museum itinerary and public transport options ' * 4)
        self.pump()
        scrollbar = self.panel.chat_layout.history_x
        start, end, left, right, visible, travel = scrollbar._geometry()
        scrollbar.event_generate('<ButtonPress-1>', x=round((left + right) / 2), y=7)
        scrollbar.event_generate('<B1-Motion>', x=round(end - 3), y=7)
        scrollbar.event_generate('<ButtonRelease-1>', x=round(end - 3), y=7)
        self.pump()
        self.assertGreater(self.panel.session_list.xview()[0], .1)

    def test_dragging_history_divider_grows_history_and_shrinks_conversation(self):
        layout = self.panel.chat_layout
        before_history, before_main = self.panel.history_pane.winfo_width(), self.panel.main_pane.winfo_width()
        origin = self.panel.body_pane.winfo_rootx() + self.panel.body_pane.sash_coord(0)[0]
        layout._begin(SimpleNamespace(x_root=origin))
        layout._drag(SimpleNamespace(x_root=origin + 160))
        layout._release()
        self.pump(.45)
        self.assertGreater(self.panel.history_pane.winfo_width(), before_history + 130)
        self.assertLess(self.panel.main_pane.winfo_width(), before_main - 130)
        self.assertAlmostEqual(self.panel.settings['history_width_px'], self.panel.history_pane.winfo_width(), delta=3)
        self.panel.store.save_settings.assert_called_once_with()

    def test_hide_show_restores_requested_width_and_narrow_resize_does_not_overwrite_it(self):
        layout = self.panel.chat_layout
        layout.set_width(420)
        self.pump(.4)
        self.panel._set_history_collapsed(True, persist=True)
        self.pump()
        self.assertFalse(layout.grip.winfo_ismapped())
        self.assertEqual(len(self.panel.body_pane.panes()), 1)
        self.panel._set_history_collapsed(False, persist=True)
        self.pump()
        self.assertAlmostEqual(self.panel.history_pane.winfo_width(), 420, delta=3)
        self.app.geometry('620x820+3500+3500')
        self.pump()
        self.assertLess(self.panel.history_pane.winfo_width(), 420)
        self.assertGreater(self.panel.main_pane.winfo_width(), 240)
        self.assertEqual(layout.wanted, 420)
        self.app.geometry('1100x820+3500+3500')
        self.pump()
        self.assertAlmostEqual(self.panel.history_pane.winfo_width(), 420, delta=3)

    def test_keyboard_resize_and_profile_save_are_blocked_by_lock_and_close(self):
        layout = self.panel.chat_layout
        self.app._portalai_modal_guard = SimpleNamespace(surface=object())
        layout._keyboard(80)
        self.assertNotIn('history_width_px', self.panel.settings)
        self.app._portalai_modal_guard.surface = None
        layout._keyboard(40)
        layout.close()
        self.pump(.5)
        self.panel.store.save_settings.assert_not_called()

    def test_theme_refresh_repaints_new_surface_corners_and_scrollbars(self):
        self.panel.COL.update(DARK)
        self.panel.chat_layout.apply_palette()
        self.pump()
        for widget in (self.panel.history_pane, self.panel.conversation_shell):
            canvas = widget._portalai_conversation_border.canvas
            mask = canvas.find_withtag('ornate-corner-mask')[0]
            self.assertEqual(canvas.itemcget(mask, 'fill'), DARK['bg'])
        self.assertEqual(self.panel.chat_layout.history_x.cget('bg'), DARK['panel'])
        self.assertEqual(self.panel.chat_layout.conversation_y.cget('bg'), DARK['bg'])

    def test_chat_zoom_still_changes_only_conversation(self):
        history_font = str(self.panel.session_list.cget('font'))
        self.panel.chat_zoom.set_percent(150)
        self.pump()
        self.assertEqual(self.panel.chat_zoom.percent, 150)
        self.assertEqual(str(self.panel.session_list.cget('font')), history_font)


if __name__ == '__main__':
    unittest.main()
