"""Bounded actual Windows window capture/input with an isolated synthetic UI."""
import ctypes
import json
import os
from pathlib import Path
import sys
import threading
import time
import tempfile
import ssl
import urllib.request
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'HomeAssistant'),str(ROOT/'Tools'),str(ROOT/'ControlCenter')]


def main():
    import faulthandler
    faulthandler.dump_traceback_later(30,exit=True)
    import tkinter as tk
    from tkinter import ttk
    from windows_desktop import Desktop
    from profile_shutdown import _windows_snapshot
    from validation_artifacts import ValidationArtifacts
    from remote_desktop_input import InputAdapter
    destination=ROOT/'Maintenance/Validation/HomeAssistantWindow'
    artifacts=ValidationArtifacts(ROOT,destination)
    app=tk.Tk();app.title('PortalAI synthetic remote test');app.geometry('800x600+40+40')
    entry=ttk.Entry(app);entry.pack(pady=25);clicked=[]
    button=ttk.Button(app,text='Synthetic action',command=lambda:clicked.append(True));button.pack()
    returns=[];entry.bind('<Return>',lambda _e:returns.append(True))
    app.update();desktop=Desktop();row=_windows_snapshot()[os.getpid()]
    windows=desktop.windows({os.getpid():row})
    window=max(windows,key=lambda v:v['width']*v['height']);window['executable']=row['executable']
    temporary=tempfile.TemporaryDirectory(dir=destination)
    fake_root=Path(temporary.name)
    pairing=fake_root/'HomeAssistant/pairing';pairing.mkdir(parents=True)
    adapter=InputAdapter(app,pairing)
    import portalai_bridge as bridge
    from setup_pairing import create
    certificates=fake_root/'certificates';create(certificates,'127.0.0.1','127.0.0.1',18791)
    server_context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(certificates/'server.crt',certificates/'server.key')
    server_context.load_verify_locations(certificates/'ca.crt');server_context.verify_mode=ssl.CERT_REQUIRED
    client_context=ssl.create_default_context(cafile=str(certificates/'ca.crt'))
    client_context.load_cert_chain(certificates/'client.crt',certificates/'client.key')
    manager=bridge.Manager(fake_root,desktop);manager.inventory=lambda fresh=False:{os.getpid():row}
    server=bridge.Server(('127.0.0.1',0),bridge.Handler,server_context,'127.0.0.1',manager)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    def request(action,payload):
        data=json.dumps({'action':action,'payload':{'viewer':'synthetic-viewer-0123456789',**payload}}).encode()
        req=urllib.request.Request(f'https://127.0.0.1:{server.server_port}/v1/request',data=data)
        try:
            with urllib.request.urlopen(req,context=client_context,timeout=10) as response:return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'{action}: {exc.read(4096).decode()}') from exc
    def send(event):
        return request('input',{'window':results['window'],'event':event})
    results={};errors=[]
    def worker():
        try:
            import base64
            frame=request('frame',{});results['window']=frame['window']
            png=base64.b64decode(frame['png']);width,height=frame['width'],frame['height']
            (destination/'window.png').write_bytes(png);results['capture']=[width,height]
            for widget in (entry,button):
                # Coordinates captured by Tk main thread before worker starts.
                x,y=coords[str(widget)]
                send({'kind':'pointer','action':'down','x':x,'y':y});send({'kind':'pointer','action':'up','x':x,'y':y})
                time.sleep(.15)
                if widget is entry:
                    send({'kind':'text','text':'Remote login field 42'})
                    send({'kind':'key','key':'Enter'})
            time.sleep(.2)
            send({'kind':'resize','width':650,'height':480});time.sleep(.2)
            results['done']=True
        except Exception as exc:errors.append(str(exc));results['done']=True
    coords={str(widget):(widget.winfo_rootx()-app.winfo_rootx()+10,widget.winfo_rooty()-app.winfo_rooty()+10) for widget in (entry,button)}
    def check():
        if results.get('done'):
            results['entry']=entry.get();results['button']=bool(clicked);results['return_key']=bool(returns);results['resize']=[app.winfo_width(),app.winfo_height()]
            app.destroy()
        else:app.after(50,check)
    app.after(50,check);thread=threading.Thread(target=worker,daemon=True);app.after(100,thread.start)
    try:
        with patch.object(bridge,'gui_row',side_effect=lambda root,item:item['pid']==os.getpid()):app.mainloop();thread.join(3)
    finally:server.shutdown();server.server_close();temporary.cleanup()
    if errors:raise RuntimeError('; '.join(errors))
    assert results['entry']=='Remote login field 42',results
    assert results['button'] is True,results
    assert results['return_key'] is True,results
    assert results['resize']==[650,480],results
    results['synthetic_only']=True
    results['mutual_tls_bridge_to_real_tk']=True
    (destination/'result.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results))
    faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':main()
