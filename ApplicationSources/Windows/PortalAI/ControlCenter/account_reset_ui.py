"""Explicit staged Start fresh UI. No reset executes at import or startup."""
import hashlib
import json
import os
from pathlib import Path
import zipfile


class ResetAdapter:
    def __init__(self, gate):
        self.gate = gate
        self.root = gate.root
        self.accounts = gate.controller.backend
        from profile_reset import ResetCoordinator
        self.coordinator = ResetCoordinator(self.root, self.accounts)
        self.admin = None
        self.plan = None
        self.exported = False
        self._lease = None

    def release(self):
        if self.admin is not None:
            self.accounts.logout(self.admin)
            self.admin = None
        if self._lease is not None:
            self._lease.__exit__(None,None,None)
            self._lease = None

    def writer_check(self):
        if not self.gate.locked or self.gate.runtime.session is not None:
            raise RuntimeError('Close and seal the active account before resetting')
        for group in (self.gate.gui_jobs, self.gate.controller.jobs):
            if group is not None and group.wait(0).get('stopped') is not True:
                raise RuntimeError('GUI/account writers are still running')
        if self.gate.chat is not None and self.gate.chat.wait_for_writers(0).get('stopped') is not True:
            raise RuntimeError('Chat writers are still running')
        from profile_shutdown import verify_stopped
        receipt = verify_stopped(self.root)
        if not isinstance(receipt, dict) or receipt.get('stopped') is not True:
            raise RuntimeError('Owned process quiescence did not verify')
        return {'quiescent': True}

    def prepare(self, current_password):
        session = self.gate.session
        # Authenticate before stopping so a mistyped password cannot seal a
        # session, and authenticate again after close revoked old handles.
        checked = self.accounts.login(session.username, current_password)
        try:
            if checked.role != 'admin' or checked.user_id != session.user_id:
                raise PermissionError('Current administrator authentication is required')
        finally:
            self.accounts.logout(checked)
        self.gate.close(session)
        self._lease = self.coordinator.hold_session()
        self._lease.__enter__()
        self.admin = self.accounts.login(session.username, current_password)
        self.plan = self.coordinator.plan(self.admin, writer_check=self.writer_check)
        return self.plan

    def export(self, destination):
        if self.plan is None:
            raise RuntimeError('Review a sealed reset plan first')
        self.writer_check()
        self.coordinator._reviewed(self.admin, self.plan, self.writer_check)
        receipt = export_reset_plan(self.root, self.plan, destination)
        self.exported = receipt.get('verified') is True
        return receipt

    def execute(self, current_password, typed, username, password, confirmation, *, decline_export=False):
        if not password or password != confirmation:
            raise ValueError('Enter a new administrator password and matching confirmation')
        if not self.exported and decline_export is not True:
            raise ValueError('Export the old profiles or explicitly choose to proceed without another export')
        if self.admin is None or self.plan is None:
            raise RuntimeError('Review the sealed reset plan first')
        token = self.coordinator.request_confirmation(self.admin, self.plan,
                 admin_password=current_password, typed_confirmation=typed, writer_check=self.writer_check)
        result = self.coordinator.execute(self.admin, self.plan, token,
                 admin_password=current_password, new_username=username, new_password=password,
                 writer_check=self.writer_check)
        if result.get('reset') is True:
            self.release()
        return result


def export_reset_plan(root, plan, destination):
    """Copy the exact reviewed encrypted files, with a fully checked ZIP manifest."""
    from profile_paths import _contained
    from runtime_policy import require_space
    from profile_workspace import digest
    root=Path(root).resolve(); destination=Path(destination).absolute()
    if destination.exists() or destination.resolve().is_relative_to(root):
        raise ValueError('Choose a new full-profile backup outside this PortalAI root, on another drive or folder')
    rows=plan['files']; needed=sum(row['bytes'] for row in rows)+len(rows)*2048+8*1024**2
    if destination.parent.stat().st_dev == root.stat().st_dev:
        require_space(root,needed,for_outputs=True)
    else:
        import shutil
        if shutil.disk_usage(destination.parent).free < needed+64*1024**2:
            raise RuntimeError('Backup destination has insufficient space')
    identity=None
    try:
        with destination.open('xb') as output:
            info=os.fstat(output.fileno()); identity=(info.st_dev,info.st_ino)
            with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
                for row in rows:
                    source=root/row['path']; _contained(root,source)
                    if not any(source.is_relative_to(root/base) for base in ('Private/Accounts','Private/Users')):
                        raise ValueError('Backup plan contains an unexpected source')
                    if source.stat().st_nlink != 1 or digest(source) != row['sha256']:
                        raise RuntimeError('Private backup source changed')
                    archive.write(source,row['path'])
                archive.writestr('PortalAI-private-backup-manifest.json',json.dumps(plan,ensure_ascii=True))
            output.flush(); os.fsync(output.fileno())
        with zipfile.ZipFile(destination) as archive:
            if set(archive.namelist()) != {r['path'] for r in rows}|{'PortalAI-private-backup-manifest.json'}:
                raise RuntimeError('Backup entries differ from reviewed inventory')
            for row in rows:
                h=hashlib.sha256(); size=0
                with archive.open(row['path']) as src:
                    while block:=src.read(1024**2):h.update(block);size+=len(block)
                if size!=row['bytes'] or h.hexdigest()!=row['sha256']:
                    raise RuntimeError('Private backup did not verify')
        return {'verified':True,'path':str(destination),'files':len(rows)}
    except BaseException:
        if identity is not None and destination.exists():
            info=destination.lstat()
            if (info.st_dev,info.st_ino)==identity:destination.unlink()
        raise


def show_start_fresh(parent, gate, colors, *, lock_application, exit_application):
    from account_ui import _Dialog
    import tkinter as tk
    from tkinter import filedialog
    from tkinter.scrolledtext import ScrolledText
    adapter=ResetAdapter(gate)
    dialog=_Dialog(parent,'Start fresh',colors)
    dialog.label('This resets every local account, chat, memory and output after a verified inventory. Models, runtimes and source files remain installed. Separate backups and SSD blocks may retain earlier data.')
    dialog.label('The review step stops jobs, seals profiles and locks this GUI. Closing this dialog afterward exits PortalAI; it never returns to an unsealed chat.')
    admin_password=dialog.entry('Current administrator password',secret=True)
    state={'prepared':False}
    def leave():
        if dialog.busy:return
        if gate.locked and gate.runtime.session is not None:
            dialog.run(lambda:gate.close(),lambda _: (adapter.release(),dialog.close(),exit_application()),lifecycle=True)
            return
        adapter.release()
        dialog.close()
        if gate.locked:exit_application()
    dialog.set_close_handler(leave)
    def reviewed(plan):
        state['prepared']=True
        # Only the ordinary post-seal recovery form is public to the native
        # renderer. Its reset still requires fresh real admin authentication.
        dialog.native_public_recovery=True
        for widget in list(dialog.body.winfo_children()):widget.destroy()
        dialog.buttons=[];dialog.secrets=[]
        dialog.label(f"Reviewed {len(plan['users'])} accounts and {len(plan['files'])} files ({plan['bytes']/1024**2:.1f} MiB). All private workspaces are sealed.",bold=True)
        listing=ScrolledText(dialog.body,height=8,wrap='none',bg=dialog.bg,fg=dialog.fg)
        listing.pack(fill='both',expand=True,pady=6)
        listing.insert('1.0','\n'.join(f"{r['bytes']} bytes  {r['sha256']}  {r['path']}" for r in plan['files']))
        listing.configure(state='disabled')
        def export():
            target=filedialog.asksaveasfilename(parent=dialog.win,title='Export encrypted profiles outside the PortalAI drive folder',defaultextension='.zip',initialfile='PortalAI-private-backup.zip')
            if target:dialog.run(lambda:adapter.export(target),lambda r:dialog.status.set('Backup verified: '+r['path']),lifecycle=True)
        dialog.label('Save the full private backup outside this PortalAI folder, preferably on another drive. Start fresh will not remove that separate backup.')
        dialog.button('Export all encrypted private profiles…',export)
        decline=tk.BooleanVar(master=dialog.win,value=False)
        tk.Checkbutton(dialog.body,text='Proceed without another export; I have saved anything I need',variable=decline,bg=dialog.bg,fg=dialog.fg,selectcolor=colors.get('panel2',dialog.bg),wraplength=480).pack(anchor='w')
        current=dialog.entry('Current administrator password',secret=True)
        username=dialog.entry('New administrator username')
        new=dialog.entry('New administrator password (at least 12 characters)',secret=True)
        confirmation=dialog.entry('Confirm new password',secret=True)
        phrase=dialog.entry('Type RESET ALL PRIVATE PROFILES')
        def execute():
            values=current.get(),phrase.get(),username.get(),new.get(),confirmation.get()
            no_export=decline.get()
            def finished(receipt):
                if receipt.get('reset') is not True or receipt.get('login_required') is not True:
                    raise RuntimeError('Reset completion did not verify')
                dialog.close();exit_application()
            confirm=_Dialog(dialog.win,'Confirm Start fresh',colors)
            confirm.label('Delete the reviewed private data?',bold=True)
            confirm.label(f"This removes {len(plan['users'])} local accounts and their chats, memory and outputs. Models and packages remain installed. Cancel keeps the reviewed data.")
            def approved():
                confirm.close()
                dialog.run(lambda:adapter.execute(*values,decline_export=no_export),finished,lifecycle=True)
            confirm.button('Cancel — keep data',confirm.close)
            confirm.button('Yes, reset reviewed private data',approved,tone='danger')
        dialog.button('Reset reviewed private profiles and close',execute,tone='danger')
        dialog.button('Keep data and close PortalAI',leave)
        dialog.status_line()
    def prepare():
        password=admin_password.get()
        lock_application()
        dialog.show_locked()
        dialog.run(lambda:adapter.prepare(password),reviewed,lifecycle=True)
    dialog.button('Stop, seal and review',prepare)
    dialog.button('Cancel',leave)
    dialog.status_line()
    return dialog
