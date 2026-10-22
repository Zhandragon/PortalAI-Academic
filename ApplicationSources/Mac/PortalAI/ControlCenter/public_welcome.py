"""Public branding only; safe before accounts, history and workers exist."""
from pathlib import Path
import tkinter as tk
from ornate_ui import ConnectedBorder, install_separator
from portal_frontend_v15136 import portal_display_font, display_caps, install_wordmark_label
from elegant_native_ui import ElegantButton


def build_public_welcome(host, root, colors):
    frame=tk.Frame(host,bg=colors['bg']); frame.pack(fill='both',expand=True)
    frame.images=[]; frame.borders=[]
    nav=tk.Frame(frame,bg=colors['panel3']); nav.pack(fill='x',padx=8,pady=4)
    frame.borders.append(ConnectedBorder(nav,colors,radius=11))
    for name in ('Welcome','Controls','Chat','Activity/GPU','Runtime','Installed','Settings','Help'):
        ElegantButton(nav,text=display_caps(name),command=lambda:None,
                      bg=colors['button'],fg=colors['text'],font=(portal_display_font(host),10,'bold'),
                      padx=8,pady=5,bd=0,takefocus=0).pack(side='left',padx=3,pady=5)
    content=tk.Frame(frame,bg=colors['bg']); content.pack(fill='both',expand=True,padx=38,pady=35)
    def image(name,parent,side=None):
        try:
            photo=tk.PhotoImage(master=host,file=str(Path(root)/'ControlCenter/Branding'/name))
            frame.images.append(photo)
            label=tk.Label(parent,image=photo,bg=colors['bg'],bd=0)
            label.pack(**({'side':side} if side else {})); return True
        except (OSError,tk.TclError):return False
    header=tk.Frame(content,bg=colors['bg']);header.pack(fill='x')
    wordmark=tk.Label(header,bg=colors['bg'],bd=0)
    install_wordmark_label(wordmark,root,'welcome',colors);wordmark.pack(side='left')
    image('PortableAI_Header_72.png',header,'right')
    tk.Label(content,text=display_caps('Control Center'),bg=colors['bg'],fg=colors['muted'],
             font=(portal_display_font(host),11,'bold'),anchor='w').pack(fill='x',pady=(14,2))
    tk.Label(content,text='PortalAI distribution designed and implemented by Zhandragon',bg=colors['bg'],fg=colors['accent'],anchor='w').pack(fill='x',pady=(8,2))
    note=tk.Frame(content,bg=colors['panel']);note.pack(fill='x',pady=26)
    frame.borders.append(ConnectedBorder(note,colors,radius=17))
    tk.Label(note,text=display_caps('Welcome to PortalAI'),bg=colors['panel'],fg=colors['text'],font=(portal_display_font(host),13,'bold'),anchor='w').pack(fill='x',padx=16,pady=(14,5))
    install_separator(note,colors,height=8)
    message=tk.Label(note,text='PortalAI Native Chat is the primary frontend. Use the tabs above for lifecycle controls, chat, live activity/GPU telemetry, runtime state, installed capabilities, and generalized maintenance.',bg=colors['panel'],fg=colors['muted'],anchor='w',justify='left',wraplength=900)
    message.pack(fill='x',padx=16,pady=(0,12))
    message.bind('<Configure>',lambda e:message.configure(wraplength=max(100,e.width)))
    image('PortalAI_Emblem_HeroBright_240.png',content) or image('PortableAI_Header_72.png',content)
    return frame
