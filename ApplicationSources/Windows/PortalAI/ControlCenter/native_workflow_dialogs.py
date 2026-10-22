"""Native forms for the few remaining blocking OS dialogs, scoped to admission."""
import tkinter as tk
from tkinter import filedialog,messagebox
import uuid
from native_workflow import LOCAL_RECOVERY

_installed=False


def owner(options):
    parent=options.get('parent') or tk._default_root
    if parent is None:return None
    controller=getattr(parent.winfo_toplevel(),'_portalai_native_workflow',None)
    return controller if controller is not None and controller.active is not None else None


def install():
    global _installed
    if _installed:return
    _installed=True
    old_save=filedialog.asksaveasfilename;old_ask=messagebox.askyesno
    def save(**options):
        c=owner(options)
        if c is None:return old_save(**options)
        if options.get('title','').startswith('Export encrypted profiles'):
            c.notice(LOCAL_RECOVERY);return ''
        return c.files.export_path(options.get('initialfile','PortalAI-export.zip'))
    def ask(title=None,message=None,**options):
        c=owner(options)
        if c is None:return old_ask(title,message,**options)
        answer=tk.IntVar(c.app,value=-1);marker=uuid.uuid4().hex
        def decide(value):
            if c.virtual is not None and c.virtual['identity']==marker:c.virtual=None
            answer.set(1 if value else 0)
        c.virtual={'identity':marker,'nodes':[
            {'id':'confirm_title','kind':'heading','label':str(title or 'Confirm')[:1000],'enabled':False},
            {'id':'confirm_message','kind':'note','label':str(message or '')[:1000],'enabled':False},
            {'id':'confirm_yes','kind':'button','label':'Yes','enabled':True,'action':'confirm_yes'},
            {'id':'confirm_no','kind':'button','label':'Cancel','enabled':True,'action':'confirm_no'}],
            'actions':{'confirm_yes':lambda:decide(True),'confirm_no':lambda:decide(False)}}
        # Admission is acknowledged once this real confirmation is available.
        # The original GUI callback continues only after a separate human choice.
        original=c.active
        # The confirmation is a new human action with its own admission
        # deadline. The original callback may not outlive its account binding.
        def watch():
            if answer.get()!=-1:return
            binding,account=c.current()
            if original.payload['binding']!={'view':binding[0],'epoch':binding[1]} or account['state']!='ready':decide(False)
            else:c.app.after(100,watch)
        c.app.after(100,watch);c.app.wait_variable(answer)
        return answer.get()==1
    filedialog.asksaveasfilename=save;messagebox.askyesno=ask
