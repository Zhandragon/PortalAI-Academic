"""In-memory account handoff; credentials and keys never enter argv or files."""
from pathlib import Path


class SwitchTicket:
    def __init__(self, root, backend, session):
        self.root=Path(root).resolve()
        self.backend=backend
        self._session=session
        self.instance_mutex=None
        self.geometry=None

    def take(self, root):
        if Path(root).resolve()!=self.root or self._session is None:
            raise PermissionError('Account handoff is invalid or was already consumed')
        session,self._session=self._session,None
        return session


def authenticate_candidate(gate, username, password):
    candidate=gate.controller.login(username,password,guest=username=='Guest')
    try:
        if gate.locked or candidate.user_id==gate.session.user_id:
            raise ValueError('Choose a different account while the current account is open')
        gate.controller.backend.validate_session(candidate)
        return candidate
    except BaseException:
        gate.controller.backend.logout(candidate)
        raise


def seal_for_switch(gate, candidate):
    if not gate.locked:
        raise RuntimeError('Lock and stop writer admission before changing users')
    gate.controller.backend.validate_session(candidate)
    if candidate.user_id==gate.session.user_id:
        raise PermissionError('The new account must differ from the current account')
    old_id=gate.session.user_id
    receipt=gate.close()
    if not isinstance(receipt,dict) or receipt.get('user_id')!=old_id or any(
            receipt.get(k) is not True for k in ('stopped','sealed')) or gate.runtime.session is not None:
        raise RuntimeError('The current account did not verify sealed')
    return SwitchTicket(gate.root,gate.controller.backend,candidate)


def show_change_user(parent, gate, colors, *, lock_application, on_ready, exit_application):
    import tkinter as tk
    from account_ui import _Dialog, _pending
    dialog=_Dialog(parent,'Change current user',colors,jobs=gate.controller.jobs)
    dialog.label('Choose another account. Your current account stays signed in until the new credentials are accepted.')
    rows=gate.controller.status().get('users',[])
    names=[r['username'] for r in rows if r['username']!=gate.session.username and not _pending(r)]
    selected=tk.StringVar(dialog.win,value=next(iter(names),''))
    dialog.label('Username');dialog.picker(selected,names)
    password=dialog.entry('Password',secret=True,submit=lambda:sign_in.invoke())
    dialog.label('After sign-in is accepted, PortalAI stops current jobs, saves and seals this account, then opens the selected account. Guest does not require a password.')
    state={'candidate':None,'committing':False}
    def leave():
        if dialog.busy:return
        gate.on_shutdown_status=previous
        candidate=state['candidate'];state['candidate']=None
        if candidate is not None:gate.controller.backend.logout(candidate)
        dialog.close()
        if state['committing']:exit_application()
    dialog.set_close_handler(leave)
    previous=gate.on_shutdown_status
    def status(message):dialog.progress.publish({'message':message})
    def ready(ticket):
        gate.on_shutdown_status=previous
        state['candidate']=None
        dialog.busy=True
        dialog.status.set('Current account sealed. Opening the selected account…')
        on_ready(ticket)
    def commit(candidate):
        state['candidate']=candidate
        if gate.locked and not state['committing']:
            gate.controller.backend.logout(candidate);state['candidate']=None
            dialog.status.set('PortalAI is already closing. Account change was cancelled.')
            return
        state['committing']=True
        gate.on_shutdown_status=status
        try:
            lock_application()
            dialog.show_locked()
        except Exception:
            dialog.status.set('Account change is locked. Retry to finish sealing, or close PortalAI.')
            return
        dialog.operation_label='Saving and sealing the current account…'
        dialog.run(lambda:seal_for_switch(gate,candidate),ready,lifecycle=True)
    def sign():
        if state['candidate'] is not None:
            commit(state['candidate']);return
        values=selected.get(),password.get()
        dialog.operation_label='Checking the new account credentials…'
        dialog.run(lambda:authenticate_candidate(gate,*values),commit)
    sign_in=dialog.button('Sign in and change user',sign,enabled=bool(names),tone='warning')
    dialog.button('Cancel',leave)
    dialog.status_line()
    return dialog
