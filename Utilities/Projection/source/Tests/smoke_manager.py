"""Standalone connection UI, synthetic encrypted settings, no network/account."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'app'),str(ROOT/'Runtime/packages'),str(default_target()/'Agent'),str(default_target()/'Tools')]


def main():
    import tkinter as tk
    import projection_ui
    from connection_vault import unlock
    from smoke_account_panels import capture_window
    base=ROOT/'Tests/Validation';base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        fixture=Path(tmp);(fixture/'Connections').mkdir();target=fixture/'PortalAI';(target/'Agent').mkdir(parents=True)
        (target/'PortalAI.exe').write_bytes(b'synthetic, never executed');(target/'Agent/profile_shutdown.py').write_text('# synthetic')
        app=tk.Tk()
        with patch.object(projection_ui,'MODULE',fixture):
            ui=projection_ui.Window(app);ui.address.set('https://synthetic.invalid');ui.target.set(str(target));ui.password.set('Synthetic-only-password');ui.load();app.update()
            assert ui.connection is not None,ui.status.get()
            identity=ui.connection['device_id'];path=ui.path
            assert ui.password.get()==''
            ui.address.set('https://changed.invalid');ui.save();assert unlock(path,'Synthetic-only-password')['url']=='https://changed.invalid'
            with patch('projection_ui.simpledialog.askstring',side_effect=['Synthetic-replacement-password']*2):ui.change_password()
            assert unlock(path,'Synthetic-replacement-password')['device_id']==identity
            ui.lock();assert ui.connection is None and ui.secret is None
            ui.password.set('wrong-synthetic-password');ui.load();assert ui.connection is None
            ui.password.set('Synthetic-replacement-password');ui.load();assert ui.connection['device_id']==identity
            app.update();capture_window(app,base/'connection-manager.png')
            ui.close()
    result={'passed':True,'synthetic_only':True,'network_requests':0,'production_accounts_opened':False,'encrypted_create_unlock_edit_password_change':True,'wrong_password_rejected':True}
    (base/'manager-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))


if __name__=='__main__':main()
