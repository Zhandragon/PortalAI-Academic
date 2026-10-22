"""Real Tk responsive chat-settings labels with synthetic settings only."""
import tkinter as tk
import unittest

from test_settings_surfaces_tk import chat_fixture, widgets
from tk_fixture_cleanup import finish_tk_fixture


class SettingsLayoutTests(unittest.TestCase):
    def test_labels_wrap_without_overlapping_fields_at_narrow_and_wide_widths(self):
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(str(exc))
        panel = None
        try:
            root.geometry('430x780+10000+10000')
            panel = chat_fixture(root)
            for width in (430, 1080, 430):
                root.geometry(f'{width}x780+10000+10000'); root.update_idletasks(); root.update()
                for key in panel._preferences_tabs.pages:
                    panel._preferences_tabs.select(key); root.update_idletasks(); root.update()
                    entries = [widget for widget in widgets(panel._preferences_tabs.pages[key]) if isinstance(widget, tk.Entry)]
                    for entry in entries:
                        row = entry.master
                        label = next(child for child in row.winfo_children() if isinstance(child, tk.Label))
                        if int(entry.grid_info()['row']) == 1:
                            self.assertLessEqual(label.winfo_y()+label.winfo_height(), entry.winfo_y())
                        else:
                            self.assertLessEqual(label.winfo_x()+label.winfo_width(), entry.winfo_x())
                        self.assertLessEqual(entry.winfo_x()+entry.winfo_width(), row.winfo_width())
                        self.assertGreaterEqual(entry.winfo_width(), 90)
                        self.assertLessEqual(int(label.cget('wraplength')), label.winfo_width())
        finally:
            if panel: panel._close_sheet()
            panel = None
            finish_tk_fixture(root)


if __name__ == '__main__': unittest.main()
