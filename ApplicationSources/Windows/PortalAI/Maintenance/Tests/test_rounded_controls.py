"""Native input behavior and separate disk-policy saves survive visual changes."""
import json
from pathlib import Path
import tempfile
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch
from test_gui_polish import PolishTests
from test_settings_surfaces_tk import LIGHT,DARK
from rounded_controls import RoundedCombobox
from gold_controls import GoldScale,GoldSpinbox
from settings_page import save_storage_settings


class RoundedBehaviorTests(PolishTests):
    def test_chat_validation_report_copies_complete_text_with_persistent_footer(self):
        from test_settings_surfaces_tk import chat_fixture,button,widgets
        from rounded_text import RoundedText
        panel=chat_fixture(self.app)
        try:
            panel.open_frontend_validation()
            payload='Synthetic report line\n'*20000
            panel._validation_emit(payload)
            self.app.update()
            box=next(w for w in widgets(panel._sheet_overlay) if isinstance(w,RoundedText))
            action=button(panel._sheet_overlay,'Copy to clipboard')
            self.assertTrue(action.winfo_ismapped())
            self.assertLessEqual(action.winfo_rooty()+action.winfo_height(),panel._sheet_overlay.winfo_rooty()+panel._sheet_overlay.winfo_height())
            with patch.object(self.app,'clipboard_clear'),patch.object(self.app,'clipboard_append') as copied:
                action.invoke()
                self.assertEqual(copied.call_args.args[0],box.get('1.0','end-1c'))
                self.assertIn(payload,copied.call_args.args[0])
            panel._sheet_skin.apply_palette(DARK);self.app.update()
            self.assertEqual(box.cget('bg'),DARK['panel2'])
        finally:panel._close_sheet()

    def test_dropdown_popup_keyboard_selection_and_theme(self):
        value=tk.StringVar(self.app,value='one')
        combo=RoundedCombobox(self.app,palette=LIGHT,textvariable=value,values=('one','two'),state='readonly')
        combo.pack();self.app.update()
        for palette in (DARK,LIGHT):
            combo.apply_palette(palette);combo.tk.call('ttk::combobox::Post',str(combo));self.app.update()
            popup=combo.popup_path
            self.assertTrue(int(combo.tk.call('winfo','ismapped',popup)))
            self.assertEqual(combo.tk.call(popup+'.f.l','cget','-background'),palette['panel2'])
            combo.tk.call(popup+'.f.l','selection','clear',0,'end')
            combo.tk.call(popup+'.f.l','selection','set',1)
            combo.tk.call('event','generate',popup+'.f.l','<Return>');self.app.update()
            self.assertEqual(value.get(),'two')
            self.assertFalse(int(combo.tk.call('winfo','ismapped',popup)))

    def test_rounded_slider_mouse_drag_and_numeric_arrow(self):
        scale=GoldScale(self.app,palette=LIGHT,from_=0,to=100,resolution=5,length=300)
        scale.pack();self.app.update();scale.set(20);self.app.update()
        x,y=map(int,self.app.tk.call(str(scale),'coords',20))
        endx,endy=map(int,self.app.tk.call(str(scale),'coords',80))
        scale.event_generate('<ButtonPress-1>',x=x,y=y)
        scale.event_generate('<B1-Motion>',x=endx,y=endy)
        scale.event_generate('<ButtonRelease-1>',x=endx,y=endy)
        self.assertEqual(scale.get(),80)
        value=tk.StringVar(self.app,value='10')
        number=GoldSpinbox(self.app,palette=LIGHT,from_=0,to=20,increment=2,textvariable=value)
        number.pack();self.app.update()
        points=[(x,y) for x in range(number.winfo_width()) for y in range(number.winfo_height()) if number.identify(x,y).endswith('uparrow')]
        self.assertTrue(points)
        x,y=points[len(points)//2]
        number.event_generate('<ButtonPress-1>',x=x,y=y);number.event_generate('<ButtonRelease-1>',x=x,y=y)
        self.assertEqual(value.get(),'12')

    def test_storage_save_preserves_latest_model_policy_and_rejects_bad_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'Agent').mkdir()
            policy={'selection':'latest-model','backend':'vulkan','future':{'keep':True},'storage':{'extension':'keep'}}
            target=root/'Agent/hardware_profiles.json';target.write_text(json.dumps(policy))
            with patch('settings_page.require_admin'),patch('settings_page.load_policy',return_value=policy.copy()):
                save_storage_settings(root,{'output_reserve_gib':'120','minimum_free_gib':'50','minimum_free_percent':'10'})
                saved=json.loads(target.read_text());self.assertEqual(saved['selection'],'latest-model');self.assertEqual(saved['storage']['extension'],'keep')
                before=target.read_bytes()
                with self.assertRaises(ValueError):save_storage_settings(root,{'output_reserve_gib':'nan'})
                self.assertEqual(before,target.read_bytes())
            with patch('settings_page.require_admin',side_effect=PermissionError):
                with self.assertRaises(PermissionError):save_storage_settings(root,{'output_reserve_gib':'130'})
            self.assertEqual(before,target.read_bytes())


if __name__=='__main__':unittest.main()
