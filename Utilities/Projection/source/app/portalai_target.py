"""Window ownership and PortalAI lifecycle adapter. No network listener."""
from pathlib import Path
import base64
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid

MODULE=Path(__file__).resolve().parents[1]


def configure(root):
    global ROOT
    ROOT=Path(root).resolve()
    sys.path.insert(0,str(ROOT/'Agent'))


def gui_row(root, row):
    if sys.platform=='darwin':
        from macos_target import gui_row as mac_gui
        return mac_gui(root,row)
    if os.name!='nt':
        from linux_target import gui_row as linux_gui
        return linux_gui(root,row)
    return any(arg in (str(root/'ControlCenter/control_center_bootstrap.py'),str(root/'ControlCenter/PortableAI_GUI.py')) for arg in row.get('argv',[])) and Path(row.get('executable','')).resolve() in (root/'Runtime/BootstrapPython/pythonw.exe',root/'Runtime/BootstrapPython/python.exe')


class Manager:
    def __init__(self, root, desktop=None):
        self.root=Path(root).resolve()
        self.endpoint_dir=None
        if desktop is None:
            if os.name=='nt':
                from windows_desktop import Desktop
                desktop=Desktop()
            elif sys.platform=='darwin':
                from macos_desktop import Desktop
                desktop=Desktop(self)
            else:
                from linux_desktop import Desktop
                desktop=Desktop(self)
        self.desktop=desktop
        self.lock=threading.RLock();self.frame_lock=threading.Lock()
        # Serialize input with lifecycle admission, without holding the state
        # lock across a GUI acknowledgement. Status/capture must remain live.
        self.input_lock=threading.RLock()
        self.windows={};self.rows={};self.inventory_at=0
        self.operation={'state':'idle'};self.seen={};self.viewer=None

    def inventory(self, fresh=False):
        from profile_shutdown import _windows_snapshot, _linux_snapshot, _mac_snapshot
        if fresh or time.monotonic()-self.inventory_at>3:
            self.rows=(_mac_snapshot(self.root) if sys.platform=='darwin' else (_windows_snapshot if os.name=='nt' else _linux_snapshot)());self.inventory_at=time.monotonic()
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
        rows=self.inventory()
        try:marker=_marker(self.root);profile_state=marker['state'] if marker else 'no-active-profile'
        except (RuntimeError,ValueError,OSError,KeyError):profile_state='unavailable; recovery may be required'
        native_attachments=False; native=False; native_ui=False; native_rich=False; media_batch=False; upload_v2=False
        try:
            _,endpoint=self.native_chat_endpoint(rows, protocol=None)
            native=endpoint.get('native_chat_protocol')==1
            native_attachments=native and type(endpoint.get('native_chat_attachment_protocol')) is int and endpoint['native_chat_attachment_protocol']==1
            native_ui=endpoint.get('native_ui_protocol')==1
            upload_v2=native_ui and type(endpoint.get('native_file_upload_protocol')) is int and endpoint['native_file_upload_protocol']==2
            native_rich=endpoint.get('native_rich_protocol')==1
            media_batch=endpoint.get('native_media_batch_protocol')==1
        except (OSError,ValueError,RuntimeError,KeyError,TypeError):pass
        with self.lock:
            result={'running':any(gui_row(self.root,r) for r in rows.values()),
                    'profile_state':profile_state,
                    'operation':dict(self.operation),'platform':'macos' if sys.platform=='darwin' else 'windows' if os.name=='nt' else 'linux-x11',
                    'stream':'PortalAI windows only; shared desktop login session'}
            if native:result['native_chat_protocol']=1
            if native_attachments:result['native_chat_attachment_protocol']=1
            if native_ui:result['native_ui_protocol']=1
            if upload_v2:result['native_file_upload_protocol']=2
            if native_rich:result['native_rich_protocol']=1
            if media_batch:result['native_media_batch_protocol']=1
            return result

    def _lease(self, viewer):
        if not isinstance(viewer,str) or not 16<=len(viewer)<=128:raise ValueError('Missing viewer identity')
        now=time.monotonic()
        with self.lock:
            if self.viewer and self.viewer[0]!=viewer and self.viewer[1]>now:
                raise PermissionError('Another viewer controls this desktop; disconnect it or wait 30 seconds')
            self.viewer=(viewer,now+30)

    def frame(self, payload, *, background=False):
        # The outbound publisher captures on behalf of the receiver, not a
        # viewer. Only authenticated interactive requests acquire control.
        if not background:self._lease(payload.get('viewer'))
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
                focused=self.desktop.focused_window([current[k] for k in visible])
                selected=next((k for k in visible if current[k]['class'] in ('#32768','ComboLBox','Menu','ComboboxPopdown')),None)
                selected=selected or next((k for k in visible if current[k]['hwnd']==focused),None)
                selected=selected or next((k for k in visible if current[k]['hwnd']==self.desktop.u.GetForegroundWindow()),None)
                selected=selected or max(visible or list(current),key=lambda k:current[k]['width']*current[k]['height'])
                popup=self.desktop.u.GetLastActivePopup(current[selected]['hwnd'])
                selected=next((k for k in visible if current[k]['hwnd']==popup),selected)
            window=current[selected]
            data,width,height=self.desktop.capture(window)
            if len(data)>4*1024**2:raise RuntimeError('Capture exceeds transport limit')
            from profile_shutdown import _marker
            try:marker=_marker(self.root)
            except (RuntimeError,ValueError,OSError,KeyError):marker=None
            try:main_hwnd=self.endpoint(window).get('hwnd')
            except (OSError,ValueError,RuntimeError,KeyError,TypeError):main_hwnd=None
            return {'window':selected,'width':width,'height':height,'profile_open':bool(marker and marker['state']=='open'),
                    'native_dialog':window['class'] in ('#32770','#32768','ComboLBox') or main_hwnd!=window['hwnd'],'png':base64.b64encode(data).decode('ascii'),
                    'windows':[{'id':k,'title':v['title']} for k,v in current.items()]}
        finally:self.frame_lock.release()

    def endpoint(self,window):
        if self.endpoint_dir is None:raise RuntimeError('Projection input scope unavailable')
        path=self.endpoint_dir/f'gui-{window["pid"]}.json'
        if path.is_symlink() or path.resolve().parent!=self.endpoint_dir.resolve():raise RuntimeError('Linked input endpoint refused')
        if not path.is_file() or path.stat().st_size>4096:raise RuntimeError('Full Restart PortalAI to load the optional projection input adapter')
        endpoint=json.loads(path.read_text(encoding='utf-8'))
        divisor=10 if os.name=='nt' else 1
        if endpoint.get('pid')!=window['pid'] or type(endpoint.get('start')) is not int or endpoint['start']//divisor!=window['start']//divisor or type(endpoint.get('port')) is not int or not 1024<=endpoint['port']<=65535:
            raise RuntimeError('Invalid GUI endpoint')
        return endpoint

    def input(self, payload, deadline=None):
        self._lease(payload.get('viewer'))
        with self.input_lock:
            if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('Expired input was not executed')
            with self.lock:
                if self.operation.get('state')=='running':raise RuntimeError('Lifecycle operation in progress')
                window=self.windows.get(payload.get('window'))
                if window is None:raise ValueError('Refresh the viewer before sending input')
            self.desktop.validate(window)
            if deadline is not None and time.monotonic()>=deadline:raise TimeoutError('Expired input was not executed')
            if window['class'] in ('#32770','#32768','ComboLBox'):
                self.desktop.input(window,payload.get('event',{}))
                return {'accepted':True}
            endpoint=self.endpoint(window)
            import http.client
            conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=7)
            try:
                item={'hwnd':window['hwnd'],'event':payload.get('event',{}),'request_id':uuid.uuid4().hex}
                # Both processes share the host monotonic clock. Do not renew
                # a queued HA command's lifetime at each local hop.
                if deadline is not None:item['expires_at']=deadline
                data=json.dumps(item).encode()
                conn.request('POST','/input',data,{'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
                response=conn.getresponse();reply=response.read(4097)
                if len(reply)>4096:raise RuntimeError('Invalid GUI acknowledgement')
                result=json.loads(reply)
                if not isinstance(result,dict):raise RuntimeError('Invalid GUI acknowledgement')
                if response.status!=200:raise RuntimeError(result.get('error','GUI input refused'))
                if result.get('accepted') is not True:raise RuntimeError('Invalid GUI acknowledgement')
            finally:conn.close()
        return result

    def native_chat_endpoint(self, rows=None, *, protocol='native_chat_protocol'):
        rows=self.inventory(True) if rows is None else rows
        owned={pid:row for pid,row in rows.items() if gui_row(self.root,row)}
        if len(owned)!=1:raise RuntimeError('single_owned_GUI_required')
        pid,row=next(iter(owned.items()))
        folder=self.endpoint_dir
        if folder is None:raise RuntimeError('input_scope_unavailable')
        for part in (folder,*folder.parents):
            if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise RuntimeError('linked_input_scope')
        path=folder/f'gui-{pid}.json'
        if not path.is_file() or path.stat().st_nlink!=1:raise RuntimeError('input_endpoint_unavailable')
        endpoint=self.endpoint({'pid':pid,'start':row['start']})
        if ((protocol is not None and endpoint.get(protocol)!=1) or type(endpoint.get('hwnd')) is not int
                or not isinstance(endpoint.get('token'),str) or not 32<=len(endpoint['token'])<=128):
            raise RuntimeError('native_chat_restart_required')
        windows=self.desktop.windows(owned)
        window=next((w for w in windows if w['pid']==pid and w['hwnd']==endpoint['hwnd']),None)
        if window is None:raise RuntimeError('owned_main_GUI_required')
        window={**window,'executable':row['executable']}
        self.desktop.validate(window)
        return window,endpoint

    def native_chat(self, payload, deadline):
        # Shape is revalidated at the GUI effect boundary. No GUI modules or
        # private profile consumers are imported into the companion.
        import re, math, http.client
        if not isinstance(payload,dict) or not isinstance(payload.get('viewer'),str) or not re.fullmatch('[0-9a-f]{32}',payload['viewer']):
            raise ValueError('native_chat_viewer')
        from contextlib import nullcontext
        with (nullcontext() if payload.get('operation')=='stop' else self.input_lock):
            if type(deadline) not in (float,int) or not math.isfinite(deadline) or time.monotonic()>=deadline:
                raise TimeoutError('native_chat_expired')
            with self.lock:
                if self.operation.get('state')=='running':raise RuntimeError('Lifecycle operation in progress')
            self._lease(payload['viewer'])
            window,endpoint=self.native_chat_endpoint()
            if payload.get('include_pending_attachments') is True and (type(endpoint.get('native_chat_attachment_protocol')) is not int or endpoint['native_chat_attachment_protocol']!=1):raise RuntimeError('native_chat_attachment_update_required')
            if time.monotonic()>=deadline:raise TimeoutError('native_chat_expired')
            conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=7)
            try:
                item={'hwnd':window['hwnd'],'event':{'kind':'native_chat','payload':payload},
                      'request_id':uuid.uuid4().hex,'expires_at':deadline}
                conn.request('POST','/input',json.dumps(item,ensure_ascii=False).encode('utf-8'),
                             {'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
                response=conn.getresponse();raw=response.read(4097)
                if response.status!=200 or len(raw)>4096:raise RuntimeError('native_chat_refused_or_expired; do not replay automatically')
                result=json.loads(raw)
                if (not isinstance(result,dict) or result.get('accepted') is not True
                        or result.get('request_id')!=payload.get('request_id') or result.get('operation')!=payload.get('operation')):
                    raise RuntimeError('Invalid native chat acknowledgement; do not replay automatically')
                return {k:result[k] for k in ('accepted','request_id','operation')}
            finally:conn.close()

    def native_ui(self, payload, deadline):
        """Bounded commands to the owned GUI, independent of screenshot/input locks.

        The GUI validates the complete typed schema and current account/form at
        the final effect boundary. No private GUI imports in the companion.
        """
        import re, math, http.client
        if (not isinstance(payload,dict) or not isinstance(payload.get('viewer'),str)
                or not re.fullmatch('[0-9a-f]{32}',payload['viewer'])):
            raise ValueError('native_ui_identity')
        if (type(deadline) not in (int,float) or not math.isfinite(deadline)
                or time.monotonic()>=deadline):raise TimeoutError('native_ui_expired')
        raw=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        bulk=payload.get('operation')=='file_chunk_v2' and type(payload.get('protocol')) is int and payload['protocol']==2
        if len(raw)>(1400000 if bulk else 56000):raise ValueError('native_ui_limit')
        with self.lock:
            if self.operation.get('state')=='running':raise RuntimeError('Lifecycle operation in progress')
        if payload.get('operation') not in ('describe','file_get','rich_index','rich_detail','rich_media','rich_media_batch','rich_preview'):self._lease(payload['viewer'])
        window,endpoint=self.native_chat_endpoint(protocol='native_ui_protocol')
        if bulk and endpoint.get('native_file_upload_protocol')!=2:raise RuntimeError('native_upload_v2_unavailable')
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('native_ui_expired')
        conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=min(5,remaining))
        try:
            item={'hwnd':window['hwnd'],'event':{'kind':'native_ui','payload':payload},
                  'request_id':uuid.uuid4().hex,'expires_at':deadline}
            conn.request('POST','/input',json.dumps(item,ensure_ascii=False).encode('utf-8'),
                         {'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
            limit=360000 if payload.get('operation')=='rich_media_batch' and payload.get('protocol')==2 else 65000
            response=conn.getresponse();raw=response.read(limit+1)
            if len(raw)>limit:raise RuntimeError('native_ui_reply_limit; do not replay automatically')
            result=json.loads(raw)
            if response.status!=200:
                # GUI messages are controlled codes, never submitted values.
                raise RuntimeError('native_ui_refused_or_uncertain; do not replay automatically')
            allowed={'accepted','request_id','operation','model','transfer','offset','file','name','mime','size','data','eof','sha256','message','rich'}
            if (not isinstance(result,dict) or set(result)-allowed or result.get('accepted') is not True
                    or result.get('request_id')!=payload.get('request_id')
                    or result.get('operation')!=payload.get('operation')):
                raise RuntimeError('native_ui_invalid_acknowledgement; do not replay automatically')
            return result
        finally:conn.close()

    def lifecycle(self, action, payload):
        if action not in ('start','restart','force_shutdown'):raise ValueError('Unsupported lifecycle action')
        key=payload.get('request_id','')
        if not isinstance(key,str) or uuid.UUID(key).hex!=key:raise ValueError('A unique request_id is required')
        if action=='force_shutdown' and payload.get('confirm')!='UNSAFE SHUTDOWN':
            raise PermissionError('Explicit unsafe shutdown confirmation required')
        with self.input_lock, self.lock:
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
        environment=clean_environment();environment['PORTALAI_PROJECTION_HOME']=str(MODULE)
        environment['PORTALAI_PROJECTION_INPUT']=str(self.endpoint_dir)
        # Opts into a separate local read-only capability. The v1 projection
        # protocol cannot forward native state or confer a native receiver grant.
        environment['PORTALAI_NATIVE_STATE']='2'
        if sys.platform=='darwin':
            from macos_target import launch
            return launch(self,environment)
        if os.name!='nt':
            from linux_target import launch
            return launch(self,environment)
        subprocess.Popen([str(self.root/'PortalAI.exe')],cwd=self.root,env=environment,
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
                    if os.name=='nt':
                        for row in sorted(remaining.values(),key=lambda r:r['start'],reverse=True):_windows_stop(row,self.root)
                    elif sys.platform=='darwin':
                        from macos_target import stop_owned
                        stop_owned(self,remaining)
                    else:
                        from linux_target import stop_owned
                        stop_owned(self,remaining)
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
                    if marker and marker['state']!='closed':
                        raise RuntimeError('Shutdown left an unsealed profile; restart refused')
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

