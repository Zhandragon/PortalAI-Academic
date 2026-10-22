"""Real Windows file dialog; only a disposable validation text file is opened."""
import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import sys
import threading
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','HomeAssistant','Tools')]


def main():
    import faulthandler,tkinter as tk
    from tkinter import filedialog
    from windows_desktop import Desktop
    from profile_shutdown import _windows_snapshot
    from validation_artifacts import ValidationArtifacts
    faulthandler.dump_traceback_later(18,exit=True)
    artifacts=ValidationArtifacts(ROOT,ROOT/'Maintenance/Validation/HomeAssistantFileDialog')
    target=artifacts.path('synthetic.txt');target.write_text('Disposable remote file selection')
    app=tk.Tk();app.geometry('600x450+40+40');app.update()
    desktop=Desktop();row=_windows_snapshot()[os.getpid()];results={};errors=[]
    def worker():
        try:
            deadline=time.monotonic()+8
            while True:
                dialogs=[v for v in desktop.windows({os.getpid():row}) if v['class']=='#32770' and v['visible']]
                if dialogs:break
                if time.monotonic()>deadline:raise TimeoutError('No synthetic file dialog')
                time.sleep(.05)
            window=dialogs[0];window['executable']=row['executable']
            data,_,_=desktop.capture(window);artifacts.path('dialog.png').write_bytes(data)
            children=[]
            @desktop.callback
            def visit(hwnd,_):
                name=c.create_unicode_buffer(128);desktop.u.GetClassNameW(hwnd,name,128)
                if desktop.u.IsWindowVisible(hwnd):children.append((hwnd,name.value))
                return True
            desktop.u.EnumChildWindows.argtypes=[w.HWND,desktop.callback,w.LPARAM]
            desktop.u.GetDlgCtrlID.argtypes=[w.HWND];desktop.u.GetDlgCtrlID.restype=c.c_int
            desktop.u.EnumChildWindows(window['hwnd'],visit,0)
            edits=[h for h,cls in children if cls=='Edit']
            # The Windows common dialog's filename edit lives under control
            # 1148 (file name combo); avoid its search/address fields.
            desktop.u.GetParent.argtypes=[w.HWND];desktop.u.GetParent.restype=w.HWND
            edit=next((h for h in edits if desktop.u.GetDlgCtrlID(desktop.u.GetParent(h))==1148),None)
            if edit is None:raise RuntimeError('Filename field could not be identified')
            def click(hwnd):
                rect=w.RECT();desktop.u.GetWindowRect(hwnd,c.byref(rect));point=w.POINT(rect.left+8,rect.top+8)
                desktop.u.ScreenToClient(window['hwnd'],c.byref(point))
                for action in ('down','up'):desktop.input(window,{'kind':'pointer','action':action,'x':point.x,'y':point.y})
            click(edit);time.sleep(.15);desktop.input(window,{'kind':'text','text':str(target)})
            time.sleep(.15)
            opened=next(h for h,cls in children if cls=='Button' and desktop.u.GetDlgCtrlID(h)==1)
            click(opened);results['input_sent']=True
        except Exception as exc:
            errors.append(str(exc))
            for window in desktop.windows({os.getpid():row}):
                if window['class']=='#32770':window['executable']=row['executable'];desktop.close(window)
    thread=threading.Thread(target=worker,daemon=True)
    def choose():
        thread.start()
        results['selected']=filedialog.askopenfilename(parent=app,initialdir=str(artifacts.base),title='PortalAI synthetic file selection')
        app.destroy()
    app.after(100,choose);app.mainloop();thread.join(3)
    if errors:raise RuntimeError('; '.join(errors))
    assert Path(results['selected']).resolve()==target,results
    results['passed']=True;artifacts.path('result.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
    faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':main()
