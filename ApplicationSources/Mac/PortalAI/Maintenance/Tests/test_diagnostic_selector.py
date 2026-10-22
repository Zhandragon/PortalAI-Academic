"""Real Tk interaction with the in-window diagnostic selector; no model work."""
import tkinter as tk
import unittest
from diagnostic_catalog import CHOICES
from diagnostic_selector import DiagnosticSelector
from internal_sheet import InternalSheet
from test_settings_surfaces_tk import LIGHT, DARK


class DiagnosticSelectorTests(unittest.TestCase):
    def setUp(self):
        self.app = tk.Tk()
        self.app.geometry('800x640')
        self.host = tk.Frame(self.app)
        self.host.pack(fill='both', expand=True)
        self.value = tk.StringVar(self.app, value='Qwen')
        self.combo = DiagnosticSelector(self.host, chooser_parent=self.host, palette=LIGHT,
            textvariable=self.value, values=CHOICES, state='readonly', width=24)
        self.combo.pack()
        self.events = []
        self.errors = []
        self.combo.bind('<<ComboboxSelected>>', lambda e: self.events.append(self.value.get()))
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.assertEqual(self.errors, [])

    def click(self, fraction):
        x = int(self.combo.winfo_width() * fraction)
        y = self.combo.winfo_height() // 2
        self.combo.event_generate('<ButtonPress-1>', x=x, y=y)
        self.combo.event_generate('<ButtonRelease-1>', x=x, y=y)
        self.app.update()

    def test_mouse_text_and_arrow_open_same_window_with_every_choice(self):
        for fraction in (.3, .96):
            self.click(fraction)
            self.assertIsInstance(self.combo.chooser, InternalSheet)
            self.assertIs(self.combo.chooser.winfo_toplevel(), self.app)
            self.assertTrue(self.combo.chooser.winfo_ismapped())
            self.assertEqual([self.combo.tree.item(k, 'text') for k in self.combo.tree.get_children()], list(CHOICES))
            self.assertFalse(int(self.app.tk.call('winfo', 'ismapped', self.combo.popup_path)))
            self.combo.close_choices()
            self.assertEqual(self.value.get(), 'Qwen')
        self.assertEqual(self.events, [])

    def test_filter_keyboard_select_emits_once_without_running_diagnostics(self):
        self.combo.focus_force()
        self.combo.event_generate('<Down>')
        self.app.update()
        self.combo.query.set('comfy')
        self.app.update()
        self.assertEqual(len(self.combo.tree.get_children()), 1)
        self.assertEqual(self.value.get(), 'Qwen')
        self.combo.search.event_generate('<Down>')
        self.combo.tree.event_generate('<Return>')
        self.app.update()
        self.assertEqual(self.value.get(), 'ComfyUI')
        self.assertEqual(self.events, ['ComfyUI'])
        self.assertIsNone(self.combo.chooser)

    def test_no_match_cancel_and_escape_preserve_selection(self):
        self.click(.5)
        self.combo.query.set('definitely no matching component')
        self.app.update()
        self.assertEqual(self.combo.tree.get_children(), ())
        self.assertEqual(str(self.combo.choose_button.cget('state')), 'disabled')
        self.combo.choose()
        self.assertEqual(self.value.get(), 'Qwen')
        self.combo.chooser._escape_close()
        self.assertIsNone(self.combo.chooser)
        self.click(.5)
        self.assertEqual(self.combo.query.get(), '')
        self.combo.close_choices()
        self.assertEqual(self.events, [])

    def test_disabled_and_stale_selection_do_not_commit(self):
        self.combo.state(['disabled'])
        self.click(.5)
        self.assertIsNone(self.combo.chooser)
        self.combo.state(['!disabled'])
        self.click(.5)
        self.combo.configure(values=('ComfyUI',))
        self.combo.choose()
        self.assertEqual(self.value.get(), 'Qwen')
        self.assertEqual(self.events, [])

    def test_theme_small_window_reopen_and_destroy_cleanup(self):
        self.click(.5)
        initial = self.combo.chooser
        self.combo.open_choices()
        self.assertIs(self.combo.chooser, initial)
        self.app.geometry('600x400')
        self.combo.apply_palette(DARK)
        self.app.update()
        self.assertEqual(self.combo.chooser.colors['panel'], DARK['panel'])
        self.assertTrue(self.combo.choose_button.winfo_ismapped())
        self.assertLess(self.combo.choose_button.winfo_rooty(), self.app.winfo_rooty()+400)
        self.combo.destroy()
        self.app.update()
        self.assertIsNone(self.combo.chooser)
        self.assertFalse(initial.winfo_exists())

    def test_native_ha_combobox_contract_and_local_selection_agree(self):
        self.assertEqual(self.combo.winfo_class(), 'TCombobox')
        self.assertEqual(tuple(self.combo['values']), CHOICES)
        self.combo.set('Web Tools')
        self.combo.event_generate('<<ComboboxSelected>>')
        self.click(.5)
        chosen = self.combo.tree.selection()
        self.assertEqual(self.combo.tree.item(chosen[0], 'text'), 'Web Tools')
        self.combo.close_choices()
        self.assertEqual(self.value.get(), 'Web Tools')


if __name__ == '__main__':
    unittest.main()
