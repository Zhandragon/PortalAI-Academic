"""Real launcher startup on synthetic accounts; no production profiles/services."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'), str(ROOT/'Tools')]


def run(destination, theme='light', chat_settings=False, inspector=None):
    if os.name != 'nt': raise RuntimeError('This fixture verifies the Windows native wrapper')
    destination = Path(destination).resolve()
    if not destination.is_relative_to(ROOT/'Maintenance/Validation'):
        raise ValueError('Use a synthetic Maintenance/Validation directory')
    destination.mkdir(parents=True, exist_ok=True)
    import tkinter as tk
    from tkinter import ttk
    import account_ui, account_gate, writer_jobs, native_chat, settings_page
    from local_accounts import LocalAccounts
    from profile_workspace import ProfileWorkspace
    from profile_runtime import ProfileRuntime
    import profile_diagnostics
    from smoke_account_panels import capture_window
    temporary = tempfile.TemporaryDirectory(prefix='fixture-', dir=destination)
    fixture = Path(temporary.name).resolve()
    if not fixture.is_relative_to(destination): raise ValueError('Invalid fixture root')
    (fixture/'Agent').mkdir()
    runtime=fixture/'Agent/.runtime';runtime.mkdir()
    (runtime/'control_center_theme.json').write_text(json.dumps({'theme':theme}),encoding='utf-8')
    shutil.copy2(ROOT/'Agent/hardware_profiles.json', fixture/'Agent/hardware_profiles.json')
    brand = fixture/'ControlCenter/Branding';brand.mkdir(parents=True)
    for path in (ROOT/'ControlCenter/Branding').glob('*.png'):
        if path.stat().st_size < 4*1024*1024: shutil.copy2(path,brand/path.name)
    backend = LocalAccounts(fixture)
    secret = 'Synthetic-startup-password-2026'
    session = backend.bootstrap('StartupFixture', secret)
    workspace = ProfileWorkspace(fixture, session)
    payload = workspace.workspace/'Outputs/synthetic.txt'
    payload.parent.mkdir(parents=True, exist_ok=True);payload.write_text('Synthetic GUI fixture only')
    workspace.seal(writers_stopped=True);backend.logout(session)
    state = {'step':0, 'start':time.monotonic(), 'dialogs':[], 'private':[], 'maps':[], 'error':None}
    held = threading.Event();release = threading.Event()
    closing = threading.Event();close_release = threading.Event()
    original_tk = tk.Tk; original_dialog = account_ui._Dialog.__init__
    original_prepare = ProfileRuntime.prepare; original_gate = account_gate.GUIAccountGate.__init__
    original_threads = writer_jobs.WriterJobs.thread
    original_chat = native_chat.NativeChat.__init__; original_settings = settings_page.SettingsPage.__init__
    user = ctypes.WinDLL('user32',use_last_error=True)
    user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
    user.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int];user.GetWindowLongW.restype=ctypes.c_long

    def native_identity(app):
        child=app.winfo_id();hwnd=int(user.GetParent(child) or child)
        return {'tk_id':child,'hwnd':hwnd,'caption':bool(user.GetWindowLongW(hwnd,-16)&0x00C00000),
                'override':bool(app.overrideredirect()),'geometry':app.geometry()}

    class Suppressed:
        def start(self): pass
        def is_alive(self): return False
        def join(self,*args,**kwargs): pass
    def threads(group,**kwargs):
        if kwargs.get('name')=='PortalAI-account-operation': return original_threads(group,**kwargs)
        return Suppressed()
    def dialog_init(dialog,*args,**kwargs):
        original_dialog(dialog,*args,**kwargs);state['dialogs'].append(dialog)
    def gate_init(gate,*args,**kwargs):
        original_gate(gate,*args,**kwargs);state['gate']=gate
        gate.stop_owned=lambda *_:{'stopped':True}
    def prepare(runtime, session):
        result=original_prepare(runtime,session);held.set()
        if not release.wait(8):raise TimeoutError('Synthetic restore hold timed out')
        return result
    def private_init(original, label):
        def wrapped(instance,*args,**kwargs):
            assert held.is_set() and release.is_set(), 'Private UI constructed before verified readiness'
            login=state['app']._portalai_login_dialog
            assert login.busy and not login.closed and login.win.winfo_ismapped()
            state['private'].append(label)
            return original(instance,*args,**kwargs)
        return wrapped
    def fixture_close(gate,session=None):
        assert gate.locked
        closing.set()
        if not close_release.wait(8):raise TimeoutError('Synthetic shutdown presentation hold timed out')
        return gate.runtime.close(session or gate.session,writers_stopped=True)
    def newest():return next(d for d in reversed(state['dialogs']) if not d.closed)
    def button(dialog,text):return next(b for b,_ in dialog.buttons if b.cget('text')==text)
    def password(dialog,value):
        entry=next(w for w in dialog.body.winfo_children() if isinstance(w,(tk.Entry,ttk.Entry)) and not isinstance(w,ttk.Combobox))
        entry.delete(0,'end');entry.insert(0,value)
    def fail(exc):
        if state['error']:return
        import traceback
        state['error']=f"step {state['step']}: {type(exc).__name__}: {exc}\n{traceback.format_exc(limit=4)}"
        release.set();close_release.set()
        for dialog in state['dialogs']:
            try:dialog.busy=False;dialog.close()
            except Exception:pass
        try:state['app'].destroy()
        except Exception:pass
    def tick():
        if state.get('in_tick'):return
        state['in_tick']=True
        try:
            if time.monotonic()-state['start']>(100 if inspector else 40):raise TimeoutError('Startup continuity fixture exceeded its bounded allowance')
            if state['step']==0 and state['dialogs']:
                dialog=newest();app=state['app'];app.update_idletasks()
                initial=native_identity(app);state['initial']=initial
                assert initial['override'] and not initial['caption']
                assert state['shell']['titlebar'].winfo_ismapped()
                assert dialog.surface.host is state['shell']['body']
                assert dialog.win.winfo_y() >= state['shell']['titlebar'].winfo_y()+state['shell']['titlebar'].winfo_height()
                assert not state['private']
                assert dialog.surface.snapshot is not None,'Public welcome did not render behind login'
                assert state['shell']['theme_mode']==theme
                assert dialog.bg==state['shell']['THEMES'][theme]['panel']
                # Exercise actual chrome bindings while the account guard owns
                # the input grab, then restore the synthetic window geometry.
                drag=state['shell']['titlebar_text'];before=app.geometry()
                drag.event_generate('<ButtonPress-1>',x=5,y=5)
                drag.event_generate('<B1-Motion>',x=25,y=25);app.update_idletasks()
                assert app.geometry()!=before,'Login chrome drag was intercepted'
                app.geometry(before);app.update_idletasks()
                state['maps'].clear()
                capture_window(app,destination/'login-shell.png')
                next(w for w in dialog.body.winfo_children() if isinstance(w,ttk.Combobox)).set('StartupFixture')
                password(dialog,'incorrect-synthetic-password');button(dialog,'Sign in').invoke();state['step']=1
            elif state['step']==1 and not newest().busy:
                dialog=newest();assert 'failed' in dialog.status.get().lower(),dialog.status.get();assert not state['private']
                state['wrong_password']=True;password(dialog,secret);button(dialog,'Sign in').invoke();state['step']=2
            elif state['step']==2 and held.is_set():
                dialog=newest();assert dialog.busy and not state['private']
                state['progress']=dialog.status.get()
                assert state['progress'] and state['progress']!='Working…'
                state['shell']['chrome_buttons']['close'].invoke()
                assert not dialog.closed and dialog.busy
                state['busy_close_guard']=True;release.set();state['step']=3
            elif state['step']==4:
                app=state['app'];final=native_identity(app);initial=state['initial']
                assert final==initial, (initial,final)
                assert not state['maps'],state['maps']
                assert len(state['private'])==2 and state['retained_until_built']
                assert app._portalai_login_dialog is None
                assert state['built']['native_chat_panel'] is not None
                assert len(state['built']['buttons'])==6
                for _ in range(2):
                    state['built']['toggle_theme']();app.update_idletasks()
                    border=state['built']['welcome_note_border']
                    expected=state['built']['welcome_note'].master.cget('bg')
                    assert {border.canvas.itemcget(i,'fill') for i in border.canvas.find_withtag('ornate-corner-mask')}=={expected}
                capture_window(app,destination/'main-same-window.png')
                if inspector: inspector(state['built'], app, destination)
                if chat_settings:
                    state['built']['show_tab']('chat')
                    panel=state['built']['native_chat_panel'];panel.open_settings()
                    app.update_idletasks()
                    capture_window(app,destination/'chat-settings-wide.png')
                    app.geometry('720x820+40+40');app.update_idletasks()
                    capture_window(app,destination/'chat-settings-narrow.png')
                    panel._close_sheet();app.geometry(initial['geometry']);app.update_idletasks()
                state['built']['show_tab']('controls');app.update_idletasks()
                capture_window(app,destination/'last-page-before-close.png')
                state['final']=final;state['step']=5
                # Dispatch the actual final native window close protocol. It
                # must retain the verified account shutdown path after login.
                app.tk.call(app.protocol('WM_DELETE_WINDOW'))
            elif state['step']==5 and closing.is_set() and not close_release.is_set():
                app=state['app'];dialog=newest()
                assert dialog.surface.snapshot is not None
                assert dialog.bg==state['shell']['THEMES'][theme]['panel']
                assert state['shell']['titlebar'].winfo_ismapped()
                assert dialog.win.winfo_y()>=state['shell']['body'].winfo_rooty()-app.winfo_rooty()
                capture_window(app,destination/'shutdown-shell.png')
                state['shutdown_backdrop']=True
                close_release.set()
            if state['app'].winfo_exists():state['app'].after(30,tick)
        except tk.TclError:
            if state['step']!=5:fail(RuntimeError('Tk closed before fixture completed'))
        except BaseException as exc:fail(exc)
        finally:state['in_tick']=False
    def make_tk(*args,**kwargs):
        app=original_tk(*args,**kwargs);state['app']=app
        app.report_callback_exception=lambda typ,value,tb:fail(value)
        for kind in ('<Map>','<Unmap>'):
            app.bind(kind,lambda event,k=kind:state['maps'].append(k) if event.widget is app else None,add='+')
        app.after(30,tick);return app
    def shell(loc):
        state['shell']=loc.copy()
    def before_ready(loc):
        dialog=loc['app']._portalai_login_dialog
        state['retained_until_built']=dialog.busy and not dialog.closed and dialog.win.winfo_ismapped()
    def built(loc):
        state['built']=loc.copy();loc['tray'].show=lambda:False;state['step']=4
    source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8')
    source=source.replace('Local\\\\Zhandragon.PortableAI.ControlCenter','Local\\\\PortalAI.StartupFixture.'+uuid.uuid4().hex)
    needle="    if accounts_enabled(root) or LocalAccounts(root).status().get('state') == 'fresh':"
    source=source.replace(needle,'    _fixture_shell(locals())\n'+needle,1)
    needle='    if account_gate is not None: account_gate.application_ready()'
    source=source.replace(needle,'    _fixture_before_ready(locals())\n'+needle+'\n    _fixture_built(locals())',1)
    namespace={'__name__':'portalai_startup_fixture','__file__':str(ROOT/'ControlCenter/PortableAI_GUI.py'),
               '_fixture_shell':shell,'_fixture_before_ready':before_ready,'_fixture_built':built}
    try:
        with patch.dict(os.environ,{},clear=False),patch.object(sys,'argv',['fixture','--root',str(fixture)]), \
             patch.object(tk,'Tk',make_tk),patch.object(account_ui._Dialog,'__init__',dialog_init), \
             patch.object(account_gate.GUIAccountGate,'__init__',gate_init), \
             patch.object(ProfileRuntime,'prepare',prepare),patch.object(writer_jobs.WriterJobs,'thread',threads), \
             patch.object(native_chat.NativeChat,'__init__',private_init(original_chat,'chat')), \
             patch.object(settings_page.SettingsPage,'__init__',private_init(original_settings,'settings')), \
             patch('portable_runtime.bootstrap_python',return_value=str(ROOT/'Runtime/BootstrapPython/python.exe')), \
             patch('native_chat.bootstrap_python',return_value=str(ROOT/'Runtime/BootstrapPython/python.exe')), \
             patch.object(account_gate.GUIAccountGate,'close',fixture_close):
            os.environ.pop('PORTALAI_PROFILE_ID',None);os.environ.pop('PORTALAI_PROFILE_EPOCH',None)
            exec(compile(source,namespace['__file__'],'exec'),namespace)
            try:code=namespace['main']()
            except BaseException:
                if state['error']:raise RuntimeError(state['error']) from None
                raise
            if state['error']:raise RuntimeError(state['error'])
            assert code==0 and state['step']==5
            marker=json.loads((fixture/'Private/active-session.json').read_text())
            assert marker['state']=='closed'
            assert not any(p.is_file() for p in (fixture/'Private/Users'/marker['user_id']/'Workspace').rglob('*'))
            return {'passed':True,'production_accounts_opened':False,'model_services_started':False,
                    'one_native_window':state['initial']==state['final'],'initial':state['initial'],
                    'final':state['final'],'root_remap_events':state['maps'],'wrong_password_rejected':state['wrong_password'],
                    'busy_chrome_close_refused':state['busy_close_guard'],'progress':state['progress'],
                    'private_ui_after_ready':state['private'],'login_retained_until_main_ready':state['retained_until_built'],
                    'six_controls':True,'final_close_verified_sealed':True,
                    'stored_theme':theme,'corner_theme_roundtrip':True,'login_chrome_drag':True,
                    'shutdown_backdrop':state.get('shutdown_backdrop',False),
                    'shutdown_last_page':'controls','chat_settings_rendered':chat_settings}
    finally:
        release.set();close_release.set();profile_diagnostics.suspend()
        gate=state.get('gate')
        if gate is not None:
            gate.controller.jobs.close();gate.controller.jobs.wait(5)
            if gate.runtime._process_lock is not None:
                # Test-only failure cleanup: this runtime owns exclusively the
                # checked synthetic fixture, never a production profile.
                gate.runtime._process_lock.__exit__(None,None,None)
                gate.runtime._process_lock=None
        try:
            app=state.get('app')
            if app is not None:app.destroy()
        except tk.TclError:pass
        if not fixture.is_relative_to(destination):raise RuntimeError('Invalid fixture cleanup')
        temporary.cleanup()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--theme',choices=('light','dark'),default='light')
    parser.add_argument('--chat-settings',action='store_true')
    args=parser.parse_args()
    try:result=run(args.artifacts_dir,args.theme,args.chat_settings)
    except BaseException as exc:result={'passed':False,'error':f'{type(exc).__name__}: {exc}'}
    args.artifacts_dir.resolve().mkdir(parents=True,exist_ok=True)
    (args.artifacts_dir/'startup-continuity.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result.get('passed') else 1)
