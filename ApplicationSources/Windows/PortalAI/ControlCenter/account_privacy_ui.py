"""Small privacy controls; explicit descriptions match actual storage behavior."""
import tkinter as tk

def privacy_fields(dialog,password,confirmation,*,administrator=False,encrypted=True,password_required=True):
    encryption=tk.BooleanVar(dialog.win,value=encrypted)
    required=tk.BooleanVar(dialog.win,value=password_required)
    text=tk.StringVar(dialog.win)
    role={'administrator':administrator}
    for label,var in (('Encrypt saved account data',encryption),('Require a password',required)):
        tk.Checkbutton(dialog.body,text=label,variable=var,bg=dialog.bg,fg=dialog.fg,
                       selectcolor=dialog.colors.get('panel2',dialog.bg)).pack(anchor='w',pady=3)
    widget=tk.Label(dialog.body,textvariable=text,bg=dialog.bg,fg=dialog.fg,justify='left',anchor='w',wraplength=590)
    widget.pack(fill='x',pady=(4,10))
    widget.bind('<Configure>',lambda e:widget.configure(wraplength=max(180,e.width-8)))
    def refresh(*_):
        if not required.get():password.set('');confirmation.set('')
        for variable in (password,confirmation):
            widget=getattr(variable,'_entry_widget',None)
            if widget is not None:widget.configure(state='normal' if required.get() else 'disabled')
        if encryption.get() and required.get():message='Saved files are encrypted while this account is closed. The password unlocks them.'
        elif encryption.get():message='Files use encryption, but the unlock key is stored on this drive. Anyone with the drive can unlock them.'
        elif required.get():message='Files and saved service credentials remain readable on the SSD. The password locks only the PortalAI interface.'
        else:message='Files and saved service credentials remain readable. Anyone using this installation can open this workspace.'
        if role['administrator'] and not required.get():message+=' Anyone can use this administrator account and access the other accounts.'
        text.set(message)
    dialog.watch(encryption,refresh);dialog.watch(required,refresh);refresh()
    def selected():return {'encrypted':bool(encryption.get()),'password_required':bool(required.get())}
    def set_values(encrypted,password_required):encryption.set(encrypted);required.set(password_required)
    selected.set_values=set_values
    def set_administrator(value):role['administrator']=bool(value);refresh()
    selected.set_administrator=set_administrator
    return selected


def show_privacy(gate,*,lock_application,exit_application):
    from account_ui import _Dialog,AccountUIError
    dialog=_Dialog(gate.app,'Privacy and sign-in',gate.colors,jobs=gate.controller.jobs)
    if gate.session.role!='admin':
        dialog.label('An administrator can change storage and password requirements for each account.');return dialog
    rows=[r for r in gate.controller.backend.list_users(gate.session) if r['role']!='guest' and not r['pending']]
    labels={r['username']:r for r in rows};chosen=tk.StringVar(dialog.win,value=gate.session.username)
    dialog.label('Account or shared workspace');dialog.picker(chosen,list(labels))
    admin=dialog.entry('Current administrator password (blank if passwordless)',secret=True)
    password=dialog.entry('Password for the new settings',secret=True)
    confirmation=dialog.entry('Confirm new password',secret=True)
    row=labels[chosen.get()]
    privacy=privacy_fields(dialog,password,confirmation,administrator=row['role']=='admin',encrypted=row.get('encrypted',True),password_required=row.get('password_required',True))
    shared=tk.BooleanVar(dialog.win,value=row.get('anonymous',False))
    tk.Checkbutton(dialog.body,text='Use this as the account-free shared workspace at startup',variable=shared,
                   bg=dialog.bg,fg=dialog.fg,selectcolor=dialog.colors.get('panel2',dialog.bg)).pack(anchor='w',pady=4)
    def selection(*_):
        current=labels[chosen.get()];privacy.set_administrator(current['role']=='admin');privacy.set_values(current.get('encrypted',True),current.get('password_required',True));shared.set(current.get('anonymous',False))
    def sharing(*_):
        if shared.get():privacy.set_values(False,False)
    dialog.watch(chosen,selection);dialog.watch(shared,sharing);sharing()
    dialog.label('Applying saves and closes PortalAI first. The profile and its historical recovery files are converted and verified before replacement. Previous profile files are retained within the new profile. At least 80 GiB must remain free. External backups keep their existing protection.')
    dialog.label('Choosing account-free mode makes the selected profile shared and unencrypted. If it is an administrator, anyone can use its administrator privileges.')
    state={'started':False}
    previous=gate.on_shutdown_status
    def apply():
        current=labels[chosen.get()];options=privacy();anonymous=shared.get()
        if anonymous and (options['encrypted'] or options['password_required']):
            dialog.status.set('Account-free mode requires both encryption and password protection to be off.');return
        secret=password.get();repeat=confirmation.get();admin_secret=admin.get();name=gate.session.username
        if options['password_required'] and (not secret or secret!=repeat):
            dialog.status.set('Enter the password for the new settings and a matching confirmation.');return
        if not options['password_required'] and (secret or repeat):
            dialog.status.set('Clear the new password fields for passwordless mode.');return
        def authenticate():
            actor=gate.controller.backend.login(name,admin_secret)
            try:
                if actor.role!='admin':raise AccountUIError('An administrator is required.')
                if options['password_required']:
                    from local_accounts import _password
                    _password(secret)
                return True
            finally:gate.controller.backend.logout(actor)
        def commit(_):
            try:lock_application();dialog.show_locked()
            except Exception:
                dialog.status.set('Writer shutdown could not start. Close PortalAI safely before retrying.');return
            state['started']=True;gate.on_shutdown_status=lambda message:dialog.progress.publish({'message':message})
            def work():
                try:
                    gate.close()
                    from account_privacy import PrivacyChange
                    from profile_shutdown import verify_stopped
                    converter=PrivacyChange(gate.root,writer_check=lambda:verify_stopped(gate.root),on_progress=dialog.progress.publish)
                    return converter.apply(name,admin_secret,current['user_id'],new_password=secret,anonymous=anonymous,start_without_account=anonymous,**options)
                except Exception as exc:
                    raise AccountUIError('Privacy conversion did not finish. Close and reopen PortalAI; use Recover privacy change if offered. Existing data is retained until the replacement verifies.') from exc
            def completed(receipt):
                if receipt.get('verified') is not True:raise RuntimeError('Privacy change did not verify')
                gate.on_shutdown_status=previous;dialog.close();exit_application()
            dialog.operation_label='Saving and converting account storage…'
            dialog.run(work,completed,lifecycle=True)
        dialog.run(authenticate,commit)
    dialog.button('Apply changes and close PortalAI',apply)
    def leave():
        if dialog.busy:return
        gate.on_shutdown_status=previous;dialog.close()
        if state['started']:exit_application()
    dialog.set_close_handler(leave);dialog.button('Close',leave);dialog.status_line()
    return dialog


def recover_privacy(dialog,controller):
    from account_ui import _Dialog
    child=_Dialog(dialog.win,'Recover privacy change',dialog.colors,jobs=controller.jobs)
    child.label('Roll back an uncommitted conversion with the original administrator password. Finish a committed conversion using the administrator password under the new settings. Leave it blank if that administrator is passwordless.')
    username=child.entry('Administrator username');password=child.entry('Administrator password',secret=True)
    action=tk.StringVar(child.win,value='finish');child.picker(action,['finish','rollback'])
    def apply():
        name,secret,choice=username.get(),password.get(),action.get()
        def work():
            from account_privacy import PrivacyChange
            from profile_shutdown import verify_stopped
            return PrivacyChange(controller.root,writer_check=lambda:verify_stopped(controller.root),on_progress=child.progress.publish).recover(name,secret,action=choice)
        child.run(work,lambda _:child.status.set('Recovery verified. Close and reopen PortalAI.'))
    child.button('Recover selected privacy change',apply);child.status_line()
    return child
