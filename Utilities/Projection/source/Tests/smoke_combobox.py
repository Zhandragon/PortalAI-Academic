"""Actual readonly Tk combobox popup through the standalone target adapter."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import sys,os,json,threading,time,tempfile,faulthandler
from unittest.mock import patch
MODULE=Path(__file__).resolve().parents[1];PORTAL=default_target()
sys.path[:0]=[str(MODULE/'app'),str(PORTAL/'Agent'),str(PORTAL/'ControlCenter')]


def main():
    import tkinter as tk
    from tkinter import ttk
    from remote_desktop_input import InputAdapter
    from profile_shutdown import _snapshot
    import portalai_target
    faulthandler.dump_traceback_later(15,exit=True)
    app=tk.Tk();app.title('Synthetic PortalAI dropdown');app.geometry('700x450+60+60')
    combo=ttk.Combobox(app,values=['Fixture first','Fixture second','Fixture third'],state='readonly');combo.pack(pady=40);combo.current(0);app.update()
    result={};errors=[];row=_snapshot()[os.getpid()]
    with tempfile.TemporaryDirectory(dir=MODULE/'Tests/Validation') as temporary:
        scope=Path(temporary);adapter=InputAdapter(app,scope);manager=portalai_target.Manager(PORTAL if os.name!='nt' else scope);manager.endpoint_dir=scope;manager.inventory=lambda fresh=False:{os.getpid():row}
        def worker():
            try:
                time.sleep(.5);screen=manager.frame({'viewer':'synthetic-combobox-viewer'})
                result['classes']=[(x['class'],x['width'],x['height']) for x in manager.windows.values()]
                key=min(manager.windows,key=lambda k:manager.windows[k]['width']*manager.windows[k]['height']);item=manager.windows[key]
                result['popup_size']=[item['width'],item['height']]
                result['auto_selected_popup']=screen['window']==key
                assert result['auto_selected_popup'] and screen['native_dialog'],result
                for action in ('down','up'):manager.input({'viewer':'synthetic-combobox-viewer','window':key,'event':{'kind':'pointer','action':action,'x':25,'y':28}})
                time.sleep(.2)
            except Exception as exc:errors.append(repr(exc))
            finally:
                result['done']=True
                print(json.dumps({'stage':'dropdown_input_done','errors':errors}),flush=True)
        def check():
            if result.get('done'):
                result['value']=combo.get();app.tk.call('ttk::combobox::Unpost',combo);app.destroy()
            else:app.after(40,check)
        app.after(50,check);app.after(100,lambda:app.tk.call('ttk::combobox::Post',combo));threading.Thread(target=worker,daemon=True).start()
        app.after(8000,app.quit)
        with patch.object(portalai_target,'gui_row',side_effect=lambda root,item:item['pid']==os.getpid()):app.mainloop()
    if errors:raise RuntimeError('; '.join(errors)+' '+json.dumps(result))
    assert result['value']=='Fixture second',result
    result.update(passed=True,synthetic_only=True)
    (MODULE/'Tests/Validation/combobox-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':main()
