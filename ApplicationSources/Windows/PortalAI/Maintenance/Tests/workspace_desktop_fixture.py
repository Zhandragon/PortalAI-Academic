"""A disposable owned window for actual mouse/key/window acceptance."""
import json,sys,tkinter as tk
from pathlib import Path
base=Path(sys.argv[1]);app=tk.Tk();app.title('PortalAI synthetic computer-use fixture');app.geometry('640x360+80+80')
entry=tk.Entry(app,font=('Arial',18));entry.pack(fill='x',padx=30,pady=30)
status=tk.Label(app,text='Waiting for test input',font=('Arial',16));status.pack(pady=20)
def save():
    value=entry.get();(base/'desktop-result.json').write_text(json.dumps({'text':value}));status.configure(text='Saved: '+value)
button=tk.Button(app,text='Save synthetic text',command=save,font=('Arial',16));button.pack(pady=15)
app.lift();app.focus_force();app.update()
import ctypes
from ctypes import wintypes
u=ctypes.WinDLL('user32');u.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];u.GetAncestor.restype=wintypes.HWND
hwnd=int(u.GetAncestor(entry.winfo_id(),2))
rect=wintypes.RECT();u.GetWindowRect(wintypes.HWND(hwnd),ctypes.byref(rect))
(base/'desktop-window.json').write_text(json.dumps({'window':hwnd,'entry':[entry.winfo_rootx()+30-rect.left,entry.winfo_rooty()+15-rect.top],
    'button':[button.winfo_rootx()+50-rect.left,button.winfo_rooty()+15-rect.top]}))
app.after(120000,app.destroy);app.mainloop()
