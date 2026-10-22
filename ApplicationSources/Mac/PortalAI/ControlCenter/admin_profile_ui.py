"""Administrator inspection of sealed profiles without switching active users."""
import tkinter as tk
from tkinter import ttk, filedialog
from tkinter.scrolledtext import ScrolledText


def show_admin_profiles(parent, controller, session, colors):
    from account_ui import _Dialog
    from admin_profile_access import inspect_profile, preview_text, export_profile
    controller._admin(session)
    rows=[row for row in controller.backend.list_users(session) if row['user_id'] != session.user_id]
    dialog=_Dialog(parent,'Inspect sealed profiles',colors,jobs=controller.jobs)
    dialog.label('Administrator access opens verified encrypted data for review. The selected account stays sealed. Use the main account dialog to export your active profile.')
    labels={row['username']:row['user_id'] for row in rows}
    selected=tk.StringVar(master=dialog.win,value=next(iter(labels),''))
    dialog.picker(selected,list(labels))
    file_list=tk.Listbox(dialog.body,height=9,bg=dialog.bg,fg=dialog.fg,exportselection=False)
    file_list.pack(fill='both',expand=True,pady=6)
    preview=ScrolledText(dialog.body,height=10,wrap='word',bg=dialog.bg,fg=dialog.fg)
    preview.pack(fill='both',expand=True,pady=6);preview.configure(state='disabled')
    state={'uid':None,'files':[]}
    def inspect():
        uid=labels.get(selected.get())
        if not uid:return
        def display(result):
            state.update(uid=uid,files=[row['path'] for row in result['files']])
            file_list.delete(0,'end')
            for path in state['files']:file_list.insert('end',path)
            preview.configure(state='normal');preview.delete('1.0','end');preview.configure(state='disabled')
            dialog.status.set('Verified sealed profile: '+str(len(state['files']))+' files.')
        dialog.run(lambda:inspect_profile(controller.backend,session,uid),display)
    def view():
        choices=file_list.curselection()
        if not choices or state['uid'] != labels.get(selected.get()):
            dialog.status.set('Inspect this profile and select a text file first.');return
        path=state['files'][choices[0]];uid=state['uid']
        def display(result):
            text=result.get('text','') if isinstance(result,dict) else str(result)
            preview.configure(state='normal');preview.delete('1.0','end');preview.insert('1.0',text);preview.configure(state='disabled')
            dialog.status.set('Verified text preview (bounded to 64 KiB).')
        dialog.run(lambda:preview_text(controller.backend,session,uid,path,max_bytes=65536),display)
    def export(kind):
        uid=labels.get(selected.get())
        if not uid:return
        destination=filedialog.asksaveasfilename(parent=dialog.win,title='Export selected profile (unencrypted copy)',
                    defaultextension='.zip',initialfile='PortalAI-'+kind+'.zip',filetypes=[('ZIP archive','*.zip')])
        if destination:
            dialog.run(lambda:export_profile(controller.backend,session,uid,kind,destination),
                       lambda result:dialog.status.set('Verified unencrypted export: '+result['path']))
    dialog.button('Inspect selected sealed profile',inspect,enabled=bool(labels))
    dialog.button('Preview selected text file',view,enabled=bool(labels))
    dialog.button('Export selected profile history…',lambda:export('history'),enabled=bool(labels))
    dialog.button('Export selected profile outputs…',lambda:export('outputs'),enabled=bool(labels))
    dialog.button('Close',dialog.close)
    dialog.status_line()
    return dialog
