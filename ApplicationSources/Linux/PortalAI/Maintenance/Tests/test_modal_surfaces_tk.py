"""Synthetic Tk input boundaries and in-memory backdrop/theme regressions."""
import gc
import os
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'ControlCenter'),str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
from account_ui import _Dialog
from modal_backdrop import snapshot_host, dim_color
from modal_guard import set_modal_surface
from types import SimpleNamespace
from ornate_ui import ConnectedBorder
from shutdown_ui import ShutdownStatus
from test_account_presentation_tk import LIGHT, DARK
from tk_fixture_cleanup import finish_tk_fixture


class ModalSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.geometry('1000x780-10000-10000')
        self.chrome=tk.Frame(self.app,height=44,bg=LIGHT['panel2']);self.chrome.pack(fill='x')
        self.chrome.pack_propagate(False)
        self.drag=tk.Label(self.chrome,text='Synthetic launcher chrome');self.drag.pack(side='left')
        self.host=tk.Frame(self.app,bg=LIGHT['bg']);self.host.pack(fill='both',expand=True)
        self.app._portalai_login_host=self.host
        self.app._portalai_chrome_widget=self.chrome
        self.app._portalai_account_root=ROOT
        self.hits=[]
        self.background=tk.Button(self.host,text='Synthetic underlying action')
        self.background.pack()
        for event in ('<ButtonPress-1>','<Enter>','<MouseWheel>'):
            self.background.bind(event,lambda _,e=event:self.hits.append(e))
        self.drag.bind('<ButtonPress-1>',lambda _:self.hits.append('chrome'))
        self.drag.bind('<B1-Motion>',lambda _:self.app.geometry('+20+20'))
        self.app.update()

    def tearDown(self):
        remaining=finish_tk_fixture(self.app)
        self.app=None;self.chrome=None;self.host=None;self.background=None;self.drag=None
        gc.collect()
        self.assertEqual(remaining,0)

    def dialog(self):
        dialog=_Dialog(self.app,'Synthetic login',dict(LIGHT),startup=True)
        self.app.update()
        return dialog

    def test_chrome_mouse_and_drag_work_but_background_events_are_blocked(self):
        dialog=self.dialog()
        for event in ('<ButtonPress-1>','<Enter>','<MouseWheel>'):
            self.background.event_generate(event)
        self.drag.event_generate('<ButtonPress-1>',x=5,y=5)
        self.drag.event_generate('<B1-Motion>',x=25,y=25)
        self.app.update()
        self.assertEqual(self.hits,['chrome'])
        self.assertEqual((self.app.winfo_x(),self.app.winfo_y()),(20,20))
        self.assertGreaterEqual(dialog.win.winfo_y(),self.chrome.winfo_height())
        self.assertIs(self.app.grab_current(),self.app)
        dialog.close();self.background.event_generate('<ButtonPress-1>')
        self.assertEqual(self.hits,['chrome','<ButtonPress-1>'])
        self.assertIsNone(self.app.grab_current())

    def test_late_widgets_and_nested_dialogs_remain_guarded(self):
        parent=self.dialog()
        parent.button('Parent action',lambda:None)
        self.app.update()
        button=parent.buttons[0][0]
        button.bind('<ButtonPress-1>',lambda _:self.hits.append('parent'))
        child=_Dialog(parent.win,'Nested synthetic',LIGHT);self.app.update()
        button.event_generate('<ButtonPress-1>');self.assertEqual(self.hits,[])
        late=tk.Label(self.host,text='Late underlying widget');late.pack()
        late.bind('<Enter>',lambda _:self.hits.append('late'));self.app.update()
        late.event_generate('<Enter>');self.assertEqual(self.hits,[])
        child.close();button.event_generate('<ButtonPress-1>')
        self.assertEqual(self.hits,['parent'])

    def test_repeated_guards_release_registered_tcl_callbacks(self):
        surface=SimpleNamespace(card=self.host,on_close=lambda:None)
        commands=lambda:set(self.app.tk.splitlist(self.app.tk.call('info','commands')))
        before=commands()
        for _ in range(10):
            set_modal_surface(self.app,surface)
            set_modal_surface(self.app,None)
        self.assertEqual(commands(),before)

    def test_modal_keyboard_stays_in_card_and_picker_popup_is_usable(self):
        dialog=self.dialog();value=dialog.entry('Synthetic value',value='a')
        entry=next(w for w in dialog.body.winfo_children() if isinstance(w,tk.Entry))
        self.app.bind('<KeyPress>',lambda _:self.hits.append('global-key'))
        self.app.update();self.app.focus_force();entry.focus_set();entry.icursor('end');self.app.update()
        self.assertEqual(value.get(), 'a')  # Retain StringVar, like production callers.
        # Native focus traversal may select existing text. This assertion tests
        # modal key delivery, so explicitly request insertion after that text.
        entry.selection_clear();entry.icursor('end')
        entry.event_generate('<KeyPress-b>');self.app.update()
        self.assertEqual(entry.get(),'ab');self.assertEqual(self.hits,[])
        second=tk.Entry(dialog.body);second.pack();self.app.update()
        entry.event_generate('<Tab>');self.app.update()
        self.assertIs(self.app.focus_get(),second)
        second.event_generate('<Shift-Tab>');self.app.update()
        self.assertIs(self.app.focus_get(),entry)
        picker=ttk.Combobox(dialog.body,values=['One','Two'],state='readonly');picker.pack()
        self.app.update();picker.tk.call('ttk::combobox::Post',str(picker));self.app.update()
        pop=picker.tk.call('ttk::combobox::PopdownWindow',str(picker))
        listbox=str(pop)+'.f.l'
        guard=self.app._portalai_modal_guard
        self.assertTrue(guard.allowed(listbox))
        self.assertIn(guard.tag,self.app.tk.splitlist(self.app.tk.call('bindtags',listbox)))
        self.app.tk.call(listbox,'selection','clear',0,'end')
        self.app.tk.call(listbox,'selection','set',1)
        self.app.tk.call('ttk::combobox::LBSelected',listbox)
        self.assertEqual(picker.get(),'Two')
        self.assertIs(self.app.grab_current(),self.app)

    def test_wheel_scrolls_card_and_escape_closes_only_top_dialog_once(self):
        parent=self.dialog()
        child=_Dialog(parent.win,'Nested scrolling synthetic',LIGHT)
        for i in range(40):child.label('Row '+str(i))
        self.app.update()
        label=child.body.winfo_children()[0]
        label.event_generate('<MouseWheel>',delta=-120);self.app.update()
        self.assertGreater(child.canvas.yview()[0],0)
        self.app.focus_force();child.surface.card.focus_set();self.app.update()
        child.surface.card.event_generate('<KeyPress-Escape>');self.app.update()
        parent.surface.card.event_generate('<KeyRelease-Escape>');self.app.update()
        self.assertTrue(child.closed);self.assertFalse(parent.closed)

    @unittest.skipUnless(os.name=='nt','Owned-window capture is Windows-specific')
    def test_snapshot_is_in_memory_dimmed_and_shutdown_preserves_last_page(self):
        self.app.geometry('1000x780+20+20')
        marker=tk.Frame(self.host,bg='#fa6432');marker.place(x=0,y=100,width=200,height=120)
        self.app.update()
        self.assertTrue(marker.winfo_ismapped())
        # The synthetic window has just moved from off-screen. Tk's update
        # drains events but does not wait for DWM's first visible frame; native
        # PrintWindow may otherwise capture the initial white surface. Wait
        # for exactly one compositor flush before taking the first snapshot.
        # Keep all exact pixel assertions, with no failed-capture retries.
        import ctypes
        flush=ctypes.WinDLL('dwmapi').DwmFlush;flush.restype=ctypes.c_long
        self.assertEqual(flush(),0)
        snap=snapshot_host(self.app,self.host,LIGHT)
        self.assertIsNotNone(snap)
        offset=(110*snap.width+10)*3
        self.assertEqual(snap.rgb[offset:offset+3],bytes((250,100,50)))
        status=ShutdownStatus(self.app,LIGHT,lambda:None);status.begin();self.app.update()
        surface=status.dialog.surface
        self.assertEqual(tuple(surface.backdrop.photo.get(10,110)),(145,58,29))
        self.assertEqual((surface.snapshot.width,surface.snapshot.height),(snap.width,snap.height))
        self.assertEqual(surface.snapshot.rgb[offset:offset+3],bytes((250,100,50)))
        self.assertEqual(surface.overlay.winfo_y(),self.host.winfo_y())
        status._close_requested();self.assertFalse(status.dialog.closed)
        status.finish()

    def test_corner_masks_follow_theme_without_geometry_change(self):
        card=tk.Frame(self.host,bg=LIGHT['panel'],height=160);card.pack(fill='x')
        palette=dict(LIGHT);border=ConnectedBorder(card,palette);self.app.update()
        initial=(card.winfo_width(),card.winfo_height())
        for colors in (DARK,LIGHT,DARK):
            palette.clear();palette.update(colors)
            self.host.configure(bg=colors['bg']);card.configure(bg=colors['panel'])
            border.apply_palette(palette);self.app.update()
            self.assertEqual(initial,(card.winfo_width(),card.winfo_height()))
            masks=border.canvas.find_withtag('ornate-corner-mask')
            self.assertEqual(len(masks),4)
            self.assertEqual({border.canvas.itemcget(i,'fill') for i in masks},{colors['bg']})
            fills=border.canvas.find_withtag('ornate-corner-fill')
            self.assertEqual({border.canvas.itemcget(i,'fill') for i in fills},{colors['panel']})


if __name__=='__main__':unittest.main()
