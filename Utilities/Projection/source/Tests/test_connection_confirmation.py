"""Actual internal confirmation, exact typing and theme cleanup."""
import tkinter as tk
import unittest
from test_projection_ui import WindowTests

class InternalConfirmationTests(unittest.TestCase):
    setUp=WindowTests.setUp
    tearDown=WindowTests.tearDown
    def check_confirmation(self,mode,text,accepted):
        self.app.deiconify();self.w.skin.change('mode',mode);self.app.update()
        before=len(self.w.skin.borders);errors=[]
        def visit(widget):
            yield widget
            for child in widget.winfo_children():yield from visit(child)
        def operate():
            try:
                modal=self.w.skin.confirmation
                self.assertIsNotNone(modal);self.assertEqual(modal.winfo_toplevel(),self.app)
                self.assertEqual(modal.cget('bg'),self.w.skin.palette['bg'])
                widgets=list(visit(modal))
                entry=next(w for w in widgets if w.winfo_class()=='TEntry')
                button=next(w for w in widgets if w.winfo_class()=='TButton' and w.cget('text')=='Delete selected')
                self.assertEqual(str(button.cget('state')),'disabled')
                self.app.setvar(entry.cget('textvariable'),text);self.app.update_idletasks()
                self.assertEqual(str(button.cget('state')),'normal' if accepted else 'disabled')
                self.w.skin.menu((20,20));self.assertIsNone(self.w.skin.popup)
                if accepted:button.invoke()
                else:next(w for w in widgets if w.winfo_class()=='TButton' and w.cget('text')=='Cancel').invoke()
            except BaseException as exc:
                errors.append(exc)
                if self.w.skin.confirmation is not None:self.w.skin.confirmation.destroy()
        self.app.tk.call('frame','.nativefocus')
        self.app.tk.call('pack','.nativefocus')
        self.app.tk.call('focus','-force','.nativefocus')
        self.app.update()
        self.app.after(60,operate)
        self.assertEqual(self.w.confirm_delete('a'*32),accepted)
        self.app.tk.call('destroy','.nativefocus')
        if errors:raise errors[0]
        self.assertIsNone(self.w.skin.confirmation);self.assertEqual(len(self.w.skin.borders),before)
        self.w.skin.change('mode','dark' if mode=='light' else 'light');self.app.update()
    def test_exact_confirmation_in_both_themes(self):
        for mode in ('light','dark'):
            self.check_confirmation(mode,'confirm',False)
            self.check_confirmation(mode,'CONFIRM',True)
