"""Guarded GUI integration; importing this module never initializes accounts."""
from pathlib import Path
import json
import os
import subprocess
import sys


class GUIAccountGate:
    def __init__(self, app, root, colors, *, stop_owned=None, authenticated=None):
        self.app = app
        self.root = Path(root).resolve()
        self.colors = colors
        sys.path.insert(0, str(self.root/'Agent'))
        from account_ui import AccountController
        from profile_runtime import ProfileRuntime
        self.controller = AccountController(self.root, backend=authenticated.backend if authenticated else None)
        self._authenticated_session = authenticated.take(self.root) if authenticated else None
        self.session = None
        self.gui_jobs = None
        self.chat = None
        self.stop_owned = stop_owned
        self.locked = False
        self._explicit_stop_verified = False
        self.on_shutdown_status = None
        self.runtime = ProfileRuntime(self.root, self.controller.backend,
                                      quiesce=self._quiesce, harvest=self._harvest, lazy_restore=True)

    def login(self):
        from account_ui import ProgressMailbox, show_login
        progress = ProgressMailbox()
        previous = getattr(self.runtime, 'on_progress', None)
        self.runtime.on_progress = progress.publish
        try:
            self.session = show_login(self.app, self.controller, self.colors,
                                      prepare_session=self.runtime.prepare, recover_reset=self.recover_reset,
                                      progress=progress, retain_until_ready=True,
                                      authenticated_session=self._authenticated_session)
        finally:
            self.runtime.on_progress = previous
        if self.session is None:
            return False
        self.app._portalai_account_session = self.session
        self.app._portalai_account_warning = bool(getattr(self.session, 'recovery_warning', None))
        from profile_diagnostics import resume
        resume(self.root)
        return True

    def application_ready(self):
        """Tk thread: reveal the built interface without remapping the root."""
        dialog = getattr(self.app, '_portalai_login_dialog', None)
        if dialog is not None and not dialog.closed:
            dialog.busy = False
            dialog.close()
        self.app._portalai_login_dialog = None

    def bind_writers(self, gui_jobs, chat):
        self.gui_jobs, self.chat = gui_jobs, chat

    def recover_reset(self, username, password, action):
        from profile_diagnostics import suspend
        from profile_shutdown import verify_stopped
        from profile_reset import ResetCoordinator
        suspend()
        def checked():
            result = verify_stopped(self.root)
            if not isinstance(result, dict) or result.get('stopped') is not True:
                raise RuntimeError('Owned process quiescence did not verify')
            return {'quiescent': True}
        return ResetCoordinator(self.root, self.controller.backend).recover(
            username, password, action=action, writer_check=checked)

    def _quiesce(self, session, marker):
        self._status('Verifying that owned background processes have stopped…')
        from profile_diagnostics import suspend
        suspend()
        callback = self.stop_owned
        if callback is None:
            # This API owns process attribution and shutdown-only path mapping.
            # Missing/incomplete implementations never become a successful login.
            from profile_shutdown import stop_owned
            callback = stop_owned
        receipt = callback(self.root, session, marker)
        if not isinstance(receipt, dict) or receipt.get('stopped') is not True:
            raise RuntimeError('Owned process shutdown did not verify')
        if self.gui_jobs is not None:
            self._status('Waiting for account, GUI and chat writers to finish…')
            for group in (self.gui_jobs, self.controller.jobs):
                if group.wait(45).get('stopped') is not True:
                    raise RuntimeError('Background account/GUI writers have not finished')
            if self.chat is not None and self.chat.wait_for_writers(45).get('stopped') is not True:
                raise RuntimeError('Background chat writers have not finished')
            # A startup or media thread could have been in its final launch
            # section during the first stop; prove process quiescence again.
            receipt = callback(self.root, session, marker)
            if not isinstance(receipt, dict) or receipt.get('stopped') is not True:
                raise RuntimeError('Final owned process shutdown did not verify')
        return {'stopped': True}

    def _harvest(self, session):
        from profile_migration import SessionHarvest
        self._status('Preserving session diagnostics in this account…')
        result = SessionHarvest(self.root, session).run(writers_stopped=True)
        self._status('Encrypting and verifying account files; larger workspaces can take several minutes…')
        return result

    def _status(self, message):
        callback = getattr(self, 'on_shutdown_status', None)
        if self.locked and callable(callback):
            # Presentation cannot turn successful sealing into a failed close.
            try: callback(message)
            except Exception: pass
        elif not self.locked:
            callback = getattr(self.runtime, 'on_progress', None)
            if callable(callback):
                try: callback({'stage': 'recovery', 'message': message})
                except Exception: pass

    def lock(self):
        """Tk thread: hide private surfaces and cancel writers before sealing."""
        self.locked = True
        exporter=getattr(self.app,'_portalai_native_exporter',None)
        if exporter is not None:exporter.invalidate('closing')
        self.runtime.pause_hydration()
        # Close admission even if presentation fails; a locked-looking sheet
        # must never leave background writers free to start new operations.
        self.controller.jobs.close()
        if self.gui_jobs is not None:
            self.gui_jobs.close()
        failures = []
        if self.chat is not None:
            try: self.chat.shutdown()
            except Exception as exc: failures.append(exc)
        from account_presentation import lock_account_surfaces
        try: lock_account_surfaces(self.app,self.colors)
        except Exception:
            self.app.withdraw()
            raise
        import tkinter as tk
        def hide_children(widget):
            for child in widget.winfo_children():
                if isinstance(child, tk.Toplevel):
                    child.withdraw()
                hide_children(child)
        hide_children(self.app)
        if failures:
            raise RuntimeError('Chat cleanup did not finish; retry verified shutdown') from failures[0]

    def replace_session(self, session):
        exporter=getattr(self.app,'_portalai_native_exporter',None)
        if exporter is not None:exporter.invalidate('switching')
        self.runtime.replace_session(session)
        self.session = session
        self.app._portalai_account_session = session
        if self.chat is not None:
            self.chat.tool_runtime.bind_account(session)
        if exporter is not None:
            try:exporter.reauthorize()
            except (OSError,ValueError,RuntimeError,PermissionError):exporter.invalidate()

    def close(self, session=None):
        if not self.locked:
            raise RuntimeError('Lock the GUI before sealing the account')
        # Clean logout/Exit is an explicit Stop; crash-recovery login is not.
        # Run while this epoch is still open, before sealing closes path access.
        if not self._explicit_stop_verified:
            self._status('Stopping owned models, tools and explicitly armed missions…')
            from portable_runtime import bootstrap_python
            env = dict(os.environ); env.pop('PORTALAI_ACCOUNT_UNLOCK', None)
            cp = subprocess.run([str(bootstrap_python(self.root)), str(self.root/'Launchers/Stop_PortableAI.py'),
                                 '--root', str(self.root), '--include-opengui'],
                                cwd=str(self.root), env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace',
                                timeout=120, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0)
            try:
                result = json.loads(cp.stdout)
            except (ValueError, TypeError):
                result = {}
            if cp.returncode != 0 or result.get('success') is not True:
                raise RuntimeError('Explicit mission/model Stop could not be verified; workspace remains locked')
            self._explicit_stop_verified = True
        return self.runtime.close(session or self.session, writers_stopped=True)

    def link(self, parent, *, lock_application, exit_application):
        from account_ui import account_link
        from profile_exports import export_factory
        from account_reset_ui import show_start_fresh
        return account_link(parent, self.controller, lambda: self.session, self.colors,
                            lock_application=lock_application, stop_and_seal=self.close,
                            exit_application=exit_application, on_session_changed=self.replace_session,
                            export_history=export_factory(self.root, 'history'),
                            export_outputs=export_factory(self.root, 'outputs'),
                            start_fresh_adapter=lambda: show_start_fresh(self.app, self, self.colors,
                                lock_application=lock_application, exit_application=exit_application))

    def page(self,parent,*,lock_application,exit_application,change_user=None):
        from account_ui import show_accounts
        from profile_exports import export_factory
        from account_reset_ui import show_start_fresh
        return show_accounts(parent,self.controller,self.session,self.colors,page=True,
            lock_application=lock_application,stop_and_seal=self.close,
            exit_application=exit_application,on_session_changed=self.replace_session,
            export_history=export_factory(self.root,'history'),export_outputs=export_factory(self.root,'outputs'),
            export_both=export_factory(self.root,'both'),change_user=change_user,
            start_fresh_adapter=lambda:show_start_fresh(self.app,self,self.colors,
                lock_application=lock_application,exit_application=exit_application))
