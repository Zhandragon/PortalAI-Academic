"""Bounded real native menu capture/control; only this fixture's process."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import sys,os,json,threading,time,faulthandler
from unittest.mock import patch
MODULE=Path(__file__).resolve().parents[1];PORTAL=default_target()
sys.path[:0]=[str(MODULE/'app'),str(PORTAL/'Agent')]


def main():
    import tkinter as tk
    import portalai_target
    from profile_shutdown import _windows_snapshot
    faulthandler.dump_traceback_later(15,exit=True)
    app=tk.Tk();app.title('Synthetic PortalAI native menu');app.geometry('700x450+60+60')
    chosen=[];menu=tk.Menu(app,tearoff=False);menu.add_command(label='Disabled fixture action',state='disabled',command=lambda:chosen.append(False));menu.add_separator();menu.add_command(label='Synthetic menu action',command=lambda:chosen.append(True));menu.add_command(label='Cancel',command=lambda:None)
    app.update();row=_windows_snapshot()[os.getpid()]
    manager=portalai_target.Manager(PORTAL);manager.inventory=lambda fresh=False:{os.getpid():row}
    result={};errors=[]
    def worker():
        try:
            time.sleep(.7)
            frame=manager.frame({'viewer':'synthetic-menu-viewer'})
            selected=manager.windows[frame['window']];result['class']=selected['class']
            result['classes']=[item['class'] for item in manager.windows.values()]
            assert selected['class']=='#32768',result
            assert frame['native_dialog']
            try:manager.input({'viewer':'synthetic-menu-viewer','window':frame['window'],'event':{'kind':'pointer','action':'up','x':20,'y':12}})
            except ValueError:result['disabled_refused']=True
            import ctypes as c
            from ctypes import wintypes as w
            handle=c.c_size_t();u=manager.desktop.u
            u.SendMessageTimeoutW(selected['hwnd'],0x1e1,0,0,2,1000,c.byref(handle))
            u.GetMenuItemRect.argtypes=[w.HWND,w.HANDLE,w.UINT,c.POINTER(w.RECT)];rect=w.RECT()
            assert u.GetMenuItemRect(None,handle.value,2,c.byref(rect))
            point=w.POINT((rect.left+rect.right)//2,(rect.top+rect.bottom)//2);u.ScreenToClient(selected['hwnd'],c.byref(point))
            for action in ('move','down','up'):
                result['last_action']=action
                manager.input({'viewer':'synthetic-menu-viewer','window':frame['window'],'event':{'kind':'pointer','action':action,'x':point.x,'y':point.y}})
                time.sleep(.1)
        except Exception as exc:errors.append(repr(exc))
        finally:
            result['done']=True
            print(json.dumps({'stage':'menu_input_done','chosen':chosen,'errors':errors}),flush=True)
    def check():
        if result.get('done'):
            result['selected']=bool(chosen);menu.unpost();app.destroy()
        else:app.after(40,check)
    def popup():
        try:menu.tk_popup(app.winfo_rootx()+50,app.winfo_rooty()+50)
        finally:menu.grab_release()
    app.after(50,check);app.after(100,popup);threading.Thread(target=worker,daemon=True).start()
    with patch.object(portalai_target,'gui_row',side_effect=lambda root,item:item['pid']==os.getpid()):app.mainloop()
    if errors:raise RuntimeError('; '.join(errors)+' '+json.dumps(result))
    assert result['selected'] and result['disabled_refused'] and chosen==[True],result
    result.update(passed=True,synthetic_only=True)
    (MODULE/'Tests/Validation/native-menu-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':main()
