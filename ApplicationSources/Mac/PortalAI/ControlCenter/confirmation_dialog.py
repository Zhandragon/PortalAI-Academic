"""Explicit yes/no choices inside PortalAI's existing themed modal surface."""
import tkinter as tk
from tkinter import messagebox


def ask_yes_no(title, message, *, parent, colors, validate=None,
               yes_label='Yes — move to Deleted', no_label='No — keep in working list'):
    app=parent.winfo_toplevel()
    controller=getattr(app,'_portalai_native_workflow',None)
    if controller is not None and controller.active is not None:
        # Keep the admitted Home Assistant confirmation and its account binding.
        return messagebox.askyesno(title,message,parent=parent)
    from account_ui import _Dialog
    dialog=_Dialog(parent,title,colors)
    accepted=False;failure=None;watch_timer=None

    def choose(value):
        nonlocal accepted,failure
        if dialog.closed:return
        if value:
            try:
                if not parent.winfo_exists():value=False
                elif validate is not None:validate()
            except Exception as error:
                failure=error;value=False
        accepted=bool(value)
        dialog.close()

    def watch():
        nonlocal watch_timer
        watch_timer=None
        if dialog.closed:return
        try:
            if not parent.winfo_exists():choose(False);return
            if validate is not None:validate()
        except Exception:
            choose(False);return
        watch_timer=app.after(100,watch)

    dialog.set_close_handler(lambda:choose(False))
    for paragraph in message.split('\n\n'):dialog.label(paragraph)
    cancel=dialog.button(no_label,lambda:choose(False))
    dialog.button(yes_label,lambda:choose(True))
    def fit_content(_event=None):
        height=min(680,max(280,dialog.body.winfo_reqheight()+dialog.surface.head.winfo_reqheight()+28))
        if getattr(dialog.surface,'preferred_height',None)!=height:
            dialog.surface.preferred_height=height;dialog.surface.layout()
    dialog.body.bind('<Configure>',fit_content,add='+')
    dialog.win.update_idletasks();fit_content()
    cancel.focus_set()
    watch_timer=app.after(100,watch)
    try:
        app.wait_window(dialog.win)
    except tk.TclError:
        accepted=False
    finally:
        if watch_timer is not None:
            try:app.after_cancel(watch_timer)
            except tk.TclError:pass
        if not dialog.closed:
            try:dialog.close()
            except tk.TclError:pass
    if failure is not None:raise failure
    return accepted
