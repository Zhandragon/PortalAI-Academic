"""Additional Settings tab; main Controls layout is unchanged."""
import json
import tkinter as tk
from tkinter import messagebox
from account_permissions import require_admin, require_user

def add_tab(page):
    from instance_runtime import settings,status,save_settings,DEFAULTS
    root=page.root_dir;skin=page.skin;tab=page.tabs.add('instances','Web and agents')
    section=skin.section(tab,'This installation and service ports')
    current=settings(root);fields={}
    skin.label(section,'Automatic (0) selects unused loopback ports on launch. Saved changes apply after a normal Exit and restart. Each installation keeps its own model and account data.',muted=True).pack(fill='x')
    fields['name']=skin.row(section,'Installation name',lambda row:skin.entry(row,current['name']))
    for key in DEFAULTS:
        fields[key]=skin.row(section,key.title()+' port',lambda row,key=key:skin.entry(row,current['ports'].get(key,0)))
    report=skin.label(section,'Active ports: '+', '.join(k+' '+str(v) for k,v in status(root)['active_ports'].items()),muted=True);report.pack(fill='x')
    def save():
        try:
            require_admin(root,page.account_session)
            save_settings(root,{'name':fields['name'].get(),'ports':{k:int(fields[k].get()) for k in DEFAULTS}})
            report.configure(text='Saved. New ports take effect after a normal Exit and restart.')
        except Exception as exc:messagebox.showerror('PortalAI ports',str(exc),parent=page)
    skin.button(section,'Save ports',save).pack(anchor='w',pady=4)
    section=skin.section(tab,'Agent collaboration')
    skin.label(section,'Use the agents tool in chat to create named agents, assign tasks, read results and exchange messages. One installation shares one model and schedules agent steps. Different installations can run concurrently when RAM/VRAM permits. Pairing codes last until Stop or Exit.',muted=True).pack(fill='x')
    from agent_collaboration import config
    try:saved=config(root)
    except (OSError,ValueError,RuntimeError):saved={}
    enabled=tk.BooleanVar(page,saved.get('enabled',False));tasks=tk.BooleanVar(page,saved.get('accept_tasks',False));mode=tk.StringVar(page,saved.get('max_mode','observe'))
    for title,var in (('Enable incoming peer messages',enabled),('Accept incoming delegated tasks',tasks)):
        skin.check(section,title,var).pack(anchor='w')
    skin.row(section,'Maximum delegated mode',lambda row:skin.combo(row,mode,['observe','full']))
    result=skin.label(section,'Peer messages are untrusted notes. A pairing code grants access only to this collaboration session.',muted=True);result.pack(fill='x')
    def apply(copy=False):
        try:
            require_user(root,page.account_session)
            if mode.get()=='full':require_admin(root,page.account_session)
            from agent_collaboration import configure,broker_for,close_profile
            from profile_context import CapturedProfile
            profile=CapturedProfile(root);configure(root,enabled.get(),tasks.get(),mode.get())
            if not enabled.get():close_profile(root,profile.identity);result.configure(text='Incoming collaboration disabled.');return
            role=page.account_session.role if page.account_session else 'admin'
            broker=broker_for(root,profile,role).start()
            if copy:
                page.clipboard_clear();page.clipboard_append(broker.code())
                result.configure(text='Pairing code copied. Paste into the other PortalAI using agents pair. Treat the code as a session secret.')
            else:result.configure(text='Incoming collaboration enabled for this signed-in account.')
        except Exception as exc:messagebox.showerror('PortalAI collaboration',str(exc),parent=page)
    skin.button(section,'Apply collaboration settings',apply).pack(anchor='w',pady=3)
    skin.button(section,'Copy pairing code',lambda:apply(True)).pack(anchor='w',pady=3)
    section=skin.section(tab,'Portable web tools')
    skin.label(section,'Ask Nice to use web help for page/PDF reading, a live Chromium browser, screenshots and HTTP APIs. Tabs and cookies are private to the current chat tool session and close on Stop/logout. No host browser profile is imported. Login requirements, site restrictions and TLS checks still apply.',muted=True).pack(fill='x')
