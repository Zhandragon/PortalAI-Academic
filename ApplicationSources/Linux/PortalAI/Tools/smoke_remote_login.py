"""Real disposable launcher login/seal with the optional remote adapter active."""
import ctypes
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent')]


def main():
    import tkinter as tk
    import remote_desktop_input as remote
    from validation_artifacts import ValidationArtifacts
    from smoke_login_continuity import run
    destination=ROOT/'Maintenance/Validation/HomeAssistantLogin'
    artifacts=ValidationArtifacts(ROOT,destination)
    state={'remote_password_entries':0};original=tk.Entry.insert
    def install(app,root):
        state['adapter']=remote.InputAdapter(app,destination)
        return state['adapter']
    def insert(widget,index,text):
        adapter=state.get('adapter')
        if adapter and not state.get('inside') and str(widget.cget('show')) and text in ('incorrect-synthetic-password','Synthetic-startup-password-2026'):
            adapter.focus_target=str(widget)
            user=ctypes.WinDLL('user32');user.GetAncestor.argtypes=[ctypes.c_void_p,ctypes.c_uint];user.GetAncestor.restype=ctypes.c_void_p
            hwnd=int(user.GetAncestor(widget.winfo_toplevel().winfo_id(),2))
            state['inside']=True
            try:adapter.apply({'hwnd':hwnd,'event':{'kind':'text','text':text}})
            finally:state['inside']=False
            state['remote_password_entries']+=1
            return
        return original(widget,index,text)
    def inspector(built,app,destination):
        import time
        from smoke_account_panels import capture_window
        layout=built['remote_layout'];compact=built['portal_compact_mode'];panel=built['native_chat_panel']
        identity=panel.session
        layout.apply({'view':'portrait_chat','width':500,'height':770})
        deadline=time.monotonic()+.6
        while time.monotonic()<deadline:app.update();time.sleep(.01)
        assert compact.active and compact.expanded and built['selected_tab']['key']=='chat'
        assert panel.session is identity
        capture_window(app,destination/'phone-portrait-chat.png')
        # Exercise the existing compact submit dispatch, while replacing only
        # its last inference-triggering method with a read-only draft capture.
        sent=[]
        with patch.object(compact,'_send_compact',side_effect=lambda:sent.append(compact._entry_var.get())):
            layout.send_chat('Synthetic portrait message')
            assert sent==['Synthetic portrait message']
            with patch.object(layout,'available',return_value=False):
                try:layout.send_chat('Must not cross account lock')
                except PermissionError:pass
                else:raise AssertionError('Account lock bypass')
            assert len(sent)==1
        compact._entry_var.set('')
        state['portrait_dispatch_and_lock_guard']=True
        layout.apply({'view':'full','width':932,'height':430})
        deadline=time.monotonic()+.4
        while time.monotonic()<deadline:app.update();time.sleep(.01)
        assert not compact.active and panel.session is identity
        capture_window(app,destination/'phone-landscape-full.png')
        layout.apply({'view':'full','width':820,'height':1000});app.update()
        assert not compact.active and panel.session is identity
        state['rotation_preserved_chat']=True
    with patch.object(remote,'install',install),patch.object(tk.Entry,'insert',insert):
        result=run(destination,inspector=inspector)
    assert state['remote_password_entries']>=2,state
    result['remote_password_entries']=state['remote_password_entries']
    result['rotation_preserved_chat']=state['rotation_preserved_chat']
    result['portrait_dispatch_and_lock_guard']=state['portrait_dispatch_and_lock_guard']
    artifacts.path('result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':main()
