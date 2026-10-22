"""Optional Windows Home Assistant bridge. Run with bundled Python -B -I.

Only the paired Green can connect (source IP plus mutual TLS). This process
never authenticates/decrypts profiles; login happens in the real desktop GUI.
"""
from pathlib import Path
import base64
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import secrets
import ssl
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'HomeAssistant')]
MAX_BODY=65536


def gui_row(root, row):
    return any(arg in (str(root/'ControlCenter/control_center_bootstrap.py'),str(root/'ControlCenter/PortableAI_GUI.py')) for arg in row.get('argv',[])) and Path(row.get('executable','')).resolve() in (root/'Runtime/BootstrapPython/pythonw.exe',root/'Runtime/BootstrapPython/python.exe')


class Manager:
    def __init__(self, root, desktop=None):
        self.root=Path(root).resolve()
        if desktop is None:
            from windows_desktop import Desktop
            desktop=Desktop()
        self.desktop=desktop
        self.lock=threading.RLock();self.frame_lock=threading.Lock()
        self.windows={};self.rows={};self.inventory_at=0
        self.operation={'state':'idle'};self.seen={};self.viewer=None

    def inventory(self, fresh=False):
        from profile_shutdown import _windows_snapshot
        if fresh or time.monotonic()-self.inventory_at>3:
            self.rows=_windows_snapshot();self.inventory_at=time.monotonic()
        return self.rows

    def owned(self, rows):
        from profile_shutdown import _contained, _script_owned
        from remote_lifecycle import is_bridge
        owned={p:r for p,r in rows.items() if p!=os.getpid() and not is_bridge(self.root,r)
               and (_contained(self.root,r.get('executable')) or _script_owned(self.root,r))}
        for _ in range(len(rows)):
            extra={p:r for p,r in rows.items() if p not in owned and p!=os.getpid()
                   and r.get('ppid') in owned and owned[r['ppid']]['start']<=r['start']
                   and not is_bridge(self.root,r)}
            if not extra:break
            owned.update(extra)
        return owned

    def status(self):
        from profile_shutdown import _marker
        rows=self.inventory();marker=_marker(self.root)
        with self.lock:
            return {'running':any(gui_row(self.root,r) for r in rows.values()),
                    'profile_state':marker['state'] if marker else 'no-active-profile',
                    'operation':dict(self.operation),'platform':'windows',
                    'stream':'PortalAI windows only; shared desktop login session'}

    def _lease(self, viewer):
        if not isinstance(viewer,str) or not 16<=len(viewer)<=128:raise ValueError('Missing viewer identity')
        now=time.monotonic()
        with self.lock:
            if self.viewer and self.viewer[0]!=viewer and self.viewer[1]>now:
                raise PermissionError('Another viewer controls this desktop; disconnect it or wait 30 seconds')
            self.viewer=(viewer,now+30)

    def frame(self, payload):
        self._lease(payload.get('viewer'))
        if not self.frame_lock.acquire(False):raise RuntimeError('Previous capture still pending')
        try:
            rows={p:r for p,r in self.inventory().items() if gui_row(self.root,r)}
            windows=self.desktop.windows(rows)
            current={}
            for window in windows:
                window['executable']=rows[window['pid']]['executable']
                identity=f"{window['pid']}:{window['start']}:{window['hwnd']}"
                key=hashlib.sha256(identity.encode()).hexdigest()[:32]
                current[key]=window
            with self.lock:self.windows=current
            if not current:return {'windows':[], 'status':self.status()}
            selected=payload.get('window')
            if selected not in current:
                visible=[k for k,v in current.items() if v['visible']]
                selected=next((k for k in visible if current[k]['hwnd']==self.desktop.u.GetForegroundWindow()),None)
                selected=selected or max(visible or list(current),key=lambda k:current[k]['width']*current[k]['height'])
                popup=self.desktop.u.GetLastActivePopup(current[selected]['hwnd'])
                selected=next((k for k in visible if current[k]['hwnd']==popup),selected)
            window=current[selected]
            data,width,height=self.desktop.capture(window)
            if len(data)>4*1024**2:raise RuntimeError('Capture exceeds transport limit')
            from profile_shutdown import _marker
            marker=_marker(self.root)
            return {'window':selected,'width':width,'height':height,'profile_open':bool(marker and marker['state']=='open'),
                    'native_dialog':window['class']=='#32770','png':base64.b64encode(data).decode('ascii'),
                    'windows':[{'id':k,'title':v['title']} for k,v in current.items()]}
        finally:self.frame_lock.release()

    def input(self, payload):
        self._lease(payload.get('viewer'))
        with self.lock:
            if self.operation.get('state')=='running':raise RuntimeError('Lifecycle operation in progress')
            window=self.windows.get(payload.get('window'))
            if window is None:raise ValueError('Refresh the viewer before sending input')
            self.desktop.validate(window)
            if window['class']=='#32770':
                self.desktop.input(window,payload.get('event',{}))
                return {'accepted':True}
            from runtime_policy import portable_path
            path=portable_path(self.root,f'HomeAssistant/pairing/gui-{window["pid"]}.json')
            if not path.is_file() or path.stat().st_size>4096:raise RuntimeError('Restart PortalAI normally to load the paired remote input adapter')
            endpoint=json.loads(path.read_text(encoding='utf-8'))
            if endpoint.get('pid')!=window['pid'] or type(endpoint.get('start')) is not int or endpoint['start']//10!=window['start']//10 or type(endpoint.get('port')) is not int or not 1024<=endpoint['port']<=65535:
                raise RuntimeError('Invalid GUI endpoint')
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=7)
            try:
                data=json.dumps({'hwnd':window['hwnd'],'event':payload.get('event',{}),'request_id':uuid.uuid4().hex}).encode()
                conn.request('POST','/input',data,{'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
                response=conn.getresponse();reply=response.read(4097)
                if len(reply)>4096:raise RuntimeError('Invalid GUI acknowledgement')
                result=json.loads(reply)
                if response.status!=200:raise RuntimeError(result.get('error','GUI input refused'))
            finally:conn.close()
        return {'accepted':True}

    def lifecycle(self, action, payload):
        if action not in ('start','restart','force_shutdown'):raise ValueError('Unsupported lifecycle action')
        key=payload.get('request_id','')
        if not isinstance(key,str) or uuid.UUID(key).hex!=key:raise ValueError('A unique request_id is required')
        if action=='force_shutdown' and payload.get('confirm')!='UNSAFE SHUTDOWN':
            raise PermissionError('Explicit unsafe shutdown confirmation required')
        with self.lock:
            if key in self.seen:return dict(self.seen[key])
            if self.operation.get('state')=='running':raise RuntimeError('Another lifecycle operation is running')
            self.operation={'state':'running','action':action,'request_id':key,'message':'Request accepted'}
            self.seen[key]=self.operation
            if len(self.seen)>128:self.seen.pop(next(iter(self.seen)))
            threading.Thread(target=self._operate,args=(action,key),name='PortalAI-remote-lifecycle',daemon=True).start()
            return dict(self.operation)

    def _launch(self):
        from remote_lifecycle import clean_environment
        if any(gui_row(self.root,r) for r in self.inventory(True).values()):return
        subprocess.Popen([str(self.root/'PortalAI.exe')],cwd=self.root,env=clean_environment(),
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.DETACHED_PROCESS)

    def _operate(self, action, key):
        from profile_shutdown import _marker, _windows_stop, _fence
        try:
            rows=self.inventory(True);guis={p:r for p,r in rows.items() if gui_row(self.root,r)}
            if action=='force_shutdown':
                from remote_lifecycle import force_fence
                force_fence(self.root);_fence(self.root)
                for _ in range(4):
                    remaining=self.owned(self.inventory(True))
                    if not remaining:break
                    for row in sorted(remaining.values(),key=lambda r:r['start'],reverse=True):
                        _windows_stop(row,self.root)
                if self.owned(self.inventory(True)):raise RuntimeError('Owned processes remain; forced shutdown incomplete')
                message='Forced shutdown completed. Profile was NOT sealed. Recovery and review may be required at next login.'
            else:
                prior=_marker(self.root)
                if action=='restart' and guis:
                    windows=self.desktop.windows(guis)
                    for pid,row in guis.items():
                        candidates=[v for v in windows if v['pid']==pid and v['class']=='TkTopLevel']
                        if not candidates:raise RuntimeError('No owned PortalAI close target; use Force Shutdown only if necessary')
                        window=max(candidates,key=lambda v:v['width']*v['height'])
                        window['executable']=row['executable'];self.desktop.close(window)
                    deadline=time.monotonic()+180
                    while self.owned(self.inventory(True)):
                        if time.monotonic()>=deadline:raise TimeoutError('Normal shutdown did not finish in 180 seconds; nothing was forcibly terminated or reopened')
                        time.sleep(.5)
                    marker=_marker(self.root)
                    if prior and prior['state']!='closed' and (not marker or marker['state']!='closed' or marker['epoch']!=prior['epoch']):
                        raise RuntimeError('Shutdown did not prove profile sealing; restart refused')
                elif action=='restart' and self.owned(rows):
                    raise RuntimeError('GUI is absent but owned workers remain. Use explicit Force Shutdown before opening recovery login')
                self._launch()
                deadline=time.monotonic()+25
                while not any(gui_row(self.root,r) for r in self.inventory(True).values()):
                    if time.monotonic()>=deadline:raise TimeoutError('Launcher started but GUI readiness was not observed')
                    time.sleep(.5)
                message='PortalAI opened. Sign in through the viewer.'
                if not guis and prior and prior['state']!='closed':message+=' Previous crash left an unsealed profile; normal authenticated recovery is required.'
            result={'state':'complete','action':action,'request_id':key,'message':message}
        except Exception as exc:
            result={'state':'failed','action':action,'request_id':key,'message':str(exc)}
        with self.lock:self.operation=result;self.seen[key]=result;self.inventory_at=0


class Server(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=False
    def __init__(self,address,handler,context,allowed,manager):
        self.context=context;self.allowed=allowed;self.manager=manager
        self.slots=threading.BoundedSemaphore(4)
        super().__init__(address,handler)
    def get_request(self):
        sock,address=super().get_request();sock.settimeout(8)
        if address[0]!=self.allowed:
            sock.close();raise OSError('Source refused')
        try:return self.context.wrap_socket(sock,server_side=True),address
        except Exception:sock.close();raise
    def process_request(self,request,address):
        if not self.slots.acquire(False):self.shutdown_request(request);return
        try:super().process_request(request,address)
        except BaseException:self.slots.release();raise
    def process_request_thread(self,request,address):
        try:super().process_request_thread(request,address)
        finally:self.slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version='PortalAI';sys_version=''
    def log_message(self,*_):pass  # No screenshots, keystrokes, or credentials in logs.
    def do_POST(self):
        try:
            if self.path!='/v1/request':raise ValueError('Unknown endpoint')
            if self.headers.get('Transfer-Encoding'):raise ValueError('Chunked requests refused')
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=MAX_BODY:raise ValueError('Invalid request size')
            data=self.rfile.read(length)
            if len(data)!=length:raise ValueError('Incomplete request')
            value=json.loads(data)
            if not isinstance(value,dict):raise ValueError('Object required')
            action=value.get('action');payload=value.get('payload',{})
            if not isinstance(payload,dict):raise ValueError('Object required')
            manager=self.server.manager
            if action=='status':result=manager.status()
            elif action=='frame':result=manager.frame(payload)
            elif action=='input':result=manager.input(payload)
            elif action=='disconnect':
                with manager.lock:
                    if manager.viewer and manager.viewer[0]==payload.get('viewer'):manager.viewer=None
                result={'disconnected':True}
            elif action in ('start','restart','force_shutdown'):result=manager.lifecycle(action,payload)
            else:raise ValueError('Unsupported action')
            self.reply(200,result)
        except (ValueError,KeyError,TypeError,PermissionError,RuntimeError,TimeoutError,OSError) as exc:
            self.reply(400,{'error':str(exc)[:500]})
    def reply(self,status,value):
        body=json.dumps(value,ensure_ascii=True).encode('utf-8')
        self.send_response(status);self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
        self.send_header('Connection','close');self.end_headers();self.wfile.write(body)


def main():
    raise RuntimeError('Retired LAN prototype. Use the separate PortalAI-Projection module.')
    if os.name!='nt':raise RuntimeError('This window-streaming adapter currently supports Windows only')
    from runtime_policy import portable_path
    from mission_runner import process_lock
    folder=portable_path(ROOT,'HomeAssistant/pairing')
    config=json.loads((folder/'bridge.json').read_text(encoding='utf-8'))
    import ipaddress
    for field in ('bind_host','ha_host'):ipaddress.IPv4Address(config[field])
    if not 1024<=int(config['port'])<=65535:raise ValueError('Invalid port')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(str(folder/'server.crt'),str(folder/'server.key'))
    context.load_verify_locations(str(folder/'ca.crt'));context.verify_mode=ssl.CERT_REQUIRED
    os.environ.clear();os.environ.update(_initial_environment)
    with process_lock(folder/'bridge.lock'):
        server=Server((config['bind_host'],config['port']),Handler,context,config['ha_host'],Manager(ROOT))
        try:server.serve_forever(poll_interval=.5)
        finally:server.server_close()


if __name__=='__main__':
    from remote_lifecycle import clean_environment
    _initial_environment=clean_environment()
    main()
