"""Real Tk controls; maintenance actions use mocks or disposable roots."""
import json
import gc
from pathlib import Path
import sys
import tkinter as tk
from unittest.mock import Mock,patch
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools'),str(ROOT/'Maintenance/Tests')]
import test_account_presentation_tk as fixtures
from test_account_presentation_tk import LIGHT,button
import account_ui
import utilities_ui
import suite_utilities
import portalai_full_reset


class SuiteTkTests(unittest.TestCase):
    setUp=fixtures.AccountPresentationTests.setUp
    tearDown=fixtures.AccountPresentationTests.tearDown

    def open_button_help(self, dialog, control, topic, gesture='<Button-3>'):
        from themed_popup_menu import ThemedPopupMenu
        from help_catalog import TOPICS
        show=ThemedPopupMenu.show;calls=[]
        def capture(menu,x,y,items,**kwargs):
            calls.append((menu,items));return show(menu,x,y,items,**kwargs)
        with patch.object(ThemedPopupMenu,'show',capture):
            control.event_generate(gesture,x=5,y=5);self.app.update()
        self.assertEqual(len(calls),1)
        menu,items=calls[0]
        self.assertTrue(self.app._portalai_modal_guard.allowed(str(menu.window)))
        self.assertEqual([item['label'] for item in items],['What this does…'])
        menu._run(items[0]['command']);self.app.update()
        info=next(d for d in reversed(self.app._portalai_account_dialogs) if not d.closed)
        self.assertIsNot(info,dialog)
        text='\n'.join(w.cget('text') for w in info.body.winfo_children() if w.winfo_class()=='Label')
        self.assertIn(TOPICS[topic]['body'],text)
        self.assertEqual([b.cget('text') for b,_ in info.buttons],['Close'])
        button(info,'Close').invoke();self.app.update()
        self.assertFalse(dialog.closed)

    def test_utility_help_works_without_launching_even_for_unavailable_platform(self):
        with patch.object(suite_utilities,'current_platform',return_value='Mac'), \
             patch.object(suite_utilities,'launch') as launch,patch.object(suite_utilities,'reveal') as reveal:
            d=utilities_ui.show_utilities(self.host,self.controller.root,self.colors);self.app.update()
            for b,_ in d.buttons:
                label=b.cget('text')
                if label=='Close':continue
                topic=('suite_abliterator' if label=='PortalAI Abliterator' else
                       'suite_projection' if label=='PortalAI Home Assistant Projection' else 'suite_installers')
                self.open_button_help(d,b,topic)
            launch.assert_not_called();reveal.assert_not_called();d.close()

    def test_full_utility_panel_buttons_and_theme(self):
        d=utilities_ui.show_utilities(self.host,self.controller.root,self.colors);self.app.update()
        labels=[b.cget('text') for b,_ in d.buttons]
        self.assertIn('PortalAI Abliterator',labels)
        self.assertIn('PortalAI Home Assistant Projection',labels)
        self.assertEqual(labels.count('Locate Windows Installer'),2)
        self.assertGreater(d.surface.card.winfo_width(),400)
        d.apply_palette(dict(self.colors,panel='#1C1E20',text='#F2ECE2'));self.app.update()
        self.assertEqual(d.body.cget('bg').lower(),'#1c1e20')
        d.close()

    def test_academic_panel_only_one_of_each_installer(self):
        root=self.controller.root;(root/'Agent').mkdir();(root/'Agent/academic_policy.py').write_text('#Academic')
        with patch.object(suite_utilities,'current_platform',return_value='Mac'):
            d=utilities_ui.show_utilities(self.host,root,self.colors);self.app.update()
        labels=[b.cget('text') for b,_ in d.buttons]
        self.assertEqual(labels.count('Locate Mac Installer'),1)
        self.assertNotIn('PortalAI Abliterator',labels)
        d.close()

    def test_login_maintenance_waits_for_idle_and_only_queues(self):
        d=account_ui._Dialog(self.host,'Login',self.colors)
        utilities_ui.add_login_utilities(d,self.controller);self.app.update()
        with patch.object(suite_utilities,'request_after_exit') as request:
            d.busy=True;button(d,'Wipe all accounts…').invoke();request.assert_not_called()
            d.busy=False;button(d,'Crash recovery').invoke()
            request.assert_called_once_with(self.controller.root,'recover');self.assertTrue(d.closed)

    def test_login_contains_one_entry_per_maintenance_action(self):
        errors=[]
        def inspect():
            dialog=next(d for d in reversed(self.app._portalai_account_dialogs) if not d.closed)
            try:
                self.app.update_idletasks()
                labels=[b.cget('text') for b,_ in dialog.buttons]
                self.assertEqual(labels.count('Wipe all accounts…'),1)
                self.assertEqual(labels.count('Crash recovery'),1)
                recovery=button(dialog,'Crash recovery');registry=button(dialog,'Recover account registry…')
                wipe=button(dialog,'Wipe all accounts…');sign_in=button(dialog,'Sign in')
                self.assertEqual(recovery.pack_info()['in'],registry.pack_info()['in'])
                self.assertEqual(wipe.pack_info()['in'],sign_in.pack_info()['in'])
                self.assertGreater(recovery.winfo_rooty(),registry.winfo_rooty())
                self.assertGreater(wipe.winfo_rooty(),sign_in.winfo_rooty())
                headings=[w.cget('text') for w in dialog.body.winfo_children() if w.winfo_class()=='Label']
                self.assertNotIn('Maintenance',headings)
                self.assertFalse(any('Nothing is deleted' in text or 'Crash recovery closes' in text for text in headings))
                self.assertTrue(recovery.bind('<Button-3>'));self.assertTrue(wipe.bind('<Button-3>'))
                with patch.object(suite_utilities,'request_after_exit') as request, \
                     patch.object(self.controller.backend,'recover_registry') as recover_registry:
                    self.open_button_help(dialog,registry,'account_registry_recovery')
                    self.open_button_help(dialog,recovery,'login_crash_recovery')
                    self.open_button_help(dialog,wipe,'wipe_all_accounts')
                    request.assert_not_called();recover_registry.assert_not_called()
            except BaseException as exc:errors.append(exc)
            finally:dialog.close()
        self.app.after(150,inspect)
        account_ui.show_login(self.app,self.controller,self.colors,prepare_session=Mock())
        if errors:raise errors[0]

    def test_reset_window_exact_confirmation_and_cancel(self):
        original=tk.Tk;errors=[];engine=Mock()
        def create():
            window=original();window.geometry('+10000+10000')
            window.mainloop=lambda:window.wait_window(window)
            def verify():
                try:
                    def widgets(w):
                        yield w
                        for c in w.winfo_children():yield from widgets(c)
                    allwidgets=list(widgets(window));buttons={w.cget('text'):w for w in allwidgets if w.winfo_class()=='TButton'}
                    entry=next(w for w in allwidgets if w.winfo_class()=='TEntry')
                    for value,enabled in [('confirm',False),(' CONFIRM',False),('CONFIRM ',False),('CONFIRM',True),('',False)]:
                        entry.delete(0,'end');entry.insert(0,value);window.update_idletasks()
                        self.assertEqual(str(buttons['Confirm'].cget('state'))=='normal',enabled)
                    self.assertIn('X',buttons);buttons['Cancel'].invoke()
                except BaseException as exc:errors.append(exc);window.destroy()
            window.after(30,verify);return window
        with patch.object(tk,'Tk',side_effect=create),patch.object(portalai_full_reset,'FactoryReset',return_value=engine):
            portalai_full_reset.main()
        engine.reset.assert_not_called()
        if errors:raise errors[0]
        gc.collect()

    def test_right_click_help_remains_inside_login_guard(self):
        import themed_popup_menu
        original=themed_popup_menu.ThemedPopupMenu;menus=[]
        def make(*args,**kwargs):
            menu=original(*args,**kwargs);menus.append(menu);return menu
        d=account_ui._Dialog(self.host,'Login',self.colors)
        with patch.object(themed_popup_menu,'ThemedPopupMenu',side_effect=make):
            utilities_ui.add_login_utilities(d,self.controller)
        self.app.update()
        recovery=button(d,'Crash recovery')
        recovery.event_generate('<Button-3>',x=5,y=5);self.app.update()
        self.assertIsNotNone(menus[0].window)
        self.assertTrue(self.app._portalai_modal_guard.allowed(str(menus[0].window)))
        menus[0].close();d.close()


if __name__=='__main__':unittest.main()
