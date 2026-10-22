"""Real Tk page scrolling: full thumbs must never reveal blank canvas space."""
from pathlib import Path
import sys
from types import SimpleNamespace
import tkinter as tk
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Maintenance/Tests')]
from settings_style import SettingsSkin
from test_settings_surfaces_tk import LIGHT
from tk_fixture_cleanup import finish_tk_fixture


class PageScrollTests(unittest.TestCase):
    def setUp(self):
        self.app = tk.Tk(); self.app.geometry('600x500-10000-10000')
        self.errors = []
        self.app.report_callback_exception = lambda *error: self.errors.append(error)
        self.skin = SettingsSkin(self.app, LIGHT)
        self.content = self.skin.scrolling_body(self.app)
        self.canvas = self.skin.canvas; self.bar = self.skin.scrollbars[0]
        self.skin.label(self.content, 'Short page').pack()
        self.app.update()

    def tearDown(self):
        finish_tk_fixture(self.app)
        self.assertEqual(self.errors, [])

    def assert_fitted(self):
        self.app.update()
        self.assertTrue(self.bar.winfo_ismapped())
        self.assertEqual(self.canvas.yview(), (0.0, 1.0))
        for amount in (-50, 50):
            self.canvas.yview_scroll(amount, 'units')
            self.skin._wheel(SimpleNamespace(delta=120*amount))
            self.assertEqual(self.canvas.canvasy(0), 0)
        for fraction in (1, -1, 0.5, 0):
            self.canvas.yview_moveto(fraction)
            self.assertEqual(self.canvas.canvasy(0), 0)

    def test_short_page_wheel_and_scrollbar_cannot_move_into_blank_space(self):
        self.assertLess(self.content.winfo_height(), self.canvas.winfo_height())
        self.assert_fitted()
        command = self.bar.command = Mock()
        for y in (2, self.bar.winfo_height()//2, self.bar.winfo_height()-2):
            self.bar._press(SimpleNamespace(y=y))
            self.bar._drag(SimpleNamespace(y=y+50))
            self.bar._release(None)
        command.assert_not_called()

    def test_overflow_scrolls_and_content_removal_resets_the_origin(self):
        tall = tk.Frame(self.content, height=1200); tall.pack(fill='x')
        self.app.update()
        self.assertLess(self.canvas.yview()[1], 1)
        self.skin._wheel(SimpleNamespace(delta=-120))
        self.assertGreater(self.canvas.canvasy(0), 0)
        self.canvas.yview_moveto(1)
        bottom = self.canvas.canvasy(0)
        self.assertEqual(bottom, self.content.winfo_height()-self.canvas.winfo_height())
        self.canvas.yview_scroll(100, 'units')
        self.assertEqual(self.canvas.canvasy(0), bottom)
        tall.destroy()
        self.assert_fitted()

    def test_resize_reenables_scroll_without_stretching_the_content(self):
        tall = tk.Frame(self.content, height=700); tall.pack(fill='x')
        self.app.update(); self.canvas.yview_moveto(1)
        natural_height = self.content.winfo_height()
        self.app.geometry('600x1100-10000-10000')
        self.assert_fitted()
        self.assertEqual(self.content.winfo_height(), natural_height)
        self.app.geometry('600x300-10000-10000'); self.app.update()
        self.assertLess(self.canvas.yview()[1], 1)
        self.bar._press(SimpleNamespace(y=self.bar.winfo_height()-2))
        self.assertGreater(self.canvas.canvasy(0), 0)

    def test_full_thumb_cancels_an_in_progress_drag(self):
        self.bar.set(0, 0.4)
        self.bar._press(SimpleNamespace(y=self.bar._thumb[0]+5))
        self.assertIsNotNone(self.bar._drag_offset)
        self.bar.command = Mock()
        self.bar.set(0, 1)
        self.bar._drag(SimpleNamespace(y=300))
        self.bar.command.assert_not_called()

    def test_welcome_hero_fits_the_viewport_and_does_not_grow_when_scrolled(self):
        from portal_frontend_v15136 import WelcomeFeatureController
        shell=tk.Frame(self.content);shell.pack(fill='x',pady=14)
        tk.Frame(shell,height=80).pack(fill='x')
        hero=tk.Frame(shell,height=135);hero.pack(fill='x',pady=(10,8))
        self.app.update()
        controller=WelcomeFeatureController.__new__(WelcomeFeatureController)
        controller.shell=shell;controller.frame=hero
        _,height=controller._visible_extent()
        hero.configure(height=height);self.app.update()
        self.assert_fitted()
        filler=tk.Frame(self.content,height=1200);filler.pack(fill='x');self.app.update()
        self.canvas.yview_scroll(3,'units');self.app.update()
        self.assertGreater(self.canvas.canvasy(0),0)
        self.assertEqual(controller._visible_extent()[1],height)


if __name__ == '__main__': unittest.main()
