"""Actual two-window account switch using disposable accounts, never live users."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('ControlCenter','Agent','Tools','Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts


def run(destination):
    import tkinter as tk
    from tkinter import ttk
    import account_gate,account_ui,writer_jobs,native_chat,local_accounts,profile_diagnostics
    from profile_workspace import ProfileWorkspace
    from smoke_account_panels import capture_window
    from test_settings_surfaces_tk import button
    with tempfile.TemporaryDirectory(prefix='switch-',dir=destination) as temp:
        root=Path(temp);(root/'Agent/.runtime').mkdir(parents=True)
        shutil.copy2(ROOT/'Agent/hardware_profiles.json',root/'Agent/hardware_profiles.json')
        (root/'Agent/.runtime/control_center_theme.json').write_text('{"theme":"light"}')
        branding=root/'ControlCenter/Branding';branding.mkdir(parents=True)
        for source in (ROOT/'ControlCenter/Branding').glob('*.png'):
            if source.stat().st_size<4*1024**2:shutil.copy2(source,branding/source.name)
        backend=local_accounts.LocalAccounts(root);password='Synthetic-switch-password-2026'
        alice=backend.bootstrap('Alice',password)
        backend.create_user(alice,'Bob',password,admin_password=password)
        workspace=ProfileWorkspace(root,alice)
        private=workspace.workspace/'Data/alice-private.txt';private.parent.mkdir(parents=True,exist_ok=True)
        private.write_text('Only Alice');workspace.seal(writers_stopped=True);backend.logout(alice)
        state={'phase':0,'apps':[],'built':[],'error':None,'start':time.monotonic(),'busy':False}
        original_tk=tk.Tk;original_threads=writer_jobs.WriterJobs.thread;original_gate=account_gate.GUIAccountGate.__init__
        class Suppressed:
            def start(self):pass
            def join(self,*_,**__):pass
            def is_alive(self):return False
        def threads(group,**kwargs):
            return original_threads(group,**kwargs) if kwargs.get('name')=='PortalAI-account-operation' else Suppressed()
        def gate_init(gate,*args,**kwargs):
            original_gate(gate,*args,**kwargs);gate.stop_owned=lambda *_:{'stopped':True}
        def close(gate,session=None):
            assert gate.locked
            return gate.runtime.close(session or gate.session,writers_stopped=True)
        def newest(app):return next(d for d in reversed(app._portalai_account_dialogs) if not d.closed)
        def choose(dialog,username,secret):
            next(w for w in dialog.body.winfo_children() if isinstance(w,ttk.Combobox)).set(username)
            entry=next(w for w in dialog.body.winfo_children() if isinstance(w,ttk.Entry) and not isinstance(w,ttk.Combobox))
            entry.delete(0,'end');entry.insert(0,secret)
        def ready(loc):
            state['built'].append(loc.copy());loc['tray'].show=lambda:False
            step('interface-ready')
        def step(label):
            (destination/'progress.json').write_text(json.dumps({'stage':label,'phase':state['phase'],'windows':len(state['apps']),'built':len(state['built'])}),encoding='utf-8')
        def fail(exc):
            if state['error'] is None:
                import traceback
                state['error']=f"phase {state['phase']}: {type(exc).__name__}: {exc}\n{traceback.format_exc(limit=5)}"
                (destination/'failure.txt').write_text(state['error'],encoding='utf-8')
            for app in state['apps']:
                try:app.quit()
                except tk.TclError:pass
                try:app.destroy()
                except tk.TclError:pass
        def tick(app):
            if state['busy']:app.after(40,lambda:tick(app));return
            state['busy']=True
            try:
                if time.monotonic()-state['start']>120:raise TimeoutError('Bounded switch fixture timed out')
                phase=state['phase']
                if phase==0 and getattr(app,'_portalai_account_dialogs',None):
                    dialog=newest(app);choose(dialog,'Alice',password)
                    button(dialog.win,'Sign in').invoke();state['phase']=1
                elif phase==1 and len(state['built'])==1:
                    built=state['built'][0];gate=built['account_gate'];state['old']=gate.session
                    built['show_tab']('accounts');app.update()
                    titles=[str(b.cget('text')) for b,_ in built['account_page'].buttons]
                    assert titles.index('Change current user')<titles.index('Start fresh…')
                    assert 'Export Data…' in titles and not any(t.startswith('Export my ') for t in titles)
                    for mode in ('light','dark'):
                        if built['theme_mode']!=mode:built['toggle_theme']()
                        for tab in ('accounts','settings','help','installed'):
                            built['show_tab'](tab);app.update()
                            if tab=='help':
                                docs=built['documentation_panel'];docs.show_topic('settings');app.update()
                                assert docs.text.tag_cget('title','foreground')==built['COLORS']['muted']
                                assert docs.title_rule.winfo_width()>300
                                docs.listbox._select(1);assert docs.listbox.curselection()==(1,)
                            capture_window(app,destination/(tab+'-'+mode+'.png'))
                    built['show_tab']('accounts');app.update()
                    button(built['account_page'].win,'Export Data…').invoke();app.update()
                    picker=next(w for w in newest(app).body.winfo_children() if isinstance(w,ttk.Combobox))
                    assert list(picker.cget('values'))==['Chat history','Outputs','Both']
                    button(newest(app).win,'Cancel').invoke()
                    marker=(root/'Private/active-session.json').read_bytes()
                    built['change_current_user']();app.update()
                    capture_window(app,destination/'change-user.png')
                    button(newest(app).win,'Cancel').invoke()
                    assert gate.session.active and not gate.locked and private.read_text()=='Only Alice'
                    assert (root/'Private/active-session.json').read_bytes()==marker
                    state['cancel_preserved']=True
                    built['change_current_user']();dialog=newest(app);choose(dialog,'Bob','wrong password')
                    button(dialog.win,'Sign in and change user').invoke();state['phase']=2
                elif phase==2 and not newest(app).busy:
                    gate=state['built'][0]['account_gate'];dialog=newest(app)
                    assert gate.session.active and not gate.locked and private.exists()
                    assert 'failed' in dialog.status.get().lower();state['wrong_password_preserved']=True
                    choose(dialog,'Bob',password);button(dialog.win,'Sign in and change user').invoke();state['phase']=3
                elif phase==3 and len(state['built'])==2:
                    old,new=state['built'];gate=new['account_gate']
                    assert gate.session.username=='Bob' and gate.session.role=='user'
                    assert not state['old'].active and not private.exists()
                    assert old['native_chat_panel'] is not new['native_chat_panel']
                    assert old['gui_jobs'] is not new['gui_jobs']
                    new['show_tab']('accounts');app.update();capture_window(app,destination/'bob-account.png')
                    assert 'Start fresh…' not in [str(b.cget('text')) for b,_ in new['account_page'].buttons]
                    state['phase']=4;new['begin_exit_portableai']()
                if app.winfo_exists():app.after(40,lambda:tick(app))
            except tk.TclError:
                if state['phase']!=4:fail(RuntimeError('Unexpected Tk close'))
            except BaseException as exc:fail(exc)
            finally:state['busy']=False
        def make_tk(*args,**kwargs):
            if state['error']:raise RuntimeError(state['error'])
            step('before-new-Tk')
            app=original_tk(*args,**kwargs);state['apps'].append(app)
            step('new-Tk-created')
            app.report_callback_exception=lambda _type,error,_trace:fail(error)
            app.after(40,lambda:tick(app));return app
        source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8')
        source=source.replace('Local\\\\Zhandragon.PortableAI.ControlCenter','Local\\\\PortalAI.SwitchFixture.'+uuid.uuid4().hex)
        needle='    if account_gate is not None: account_gate.application_ready()'
        source=source.replace(needle,needle+'\n    _fixture_ready(locals())',1)
        source=source.replace('        if not account_gate.login():',"        _fixture_step('before-login')\n        if not account_gate.login():",1)
        source=source.replace('    pump(); app.mainloop()',"    _fixture_step('before-mainloop')\n    pump(); app.mainloop()\n    _fixture_step('after-mainloop')",1)
        source=source.replace('                    def destroy_window():',"                    def destroy_window():\n                        _fixture_step('destroy-window')",1)
        namespace={'__name__':'switch_fixture','__file__':str(ROOT/'ControlCenter/PortableAI_GUI.py'),'_fixture_ready':ready,'_fixture_step':step}
        try:
            with patch.dict(os.environ,{}),patch.object(sys,'argv',['fixture','--root',str(root)]), \
                patch.object(tk,'Tk',make_tk),patch.object(writer_jobs.WriterJobs,'thread',threads), \
                patch.object(account_gate.GUIAccountGate,'__init__',gate_init),patch.object(account_gate.GUIAccountGate,'close',close), \
                patch('portable_runtime.bootstrap_python',return_value=str(ROOT/'Runtime/BootstrapPython/python.exe')), \
                patch('native_chat.bootstrap_python',return_value=str(ROOT/'Runtime/BootstrapPython/python.exe')):
                for key in ('PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH'):os.environ.pop(key,None)
                exec(compile(source,namespace['__file__'],'exec'),namespace)
                result=namespace['run_application']()
                if state['error']:raise RuntimeError(state['error'])
                assert result==0 and state['phase']==4 and len(state['apps'])==2
                marker=json.loads((root/'Private/active-session.json').read_text())
                assert marker['state']=='closed'
                return {'passed':True,'synthetic_only':True,'production_accounts_opened':False,
                    'cancel_kept_current_user':state['cancel_preserved'],'wrong_password_kept_current_user':state['wrong_password_preserved'],
                    'old_profile_sealed_before_new_ui':True,'fresh_chat_and_writer_objects':True,'new_account_role_enforced':True,
                    'new_account_shutdown_verified':True,'windows_built':2,'model_services_started':False}
        finally:
            profile_diagnostics.suspend()
            for built in state['built']:
                gate=built['account_gate'];gate.controller.jobs.close();gate.controller.jobs.wait(5)
                if gate.runtime._process_lock is not None:
                    gate.runtime._process_lock.__exit__(None,None,None);gate.runtime._process_lock=None
            for app in state['apps']:
                try:app.destroy()
                except tk.TclError:pass


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True);args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    import faulthandler
    with artifacts.path('trace.log').open('w',encoding='utf-8') as trace:
        faulthandler.dump_traceback_later(90,exit=True,file=trace)
        try:report=run(artifacts.path())
        except Exception as exc:report={'passed':False,'error':str(exc)}
        finally:faulthandler.cancel_dump_traceback_later()
    artifacts.path('switch-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(0 if report.get('passed') else 1)
