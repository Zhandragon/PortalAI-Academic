"""Themed local-account gates; intentionally not activated by importing this module.

The main controller must call show_login before constructing chat, memory, tray,
status or mission objects. Authentication alone does not open a workspace:
prepare_session must finish the verified migration/unseal boundary first.

Account switching rebuilds the GUI after stop/seal verification. It never reuses
NativeChat, Tk callbacks, model workers or memory objects for another user.
This UI is not an OS access boundary for full host tools or a filesystem owner.
"""
from pathlib import Path
import queue
import sys
import threading
import time
import tkinter as tk
from portal_frontend_v15136 import portal_display_font
from tkinter import ttk

from elegant_native_ui import ElegantButton
from account_presentation import AccountSurface, prepare_login_shell
from ornate_ui import FiligreeScrollbar, heading_font


class AccountUIError(RuntimeError):
    pass


def workspace_failure_message(error):
    """Describe a post-authentication failure without echoing paths or secrets."""
    import traceback
    detail = type(error).__name__
    if isinstance(error, OSError):
        code = getattr(error, 'winerror', None)
        if isinstance(code, int):
            detail += ' / Windows error ' + str(code)
        elif isinstance(error.errno, int):
            detail += ' / OS error ' + str(error.errno)
    owned = {'profile_workspace.py', 'profile_lazy_state.py', 'profile_runtime.py', 'profile_shutdown.py',
             'profile_hydration.py', 'profile_migration.py', 'profile_paths.py'}
    for frame in reversed(traceback.extract_tb(error.__traceback__)):
        if Path(frame.filename).name in owned:
            detail += ' / ' + Path(frame.filename).stem + ':' + str(frame.lineno)
            break
    return ('Password accepted, but workspace recovery did not finish (' + detail + '). '
            'Your encrypted recovery files are retained. Close PortalAI before retrying; '
            'resetting the password will not repair this workspace error.')


def paint_account_button(button, colors):
    tone=getattr(button,'_account_tone','normal')
    if tone=='danger':
        button.configure(bg=colors.get('danger','#7C403E'),fg='#FFFFFF',
                         activebackground=colors.get('danger_hover','#66312F'),activeforeground='#FFFFFF')
    elif tone=='warning':
        button.configure(bg=colors.get('gold_shine','#D9BE78'),fg='#202224',
                         activebackground=colors.get('gold_mid','#A87D32'),activeforeground='#202224')
    elif tone=='accent':
        button.configure(bg=colors.get('accent','#3E91A2'),fg='#FFFFFF',
                         activebackground=colors.get('accent_hover','#307889'),activeforeground='#FFFFFF')


def _value(session, name, default=None):
    return session.get(name, default) if isinstance(session, dict) else getattr(session, name, default)


def _user_id(row):
    return row.get('user_id', row.get('id'))


def _pending(row):
    return bool(row.get('pending') or row.get('state') == 'pending' or row.get('password_state') == 'pending')


def member_rows(rows, session, *, pending_only=False, promote=False):
    """Choose by immutable ID; pending users belong in the password picker."""
    return [row for row in rows if _user_id(row) != _value(session, 'user_id') and row.get('role') != 'guest'
            and (not pending_only or _pending(row)) and
            (not promote or (row.get('role') == 'user' and not _pending(row)))]


def _completed(message, result):
    warning = result.get('recovery_warning') if isinstance(result, dict) else getattr(result, 'recovery_warning', None)
    if warning:
        return message + ' The recovery copy needs repair. Your change is already saved; keep the current password and sign in as an administrator to repair recovery support.'
    return message


class AccountController:
    """Small backend adapter with no implicit login, migration or destructive reset."""

    def __init__(self, root, backend=None):
        self.root = Path(root).resolve()
        if backend is None:
            agent = str(self.root/'Agent')
            if agent not in sys.path:
                sys.path.insert(0, agent)
            from local_accounts import LocalAccounts
            backend = LocalAccounts(self.root)
        self.backend = backend
        from writer_jobs import WriterJobs
        self.jobs = WriterJobs()

    def status(self):
        value = self.backend.status()
        if not isinstance(value, dict) or value.get('state') not in {'fresh', 'locked', 'recovery_required'}:
            return {'state': 'recovery_required', 'reason': 'Account registry status could not be verified.', 'users': []}
        users = value.get('users', [])
        if not isinstance(users, list) or any(not isinstance(row, dict) or not isinstance(row.get('username'), str) for row in users):
            return {'state': 'recovery_required', 'reason': 'Account registry users could not be verified.', 'users': []}
        return value

    def login(self, username, password='', *, guest=False):
        if self.status()['state'] != 'locked':
            raise AccountUIError('The account registry requires setup or recovery.')
        if guest:
            if username != 'Guest':
                raise AccountUIError('Guest access cannot open a named private account.')
            return self.backend.login_guest()
        if not password:
            raise AccountUIError('Enter this account\'s password.')
        return self.backend.login(username, password)

    def bootstrap(self, username, password, confirmation):
        if self.status()['state'] != 'fresh':
            raise AccountUIError('Initial setup is allowed only on verified fresh storage.')
        self._matching(password, confirmation)
        if not username.strip():
            raise AccountUIError('Choose an administrator username.')
        return self.backend.bootstrap(username.strip(), password, pending_users=())

    def bootstrap_reviewed(self, username, password, confirmation):
        self._matching(password, confirmation)
        if not username.strip():
            raise AccountUIError('Choose an administrator username.')
        from local_accounts import _name, _password
        try:
            _name(username.strip()); _password(password)
        except ValueError as error:
            raise AccountUIError(str(error)) from None
        if username.strip().casefold() == 'guest':
            raise AccountUIError('Guest is reserved. Choose another administrator username.')
        from reviewed_account_setup import provision_reviewed
        try:
            return provision_reviewed(self.root, username.strip(), password)
        except Exception:
            raise AccountUIError('Initial account setup did not finish. Close and reopen PortalAI to resume with the same administrator name and password. Existing files and recovery copies are retained.') from None

    @staticmethod
    def _matching(password, confirmation):
        if not password or password != confirmation:
            raise AccountUIError('Enter a new password and matching confirmation.')

    @staticmethod
    def _admin(session):
        if not _value(session, 'active', False) or _value(session, 'role') != 'admin':
            raise AccountUIError('Sign in as an administrator first.')

    def change_password(self, session, current, new, confirmation):
        self._matching(new, confirmation)
        return self.backend.change_password(session, current, new)

    def create_user(self, session, username, password, confirmation, admin_password, *, pending=False):
        self._admin(session)
        if not username.strip() or not admin_password:
            raise AccountUIError('Enter the username and current administrator password.')
        if not pending:
            self._matching(password, confirmation)
        return self.backend.create_user(session, username.strip(), None if pending else password,
                                        role='user', admin_password=admin_password)

    def promote(self, session, target, admin_password, target_password):
        self._admin(session)
        if not target or not admin_password or not target_password:
            raise AccountUIError('Select the account and enter both current passwords.')
        return self.backend.promote(session, target, admin_password=admin_password, target_password=target_password)

    def enroll_pending(self, session, target, password, confirmation, admin_password, *, temporary_password=False):
        self._admin(session)
        self._matching(password, confirmation)
        if not admin_password:
            raise AccountUIError('Enter the current administrator password.')
        rows = self.backend.list_users(session)
        row = next((row for row in rows if _user_id(row) == target), None)
        if row is None or not (row.get('pending') or row.get('state') == 'pending' or row.get('password_state') == 'pending'):
            raise AccountUIError('Only a pending account can be enrolled here. Existing passwords are not reset by this form.')
        token = self.backend.request_confirmation(session, 'password-reset', target,
                                                  admin_password=admin_password, ttl_seconds=120)
        return self.backend.reset_password(session, target, password,
                                           admin_password=admin_password, confirmation_token=token,
                                           **({'temporary_password': True} if temporary_password else {}))

    def reset_member(self, session, target, password, confirmation, admin_password, typed_confirmation, *, temporary_password=False):
        self._admin(session)
        self._matching(password, confirmation)
        if not admin_password:
            raise AccountUIError('Enter your current administrator password.')
        row = next((row for row in self.backend.list_users(session) if _user_id(row) == target), None)
        if (row is None or target == _value(session, 'user_id') or row.get('role') == 'guest' or
                row.get('pending') or row.get('state') == 'pending' or row.get('password_state') == 'pending'):
            raise AccountUIError('Choose another enrolled member. Use Change my password for yourself or Enroll pending account for a pending user.')
        if typed_confirmation != 'RESET ' + row['username']:
            raise AccountUIError('Type RESET followed by the selected username exactly to confirm this password reset.')
        token = self.backend.request_confirmation(session, 'password-reset', target,
                                                  admin_password=admin_password, ttl_seconds=120)
        return self.backend.reset_password(session, target, password,
                                           admin_password=admin_password, confirmation_token=token,
                                           **({'temporary_password': True} if temporary_password else {}))

    def set_member_password(self, session, target, password, confirmation, admin_password, typed_confirmation,
                            *, temporary_password=False):
        self._admin(session)
        rows = member_rows(self.backend.list_users(session), session)
        row = next((row for row in rows if _user_id(row) == target), None)
        if row is None:
            raise AccountUIError('Choose another named account. Use Change my password for yourself.')
        if typed_confirmation != 'RESET ' + row['username']:
            raise AccountUIError('Type RESET followed by the selected username exactly.')
        options = {'temporary_password': True} if temporary_password else {}
        if _pending(row):
            return self.enroll_pending(session, target, password, confirmation, admin_password, **options)
        return self.reset_member(session, target, password, confirmation, admin_password, typed_confirmation, **options)

    def review_start_fresh(self, session, admin_password, confirmation):
        self._admin(session)
        if confirmation != 'RESET ALL PRIVATE PROFILES' or not admin_password:
            raise AccountUIError('Enter the administrator password and type RESET ALL PRIVATE PROFILES to review this action.')
        check = self.backend.login(_value(session, 'username'), admin_password)
        try:
            if _value(check, 'role') != 'admin' or _value(check, 'user_id') != _value(session, 'user_id'):
                raise AccountUIError('Current administrator authentication failed.')
        finally:
            self.backend.logout(check)
        return {'executable': False, 'export_required': True,
                'message': 'Administrator verified. Start fresh is unavailable until a verified export and account migration/reset path are installed. No data was changed.'}

    def start_fresh(self, *args, **kwargs):
        raise AccountUIError('Start fresh is not enabled: verified export and migration/reset support is required.')

    def activate(self, session, prepare_session):
        if not callable(prepare_session):
            self.backend.logout(session)
            raise AccountUIError('Workspace preparation is not installed; account access remains locked.')
        try:
            receipt = prepare_session(session)
            if not isinstance(receipt, dict) or receipt.get('ready') is not True or receipt.get('user_id') != _value(session, 'user_id'):
                raise AccountUIError('The selected account workspace was not verified ready.')
            return session
        except BaseException as exc:
            coordinator = getattr(prepare_session, '__self__', None)
            retains = getattr(coordinator, 'retains_session', None)
            if callable(retains) and retains(session):
                # The coordinator keeps this authentication until plaintext can
                # be verified sealed. It never authorizes another account here.
                raise AccountUIError(workspace_failure_message(exc)) from None
            self.backend.logout(session)
            # Authentication already succeeded even if preparation failed before
            # the coordinator retained recovery keys. Keep that distinction and
            # safe module/error codes instead of the generic password message.
            if isinstance(exc, Exception):
                raise AccountUIError(workspace_failure_message(exc)) from None
            raise

    def finish_logout(self, session, stop_and_seal):
        if not callable(stop_and_seal):
            raise AccountUIError('Verified stop and seal support is not installed.')
        receipt = stop_and_seal(session)
        if not isinstance(receipt, dict) or any(receipt.get(key) is not True for key in ('stopped', 'sealed')) or receipt.get('user_id') != _value(session, 'user_id'):
            raise AccountUIError('Stop and seal could not be verified. The application must stay locked.')
        self.backend.logout(session)
        return {'exit_required': True}


class ProgressMailbox:
    """One latest update; file progress never queues ahead of a terminal result."""
    def __init__(self):
        self.lock = threading.Lock()
        self.value = None

    def publish(self, value):
        if isinstance(value, dict) and isinstance(value.get('message'), str):
            with self.lock: self.value = dict(value)

    def latest(self):
        with self.lock:
            value, self.value = self.value, None
            return value


class _Dialog:
    def __init__(self, parent, title, colors, *, startup=False, jobs=None):
        self.native_management=not startup
        self.parent = parent.winfo_toplevel()
        self.jobs = jobs
        self.colors = colors
        self.bg = colors.get('panel', '#F8F3EA')
        self.fg = colors.get('text', '#202224')
        self.accent = colors.get('accent', '#3E91A2')
        self._palette = dict(colors)
        self.surface = AccountSurface(parent, title, colors, startup=startup)
        self.win = self.surface.overlay
        self.win._portalai_account_dialog = self
        self.canvas = tk.Canvas(self.surface.content, bg=self.bg, bd=0, highlightthickness=0)
        self.surface.scroll_canvas = self.canvas
        self.scroll = FiligreeScrollbar(self.surface.content, orient='vertical', command=self.canvas.yview, palette=colors)
        self.scroll.pack(side='right', fill='y', padx=(0,3))
        self.canvas.pack(side='left', fill='both', expand=True)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.body = tk.Frame(self.canvas, bg=self.bg, padx=20, pady=16)
        item = self.canvas.create_window(0, 0, window=self.body, anchor='nw')
        from page_scroll import bind_page_scroll
        bind_page_scroll(self.canvas, self.body, item)
        self.status = tk.StringVar(master=self.win)
        self.results = queue.Queue()
        self.progress = ProgressMailbox()
        self.busy = False
        self.closed = False
        self.buttons = []
        self.rounded_controls = []
        self.secrets = []
        self.surface.on_close = self.close
        if not hasattr(self.parent, '_portalai_account_dialogs'):
            self.parent._portalai_account_dialogs = []
        self.parent._portalai_account_dialogs.append(self)
        self._startup_protocol = self.parent.protocol('WM_DELETE_WINDOW') if startup else None
        if startup:self.parent.protocol('WM_DELETE_WINDOW', self._window_close)
        self._startup_handler = self.parent.protocol('WM_DELETE_WINDOW') if startup else None
        self.surface.palette_changed(colors)
        from modal_guard import set_modal_surface
        set_modal_surface(self.parent, self.surface)
        self._poll_after = self.win.after(60, self._poll)

    def _window_close(self):
        dialogs=[dialog for dialog in self.parent._portalai_account_dialogs if not dialog.closed]
        if dialogs:dialogs[-1].surface.on_close()

    def set_close_handler(self, callback):
        self.surface.on_close = callback
        if self._startup_protocol is not None:
            self.parent.protocol('WM_DELETE_WINDOW', callback)
            self._startup_handler = self.parent.protocol('WM_DELETE_WINDOW')

    def show_locked(self):
        self.surface.show_locked()

    def apply_palette(self, colors):
        previous = self._palette
        def visit(widget):
            for option in ('background','foreground','insertbackground','selectcolor','highlightbackground'):
                try:
                    current=widget.cget(option)
                    key=next((key for key,value in previous.items() if str(value).lower()==str(current).lower()),None)
                    if key is not None and key in colors:widget.configure(**{option:colors[key]})
                except tk.TclError:pass
            for child in widget.winfo_children():visit(child)
        visit(self.win)
        self.colors=colors;self.bg=colors.get('panel','#F8F3EA');self.fg=colors.get('text','#202224')
        self.accent=colors.get('accent','#3E91A2');self._palette=dict(colors)
        self.surface.palette_changed(colors);self.scroll.apply_palette(colors)
        for widget in self.rounded_controls: widget.apply_palette(colors)
        for button,_ in self.buttons:paint_account_button(button,colors)
        if hasattr(self,'identity'):self.identity.apply_palette(colors)

    def label(self, text, *, bold=False, muted=False):
        label = tk.Label(self.body, text=text, bg=self.bg, fg=self.colors.get('muted','#6E665E') if muted else self.fg,
                         font=(portal_display_font(self.win) if bold else 'Segoe UI', 12 if bold else 10, 'bold' if bold else 'normal'),
                         anchor='w', justify='left', wraplength=490)
        label.pack(fill='x', pady=(0, 8))
        label.bind('<Configure>', lambda event: label.configure(wraplength=max(220, event.width)))
        return label

    def entry(self, title, *, secret=False, value='', submit=None):
        self.label(title)
        variable = tk.StringVar(master=self.win, value=value)
        from rounded_controls import RoundedEntry
        entry = RoundedEntry(self.body, textvariable=variable, show='*' if secret else '',
                             palette=self.colors, font=('Segoe UI', 10), cursor='xterm')
        self.rounded_controls.append(entry)
        entry.pack(fill='x', pady=(0, 8))
        if submit is not None:
            def on_enter(_event):
                dialogs=[dialog for dialog in self.parent._portalai_account_dialogs if not dialog.closed]
                if not self.closed and not self.busy and dialogs and dialogs[-1] is self:
                    submit()
                return 'break'
            entry.bind('<Return>', on_enter)
            entry.bind('<KP_Enter>', on_enter)
        if secret:
            self.secrets.append(variable)
        return variable

    def button(self, text, command, *, enabled=True, tone='normal'):
        button = ElegantButton(self.body, text=text, command=command, bg=self.colors.get('button', '#E6DCCB'),
                               fg=self.fg, relief='flat', bd=0, padx=12, pady=7,
                               state='normal' if enabled else 'disabled', cursor='hand2')
        button.pack(anchor='w', pady=4)
        self.buttons.append((button, enabled))
        button._account_tone=tone;paint_account_button(button,self.colors)
        return button

    def status_line(self):
        tk.Label(self.body, textvariable=self.status, bg=self.bg, fg=self.accent,
                 wraplength=490, anchor='w', justify='left').pack(fill='x', pady=(10, 0))

    def picker(self, selected, values):
        from rounded_controls import RoundedCombobox
        widget=RoundedCombobox(self.body,textvariable=selected,values=values,state='readonly',
                               palette=self.colors,font=('Segoe UI',10),cursor='arrow')
        self.rounded_controls.append(widget)
        widget.pack(fill='x',pady=(2,12))
        return widget

    def close(self):
        dialogs=[dialog for dialog in self.parent._portalai_account_dialogs if not dialog.closed]
        if dialogs and dialogs[-1] is not self:
            dialogs[-1].surface.on_close()
            return
        if self.busy:
            self.status.set('Wait for the current account operation to finish.')
            return
        for variable in self.secrets:
            variable.set('')
        self.closed = True
        if self._poll_after is not None:
            self.win.after_cancel(self._poll_after)
            self._poll_after = None
        if self._startup_protocol is not None and self.parent.protocol('WM_DELETE_WINDOW') == self._startup_handler:
            self.parent.protocol('WM_DELETE_WINDOW',self._startup_protocol)
        self.surface.destroy()
        self.parent._portalai_account_dialogs.remove(self)

    def run(self, operation, success, *, lifecycle=False):
        if self.busy:
            return
        self.busy = True
        self.progress.latest()
        self.operation_started = time.monotonic()
        self.status.set(getattr(self, 'operation_label', 'Working…'))
        for variable in self.secrets:
            variable.set('')
        for button, _enabled in self.buttons:
            button.configure(state='disabled')
        def worker():
            try:
                self.results.put((True, operation(), success))
            except Exception as exc:
                # Never echo backend exception values: they may include sensitive
                # input or paths. Operational details belong in verified recovery.
                message = str(exc) if isinstance(exc, AccountUIError) else 'Account operation failed. Check the password, account permissions and recovery status.'
                self.results.put((False, message, success))
        factory = self.jobs.thread if self.jobs is not None and not lifecycle else threading.Thread
        try:
            factory(target=worker, name='PortalAI-account-operation', daemon=True).start()
        except RuntimeError:
            self.busy = False
            self.status.set('PortalAI is closing; new account operations are disabled.')

    def _poll(self):
        self._poll_after = None
        if self.closed:
            return
        progress = self.progress.latest()
        if progress is not None:
            message = progress['message']
            completed, total = progress.get('completed'), progress.get('total')
            if isinstance(completed, int) and isinstance(total, int) and total > 0:
                message += f' ({completed:,} / {total:,})'
            self.status.set(message)
        elapsed = getattr(self, 'elapsed', None)
        if elapsed is not None and self.busy:
            seconds = max(0, int(time.monotonic()-getattr(self, 'operation_started', time.monotonic())))
            elapsed.set(f'Elapsed: {seconds//60}:{seconds%60:02d}')
        try:
            ok, value, success = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            for button, enabled in self.buttons:
                button.configure(state='normal' if enabled else 'disabled')
            if ok:
                success(value)
            else:
                self.status.set(value)
        if not self.closed:
            self._poll_after = self.win.after(60, self._poll)


def show_login(parent, controller, colors, *, prepare_session, recover_reset=None,
               progress=None, retain_until_ready=False, authenticated_session=None):
    """Return an activated session or None; caller must exit on None.

    The caller owns the main process gate. It must not initialize private-data
    consumers before this function succeeds, and must explicitly show the app
    afterward. Missing/corrupt registries require recovery, except for an explicit
    one-time repair ticket bound to reviewed data on a registry-free copy.
    """
    prepare_login_shell(parent, controller.root, colors)
    dialog = _Dialog(parent, 'Choose your account', colors, startup=True, jobs=controller.jobs)
    if progress is not None: dialog.progress = progress
    dialog.operation_label = 'Checking account password…'
    dialog.elapsed = tk.StringVar(master=dialog.win, value='')
    completed = tk.BooleanVar(master=parent, value=False)
    if retain_until_ready:
        parent._portalai_login_dialog = dialog
        dialog.win.bind('<Destroy>', lambda event:completed.set(True) if event.widget is dialog.win else None, add='+')
    result = [None]
    try:
        status = controller.status()
    except Exception:
        status = {'state': 'recovery_required', 'reason': 'Account registry could not be read safely.'}
    from reviewed_account_setup import inspect as inspect_reviewed_setup
    reviewed_setup = inspect_reviewed_setup(controller.root, controller.backend)
    def recover_registry():
        child = _Dialog(dialog.win, 'Recover account registry', colors, jobs=controller.jobs)
        child.label('This explicitly restores a missing or damaged account registry from its verified encrypted recovery copy. Enter an existing administrator username and password. Unverifiable or stale recovery copies are rejected.',muted=True)
        username = child.entry('Existing administrator username')
        password = child.entry('Existing administrator password', secret=True)
        def apply():
            values = username.get(), password.get()
            child.run(lambda: controller.backend.recover_registry(*values),
                      lambda _: child.status.set('Account registry recovery verified. Close PortalAI and reopen to choose an account.'))
        child.button('Recover verified account registry', apply)
        child.status_line()
    if authenticated_session is not None:
        dialog.label('Opening '+str(_value(authenticated_session,'username','the selected account')),bold=True)
        dialog.label('The previous account is saved and sealed. Preparing this account’s private workspace…',muted=True)
        def resume():
            dialog.run(lambda:controller.activate(authenticated_session,prepare_session),complete)
        dialog.win.after(80,resume)
        dialog.button('Close PortalAI',dialog.close)
    elif reviewed_setup is not None:
        resuming = reviewed_setup['mode'] == 'resume'
        dialog.label('Finish initial account setup' if resuming else 'Create your administrator account', bold=True)
        dialog.label(('Enter the administrator name and password you chose when setup began. Existing files will be verified and preserved.' if resuming else
            'This copy has no accounts yet. Its existing chat, settings and recovery files have been reviewed. Creating your administrator will preserve them in your encrypted account and verify a separate encrypted recovery backup.'), muted=True)
        username = dialog.entry('Administrator username')
        if resuming: username.set(reviewed_setup['owner'])
        password = dialog.entry('Administrator password (at least 12 characters)', secret=True)
        confirmation = None if resuming else dialog.entry('Confirm password', secret=True)
        dialog.operation_label = 'Preserving existing files and preparing your account…'
        def create_reviewed():
            name = username.get().strip()
            values = name, password.get(), confirmation.get() if confirmation is not None else password.get()
            def operation():
                controller.bootstrap_reviewed(*values)
                return controller.activate(controller.login(name, values[1]), prepare_session)
            dialog.run(operation, complete)
        dialog.button('Finish account setup' if resuming else 'Create initial administrator', create_reviewed)
    elif status['state'] == 'recovery_required':
        dialog.label('Account recovery is required. This installation will remain locked.',muted=True)
        dialog.label(str(status.get('reason') or 'Restore the verified account registry and encrypted data using the recovery workflow.'),muted=True)
        if callable(recover_reset) and (controller.root/'Private/Reset/transaction.json').exists():
            dialog.label('An interrupted Start fresh transaction needs an explicit choice. Rollback uses the previous administrator password before commit. Finish uses the new administrator password after commit. Recovery verifies every retained encrypted file.',muted=True)
            username = dialog.entry('Recovery administrator username')
            password = dialog.entry('Recovery administrator password', secret=True)
            action = tk.StringVar(master=dialog.win, value='rollback')
            dialog.picker(action,['rollback','finish'])
            def recover():
                values = username.get(), password.get(), action.get()
                dialog.run(lambda: recover_reset(*values), lambda _: dialog.status.set('Recovery verified. Close PortalAI and reopen to sign in.'))
            dialog.button('Perform authenticated reset recovery', recover)
        dialog.button('Close PortalAI', dialog.close)
    elif status['state'] == 'fresh':
        dialog.label('Choose the initial administrator username and password for this fresh installation. Guest will have separate, shared history.',muted=True)
        username = dialog.entry('Administrator username')
        password = dialog.entry('Administrator password', secret=True)
        confirmation = dialog.entry('Confirm password', secret=True)
        def create():
            name = username.get().strip()
            values = name, password.get(), confirmation.get()
            def operation():
                controller.bootstrap(*values)
                return controller.activate(controller.login(name, values[1]), prepare_session)
            dialog.run(operation, complete)
        dialog.button('Create initial administrator', create)
    else:
        users = status.get('users', [])
        names = [row['username'] for row in users]
        selected = tk.StringVar(master=dialog.win, value=names[0] if names else '')
        dialog.label('Username')
        picker = dialog.picker(selected,names)
        password = dialog.entry('Password', secret=True, submit=lambda: sign_in.invoke())
        login_actions=tk.Frame(dialog.body,bg=dialog.bg)
        login_actions.pack(fill='x',pady=(0,10))
        dialog.label('Guest is passwordless and shared: anyone selecting Guest can see its saved history. Pending accounts need an administrator to set their password.',muted=True)
        dialog.label('Accounts do not isolate full host tools or protect against someone who controls this computer or its filesystem.',muted=True)
        def login():
            username, secret = selected.get(), password.get()
            dialog.run(lambda: controller.activate(controller.login(username, secret, guest=username == 'Guest'), prepare_session), complete)
        sign_in = dialog.button('Sign in', login, enabled=bool(names),tone='accent')
        sign_in.pack_forget();sign_in.pack(in_=login_actions,side='right',pady=3)
    if authenticated_session is None and reviewed_setup is None and status['state'] in ('recovery_required', 'locked'):
        if status.get('recovery_warning'):
            dialog.label('The account recovery copy needs repair. A successful administrator sign-in can repair it after verifying the active registry.',muted=True)
        recover_button=dialog.button('Recover account registry…', recover_registry)
        if status['state']=='locked':
            recover_button.pack_forget();recover_button.pack(in_=login_actions,side='left',pady=3)
    def complete(session):
        result[0] = session
        if retain_until_ready:
            dialog.busy = True
            for button, _enabled in dialog.buttons: button.configure(state='disabled')
            dialog.status.set('Account verified. Preparing the PortalAI interface…')
            dialog.win.update_idletasks()
            completed.set(True)
        else: dialog.close()
    dialog.status_line()
    tk.Label(dialog.body, textvariable=dialog.elapsed, bg=dialog.bg, fg=dialog.accent,
             anchor='w').pack(fill='x',pady=(3,0))
    dialog.label('Larger profiles can take longer to verify and open. Keep this drive connected while sign-in is in progress.',muted=True)
    if retain_until_ready: parent.wait_variable(completed)
    else: parent.wait_window(dialog.win)
    return result[0]


def show_accounts(parent, controller, session, colors, *, lock_application=None, stop_and_seal=None,
                  exit_application=None, on_session_changed=None, export_history=None, export_outputs=None,
                  export_both=None, change_user=None, start_fresh_adapter=None, page=False):
    """Same authenticated actions in a main page or an internal management sheet."""
    if page:
        from accounts_page import AccountsPage
        dialog=AccountsPage(parent,colors,jobs=controller.jobs)
    else: dialog = _Dialog(parent, 'Accounts', colors, jobs=controller.jobs)
    username = str(_value(session, 'username', 'Unknown'))
    role = str(_value(session, 'role', 'unknown'))
    from accounts_page import AccountIdentity
    dialog.identity=AccountIdentity(dialog.body,username,role,colors)
    dialog.identity.pack(fill='x',pady=(0,10))
    dialog.label('Change current user verifies the next sign-in before saving and sealing this account. Export Data saves a verified copy of the selected data.')

    def export(callback):
        # The factory runs on Tk's thread so it can request an explicit export
        # destination. Actual copying/verification runs off the UI thread.
        try:
            operation = callback(session, dialog.win)
            if operation is None:
                return
            if not callable(operation):
                raise AccountUIError('The export adapter did not prepare a verified export job.')
            def completed(receipt):
                if not isinstance(receipt, dict) or receipt.get('verified') is not True:
                    dialog.status.set('Export could not be verified. No successful export is claimed.')
                    return
                dialog.status.set('Export verified: ' + str(receipt.get('path') or 'selected destination'))
            dialog.run(operation, completed)
        except Exception:
            dialog.status.set('Export is unavailable or could not be prepared. Existing data remains in this profile.')
    def export_data():
        child=_Dialog(dialog.win,'Export Data',colors,jobs=controller.jobs)
        child.label('Choose what to include in one verified ZIP file. The exported copy is not encrypted.')
        choices={'Chat history':export_history,'Outputs':export_outputs,'Both':export_both}
        choices={name:callback for name,callback in choices.items() if callable(callback)}
        selected=tk.StringVar(child.win,value='Both' if 'Both' in choices else next(iter(choices),''))
        child.label('Data to export');child.picker(selected,list(choices))
        def choose():
            callback=choices[selected.get()];child.close();export(callback)
        child.button('Choose destination and export…',choose,enabled=bool(choices))
        child.button('Cancel',child.close)
    dialog.button('Export Data…',export_data,enabled=any(callable(c) for c in (export_history,export_outputs,export_both)))

    def form(title):
        return _Dialog(dialog.win, title, colors, jobs=controller.jobs)

    def changed(child, message):
        child.status.set(message)

    def change_password():
        child = form('Change password')
        current = child.entry('Current password', secret=True)
        new = child.entry('New password', secret=True)
        confirm = child.entry('Confirm new password', secret=True)
        def replace_session(new_session):
            nonlocal session
            try:
                on_session_changed(new_session)
            except Exception:
                if callable(lock_application):
                    lock_application()
                child.status.set('Password changed, but session replacement failed. Account access must remain locked; restart through account recovery.')
                return
            session = new_session
            dialog.identity.set_account(new_session.username,new_session.role)
            changed(child, _completed('Password changed.', new_session))
        def apply():
            args = current.get(), new.get(), confirm.get()
            child.run(lambda: controller.change_password(session, *args), replace_session)
        child.button('Change password', apply)
        child.status_line()
    dialog.button('Change my password…', change_password,
                  enabled=role != 'guest' and callable(on_session_changed) and callable(lock_application))

    def create_user():
        child = form('Create standard account')
        name = child.entry('Username')
        admin_password = child.entry('Your administrator password', secret=True)
        new = child.entry('New account password', secret=True)
        confirm = child.entry('Confirm account password', secret=True)
        pending = tk.BooleanVar(master=child.win, value=False)
        tk.Checkbutton(child.body, text='Leave pending until administrator enrollment', variable=pending,
                       bg=child.bg, fg=child.fg, selectcolor=child.colors.get('panel2', child.bg)).pack(anchor='w')
        def apply():
            args = name.get(), new.get(), confirm.get(), admin_password.get()
            is_pending = pending.get()
            child.run(lambda: controller.create_user(session, *args, pending=is_pending),
                      lambda result: changed(child, _completed('Account created.', result)))
        child.button('Create account', apply)
        child.status_line()

    def target_form(promote=False):
        child = form('Promote account' if promote else 'Enroll pending account')
        try:
            rows = controller.backend.list_users(session)
            rows = member_rows(rows,session,pending_only=not promote,promote=promote)
        except Exception:
            child.label('Account list could not be verified. No account operation is available.')
            return
        labels = {row['username']: _user_id(row) for row in rows}
        selected = tk.StringVar(master=child.win, value=next(iter(labels), ''))
        child.picker(selected,list(labels))
        admin_password = child.entry('Your administrator password', secret=True)
        password = child.entry('Target account current password' if promote else 'New account password', secret=True)
        confirm = None if promote else child.entry('Confirm account password', secret=True)
        def apply():
            target, admin, secret = labels.get(selected.get()), admin_password.get(), password.get()
            confirmation = confirm.get() if confirm else ''
            action = (lambda: controller.promote(session, target, admin, secret)) if promote else (
                lambda: controller.enroll_pending(session, target, secret, confirmation, admin))
            child.run(action, lambda result: changed(child, _completed('Account updated.', result)))
        child.button('Promote to administrator' if promote else 'Set pending password', apply, enabled=bool(labels))
        child.status_line()

    def start_fresh():
        if callable(start_fresh_adapter):
            dialog.close()
            return start_fresh_adapter()
        child = form('Start fresh · review only')
        child.label('This action is not enabled. A verified export and tested reset/migration path are required before any account or history can be removed. Models and runtimes must remain portable.')
        password = child.entry('Your administrator password', secret=True)
        confirmation = child.entry('Type RESET ALL PRIVATE PROFILES to review')
        def review():
            args = password.get(), confirmation.get()
            child.run(lambda: controller.review_start_fresh(session, *args), lambda result: child.status.set(result['message']))
        child.button('Verify administrator and review', review)
        child.button('Export and start fresh — unavailable', lambda: None, enabled=False)
        child.status_line()

    def reset_member():
        child = form('Set or reset a member password')
        try:
            rows = member_rows(controller.backend.list_users(session),session)
        except Exception:
            child.label('The member list could not be authenticated. Password reset is unavailable.')
            return
        labels = {row['username']: _user_id(row) for row in rows}
        selected = tk.StringVar(master=child.win, value=next(iter(labels), ''))
        picker=child.picker(selected,list(labels))
        state_label=child.label('')
        def describe(_event=None):
            row=next((row for row in rows if _user_id(row)==labels.get(selected.get())),None)
            state_label.configure(text=('Pending account: set its first password.' if _pending(row) else
                                         'Enrolled account: reset its password; saved data is preserved.') if row else
                                        'No other named accounts exist. Create a standard account first.')
        picker.bind('<<ComboboxSelected>>',describe);describe()
        child.label('Your own password is changed separately. Member password changes preserve saved data and end that member’s existing sessions.')
        admin = child.entry('Your current administrator password', secret=True)
        password = child.entry('New member password', secret=True)
        confirmation = child.entry('Confirm new member password', secret=True)
        typed = child.entry('Type RESET followed by the selected username')
        temporary=tk.BooleanVar(master=child.win,value=False)
        tk.Checkbutton(child.body,text='Temporary password (member should replace it after sign-in)',variable=temporary,
                       bg=child.bg,fg=child.fg,selectcolor=child.colors.get('panel2',child.bg),wraplength=490).pack(anchor='w')
        def apply():
            values = labels.get(selected.get()), password.get(), confirmation.get(), admin.get(), typed.get()
            options={'temporary_password':True} if temporary.get() else {}
            child.run(lambda: controller.set_member_password(session, *values, **options),
                      lambda result: changed(child, _completed('Member password reset. Saved data was preserved.', result)))
        child.button('Reset selected member password', apply, enabled=bool(labels))
        child.status_line()

    if role == 'admin':
        def inspect_profiles():
            from admin_profile_ui import show_admin_profiles
            show_admin_profiles(dialog.win, controller, session, colors)
        dialog.button('Inspect or export other profiles…', inspect_profiles)
        dialog.button('Create standard account…', create_user)
        dialog.button('Enroll pending account…', target_form)
        dialog.button('Set/reset member password…', reset_member)
        dialog.button('Promote an account…', lambda: target_form(True))

    def logout():
        # Root must immediately hide/lock all private surfaces before background
        # shutdown. A failure leaves that gate closed; it never returns to chat.
        try:
            lock_application()
        except Exception:
            dialog.show_locked()
            dialog.status.set('Shutdown preparation did not finish. Private surfaces remain locked. Keep the drive connected and retry Log out and close PortalAI.')
            return
        dialog.show_locked()
        def complete(_receipt):
            dialog.close()
            exit_application()
        dialog.run(lambda: controller.finish_logout(session, stop_and_seal), complete, lifecycle=True)
    enabled = all(callable(callback) for callback in (lock_application, stop_and_seal, exit_application))
    if callable(change_user):dialog.button('Change current user',change_user,tone='warning')
    else:dialog.button('Log out and close PortalAI', logout, enabled=enabled,tone='warning')
    if role=='admin':dialog.button('Start fresh…',start_fresh,tone='danger')
    if not enabled:
        dialog.label('Logout requires verified workspace sealing; it is not available in this integration yet.')
    dialog.status_line()
    return dialog


def account_link(parent, controller, session, colors, **lifecycle):
    """Small Controls-row account link; caller retains the six primary controls."""
    # A getter keeps password-change replacement sessions current without keeping
    # a revoked Session in this button's callback closure.
    current = session if callable(session) else lambda: session
    label = f"{_value(current(), 'username', 'Account')} · Accounts…"
    return ElegantButton(parent, text=label,
        command=lambda: show_accounts(parent, controller, current(), colors, **lifecycle),
        bg=colors.get('button', '#E6DCCB'), fg=colors.get('accent', '#3E91A2'),
        relief='flat', bd=0, padx=12, pady=6)
