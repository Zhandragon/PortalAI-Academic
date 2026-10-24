"""Direct mission and schedule pages; existing authorization and runners apply."""
import tkinter as tk
from account_permissions import can_admin
from settings_style import SettingsSkin
from ui_extensions import ResponsiveFlow
from portal_frontend_v15136 import portal_display_font
from ornate_ui import ConnectedBorder


class PersistencePage(tk.Frame):
    def __init__(self,parent,root,colors,*,session=None,jobs=None):
        super().__init__(parent,bg=colors['panel'])
        self.root_dir=root;self.session=session;self.jobs=jobs;self.pages={};self.selected=None
        self.skin=skin=SettingsSkin(self,colors);skin.remember(self,bg='panel')
        skin.borders.append(ConnectedBorder(self,skin.colors,radius=16))
        content=skin.frame(self);content.pack(fill='both',expand=True,padx=12,pady=10)
        self.buttons={}
        bar=ResponsiveFlow(content,bg=colors['panel']);skin.remember(bar,bg='panel');bar.pack(fill='x',pady=(0,6))
        for key,title in (('missions','Missions'),('schedules','Schedules')):
            self.buttons[key]=bar.add(skin.button(bar,title,lambda key=key:self.select(key)))
            self.buttons[key].configure(font=(portal_display_font(bar),9,'bold'))
        self.host=skin.frame(content);self.host.pack(fill='both',expand=True)
        if not can_admin(root,session):
            skin.label(self.host,'Sign in as an administrator to manage persistent missions and schedules.',muted=True).pack(fill='x',padx=18,pady=20)
            for button in self.buttons.values():button.configure(state='disabled')

    def select(self,key='missions'):
        if not can_admin(self.root_dir,self.session):return
        native=getattr(self.winfo_toplevel(),'_portalai_native_workflow',None)
        remote=native is not None and native.active is not None
        if key not in self.pages:
            if key=='missions':
                from mission_settings import show_mission_settings
                page=show_mission_settings(self.host,self.root_dir,self.skin.colors,session=self.session,jobs=self.jobs,embedded=True,framed=False)
            elif key=='schedules':
                from schedule_settings import show_schedule_settings
                page=show_schedule_settings(self.host,self.root_dir,self.skin.colors,session=self.session,embedded=True,framed=False)
            else:raise ValueError('Unknown Persistence page')
            self.pages[key]=page
            if remote:page.pack_forget()
        if remote:
            native.overrides[native.active.payload['viewer']]=self.pages[key]
            self.pages[key].refresh_records()
            return
        for page in self.pages.values():page.pack_forget()
        self.pages[key].pack(fill='both',expand=True);self.pages[key].refresh_records()
        self.selected=key;self.apply_palette(self.skin.colors)

    def apply_palette(self,colors):
        self.skin.apply_palette(colors)
        for key,button in self.buttons.items():button.configure(bg=colors['gold_mid'] if key==self.selected else colors['button'])
        for page in self.pages.values():page.apply_palette(colors)
