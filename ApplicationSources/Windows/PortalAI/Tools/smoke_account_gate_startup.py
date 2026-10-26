"""Open the actual GUI on fresh and registry-free synthetic roots, then cancel.

Never logs into production accounts or starts model services.
"""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]

def run():
    import tkinter as tk
    import account_gate, native_chat, settings_page
    parent=ROOT/'Maintenance/Validation/Aoostar-Handoff-20261018'
    parent.mkdir(parents=True,exist_ok=True)
    results=[]
    source=(ROOT/'ControlCenter/PortableAI_GUI.py').read_text(encoding='utf-8')
    for expected in ('fresh','recovery_required'):
        with tempfile.TemporaryDirectory(prefix='gate-fixture-',dir=parent) as tmp:
            fixture=Path(tmp);(fixture/'Agent').mkdir()
            shutil.copy2(ROOT/'Agent/hardware_profiles.json',fixture/'Agent/hardware_profiles.json')
            if expected=='recovery_required':
                (fixture/'Outputs').mkdir();(fixture/'Outputs/legacy.txt').write_text('Synthetic legacy record')
            state={};original_tk=tk.Tk;original_gate=account_gate.GUIAccountGate.__init__
            def initialize(gate,*args,**kwargs):
                original_gate(gate,*args,**kwargs);state['gate']=gate
            def make_tk(*args,**kwargs):
                app=original_tk(*args,**kwargs);state['app']=app
                def cancel():
                    dialogs=[d for d in getattr(app,'_portalai_account_dialogs',()) if not d.closed]
                    if not dialogs:
                        app.after(50,cancel);return
                    state['state']=state['gate'].controller.status()['state']
                    state['visible']=bool(dialogs[-1].win.winfo_ismapped())
                    dialogs[-1].close()
                app.after(200,cancel)
                def timeout():
                    state['timeout']=True;app.destroy()
                app.after(10000,timeout)
                return app
            scoped=source.replace('Local\\\\Zhandragon.PortableAI.ControlCenter','Local\\\\PortalAI.GateFixture.'+uuid.uuid4().hex)
            namespace={'__name__':'gate_fixture','__file__':str(ROOT/'ControlCenter/PortableAI_GUI.py')}
            try:
                with patch.object(sys,'argv',['fixture','--root',str(fixture)]), \
                     patch.object(tk,'Tk',make_tk), \
                     patch.object(account_gate.GUIAccountGate,'__init__',initialize), \
                     patch.object(native_chat.NativeChat,'__init__',side_effect=AssertionError('Private chat constructed before login')), \
                     patch.object(settings_page.SettingsPage,'__init__',side_effect=AssertionError('Private settings constructed before login')):
                    exec(compile(scoped,namespace['__file__'],'exec'),namespace)
                    result=namespace['main']()
                assert result==0 and state.get('state')==expected and state.get('visible') and not state.get('timeout'),state
                assert not (fixture/'Private/Accounts/registry.json').exists()
                if expected=='recovery_required':assert (fixture/'Outputs/legacy.txt').read_text()=='Synthetic legacy record'
                results.append({'state':expected,'dialog_visible':True,'cancel_returned':True,'private_ui_constructed':False})
            finally:
                try:state['app'].destroy()
                except tk.TclError:pass
    (parent/'startup-states.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    return results

if __name__=='__main__':print(json.dumps(run(),indent=2))
