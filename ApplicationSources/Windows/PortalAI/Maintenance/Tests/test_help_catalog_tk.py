"""Real Help widget navigation using synthetic content, no account or live GUI."""
from pathlib import Path
import sys,tkinter as tk,unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
from ui_extensions import DocumentationPanel
from test_settings_surfaces_tk import LIGHT,DARK
from tk_fixture_cleanup import finish_tk_fixture

class HelpNavigationTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1000x650+40+40');self.errors=[]
        self.app.report_callback_exception=lambda *error:self.errors.append(error)
        self.panel=DocumentationPanel(self.app,LIGHT);self.app.update()
    def tearDown(self):finish_tk_fixture(self.app);self.assertEqual(self.errors,[])
    def test_initial_quick_start_and_category_filter(self):
        p=self.panel;self.assertEqual(p.keys[0],'quick_start');self.assertEqual(p.listbox.curselection(),(0,))
        p.category_var.set('Home Assistant and recovery');self.app.update()
        self.assertIn('recovery',p.keys);self.assertNotIn('science',p.keys)
    def test_context_link_clears_incompatible_filters(self):
        p=self.panel;p.category_var.set('Images, video and audio');p.search_var.set('unfindable')
        self.assertEqual(p.keys,[]);p.show_topic('system_test');self.app.update()
        self.assertIn('system_test',p.keys);self.assertIn('System Test',p.text.get('1.0','end'))
        self.assertEqual(p.keys[p.listbox.curselection()[0]],'system_test')
    def test_legacy_topic_links_resolve_and_theme_stays_usable(self):
        p=self.panel;p.show_topic('component_diagnostics');p.apply_palette(DARK);self.app.update()
        self.assertIn('Full Component Diagnosis',p.text.get('1.0','end'));self.assertEqual(p.current_topic,'diagnostics')
        self.assertEqual(str(p.category.cget('state')),'readonly')
    def test_search_does_not_run_any_actions(self):
        p=self.panel;p.search_var.set('Demucs');self.app.update()
        self.assertIn('demucs',p.keys);self.assertTrue(p.listbox.winfo_ismapped())

if __name__=='__main__':unittest.main()
