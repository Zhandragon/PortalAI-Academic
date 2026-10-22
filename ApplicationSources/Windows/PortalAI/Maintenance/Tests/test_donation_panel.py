"""Real Tk donation controls: explicit actions, exact destinations and responsive layout."""
from pathlib import Path
import sys,unittest,time,ast
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
import tkinter as tk
from donation_panel import DonationPanel,DESTINATIONS,SPONSOR_URL,INTRODUCTION
from test_settings_surfaces_tk import LIGHT,DARK

class DonationTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1260x850')
        self.panel=DonationPanel(self.app,ROOT,LIGHT);self.flush()
    def flush(self):
        for _ in range(4):self.app.update();time.sleep(.015)
    def tearDown(self):self.app.destroy()
    def test_each_qr_and_button_copy_exact_destination(self):
        for index,entry in enumerate(DESTINATIONS):
            for control in [self.panel.copy_buttons[index],self.panel.qr_buttons[index]]:
                with patch.object(self.panel,'clipboard_clear') as clear,patch.object(self.panel,'clipboard_append') as copied:
                    control.invoke();clear.assert_called_once();copied.assert_called_once_with(entry[3])
                    self.assertIn('copied to clipboard',self.panel.status.get())
    def test_sponsor_opens_only_the_public_profile_on_click(self):
        with patch('donation_panel.webbrowser.open') as opened:
            self.flush();opened.assert_not_called()
            self.panel.sponsor.invoke();opened.assert_called_once_with(SPONSOR_URL)
    def test_theme_changes_preserve_exact_case_and_network_labels(self):
        self.panel.copy_destination=lambda index:None
        for palette in [DARK,LIGHT]:
            self.panel.apply_palette(palette);self.flush()
            self.assertEqual(self.panel.wordmark.cget('bg'),palette['bg'])
            self.assertEqual(self.panel.intro.cget('text'),INTRODUCTION)
            self.assertEqual(self.panel.address_labels[1].cget('text'),DESTINATIONS[1][3])
            self.assertEqual(self.panel.address_labels[2].cget('text'),DESTINATIONS[2][3])
    def test_grid_reflows_and_never_extends_beyond_page_width(self):
        for width,expected in [(1260,4),(900,2),(550,1)]:
            self.app.geometry(f'{width}x850');self.flush()
            self.assertEqual(self.panel._columns,expected)
            for card in self.panel.cards:
                self.assertLessEqual(card.winfo_x()+card.winfo_width(),self.panel.grid_host.winfo_width())
    def test_navigation_registers_donation_immediately_after_help(self):
        source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text('utf-8-sig')
        self.assertIn('("help", "Help"),\n        ("donation", "Donation"),',source)
        self.assertIn('donation_panel.apply_palette(COLORS)',source)
        ast.parse(source)

if __name__=='__main__':unittest.main(verbosity=2)
