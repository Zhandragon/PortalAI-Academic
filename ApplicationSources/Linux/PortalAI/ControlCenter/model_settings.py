"""Compatibility dialog; the main GUI now exposes a Settings page."""
import tkinter as tk
from settings_page import SettingsPage
def show_model_settings(parent,root,colors,*,session=None):
    win=tk.Toplevel(parent);win.title('PortalAI · Settings');win.geometry('780x800');win.transient(parent)
    canvas=tk.Canvas(win,highlightthickness=0);bar=tk.Scrollbar(win,command=canvas.yview)
    canvas.configure(yscrollcommand=bar.set);bar.pack(side='right',fill='y');canvas.pack(fill='both',expand=True)
    page=SettingsPage(canvas,root,colors,session=session);item=canvas.create_window(0,0,window=page,anchor='nw')
    from page_scroll import bind_page_scroll
    bind_page_scroll(canvas,page,item)
    return win
