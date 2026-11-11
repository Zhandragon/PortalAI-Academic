"""Optional, repeatable launcher tour. No downloads, model changes or tool runs."""
from pathlib import Path
import tkinter as tk

STEPS = (
    ('welcome', 'Welcome', 'PortalAI brings chat, scientific tools and media workflows into one app. The tabs follow the tasks you will use most. This tour only explains and navigates; it does not start models or run tools.'),
    ('controls', 'Start and stop', 'Controls holds Startup, system tests and Stop. Start the components you need when you are ready. Closing to the tray and quitting completely are separate choices; Help explains the window controls.'),
    ('chat', 'Ask in ordinary language', 'Use Chat for questions, files and supported science or media requests. Describe your goal rather than memorizing package names. Review generated results and any requested confirmations. The microphone and handsfree controls are optional.'),
    ('runtime', 'Models', 'Models shows the services and models available to this installation. A selected installer bundle is a download recommendation, not a promise that every model will fit your RAM or GPU. Missing optional weights can be added later.'),
    ('installed', 'Packages', 'Packages shows the installed assets. Scientific disciplines share tools; you do not need a separate large chat model for each discipline. The installer survey offers Lightweight or Full coverage for the interests you select.'),
    ('settings', 'Choose your preferences', 'Settings holds chat, voice, media and model preferences. Full-edition standard and alternate model policies remain explicit choices. Academic retains its standard-model policy. Taking this tour changes none of them.'),
    ('persistence', 'Optional ongoing work', 'Persistence manages missions and schedules. Use it when you want ongoing work; ordinary chat does not require it. Read the options before enabling a mission or schedule.'),
    ('help', 'Find help and revisit', 'Help explains workflows, component names and limitations. Take app tour here repeats this walkthrough. Use Back to revisit, or Skip tour / Escape to leave at any time. You can now return to where you started.'),
)

class AppTour:
    def __init__(self, app, root, colors, navigate, selected, gate=None):
        self.app=app; self.colors=colors; self.navigate=navigate; self.selected=selected; self.gate=gate
        self.marker=Path(root)/'Maintenance'/'app-tour-v1.seen'
        self.dialog=None; self.index=0; self.original='welcome'; self.timer=None

    def available(self):
        native=getattr(self.app,'_portalai_native_workflow',None)
        return (not (self.gate is not None and self.gate.locked)
                and not (native is not None and native.active is not None)
                and not any(not d.closed and d is not self.dialog for d in getattr(self.app,'_portalai_account_dialogs',())))

    def remember(self):
        try:
            self.marker.parent.mkdir(parents=True,exist_ok=True)
            self.marker.write_text('Tour offered. Repeat from Help.\n',encoding='utf-8')
        except OSError:
            pass  # Read-only portable folders still allow the tour and skipping.

    def offer_when_ready(self):
        self.timer=None
        if self.marker.exists():return
        if not self.available():
            self.timer=self.app.after(1500,self.offer_when_ready);return
        self.original=self.selected()
        self._open('Welcome to PortalAI')
        self.dialog.label('Would you like to take a tour of the app?',bold=True)
        self.dialog.label('A short walkthrough explains the tabs. You can skip it now and repeat it from Help whenever you like.')
        self._buttons([('Skip tour',self.close),('Take tour',self.start)])

    def _open(self,title):
        if self.dialog is not None and not self.dialog.closed:self.dialog.close()
        from account_ui import _Dialog
        self.dialog=_Dialog(self.app,title,self.colors())
        self.dialog.set_close_handler(self.close)
        self.dialog.surface.preferred_height=360
        self.dialog.surface.layout()

    def _buttons(self, actions):
        row=tk.Frame(self.dialog.body,bg=self.dialog.bg);row.pack(fill='x',pady=(12,0))
        for text,callback in actions:
            b=self.dialog.button(text,callback)
            b.pack_forget();b.pack(in_=row,side='left',padx=(0,8),pady=4)

    def start(self):
        if not self.available():return
        if self.dialog is None or self.dialog.closed:self.original=self.selected()
        self.remember();self.index=0;self.show()

    def show(self):
        if self.dialog is not None:
            if not self.dialog.closed:self.dialog.close()
            self.dialog=None
        page,title,body=STEPS[self.index]
        self.navigate(page)
        self._open('App tour · '+str(self.index+1)+' of '+str(len(STEPS)))
        self.dialog.label(title,bold=True);self.dialog.label(body)
        buttons=[]
        if self.index:buttons.append(('‹ Back',lambda:self.move(-1)))
        buttons += [('Skip tour',self.close),('Finish tour' if self.index==len(STEPS)-1 else 'Got it · Next',self.close if self.index==len(STEPS)-1 else lambda:self.move(1))]
        self._buttons(buttons)

    def move(self,delta):
        self.index=max(0,min(len(STEPS)-1,self.index+delta));self.show()

    def close(self):
        self.remember()
        if self.dialog is not None:
            if not self.dialog.closed:self.dialog.close()
            self.dialog=None
        self.navigate(self.original)

def install(app,root,colors,navigate,selected,welcome,help_page,gate=None):
    from elegant_native_ui import ElegantButton
    tour=AppTour(app,root,colors,navigate,selected,gate)
    for parent in (welcome,help_page):
        p=colors();button=ElegantButton(parent,text='Take app tour',command=tour.start,
            bg=p['button'],fg=p['text'],activebackground=p['button_hover'],relief='flat',bd=0,padx=12,pady=7)
        children=list(parent.pack_slaves())
        button.pack(anchor='e',padx=16,pady=8,**({'before':children[0]} if children else {}))
    app._portalai_app_tour=tour
    tour.timer=app.after(1200,tour.offer_when_ready)
    return tour
