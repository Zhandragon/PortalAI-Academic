"""Regression checks for live theme changes, passive branding and stepped inputs."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests')]
from gold_controls import GoldScale,GoldSpinbox
from settings_style import SettingsSkin
from elegant_native_ui import ElegantButton
from page_watermark import PageWatermark
from test_settings_surfaces_tk import LIGHT,DARK
from tk_fixture_cleanup import finish_tk_fixture


class WindowRegionTests(unittest.TestCase):
    def controller(self):
        from ornate_ui import RoundedWindowController
        ctl=RoundedWindowController.__new__(RoundedWindowController)
        ctl.app=Mock();ctl.app.winfo_width.return_value=900;ctl.app.winfo_height.return_value=600
        ctl.hwnd_getter=Mock(return_value=123);ctl.maximized_getter=Mock(return_value=False)
        ctl.radius=18;ctl._after=None;ctl._last_shape=None;ctl._set_dwm=Mock()
        return ctl

    def test_child_scroll_events_do_not_schedule_window_region_rebuild(self):
        ctl=self.controller()
        with patch('ornate_ui.os.name','nt'):
            for _ in range(100):ctl._schedule(SimpleNamespace(widget=object()))
            ctl.app.after.assert_not_called()
            ctl._schedule(SimpleNamespace(widget=ctl.app))
            ctl.app.after.assert_called_once()

    def test_same_shape_is_reused_and_resize_maximize_still_updates(self):
        ctl=self.controller();user=Mock();gdi=Mock()
        user.SetWindowRgn.return_value=1;gdi.CreateRoundRectRgn.return_value=456
        with patch('ornate_ui.os.name','nt'),patch('ctypes.WinDLL',side_effect=lambda name,**kw:user if name=='user32' else gdi):
            ctl.refresh();ctl.refresh()
            self.assertEqual(user.SetWindowRgn.call_count,1)
            ctl.app.winfo_width.return_value=1100;ctl.refresh()
            self.assertEqual(user.SetWindowRgn.call_count,2)
            ctl.maximized_getter.return_value=True;ctl.refresh();ctl.refresh()
            self.assertEqual(user.SetWindowRgn.call_count,3)
            self.assertIsNone(user.SetWindowRgn.call_args.args[1])


class PolishTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('900x600+30+30');self.errors=[]
        self.app.report_callback_exception=lambda *error:self.errors.append(error)

    def tearDown(self):
        finish_tk_fixture(self.app);self.assertEqual(self.errors,[])

    def test_hover_does_not_restore_previous_theme(self):
        button=ElegantButton(self.app,text='Dark',bg=LIGHT['button'],fg=LIGHT['text'])
        button.pack();button.use_native_hover();self.app.update()
        for palette in (DARK,LIGHT,DARK,LIGHT):
            button.event_generate('<Enter>')
            button.configure(bg=palette['button'],fg=palette['text'],activebackground=palette['panel2'])
            self.app.update();button.event_generate('<Leave>')
            self.assertEqual(button.cget('bg'),palette['button'])
            self.assertEqual(button.cget('fg'),palette['text'])
            self.assertFalse(button.instate(['active']))

    def test_slider_arrows_follow_step_and_respect_disabled_state(self):
        values=[]
        scale=GoldScale(self.app,palette=LIGHT,from_=0,to=100,resolution=5,command=values.append)
        scale.pack();scale.set(40);self.app.update();scale.focus_force();self.app.update()
        scale.event_generate('<Right>');self.app.update();self.assertEqual(scale.get(),45)
        scale.event_generate('<Left>');self.assertEqual(scale.get(),40)
        scale.set(48.7);self.assertEqual(scale.get(),50)
        scale.configure(state='disabled');scale.event_generate('<Right>');self.assertEqual(scale.get(),50)
        scale.configure(state='normal');scale.event_generate('<End>');self.assertEqual(scale.get(),100)
        self.assertEqual(float(values[-1]),100)

    def test_help_heading_follows_theme_without_reloading_topic(self):
        from ui_extensions import DocumentationPanel
        panel=DocumentationPanel(self.app,DARK)
        for palette in (LIGHT,DARK,LIGHT):
            panel.apply_palette(palette)
            self.assertEqual(panel.text.tag_cget('title','foreground'),palette['muted'])

    def test_numeric_field_and_slider_share_valid_values_without_clobbering_invalid_text(self):
        skin=SettingsSkin(self.app,LIGHT);value=tk.StringVar(self.app,value='10')
        row=skin.number(self.app,value,maximum=100,step=5);row.pack(fill='x');self.app.update()
        scale=next(w for w in row.winfo_children() if isinstance(w,GoldScale))
        entry=next(w for w in row.winfo_children() if isinstance(w,GoldSpinbox))
        value.set('25');self.assertEqual(scale.get(),25)
        entry.event_generate('<<Increment>>');self.app.update();self.assertEqual(value.get(),'30')
        value.set('invalid');skin.apply_palette(DARK);self.app.update()
        self.assertEqual(value.get(),'invalid');self.assertEqual(scale.get(),30)
        scale.set(60);self.assertEqual(value.get(),'60')
        self.assertEqual(ttk.Style(self.app).lookup(entry.style_name,'fieldbackground'),DARK['panel2'])

    def test_watermark_updates_theme_hides_for_sheets_and_uses_one_timer(self):
        page=tk.Frame(self.app,bg=LIGHT['panel']);page.pack(fill='both',expand=True)
        images={key:tk.PhotoImage(width=144,height=144) for key in
                ('chatwm_light144','chatwm_light196','chatwm_dark144','chatwm_dark196')}
        for image in images.values():image.put('#A87D32',to=(10,10,100,100))
        mode=['light'];selected=['models'];self.app.update()
        mark=PageWatermark(self.app,{'models':page},images,lambda:mode[0],lambda:selected[0])
        self.addCleanup(mark.close);mark.refresh();self.app.update()
        self.assertTrue(mark.shown);self.assertIn('light',mark.key)
        count=len(self.app.tk.call('after','info'))
        for _ in range(12):mark.refresh()
        self.assertEqual(len(self.app.tk.call('after','info')),count)
        mode[0]='dark';mark.apply_palette(DARK);self.assertIn('dark',mark.key)
        if mark.win is not None:
            mark._clickthrough();self.assertAlmostEqual(float(mark.win.attributes('-alpha')),.22)
        from internal_sheet import InternalSheet
        sheet=InternalSheet(self.app,'Synthetic menu',LIGHT);self.app.update()
        mark.refresh();self.assertFalse(mark.shown);sheet.destroy();self.app.update()
        mark.refresh();self.assertTrue(mark.shown)
        selected[0]='chat';mark.refresh();self.assertFalse(mark.shown)
        mark.close();self.assertIsNone(mark.timer)

    def test_help_uses_welcome_asset_and_real_partial_alpha(self):
        from alpha_watermark import premultiplied_bgra
        page=tk.Frame(self.app,bg=LIGHT['panel']);page.pack(fill='both',expand=True)
        self.app.update();mode=['light']
        mark=PageWatermark(self.app,{'help':page},{},lambda:mode[0],lambda:'help')
        self.addCleanup(mark.close)
        for palette,name in ((LIGHT,'light'),(DARK,'dark'),(LIGHT,'light')):
            mode[0]=name;page.configure(bg=palette['panel']);mark.apply_palette(palette);self.app.update()
            self.assertTrue(mark.shown)
            self.assertTrue(mark.key.startswith('help'))
            width,height,data=premultiplied_bgra(mark.images[mark.key])
            self.assertEqual((width,height),(128,128))
            self.assertTrue(any(0<a<255 for a in data[3::4]))
            self.assertEqual(data[(width+1)*4+3],0)
            self.assertTrue(all(max(data[i:i+3])<=data[i+3]+1 for i in range(0,len(data),4)))
            if mark.win is not None:
                self.assertIsNotNone(mark._alpha_signature)
                mark._clickthrough()
        mark.hide();mark.refresh();self.assertTrue(mark.shown)


if __name__=='__main__':unittest.main()
