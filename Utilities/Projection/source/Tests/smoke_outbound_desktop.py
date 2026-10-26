"""Actual outbound HTTPS -> receiver queue -> owned window -> Tk, synthetic only."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import base64
import faulthandler
import json
import os
import ssl
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler,HTTPServer
from unittest.mock import patch

MODULE=Path(__file__).resolve().parents[1]
PORTAL=default_target()
sys.path[:0]=[str(MODULE/'Tests'),str(MODULE/'app'),str(MODULE/'Runtime/packages'),str(PORTAL/'Agent'),str(PORTAL/'ControlCenter'),str(PORTAL/'HomeAssistant')]
if os.name!='nt':sys.path.insert(0,str(MODULE/'Runtime/LinuxPackages'))


def main():
    import tkinter as tk
    from tkinter import ttk
    from test_projection import receiver
    from connection_vault import new_connection,public_pairing
    from projection_client import Client
    from setup_pairing import create
    from remote_desktop_input import InputAdapter
    from profile_shutdown import _snapshot
    import portalai_target
    portalai_target.configure(PORTAL)
    faulthandler.dump_traceback_later(45,exit=True)
    destination=MODULE/'Tests/Validation';destination.mkdir(exist_ok=True)
    app=tk.Tk();app.title('PortalAI outbound projection — disposable fixture');app.geometry('800x600+40+40')
    entry=ttk.Entry(app);entry.pack(pady=25);clicked=[];returns=[]
    button=ttk.Button(app,text='Synthetic action',command=lambda:clicked.append(True));button.pack()
    entry.bind('<Return>',lambda _event:returns.append(True));app.update()
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        root=Path(temporary);scope=root/'input';scope.mkdir()
        adapter=InputAdapter(app,scope)
        row=_snapshot()[os.getpid()]
        manager=portalai_target.Manager(PORTAL if os.name!='nt' else root);manager.endpoint_dir=scope
        manager.inventory=lambda fresh=False:{os.getpid():row}
        certificates=root/'certificates';create(certificates,'127.0.0.1','127.0.0.1',18791)
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(certificates/'server.crt',certificates/'server.key')
        connection=new_connection('https://example.invalid','../PortalAI','Synthetic outbound')
        identity,public=receiver.pairing(public_pairing(connection));state=receiver.Receiver({identity:public})
        headers=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                try:
                    assert self.path=='/api/portalai_projection/v1'
                    headers.append(dict(self.headers))
                    value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if value['action']=='challenge':result=state.challenge(value['device_id'])
                    elif value['action']=='authenticate':result=state.authenticate(value)
                    else:result=state.poll(self.headers.get('X-PortalAI-Session'),value)
                    data=json.dumps(result).encode();self.send_response(200)
                except Exception as exc:data=json.dumps({'error':str(exc)}).encode();self.send_response(400)
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        server=HTTPServer(('127.0.0.1',0),Handler);server.socket=context.wrap_socket(server.socket,server_side=True)
        serving=threading.Thread(target=server.serve_forever,daemon=True);serving.start()
        client=Client({**connection,'url':f'https://127.0.0.1:{server.server_port}'},certificates/'ca.crt')
        coords={str(widget):(widget.winfo_rootx()-app.winfo_rootx()+10,widget.winfo_rooty()-app.winfo_rooty()+10) for widget in (entry,button)}
        result={};errors=[]
        def send(event):
            key=state.enqueue(identity,'input',{'window':result['window'],'event':event})
            commands=client.poll(None,manager.status(),[])
            assert len(commands)==1 and commands[0]['id']==key
            reply=manager.input({**commands[0]['payload'],'viewer':identity})
            client.poll(None,manager.status(),[{'id':key,'result':reply}])
            assert state.devices[identity]['replies'][key]['result']['accepted']
            state.forget(identity,key)
        def worker():
            try:
                client.authenticate()
                screen=manager.frame({'viewer':identity});client.poll(screen,manager.status(),[])
                received=state.lease(identity,'synthetic-ha-viewer')['frame']
                assert received['png']==screen['png'];result['window']=received['window']
                (destination/'outbound-window.png').write_bytes(base64.b64decode(received['png']))
                result['capture']=[received['width'],received['height']]
                for widget in (entry,button):
                    x,y=coords[str(widget)]
                    send({'kind':'pointer','action':'down','x':x,'y':y});send({'kind':'pointer','action':'up','x':x,'y':y})
                    if widget is entry:
                        send({'kind':'text','text':'Outbound encrypted projection 42'});send({'kind':'key','key':'Enter'})
                send({'kind':'resize','width':650,'height':480});time.sleep(.2)
                assert all('Authorization' not in header and 'Cookie' not in header for header in headers)
            except Exception as exc:errors.append(repr(exc))
            finally:
                result['done']=True
                print(json.dumps({'stage':'commands_finished','errors':errors}),flush=True)
        def check():
            if result.get('done'):
                result.update(entry=entry.get(),button=bool(clicked),return_key=bool(returns),resize=[app.winfo_width(),app.winfo_height()]);app.destroy()
            else:app.after(40,check)
        thread=threading.Thread(target=worker,daemon=True)
        app.after(50,check);app.after(100,thread.start)
        app.after(15000,app.quit)
        try:
            with patch.object(portalai_target,'gui_row',side_effect=lambda root,item:item['pid']==os.getpid()):app.mainloop();thread.join(3)
        finally:server.shutdown();server.server_close();serving.join(3)
        if errors:raise RuntimeError('; '.join(errors))
        assert result['entry']=='Outbound encrypted projection 42',result
        assert result['button'] and result['return_key'] and result['resize']==[650,480],result
        result.update(passed=True,synthetic_only=True,real_outbound_https=True,no_ha_credentials=True,real_tk_input=True,ha_green_deployment=False)
        (destination/'outbound-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':main()
