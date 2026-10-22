"""Opt-in native v2 GUI exporter. Read-only loopback; private state stays in RAM.

No model probes, profile hydration, effects, HA credentials or device keys.
Tk copies already loaded state; HTTP never calls Tk or waits for an input ack.
"""
import ctypes
from ctypes import wintypes
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import secrets
import threading
import time
import uuid

from native_ui_protocol import (PROTOCOL, MAX_FRAME, LEASE_MS, MEDIA, encode, decode,
                                fields, identifier, validate_snapshot)


def clip(value, limit=160):
    value = value if isinstance(value, str) else ''
    # Bound work before encoding: one code point consumes at least one UTF-16
    # unit. A huge saved turn must not make each GUI heartbeat encode it all.
    value = value[:limit].encode('utf-8', 'replace').decode('utf-8')
    return value.encode('utf-16-le')[:limit*2].decode('utf-16-le', 'ignore')


def percent(value):
    return value if type(value) in (float,int) and math.isfinite(value) and 0 <= value <= 100 else None


def bounded_int(value, low, high):
    return value if type(value) is int and low <= value <= high else None


def process_identity():
    if os.name != 'nt':
        from linux_process import identity
        return identity(os.getpid())['start_ticks']
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)]*4)]
    times = [wintypes.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(kernel.GetCurrentProcess(), *[ctypes.byref(t) for t in times]):
        raise OSError('process_identity')
    return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime


class Exporter:
    def __init__(self, app, root, gate, chat, settings, folder, hwnd):
        self.app=app; self.root=Path(root).resolve(); self.gate=gate; self.chat=chat; self.settings=settings
        self.thread_id=threading.get_ident(); self.lock=threading.RLock(); self.closed=False
        self.token=secrets.token_urlsafe(32); self.sample=None; self.sample_at=0.; self.timer=None
        self.session=None; self.profile=None; self.view=''; self.epoch=''; self.revision=0
        self.cache=None; self.published_at=0.; self.mode=None; self.observed={}
        self._rotate('locked')
        self.reauthorize()  # Real backend validation before publishing an endpoint.
        self.path=Path(folder)/('native-gui-'+str(os.getpid())+'.json')
        self.path_identity=None
        exporter=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_): pass
            def do_POST(self):
                try:
                    if self.headers.get('Origin') or not hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+exporter.token):
                        raise PermissionError('capability')
                    if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                        raise ValueError('request')
                    length=int(self.headers['Content-Length'])
                    if not 0 < length <= 2048: raise ValueError('request')
                    request=decode(self.rfile.read(length))
                    result=exporter.request(self.path, request)
                    data=encode(result); status=200
                    # A response prepared concurrently with lock/expiry is refused.
                    if not exporter.response_current(result): raise PermissionError('revoked')
                except (OSError,ValueError,TypeError,KeyError,RuntimeError,PermissionError):
                    data=b'{"error":"native_state_unavailable_or_revoked"}'; status=409
                self.send_response(status)
                self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(data))); self.send_header('Connection','close')
                self.end_headers()
                try: self.wfile.write(data)
                except OSError: pass
        class Server(HTTPServer):
            def get_request(self):
                sock,address=super().get_request(); sock.settimeout(2); return sock,address
        self.server=Server(('127.0.0.1',0),Handler)
        try:
            from runtime_policy import atomic_json
            # Folder was validated by the prelogin opt-in consumer. Reject links
            # again at publication, including an existing endpoint replacement.
            if self.path.parent.is_symlink() or getattr(self.path.parent,'is_junction',lambda:False)() or self.path.is_symlink():
                raise ValueError('linked_endpoint')
            atomic_json(self.path, {'version':2,'protocol':PROTOCOL,'scope':'native.state.read',
                'pid':os.getpid(),'start':process_identity(),'hwnd':hwnd,
                'port':self.server.server_port,'token':self.token})
            self.path_identity=self.path.stat()
        except BaseException:
            self.server.server_close(); raise
        self.server_thread=threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':.05},
                                            name='PortalAI-native-state-read', daemon=True)
        self.server_thread.start()
        self.app.bind('<Destroy>',self._destroy,add='+')
        self.tick()

    def _rotate(self, state):
        # Called under the reentrant lock; no account fields in a revoked cache.
        self.view=uuid.uuid4().hex; self.epoch=uuid.uuid4().hex; self.revision=0; self.mode=state
        self.cache={'version':2,'view':self.view,'epoch':self.epoch,'revision':0,
                    'account':{'state':state,'displayName':''}}
        self.published_at=time.monotonic()

    def invalidate(self, state=None):
        with self.lock:
            if state is None: state=self.mode if self.mode in ('locked','switching','closing') else 'locked'
            if state not in ('locked','switching','closing'): state='locked'
            if self.mode != state: self._rotate(state)
            self.observed={}; self.sample=None; self.sample_at=0.

    def reauthorize(self):
        from account_permissions import require_user
        from local_accounts import Session
        from profile_context import CapturedProfile
        session=getattr(self.gate,'session',None)
        if not isinstance(session,Session) or require_user(self.root,session) is not session:
            raise PermissionError('real_session_required')
        profile=CapturedProfile(self.root)
        if profile.identity is None: raise PermissionError('real_profile_required')
        with self.lock:
            self._rotate('locked'); self.session=session; self.profile=profile

    def allowed(self, *, authenticate=False):
        if self.closed or self.gate.locked or self.gate.session is not self.session:
            return False
        if not getattr(self.app,'_portalai_main_ready',False): return False
        # Management forms retain the authenticated account binding. Startup,
        # switch and closing gates still revoke it; quick chat blocks modals.
        if any(not d.closed and (not getattr(d,'native_management',False) or getattr(getattr(d,'surface',None),'startup',True))
               for d in getattr(self.app,'_portalai_account_dialogs',())): return False
        if getattr(self.chat,'_closing',False): return False
        try:
            store=self.session._store()
            if store is None or not self.session._active: return False
            if self.session._expires is not None and store.clock()>=self.session._expires: return False
            self.profile.check()
            if authenticate:
                from account_permissions import require_user
                if require_user(self.root,self.session) is not self.session: return False
            return True
        except (OSError,ValueError,RuntimeError,PermissionError):
            return False

    def observe(self, data):
        if threading.get_ident()!=self.thread_id: raise RuntimeError('GUI_thread_required')
        # Only public inventory/telemetry inputs are cached. No argv, raw policy,
        # paths, process rows or arbitrary dictionaries leave the main monitor.
        telemetry=data.get('telemetry',{})
        models=[]
        model_rows=data.get('settings_models',[])
        package_rows=data.get('installed',{})
        if len(model_rows)>100 or len(package_rows)>100: raise ValueError('inventory_limit')
        for row in model_rows:
            mid=row.get('id'); identifier(mid,model=True)
            models.append({'id':mid,'name':clip(row.get('label',mid)),'kind':'Chat',
                           'installed':row.get('installed') is True,'selected':False,'state':'unknown'})
        packages=[]
        for key, value in package_rows.items():
            identifier(key,model=True)
            state=value[0] if isinstance(value,(list,tuple)) and value else ''
            packages.append({'id':key,'name':clip(key.replace('_',' ').title()),'purpose':'Installed component inventory',
                             'state':'available' if state=='INSTALLED' else 'unavailable' if state in ('NOT INSTALLED','MISSING') else 'unvalidated'})
        observed={'cpu':percent(telemetry.get('cpu')),'gpu':percent(telemetry.get('gpu')),
                  'memory':percent(telemetry.get('ram')),'models':models,'packages':packages}
        with self.lock:
            self.observed=observed; self.sample_at=time.monotonic()

    def collect(self):
        """GUI thread only. Never invoke a chat/catalog/profile I/O accessor."""
        panel=self.chat; saved=dict(self.settings.saved_values)
        options=dict(panel.settings)
        current=panel.session if not getattr(panel,'_session_load_request',None) else None
        current=current if isinstance(current,dict) else None
        sid=current.get('id') if current else None
        if sid is not None: identifier(sid)
        chat={'conversations':[],'current':sid,'messages':[],'busy':bool(panel.busy) if sid else False,
              'contextUsed':None,'contextLimit':None,'replyCap':None,
              'window':{'conversationsComplete':False,'messagesComplete':True}}
        if sid:
            chat['conversations']=[{'id':sid,'title':clip(current.get('title') or 'Untitled chat'),'updated':''}]
            raw=current.get('messages') or []
            if not isinstance(raw,list): raise ValueError('messages')
            chat['window']['messagesComplete']=len(raw)<=100
            for index in range(max(0,len(raw)-100),len(raw)):
                row=raw[index]
                if not isinstance(row,dict) or row.get('role') not in ('user','assistant'): continue
                content=row.get('content')
                if not isinstance(content,str):
                    # No attachment paths/data URIs/tool arguments are serialized.
                    chat['window']['messagesComplete']=False; continue
                clipped=clip(content,16000)
                chat['messages'].append({'id':hashlib.sha256((self.epoch+':'+sid+':'+str(index)).encode()).hexdigest()[:32],
                    'role':row['role'],'text':clipped,'truncated':clipped!=content})
            meta=panel._last_context_meta or {}
            if meta.get('session_id')==sid:
                chat['contextUsed']=bounded_int(meta.get('estimated_input'),0,1048576)
                chat['contextLimit']=bounded_int(meta.get('model_limit'),1,1048576)
            if chat['contextLimit'] is None:
                chat['contextLimit']=bounded_int(panel._model_context_limit,1,1048576)
            # Do not clamp an over-budget observation into a fabricated value.
            if chat['contextLimit'] is not None and chat['contextUsed'] is not None and chat['contextUsed']>chat['contextLimit']:
                chat['contextUsed']=None
            admitted=meta.get('output_reserve') if meta.get('session_id')==sid else None
            chat['replyCap']=bounded_int(admitted,1,32768)
        model_state=getattr(panel,'_cached_model_state','offline')
        state={'ready':'ready','sleeping':'sleeping','starting':'starting','stopping':'stopping','busy':'ready'}.get(model_state,'unavailable')
        name=clip(getattr(panel,'_cached_model_name',''))
        if '/' in name or '\\' in name: name=''
        observed=self.observed if time.monotonic()-self.sample_at<=20 else {}
        models=[dict(row,selected=row['id']==saved['selection']) for row in observed.get('models',[])]
        settings={'selection':saved['selection'],'variant':saved['variant_preference'],'backend':saved['backend'],
                  'context':int(saved['context_tokens']),'reply':int(options.get('max_output_tokens',2048)),
                  'effort':str(getattr(getattr(panel,'effort',None),'profile','balanced')).title(),
                  'media':{key:saved[key] for key in MEDIA}}
        result={'version':2,'view':self.view,'epoch':self.epoch,'revision':self.revision,
            'account':{'state':'ready','displayName':clip(self.session.username)},
            'runtime':{'state':state,'cpu':observed.get('cpu'),'gpu':observed.get('gpu'),
                       'memory':observed.get('memory'),'model':name},
            'models':models,'packages':observed.get('packages',[]),'chat':chat,'settings':settings}
        size=len(json.dumps(result,ensure_ascii=False).encode('utf-8'))
        while size>MAX_FRAME-2048 and chat['messages']:
            removed=chat['messages'].pop(0)
            size-=len(json.dumps(removed,ensure_ascii=False).encode('utf-8'))+2
            chat['window']['messagesComplete']=False
        validate_snapshot(result); encode(result)
        return result

    def tick(self):
        if self.closed: return
        if threading.get_ident()!=self.thread_id: raise RuntimeError('GUI_thread_required')
        try:
            if not self.allowed(): self.invalidate()
            else:
                with self.lock:
                    if self.mode!='ready': self._rotate('ready')
                    result=self.collect()
                    if not self.allowed(): self.invalidate()
                    else:
                        if result!=self.cache:
                            self.revision+=1; result['revision']=self.revision; self.cache=result
                        self.published_at=time.monotonic()
        except (OSError,ValueError,TypeError,KeyError,RuntimeError,PermissionError):
            self.invalidate()
        finally:
            if not self.closed: self.timer=self.app.after(250,self.tick)

    def request(self, path, value):
        if path not in ('/native/v2/bind','/native/v2/rebind','/native/v2/snapshot'): raise ValueError('path')
        fields(value,'protocol generation' + (' view epoch' if path.endswith('snapshot') else ''))
        if value['protocol']!=PROTOCOL: raise ValueError('protocol')
        identifier(value['generation'])
        # Slow registry checks run on this independent read-only HTTP lane.
        authenticated=self.allowed(authenticate=True)
        with self.lock:
            if self.closed: raise PermissionError('closed')
            if not authenticated or not self.allowed() or time.monotonic()-self.published_at>LEASE_MS/1000:
                self.invalidate()
            if path.endswith('rebind'):
                # A new outbound connection needs GUI-issued fresh authority.
                # Rotate presentation IDs only; never renew cache age, open a
                # profile or change a domain setting from this HTTP thread.
                old=decode(encode(self.cache)); published_at=self.published_at
                self._rotate(self.mode)
                old.update(view=self.view,epoch=self.epoch,revision=0)
                self.cache=old; self.published_at=published_at
            if path.endswith('bind'):
                return {'protocol':PROTOCOL,'generation':value['generation'],'binding':{'view':self.view,'epoch':self.epoch},
                        'capabilities':['native.state.read'],'maxFrameBytes':MAX_FRAME,'leaseMs':LEASE_MS}
            if value['view']!=self.view or value['epoch']!=self.epoch: raise PermissionError('binding')
            # Fresh deep copy prevents callers from mutating the retained cache.
            snapshot=decode(encode(self.cache))
            return {'protocol':PROTOCOL,'generation':value['generation'],'kind':'snapshot','snapshot':snapshot}

    def response_current(self, result):
        with self.lock:
            binding=result.get('binding') or result.get('snapshot',{})
            if self.closed or binding.get('view')!=self.view or binding.get('epoch')!=self.epoch: return False
            if self.mode=='ready' and (not self.allowed() or time.monotonic()-self.published_at>LEASE_MS/1000):
                self.invalidate(); return False
            return True

    def _destroy(self, event):
        if event.widget is self.app: self.close()

    def close(self):
        if self.closed: return
        self.invalidate('closing'); self.closed=True
        if self.timer is not None:
            try: self.app.after_cancel(self.timer)
            except Exception: pass
        # shutdown waits only for the independent HTTP loop, never for a Tk job.
        self.server.shutdown(); self.server.server_close()
        if self.path_identity is not None:
            try:
                stat=self.path.stat()
                if stat.st_ino==self.path_identity.st_ino and stat.st_dev==self.path_identity.st_dev and decode(self.path.read_bytes()).get('token')==self.token:
                    self.path.unlink()
            except (OSError,ValueError,KeyError): pass


def install(app, root, gate, chat, settings):
    folder=getattr(app,'_portalai_native_state_folder',None)
    if folder is None or gate is None or chat is None: return None
    adapter=getattr(app,'_portalai_projection_adapter',None)
    if adapter is None: raise RuntimeError('owned_input_adapter_required')
    exporter=Exporter(app,root,gate,chat,settings,folder,adapter.hwnd)
    app._portalai_native_exporter=exporter
    from native_chat_command import install as install_chat_command
    install_chat_command(exporter, adapter)
    return exporter
