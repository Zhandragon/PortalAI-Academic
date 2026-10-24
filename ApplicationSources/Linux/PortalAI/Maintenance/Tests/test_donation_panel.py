"""Real Tk donation controls: explicit actions, exact destinations and responsive layout."""
from pathlib import Path
import sys,unittest,time,ast
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
import tkinter as tk
from donation_panel import DonationPanel,DonationLink,DESTINATIONS,SPONSOR_URL,INTRODUCTION,QR_INTERIORS
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
            self.assertEqual(len(self.panel.borders),4)
            for card,border in zip(self.panel.cards,self.panel.borders):
                self.assertEqual(int(card.cget('highlightthickness')),0)
                self.assertEqual((border.canvas.winfo_x(),border.canvas.winfo_y()),(0,0))
                self.assertEqual((border.canvas.winfo_width(),border.canvas.winfo_height()),(card.winfo_width(),card.winfo_height()))
                masks=border.canvas.find_withtag('ornate-corner-mask')
                self.assertEqual(len(masks),4)
                for mask in masks:self.assertEqual(border.canvas.itemcget(mask,'fill'),palette['bg'])
            self.assertEqual(self.panel.intro.cget('text'),INTRODUCTION)
            self.assertEqual(self.panel.address_labels[1].cget('text'),DESTINATIONS[1][3])
            self.assertEqual(self.panel.address_labels[2].cget('text'),DESTINATIONS[2][3])
            for qr in self.panel.qr_buttons:
                self.assertEqual(qr.cget('bg'),palette['panel'])
                self.assertEqual(qr.cget('activebackground'),palette['panel'])
    def test_grid_reflows_and_never_extends_beyond_page_width(self):
        for width,expected in [(1260,4),(900,2),(550,1)]:
            self.app.geometry(f'{width}x850');self.flush()
            self.assertEqual(self.panel._columns,expected)
            for card in self.panel.cards:
                self.assertLessEqual(card.winfo_x()+card.winfo_width(),self.panel.grid_host.winfo_width())
    def test_navigation_uses_title_link_without_a_donation_tab_button(self):
        source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text('utf-8-sig')
        self.assertNotIn('("donation", "Donation"),',source)
        self.assertLess(source.index('donate_link = DonationLink('),source.index('chrome_buttons["minimize"] ='))
        self.assertIn('donate_link.configure(command=open_donation_page, state="normal")',source)
        self.assertIn('donate_link.apply_palette(COLORS)',source)
        self.assertIn('donation_panel.apply_palette(COLORS)',source)
        ast.parse(source)
    def test_title_link_is_plain_and_explicitly_activated(self):
        from unittest.mock import Mock
        link=DonationLink(self.app,LIGHT);action=Mock();link.configure(command=action)
        self.assertEqual(link.cget('text'),'Donate')
        self.assertEqual(int(link.cget('borderwidth')),0)
        self.assertEqual(int(link.cget('highlightthickness')),0)
        link.invoke();action.assert_not_called()
        link.configure(state='normal');link._activate();action.assert_called_once()
        for palette in (DARK,LIGHT):
            link.apply_palette(palette)
            self.assertEqual(link.cget('bg'),palette['panel'])
            self.assertEqual(link.cget('activebackground'),palette['panel'])
            self.assertNotEqual(link.cget('fg'),palette['text'])
        link.destroy()
    def test_crypto_viewports_preserve_every_module_pixel_and_white_margin(self):
        for index,entry in enumerate(DESTINATIONS):
            name=entry[2]
            displayed=self.panel.qr_buttons[index].cget('image')
            self.assertEqual(int(self.app.tk.call('image','width',displayed)),230)
            self.assertEqual(int(self.app.tk.call('image','height',displayed)),230)
            for x,y in ((0,0),(229,0),(0,229),(229,229)):
                self.assertTrue(self.app.tk.getboolean(self.app.tk.call(displayed,'transparency','get',x,y)))
            for x,y in ((15,115),(115,15),(215,115),(115,215)):
                self.assertFalse(self.app.tk.getboolean(self.app.tk.call(displayed,'transparency','get',x,y)))
            if name not in QR_INTERIORS:continue
            original=tk.PhotoImage(master=self.app,file=str(ROOT/'ControlCenter/DonationAssets'/name))
            x0,y0,x1,y1=QR_INTERIORS[name][1]
            left=(230-(x1-x0))//2;top=(230-(y1-y0))//2
            for y in range(y1-y0):
                for x in range(x1-x0):
                    actual=self.app.tk.call(displayed,'get',left+x,top+y)
                    self.assertEqual(tuple(map(int,self.app.tk.splitlist(actual))),original.get(x0+x,y0+y))
                    self.assertFalse(self.app.tk.getboolean(self.app.tk.call(displayed,'transparency','get',left+x,top+y)))
            for x,y in ((0,0),(229,0),(0,229),(229,229),(15,115),(115,15),(215,115),(115,215)):
                self.assertEqual(tuple(map(int,self.app.tk.splitlist(self.app.tk.call(displayed,'get',x,y)))),(255,255,255))

if __name__=='__main__':unittest.main(verbosity=2)
