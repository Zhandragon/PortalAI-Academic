"""Main Accounts page reusing authenticated account actions and writer jobs."""
import queue
import tkinter as tk
from account_ui import _Dialog, ProgressMailbox, paint_account_button
from settings_style import SettingsSkin
from ui_extensions import ResponsiveGrid
from ornate_ui import ConnectedBorder


class AccountIdentity(tk.Frame):
    def __init__(self,parent,username,role,colors):
        super().__init__(parent,bd=0)
        self.border=ConnectedBorder(self,colors,radius=11,filigree=False)
        self.border.simple=True;self.border.simple_radius=11
        self.caption=tk.Label(self,text='CURRENT ACCOUNT',anchor='w',font=('Segoe UI',8,'bold'))
        self.caption.pack(fill='x',padx=13,pady=(9,2))
        self.value=tk.Label(self,anchor='w',font=('Segoe UI',11,'bold'))
        self.value.pack(fill='x',padx=13,pady=(0,9))
        self.value.bind('<Configure>',lambda e:self.value.configure(wraplength=max(80,e.width-5)))
        self.set_account(username,role);self.apply_palette(colors)
    def set_account(self,username,role):self.value.configure(text=f'{username}  ·  {"Administrator" if role=="admin" else role.title()}')
    def apply_palette(self,colors):
        bg=colors.get('panel2',colors['panel']);self.configure(bg=bg)
        self.caption.configure(bg=bg,fg=colors.get('muted',colors['text']))
        self.value.configure(bg=bg,fg=colors.get('accent',colors['text']))
        self.border.apply_palette(colors)


class AccountsPage(_Dialog):
    # Only the management overview is a page. Password/enrollment/reset prompts
    # retain their existing modal surfaces, authentication and secret cleanup.
    def __init__(self,parent,colors,*,jobs):
        self.parent=parent.winfo_toplevel();self.jobs=jobs;self.colors=colors
        self.win=tk.Frame(parent,bg=colors['bg']);self.win.pack(fill='both',expand=True)
        self.skin=SettingsSkin(self.win,colors);self.skin.remember(self.win,bg='bg')
        self.body=self.skin.section(self.win,'Accounts')
        self.actions=None;self.buttons=[];self.secrets=[];self.closed=False;self.busy=False
        self.progress=ProgressMailbox();self.results=queue.Queue();self.status=tk.StringVar(self.win)
        self._poll_after=self.win.after(60,self._poll)
        self.win.bind('<Destroy>',self._destroyed,add='+')

    def label(self,text,*,bold=False):
        widget=self.skin.label(self.body,text,heading=bold);widget.pack(fill='x',pady=(0,8));return widget

    def button(self,text,command,*,enabled=True,tone='normal'):
        if self.actions is None:
            self.actions=ResponsiveGrid(self.body,bg=self.colors['panel'],min_cell_width=275,max_columns=3,hgap=8,vgap=8)
            self.skin.remember(self.actions,bg='panel');self.actions.pack(fill='x',pady=8)
        button=self.skin.button(self.actions,text,command,state='normal' if enabled else 'disabled')
        button._account_tone=tone;paint_account_button(button,self.colors)
        self.actions.add(button);self.buttons.append((button,enabled));return button

    def status_line(self):self.skin.label(self.body,textvariable=self.status).pack(fill='x',pady=(10,0))
    def apply_palette(self,colors):
        self.colors=colors;self.skin.apply_palette(colors)
        for button,_ in self.buttons:paint_account_button(button,colors)
        if hasattr(self,'identity'):self.identity.apply_palette(colors)
    def show_locked(self):pass  # The launcher has already installed its opaque lock.
    def close(self):pass  # Main navigation remains mounted behind child/reset sheets.
    def _destroyed(self,event):
        if event.widget is not self.win:return
        self.closed=True
        if self._poll_after is not None:
            self.win.after_cancel(self._poll_after);self._poll_after=None
