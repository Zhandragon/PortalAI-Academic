"""Bounded Windows Tk fixture: real GUI/account forms, synthetic private data.

No models, mission workers or production profile files are opened. Process Stop
is separately covered by profile_shutdown tests; this fixture seals temp data.
"""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]


def run():
    if os.name!='nt':raise RuntimeError('This fixture validates Windows Tk; use the Linux GUI guest fixture on Linux')
    import tkinter as tk
    from tkinter import ttk
    import account_ui, account_gate, writer_jobs
    from local_accounts import LocalAccounts
    from profile_runtime import ProfileRuntime
    import profile_diagnostics
    base=ROOT/'Maintenance/AccountSmoke';base.mkdir(parents=True,exist_ok=True)
    temporary=tempfile.TemporaryDirectory(prefix='gui-',dir=base)
    fixture=Path(temporary.name).resolve()
    if not fixture.is_relative_to(base.resolve()):raise RuntimeError('Invalid smoke fixture path')
    (fixture/'Agent').mkdir()
    (fixture/'Agent/hardware_profiles.json').write_bytes((ROOT/'Agent/hardware_profiles.json').read_bytes())
    backend=LocalAccounts(fixture);password='Synthetic-owner-password-2026'
    owner=backend.bootstrap('SmokeOwner',password,pending_users=('PendingUser',))
    backend.logout(owner)
    results={'fixture':'synthetic Windows Tk','production_data_opened':False,'model_workers_started':False}
    dialogs=[];state={'step':0,'start':time.monotonic(),'locals':None,'error':None,'app':None}
    original_dialog=account_ui._Dialog.__init__; original_tk=tk.Tk
    original_gate=account_gate.GUIAccountGate.__init__
    original_thread=writer_jobs.WriterJobs.thread
    class Suppressed:
        def start(self):pass
        def is_alive(self):return False
        def join(self,*args,**kwargs):pass
    def fixture_threads(group,**kwargs):
        if kwargs.get('name')=='PortalAI-account-operation':return original_thread(group,**kwargs)
        return Suppressed()
    def dialog_init(self,*args,**kwargs):
        original_dialog(self,*args,**kwargs);dialogs.append(self)
    def gate_init(self,*args,**kwargs):
        original_gate(self,*args,**kwargs);state['gate']=self
    def button(dialog,label):
        return next(b for b,_ in dialog.buttons if b.cget('text')==label)
    def entries(dialog):return [w for w in dialog.body.winfo_children() if isinstance(w,(tk.Entry,ttk.Entry)) and not isinstance(w,ttk.Combobox)]
    def fill(dialog,values):
        fields=entries(dialog)
        if len(fields)!=len(values):raise AssertionError((len(fields),len(values),dialog.win.title()))
        for widget,value in zip(fields,values):widget.delete(0,'end');widget.insert(0,value)
    def newest():return next(d for d in reversed(dialogs) if not d.closed)
    def fixture_close(gate,session=None):
        if not gate.locked:raise RuntimeError('Fixture must be locked before sealing')
        return gate.runtime.close(session or gate.session,writers_stopped=True)
    def fail(exc):
        import traceback
        state['error']=f"step {state['step']}: {type(exc).__name__}: {exc}; {traceback.format_exc(limit=2)}"
        for dialog in dialogs:
            try:dialog.win.destroy()
            except Exception:pass
        try:state['app'].destroy()
        except Exception:pass
    def tick():
        try:
            if time.monotonic()-state['start']>50:raise TimeoutError('Tk account fixture exceeded 50 seconds')
            step=state['step']
            if step==0 and dialogs:
                d=newest();next(w for w in d.body.winfo_children() if isinstance(w,ttk.Combobox)).set('SmokeOwner')
                fill(d,['incorrect-password']);button(d,'Sign in').invoke();state['step']=1
            elif step==1 and not newest().busy:
                d=newest();assert 'failed' in d.status.get().lower();results['wrong_password_rejected']=True
                fill(d,[password]);button(d,'Sign in').invoke();state['step']=2
            elif step==2 and state['locals'] is not None:
                loc=state['locals'];gate=loc['account_gate']
                assert gate.session.username=='SmokeOwner'
                if loc['native_chat_panel'] is None:
                    raise AssertionError([w.cget('text') for w in loc['chat_tab'].winfo_children() if isinstance(w,tk.Label)])
                assert len(loc['buttons'])==6
                loc['show_tab']('controls');loc['app'].update_idletasks()
                if not state.get('mapped'):
                    loc['app'].attributes('-alpha',0.0)
                    loc['app'].geometry('1260x820-10000-10000')
                    state['map']();state['mapped']=time.monotonic()
                    state['app'].after(200,tick);return
                if time.monotonic()-state['mapped']<.15:
                    state['app'].after(50,tick);return
                results['controls']=[{'text':b.cget('text'),'x':b.winfo_x(),'y':b.winfo_y(),'width':b.winfo_width()} for b in loc['buttons']]
                assert all(row['width']>10 for row in results['controls'])
                assert len({row['y'] for row in results['controls']})==2
                assert all(row['x']+row['width']<=loc['btnrow'].winfo_width()+2 for row in results['controls'])
                results['controls_layout']='six buttons, three columns and two rows, within container'
                links=loc['account_links'].winfo_children();assert any('Accounts' in b.cget('text') for b in links)
                results['six_controls_and_account_link']=True
                next(b for b in links if 'Accounts' in b.cget('text')).invoke()
                button(newest(),'Create standard account…').invoke();state['step']=3
            elif step==3:
                d=newest();fill(d,['CreatedUser',password,'Created-user-password-2026','Created-user-password-2026'])
                button(d,'Create account').invoke();state['step']=4
            elif step==4 and not newest().busy:
                d=newest();assert 'created' in d.status.get().lower();results['create_user_form']=True;d.close()
                button(newest(),'Enroll pending account…').invoke();state['step']=5
            elif step==5:
                d=newest();next(w for w in d.body.winfo_children() if isinstance(w,ttk.Combobox)).set('PendingUser')
                fill(d,[password,'Enrolled-user-password-2026','Enrolled-user-password-2026'])
                button(d,'Set pending password').invoke();state['step']=6
            elif step==6 and not newest().busy:
                d=newest();assert 'updated' in d.status.get().lower();results['pending_enrollment_form']=True;d.close()
                button(newest(),'Reset a member password…').invoke();state['step']='reset_fill'
            elif step=='reset_fill':
                d=newest();picker=next(w for w in d.body.winfo_children() if isinstance(w,ttk.Combobox))
                choices=picker.cget('values');assert 'SmokeOwner' not in choices and 'Guest' not in choices
                picker.set('CreatedUser')
                fill(d,[password,'Reset-member-password-2026','Reset-member-password-2026','RESET CreatedUser'])
                button(d,'Reset selected member password').invoke();state['step']='reset_wait'
            elif step=='reset_wait' and not newest().busy:
                d=newest();assert 'password reset' in d.status.get().lower();results['member_password_reset_form']=True;d.close()
                button(newest(),'Change my password…').invoke();state['step']=7
            elif step==7:
                d=newest();fill(d,[password,'Changed-owner-password-2026','Changed-owner-password-2026'])
                button(d,'Change password').invoke();state['step']=8
            elif step==8 and not newest().busy:
                d=newest();assert 'changed' in d.status.get().lower();results['change_password_form']=True;d.close()
                gate=state['locals']['account_gate'];assert gate.session.active
                from account_permissions import require_admin
                standard=gate.controller.backend.login('CreatedUser','Reset-member-password-2026')
                try:
                    try:require_admin(fixture,standard)
                    except PermissionError:results['standard_admin_request_denied']=True
                    else:raise AssertionError('standard account accepted as admin')
                finally:gate.controller.backend.logout(standard)
                button(newest(),'Log out and close PortalAI').invoke();state['step']=9
            try:
                if state['app'].winfo_exists():state['app'].after(50,tick)
            except tk.TclError:
                if state['step'] != 9:raise
        except BaseException as exc:fail(exc)
    def make_tk(*args,**kwargs):
        app=original_tk(*args,**kwargs);app.withdraw();state['app']=app
        state['map']=app.deiconify
        app.deiconify=lambda:None  # Construct geometry without a visible test window.
        app.report_callback_exception=lambda typ,value,tb:fail(value)
        app.after(50,tick);return app
    def built(loc):
        state['locals']=loc.copy()
        loc['tray'].show=lambda:True
    source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8')
    source=source.replace('Local\\\\Zhandragon.PortableAI.ControlCenter','Local\\\\PortalAI.Smoke.'+uuid.uuid4().hex)
    needle='    log("PortalAI 2026.10.09 ready.'
    index=source.index(needle);source=source[:index]+'    _smoke_built(locals())\n'+source[index:]
    namespace={'__name__':'portalai_account_gui_fixture','__file__':str(ROOT/'ControlCenter/PortableAI_GUI.py'),'_smoke_built':built}
    try:
        with patch.dict(os.environ,{},clear=False), patch.object(sys,'argv',['gui-fixture','--root',str(fixture)]), \
             patch.object(tk,'Tk',make_tk),patch.object(account_ui._Dialog,'__init__',dialog_init), \
             patch.object(account_gate.GUIAccountGate,'__init__',gate_init), \
             patch('portable_runtime.bootstrap_python',return_value=str(ROOT/'Runtime/BootstrapPython/python.exe')), \
             patch('native_chat.bootstrap_python',return_value=str(ROOT/'Runtime/BootstrapPython/python.exe')), \
             patch.object(writer_jobs.WriterJobs,'thread',fixture_threads),patch.object(account_gate.GUIAccountGate,'close',fixture_close):
            os.environ.pop('PORTALAI_PROFILE_ID',None);os.environ.pop('PORTALAI_PROFILE_EPOCH',None)
            exec(compile(source,namespace['__file__'],'exec'),namespace)
            try:code=namespace['main']()
            except BaseException:
                if state['error']:raise RuntimeError(state['error']) from None
                raise
            if state['error']:raise RuntimeError(state['error'])
            if code!=0 or state['step']!=9:raise RuntimeError('GUI did not complete the account fixture')
            marker=json.loads((fixture/'Private/active-session.json').read_text())
            assert marker['state']=='closed'
            assert not any(path.is_file() for path in (fixture/'Private/Users'/marker['user_id']/'Workspace').rglob('*'))
            results.update(success=True,closed_and_sealed=True)
            return results
    finally:
        profile_diagnostics.suspend()
        gate=state.get('gate')
        if gate is not None and gate.runtime._process_lock is not None:
            gate.runtime._process_lock.__exit__(None,None,None);gate.runtime._process_lock=None
        try:
            if state['app'] is not None:state['app'].destroy()
        except Exception:pass
        if not fixture.is_relative_to(base.resolve()):raise RuntimeError('Invalid fixture cleanup')
        temporary.cleanup()


if __name__=='__main__':
    try:result=run()
    except BaseException as exc:result={'success':False,'error':f'{type(exc).__name__}: {exc}'}
    print(json.dumps(result,ensure_ascii=True,indent=2))
    raise SystemExit(0 if result.get('success') else 1)
