"""Presentation reuse must avoid global repaints without retaining stale data."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from test_settings_surfaces_tk import LIGHT, DARK
from tk_fixture_cleanup import finish_tk_fixture
from elegant_native_ui import ElegantButton, ui_font
from rounded_controls import RoundedCombobox, RoundedEntry
from internal_sheet import InternalSheet
from packages_page import PackagesView


class PresentationReuseTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1000x720+30+30');self.errors=[]
        self.app.report_callback_exception=lambda *args:self.errors.append(args)
        self.host=tk.Frame(self.app,bg=LIGHT['panel']);self.host.pack(fill='both',expand=True)
        self.repaint=[]
        self.host.bind('<<ThemeChanged>>',lambda e:self.repaint.append(1))

    def tearDown(self):
        finish_tk_fixture(self.app);self.assertFalse(self.errors,self.errors)

    def test_popup_reopening_does_not_broadcast_theme_changes(self):
        combo=RoundedCombobox(self.host,palette=LIGHT,values=('one','two'),state='readonly')
        combo.pack();self.app.update();self.repaint.clear()
        for _ in range(3):
            combo.tk.call('ttk::combobox::Post',str(combo));self.app.update()
            self.assertTrue(int(combo.tk.call('winfo','ismapped',combo.popup_path)))
            combo.tk.call('ttk::combobox::Unpost',str(combo));self.app.update()
        self.assertFalse(self.repaint,'An unchanged popup restyled the entire application')

    def test_first_settings_skin_configures_its_own_style_in_each_theme(self):
        from settings_style import SettingsSkin
        style=ttk.Style(self.app)
        for theme in style.theme_names():
            style.theme_use(theme)
            skin=SettingsSkin(self.host,LIGHT)
            self.assertEqual(style.configure(skin.combo_style,'foreground'),LIGHT['text'])
            self.assertEqual(style.layout(skin.combo_style)[0][0],'PortalSettings.field')
            self.assertEqual(style.configure(skin.scroll_style,'troughcolor'),LIGHT['panel'])
            self.assertEqual(style.configure(skin.popup_style,'background'),LIGHT['panel'])

    def test_palette_changes_and_destroyed_popups_refresh(self):
        combo=RoundedCombobox(self.host,palette=LIGHT,values=('one','two'));combo.pack();self.app.update()
        first=combo.cget('style')
        combo.apply_palette(DARK);self.app.update()
        self.assertNotEqual(first,combo.cget('style'))
        self.assertEqual(combo.tk.call(combo.popup_path+'.f.l','cget','-background'),DARK['panel2'])
        combo.apply_palette(LIGHT);self.app.update();self.assertEqual(first,combo.cget('style'))
        combo.tk.call('destroy',combo.popup_path);combo._prepare_popup();self.app.update()
        self.assertEqual(combo.tk.call(combo.popup_path+'.f.l','cget','-background'),LIGHT['panel2'])

    def test_shared_buttons_keep_independent_values_and_commands(self):
        invoked=[]
        a=ElegantButton(self.host,text='A',command=lambda:invoked.append('A'))
        b=ElegantButton(self.host,text='B',command=lambda:invoked.append('B'))
        a.pack();b.pack();self.app.update();style=a.cget('style')
        self.assertEqual(style,b.cget('style'));self.repaint.clear()
        a.configure(bg=a.cget('bg'),fg=a.cget('fg'));self.app.update()
        self.assertFalse(self.repaint)
        a.configure(fg='#FF0000');self.app.update()
        self.assertNotEqual(a.cget('style'),b.cget('style'))
        self.assertNotEqual(ttk.Style(b).lookup(b.cget('style'),'foreground'),'#FF0000')
        a.invoke();b.invoke();self.assertEqual(invoked,['A','B'])
        a.configure(state='disabled');a.invoke();self.assertEqual(invoked,['A','B'])

    def test_fields_reuse_styles_but_keep_separate_text_and_parent_colors(self):
        a=RoundedEntry(self.host,palette=LIGHT);b=RoundedEntry(self.host,palette=LIGHT)
        a.insert(0,'first');b.insert(0,'second');a.pack();b.pack();self.app.update()
        self.assertEqual(a.cget('style'),b.cget('style'))
        self.assertEqual((a.get(),b.get()),('first','second'))
        self.host.configure(bg='#123456');a.apply_palette(LIGHT)
        self.assertNotEqual(a.cget('style'),b.cget('style'))
        self.assertEqual(ttk.Style(a).lookup(a.cget('style'),'background'),'#123456')

    def test_reopening_sheet_reuses_styles_not_widgets_or_content(self):
        def make():
            sheet=InternalSheet(self.host,'Synthetic',LIGHT)
            tree=ttk.Treeview(sheet.content);tree.pack();sheet.style_tree(tree)
            sheet.skin.entry(sheet.content,'').pack();sheet.finish();self.app.update()
            return sheet,tree
        sheet,tree=make();tree.insert('','end',text='Old contents');sheet.destroy();self.app.update()
        self.repaint.clear();other,new_tree=make()
        self.assertFalse(self.repaint)
        self.assertFalse(new_tree.get_children(),'Old sheet content was cached')
        other.destroy()

    def test_package_layout_skips_unchanged_and_hidden_views_but_updates_data(self):
        view=PackagesView(self.host,LIGHT);view.pack(fill='both',expand=True)
        for i in range(10):view.add(str(i),'Synthetic '+str(i))
        self.app.update()
        with patch.object(view.measure,'create_text',wraps=view.measure.create_text) as measured:
            view.layout();self.assertFalse(measured.called)
            view.entries[0][4].configure(text='New current status');view.layout();self.assertTrue(measured.called)
            view.pack_forget();self.app.update();measured.reset_mock()
            view.layout();self.assertFalse(measured.called)
            view.entries[0][4].configure(text='Updated while hidden')
            view.pack(fill='both',expand=True);self.app.update();self.assertTrue(measured.called)

    def test_resize_does_not_cache_a_style_per_window_size(self):
        a=ElegantButton(self.host,text='Resize');a.pack(fill='x')
        field=RoundedEntry(self.host,palette=LIGHT);field.pack(fill='x');self.app.update()
        count=len(self.app._portalai_presentation_styles)
        for width in (900,1100,750,1000):self.app.geometry(f'{width}x720');self.app.update()
        self.assertEqual(len(self.app._portalai_presentation_styles),count)

    def test_cache_respects_ttk_theme_and_font_lookup_reuse(self):
        from ui_style_cache import cached_style
        calls=[]
        def build(style,name):calls.append(name);style.configure(name,foreground='red')
        first=cached_style(self.host,'Test.TLabel',('same',),build)
        other=next(name for name in ttk.Style(self.app).theme_names() if name!=ttk.Style(self.app).theme_use())
        ttk.Style(self.app).theme_use(other)
        second=cached_style(self.host,'Test.TLabel',('same',),build)
        self.assertNotEqual(first,second);self.assertEqual(len(calls),2)
        self.app._portalai_font_families={}
        with patch('elegant_native_ui.tkfont.families',return_value=('Segoe UI',)) as families:
            self.assertEqual(ui_font(self.app),ui_font(self.host));families.assert_called_once()

if __name__=='__main__':unittest.main()
