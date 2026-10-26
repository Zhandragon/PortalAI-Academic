"""Optional pre-login UI input adapter; no profile keys or private consumers.

The independent projection host receives HA-approved input. A fresh per-GUI
loopback capability connects it to the existing Tk event loop, including the
normal sign-in sheet. No HA credential or projection private key enters here.
"""
import ctypes
from ctypes import wintypes
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import queue
import secrets
import threading
import time
import uuid
import sys

ACK_TIMEOUT=5


def priority_event(event):
    payload=event.get('payload',{})
    if not isinstance(payload,dict):return False
    return ((event.get('kind')=='native_chat' and payload.get('operation')=='stop') or
            (event.get('kind')=='native_ui' and payload.get('operation')=='invoke' and
             payload.get('action') in ('controls_stop','controls_exit','chat_stop','account_close')))


class InputAdapter:
    def __init__(self, app, folder):
        self.app=app;self.token=secrets.token_urlsafe(32);self.pending=queue.Queue(32)
        self.priority=queue.Queue(4)
        self.closed=False;self.results={};self.mutex=threading.Lock();self.waiting=[]
        self.path=Path(folder)/f'gui-{os.getpid()}.json'
        adapter=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*_):pass
            def do_POST(self):
                status=200;job=None
                try:
                    if self.path!='/input' or self.headers.get('Origin') or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+adapter.token):
                        raise PermissionError('Input capability refused')
                    if self.headers.get('Transfer-Encoding'):raise ValueError('Chunked input refused')
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=1410000:raise ValueError('Input limit')
                    item=json.loads(self.rfile.read(length))
                    if not isinstance(item,dict) or not isinstance(item.get('event'),dict):raise ValueError('Invalid input')
                    event=item['event'];payload=event.get('payload',{})
                    bulk=event.get('kind')=='native_ui' and isinstance(payload,dict) and payload.get('operation')=='file_chunk_v2' and type(payload.get('protocol')) is int and payload['protocol']==2
                    if length>60000 and not bulk:raise ValueError('Input limit')
                    key=item.get('request_id','')
                    if uuid.UUID(key).hex!=key:raise ValueError('Invalid request identity')
                    with adapter.mutex:
                        job=adapter.results.get(key)
                        if job is not None and item['event'].get('kind') in ('native_chat','native_ui'):
                            raise ValueError('Native chat requires a fresh delivery identity; effects use their own receipt')
                        if job is None:
                            if adapter.closed:raise RuntimeError('UI closed')
                            now=time.monotonic();expires=item.get('expires_at',now+4)
                            if type(expires) not in (float,int) or not math.isfinite(expires):raise ValueError('Invalid input expiry')
                            if expires<=now:raise TimeoutError('Expired input was not executed')
                            job={'item':item,'done':threading.Event(),'expires':min(now+4,expires),'started':False,'queued_at':now}
                            (adapter.priority if priority_event(item['event']) else adapter.pending).put_nowait(job);adapter.results[key]=job
                            if len(adapter.results)>256:
                                old=next(iter(adapter.results))
                                if adapter.results[old]['done'].is_set():adapter.results.pop(old)
                    if not adapter.wait_for_job(job):
                        with adapter.mutex:job['expires']=0
                        raise TimeoutError('UI did not acknowledge input; do not replay blindly')
                    if 'error' in job:raise RuntimeError(job['error'])
                    result=job.get('result') or {'accepted':True}
                    if item['event'].get('kind')=='native_ui' and not adapter.native_ui.response_current(result):
                        raise PermissionError('native_view_revoked; do not replay automatically')
                    if item['event'].get('kind')!='native_ui':result={**result,'timing_ms':adapter.timings(job)}
                except (ValueError,PermissionError,RuntimeError,TimeoutError,queue.Full,KeyError,TypeError) as exc:
                    status=400;result={'error':str(exc)}
                    if job is not None:result['timing_ms']=adapter.timings(job)
                data=json.dumps(result,ensure_ascii=False).encode('utf-8')
                limit=360000 if result.get('operation')=='rich_media_batch' and result.get('rich',{}).get('protocol')==2 else 64000
                if len(data)>limit:
                    status=400;data=b'{"error":"native_reply_limit; do not replay automatically"}'
                self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store');self.send_header('Connection','close');self.end_headers()
                try:self.wfile.write(data)
                finally:
                    if job is not None and job['item']['event'].get('kind')=='native_ui':
                        job.pop('result',None);job.pop('deferred',None)
        # Bounded concurrent HTTP waits let Stop reach its reserved Tk queue
        # while an ordinary admission is waiting. The browser has no access to
        # this fresh loopback capability, and no additional listener is opened.
        class LocalServer(ThreadingHTTPServer):
            daemon_threads=True
            capacity=threading.BoundedSemaphore(16)
            def process_request(self,request,address):
                if not self.capacity.acquire(False):self.shutdown_request(request);return
                try:super().process_request(request,address)
                except BaseException:self.capacity.release();raise
            def process_request_thread(self,request,address):
                try:super().process_request_thread(request,address)
                finally:self.capacity.release()
            def get_request(self):
                sock,address=super().get_request();sock.settimeout(6);return sock,address
        self.server=LocalServer(('127.0.0.1',0),Handler)
        try:self.publish_endpoint()
        except BaseException:
            self.server.server_close()
            raise
        threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.1},name='PortalAI-public-input',daemon=True).start()
        self.timer=app.after(30,self.pump)
        app.bind('<Destroy>',self.on_destroy,add='+')

    def wake(self):
        # The HTTP thread must never call Tk. Posting to our cached, verified
        # main HWND nudges the Windows message queue while input is pending.
        # WM_NULL performs no input and is NOT evidence of Tk acknowledgement.
        if os.name!='nt':return False
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
        user.GetWindowThreadProcessId.restype=wintypes.DWORD
        user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user.PostMessageW.restype=wintypes.BOOL
        pid=wintypes.DWORD()
        thread=user.GetWindowThreadProcessId(self.hwnd,ctypes.byref(pid))
        if self.closed or pid.value!=os.getpid() or thread!=self.ui_thread:return False
        return bool(user.PostMessageW(self.hwnd,0,0,0))

    def wait_for_job(self,job):
        deadline=time.monotonic()+ACK_TIMEOUT
        while not job['done'].is_set():
            remaining=deadline-time.monotonic()
            if remaining<=0:return job['done'].is_set()
            self.wake()
            job['done'].wait(min(.1,remaining))
        return True

    @staticmethod
    def timings(job):
        # Safe metadata only: never log text, coordinates, tokens or frames.
        started=job.get('started_at');finished=job.get('finished_at',time.monotonic())
        return {'queue':round(1000*((started or finished)-job['queued_at']),1),
                'apply':round(1000*(finished-started),1) if started is not None else None}

    def publish_endpoint(self):
        from runtime_policy import atomic_json
        if os.name=='nt':
            kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
            kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
            times=[wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(kernel.GetCurrentProcess(),*[ctypes.byref(t) for t in times]):raise RuntimeError('Cannot establish UI process identity')
            start=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        else:
            from portable_process import identity
            row=identity(os.getpid())
            start=row['start_ticks'] if 'start_ticks' in row else int(float(row['create_time'])*1_000_000)
        hwnd=self.window_id(str(self.app))
        self.hwnd=hwnd;self.ui_thread=threading.get_native_id()
        metadata={'pid':os.getpid(),'start':start,'hwnd':hwnd,'port':self.server.server_port,'token':self.token}
        if getattr(self,'native_chat',None) is not None:metadata['native_chat_protocol']=1
        attachment_protocol=getattr(getattr(self,'native_chat',None),'attachment_protocol',None)
        if type(attachment_protocol) is int and attachment_protocol==1:metadata['native_chat_attachment_protocol']=1
        if getattr(getattr(self,'native_ui',None),'complete',False):
            metadata['native_ui_protocol']=1;metadata['native_rich_protocol']=1;metadata['native_media_batch_protocol']=1
            if getattr(self.native_ui,'file_upload_protocol',None)==2:metadata['native_file_upload_protocol']=2
        atomic_json(self.path,metadata)
        self.identity=self.path.stat()

    def on_destroy(self,event):
        if event.widget is not self.app or self.closed:return
        self.closed=True
        try:self.app.after_cancel(self.timer)
        except Exception:pass
        self.server.shutdown();self.server.server_close()
        try:
            stat=self.path.stat()
            if stat.st_ino==self.identity.st_ino and json.loads(self.path.read_text())['token']==self.token:self.path.unlink()
        except (OSError,ValueError,KeyError):pass

    def pump(self):
        if self.closed:return
        # Keep serving a nested Tk modal loop opened by an existing callback.
        self.timer=self.app.after(30,self.pump)
        for _ in range(8):
            try:job=self.priority.get_nowait()
            except queue.Empty:
                try:job=self.pending.get_nowait()
                except queue.Empty:break
            try:
                with self.mutex:
                    if time.monotonic()>job['expires']:raise TimeoutError('Expired input was not executed')
                    job['started']=True
                    job['started_at']=time.monotonic()
                if job['item']['event'].get('kind') in ('native_chat','native_ui'):
                    job['item']['expires_at']=job['expires']
                result=self.apply(job['item'])
                from native_chat_command import Receipt
                from native_workflow import Admission
                from native_rich_chat import MediaRead
                if isinstance(result,(Receipt,Admission,MediaRead)):
                    job['deferred']=result;self.waiting.append(job)
                else:job['result']=result
            except Exception as exc:
                job['error']=('native_chat_refused; do not replay automatically' if job['item']['event'].get('kind')=='native_chat' else str(exc))
            finally:
                if job['item']['event'].get('kind')=='native_ui':
                    # Delivery receipts must not retain submitted passwords or
                    # uploaded data. Semantic dedup uses a hash in the GUI.
                    job['item']['event']={'kind':'native_ui'}
            if 'deferred' not in job:job['finished_at']=time.monotonic();job['done'].set()
        pending=self.waiting;self.waiting=[]
        for job in pending:
            try:
                receipt=job['deferred']
                if time.monotonic()>=job['expires'] and receipt.result is None:receipt.refuse()
                result=receipt.poll()
                if result is None:self.waiting.append(job);continue
                job['result']=result
            except Exception:
                job['error']='native_chat_admission_failed_or_expired; do not replay automatically'
            job['finished_at']=time.monotonic();job['done'].set()

    def top_for_hwnd(self, hwnd):
        for path in self.top_paths():
            if self.window_id(path)==hwnd:
                try:return self.app.nametowidget(path)
                except KeyError:break
        raise ValueError('This window is outside the PortalAI Tk interface')

    def window_id(self,path):
        value=int(str(self.app.tk.call('winfo','id',path)),0)
        if os.name!='nt':return value
        user=ctypes.WinDLL('user32');user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
        return int(user.GetAncestor(value,2))

    def top_paths(self):
        tk=self.app.tk;pending=[str(self.app)]
        for _ in range(10000):
            if not pending:return
            path=str(pending.pop());pending.extend(tk.splitlist(tk.call('winfo','children',path)))
            if str(tk.call('winfo','toplevel',path))==path or tk.call('winfo','class',path)=='Menu':yield path
        raise RuntimeError('GUI tree exceeds projection limit')

    def inspect_windows(self):
        # XIDs come from this interpreter only. Never trust another client's
        # _NET_WM_PID property or capture the X server's desktop/root drawable.
        tk=self.app.tk;focus=str(tk.call('focus'));grab=str(tk.call('grab','current'))
        output=[]
        for path in self.top_paths():
            if not int(tk.call('winfo','viewable',path)):continue
            cls=str(tk.call('winfo','class',path))
            try:title=str(tk.call('wm','title',path))[:200]
            except Exception:title=cls
            output.append({'hwnd':self.window_id(path),'width':int(tk.call('winfo','width',path)),
                'height':int(tk.call('winfo','height',path)),'title':title,'class':'TkTopLevel' if path==str(self.app) else cls,
                'visible':True,'focused':bool(focus and (focus==path or focus.startswith(path+'.'))),
                'popup':bool(cls in ('Menu','ComboboxPopdown') or grab==path)})
            if sys.platform=='darwin':
                # Logical client coordinates bind this Tk input target to one
                # owned ScreenCaptureKit window. Winfo IDs are NOT CGWindowIDs.
                output[-1].update(rootx=int(tk.call('winfo','rootx',path)),rooty=int(tk.call('winfo','rooty',path)))
        return {'windows':output}

    def hit(self, top, rx, ry):
        # Walk this Tcl tree rather than asking Windows which desktop window
        # covers a screen point. Remote input must work while PortalAI is behind
        # another app, without ever sending that other app a mouse event.
        tk=self.app.tk
        def visit(path):
            if not int(tk.call('winfo','viewable',path)):return ''
            x,y=(int(tk.call('winfo',kind,path)) for kind in ('rootx','rooty'))
            width,height=(int(tk.call('winfo',kind,path)) for kind in ('width','height'))
            if not x<=rx<x+width or not y<=ry<y+height:return ''
            children=tk.splitlist(tk.call('winfo','children',path))
            for child in reversed(children):
                if str(tk.call('winfo','toplevel',child))!=str(top):continue
                found=visit(child)
                if found:return found
            return str(path)
        return visit(str(top))

    def apply(self,item):
        if item['event'].get('kind')=='native_ui':
            if int(item['hwnd'])!=self.hwnd:raise PermissionError('Native controls require the main GUI')
            controller=getattr(self,'native_ui',None)
            if controller is None:raise RuntimeError('Native controls unavailable')
            return controller.execute(item['event'].get('payload'),item.get('expires_at'))
        if item['event'].get('kind')=='native_chat':
            if int(item['hwnd'])!=self.hwnd:raise PermissionError('Native chat requires the main GUI')
            controller=getattr(self,'native_chat',None)
            if controller is None:raise RuntimeError('Native chat handler unavailable')
            return controller.execute(item['event'].get('payload'),item.get('expires_at'))
        if os.name!='nt' and item['event'].get('kind')=='inspect':return self.inspect_windows()
        try:top=self.top_for_hwnd(int(item['hwnd']))
        except ValueError:
            if os.name!='nt':return self.apply_raw_popup(int(item['hwnd']),item['event'])
            return self.apply_combobox_popup(int(item['hwnd']),item['event'])
        event=item['event'];kind=event.get('kind')
        if os.name!='nt' and top.winfo_class()=='Menu':return self.apply_raw_popup(int(item['hwnd']),event)
        if kind=='close' and os.name!='nt':
            if top is not self.app:raise ValueError('Close the main PortalAI window')
            callback=str(self.app.tk.call('wm','protocol',str(self.app),'WM_DELETE_WINDOW'))
            if not callback:raise RuntimeError('Normal shutdown callback unavailable')
            # Schedule the existing callback; it can take minutes to seal.
            self.app.tk.call('after','idle',callback)
            return
        if kind=='chat_submit':
            callback=getattr(self.app,'_portalai_remote_chat',None)
            if not callback:raise RuntimeError('Sign in to PortalAI first')
            callback(event.get('text'))
            return
        if kind=='layout':
            if event.get('view') not in ('full','portrait_chat'):raise ValueError('Invalid remote view')
            event={**event,'width':max(500,min(1920,int(event['width']))),'height':max(400,min(1200,int(event['height'])))}
            self.app._portalai_remote_layout_pending=event
            callback=getattr(self.app,'_portalai_remote_layout',None)
            if callback:callback(event)
            elif top is self.app:top.geometry(f"{event['width']}x{event['height']}")
            return
        if kind=='resize':
            if top is not self.app:raise ValueError('Resize the main window')
            top.deiconify();top.geometry(f"{max(500,min(1920,int(event['width'])))}x{max(400,min(1200,int(event['height'])))}")
            return
        if kind=='show':top.deiconify();top.lift();return
        if kind in ('pointer','wheel'):
            x,y=int(event['x']),int(event['y'])
            if not 0<=x<top.winfo_width() or not 0<=y<top.winfo_height():raise ValueError('Pointer outside window')
            rx,ry=top.winfo_rootx()+x,top.winfo_rooty()+y
            target=self.hit(top,rx,ry)
            captured=getattr(self,'pointer_target',None)
            if kind=='pointer' and event.get('action') in ('move','up') and captured:
                if int(self.app.tk.call('winfo','exists',captured)) and str(self.app.tk.call('winfo','toplevel',captured))==str(top):target=captured
            if not target:raise ValueError('No PortalAI widget at this point')
            # Native window positioning may overlap another app; only this Tcl
            # interpreter's actual widget tree can be an event target.
            if str(self.app.tk.call('winfo','toplevel',target))!=str(top):raise ValueError('Widget belongs to another dialog')
            grab=self.app.grab_current()
            if grab is not None and grab is not self.app and target!=str(grab) and not target.startswith(str(grab)+'.'):
                raise PermissionError('Complete the open dialog first')
            lx=rx-int(self.app.tk.call('winfo','rootx',target));ly=ry-int(self.app.tk.call('winfo','rooty',target))
            if kind=='wheel':
                self.app.tk.call('event','generate',target,'<MouseWheel>','-delta',120 if int(event['delta'])>0 else -120,'-x',lx,'-y',ly,'-when','tail')
            else:
                action=event.get('action');button=3 if event.get('button')==2 else 1
                if action not in ('down','up','move'):raise ValueError('Invalid pointer event')
                self.app.tk.call('event','generate',target,'<Enter>','-x',lx,'-y',ly,'-when','tail')
                sequence='<Motion>' if action=='move' else f"<Button{'Press' if action=='down' else 'Release'}-{button}>"
                self.app.tk.call('event','generate',target,sequence,'-x',lx,'-y',ly,'-rootx',rx,'-rooty',ry,
                                 '-state',256 if action=='move' and button==1 else 0,'-when','tail')
                if action=='down':
                    self.pointer_target=target
                    self.app.tk.call('focus','-force',target)
                    self.focus_target=target
                elif action=='up':self.pointer_target=None
            return
        try:focus=self.app.nametowidget(self.focus_target)
        except (AttributeError,KeyError):focus=self.app.focus_get()
        if focus is None or focus.winfo_toplevel()!=top:raise RuntimeError('Click a PortalAI input field first')
        if not focus.winfo_viewable():raise PermissionError('The input field is hidden')
        visible=self.hit(top,focus.winfo_rootx()+focus.winfo_width()//2,focus.winfo_rooty()+focus.winfo_height()//2)
        if visible!=str(focus) and not visible.startswith(str(focus)+'.'):
            raise PermissionError('The input field is covered by another panel')
        grab=self.app.grab_current()
        if grab is not None and grab is not self.app and focus!=grab and not str(focus).startswith(str(grab)+'.'):
            raise PermissionError('Complete the open dialog first')
        if kind=='text':
            value=event.get('text')
            if not isinstance(value,str) or len(value)>8192:raise ValueError('Invalid text')
            cls=focus.winfo_class()
            if cls not in ('Entry','TEntry','Text','TCombobox','TSpinbox','Spinbox'):raise ValueError('Select an editable text field')
            if 'state' in focus.keys() and str(focus.cget('state')) in ('disabled','readonly'):raise PermissionError('Field is not editable')
            if cls=='Text':
                try:focus.delete('sel.first','sel.last')
                except Exception:pass
                focus.insert('insert',value)
            else:
                if focus.selection_present():focus.delete('sel.first','sel.last')
                focus.insert('insert',value)
            focus.event_generate('<<Modified>>')
        elif kind=='key':
            keys={'Enter':'Return','Tab':'Tab','Escape':'Escape','Backspace':'BackSpace','Delete':'Delete','ArrowLeft':'Left','ArrowRight':'Right','ArrowUp':'Up','ArrowDown':'Down','Home':'Home','End':'End','PageUp':'Prior','PageDown':'Next'}
            key=keys.get(event.get('key'))
            if key is None:raise ValueError('Unsupported key')
            focus.event_generate('<KeyPress-'+key+'>',when='tail');focus.event_generate('<KeyRelease-'+key+'>',when='tail')
            def selected():
                actual=self.app.focus_get()
                if actual is not None:self.focus_target=str(actual)
            self.app.after_idle(selected)
        else:raise ValueError('Unsupported input')

    def apply_combobox_popup(self,hwnd,event):
        # ttk creates dropdowns in Tcl, so there is no Python Toplevel object.
        # Admit only this interpreter's visible ComboboxPopdown with this HWND.
        tk=self.app.tk
        pending=[str(self.app)];popup=None
        for _ in range(10000):
            if not pending:break
            path=pending.pop();pending.extend(tk.splitlist(tk.call('winfo','children',path)))
            if tk.call('winfo','class',path)!='ComboboxPopdown' or not int(tk.call('winfo','viewable',path)):continue
            if self.window_id(path)==hwnd:popup=path;break
        if popup is None:raise ValueError('This window is outside the PortalAI Tk interface')
        grab=str(tk.call('grab','current',popup))
        if grab and grab!=popup and not grab.startswith(popup+'.'):raise PermissionError('Complete the open dialog first')
        kind=event.get('kind')
        if kind in ('pointer','wheel'):
            x,y=int(event['x']),int(event['y'])
            if not 0<=x<int(tk.call('winfo','width',popup)) or not 0<=y<int(tk.call('winfo','height',popup)):raise ValueError('Pointer outside dropdown')
            rx=x+int(tk.call('winfo','rootx',popup));ry=y+int(tk.call('winfo','rooty',popup))
            target=self.hit(popup,rx,ry)
            if not target or str(tk.call('winfo','toplevel',target))!=popup:raise ValueError('Dropdown target unavailable')
            lx=rx-int(tk.call('winfo','rootx',target));ly=ry-int(tk.call('winfo','rooty',target))
            if kind=='wheel':
                tk.call('event','generate',target,'<MouseWheel>','-delta',120 if int(event['delta'])>0 else -120,'-when','tail');return
            action=event.get('action')
            if action not in ('down','up','move') or event.get('button',0)!=0:raise ValueError('Invalid dropdown pointer')
            sequence='<Motion>' if action=='move' else '<ButtonPress-1>' if action=='down' else '<ButtonRelease-1>'
            tk.call('event','generate',target,sequence,'-x',lx,'-y',ly,'-when','tail')
            return
        if kind=='key':
            key={'Enter':'Return','Escape':'Escape','ArrowUp':'Up','ArrowDown':'Down','Home':'Home','End':'End'}.get(event.get('key'))
            focus=str(tk.call('focus'))
            if not key or not focus.startswith(popup+'.') or tk.call('winfo','class',focus)!='Listbox':raise ValueError('Select a dropdown item')
            tk.call('event','generate',focus,'<KeyPress-'+key+'>','-when','tail');return
        raise ValueError('Select a dropdown item or use navigation keys')

    def apply_raw_popup(self,hwnd,event):
        tk=self.app.tk
        popup=next((p for p in self.top_paths() if self.window_id(p)==hwnd and int(tk.call('winfo','viewable',p))),None)
        if popup is None:raise ValueError('Window is outside this PortalAI interpreter')
        if tk.call('winfo','class',popup)=='ComboboxPopdown':return self.apply_combobox_popup(hwnd,event)
        grab=str(tk.call('grab','current',popup))
        if grab and grab!=popup and not popup.startswith(grab+'.'):raise PermissionError('Complete the open dialog first')
        kind=event.get('kind');target=str(tk.call('focus'))
        if kind in ('pointer','wheel'):
            x,y=int(event['x']),int(event['y'])
            if not 0<=x<int(tk.call('winfo','width',popup)) or not 0<=y<int(tk.call('winfo','height',popup)):raise ValueError('Pointer outside dialog')
            rx=x+int(tk.call('winfo','rootx',popup));ry=y+int(tk.call('winfo','rooty',popup))
            target=self.hit(popup,rx,ry)
            if not target:raise ValueError('No dialog widget at this point')
            lx=rx-int(tk.call('winfo','rootx',target));ly=ry-int(tk.call('winfo','rooty',target))
            if kind=='wheel':
                tk.call('event','generate',target,'<MouseWheel>','-delta',120 if int(event['delta'])>0 else -120,'-when','tail');return
            action=event.get('action');button=3 if event.get('button')==2 else 1
            if action not in ('down','up','move'):raise ValueError('Invalid dialog pointer')
            sequence='<Motion>' if action=='move' else f"<Button{'Press' if action=='down' else 'Release'}-{button}>"
            tk.call('event','generate',target,'<Enter>','-x',lx,'-y',ly,'-when','tail')
            tk.call('event','generate',target,sequence,'-x',lx,'-y',ly,'-rootx',rx,'-rooty',ry,'-when','tail')
            if action=='down':tk.call('focus','-force',target)
            return
        if not target or not (target==popup or target.startswith(popup+'.')):raise ValueError('Select a dialog input first')
        if kind=='text':
            value=event.get('text');cls=str(tk.call('winfo','class',target))
            if not isinstance(value,str) or len(value)>8192 or cls not in ('Entry','TEntry','TCombobox','Text','Spinbox','TSpinbox'):raise ValueError('Select an editable input')
            if str(tk.call(target,'cget','-state')) in ('readonly','disabled'):raise PermissionError('Field is not editable')
            try:tk.call(target,'delete','sel.first','sel.last')
            except Exception:pass
            tk.call(target,'insert','insert',value);return
        if kind=='key':
            key={'Enter':'Return','Escape':'Escape','Tab':'Tab','Backspace':'BackSpace','Delete':'Delete','ArrowUp':'Up','ArrowDown':'Down','ArrowLeft':'Left','ArrowRight':'Right','Home':'Home','End':'End','PageUp':'Prior','PageDown':'Next'}.get(event.get('key'))
            if not key:raise ValueError('Unsupported key')
            tk.call('event','generate',target,'<KeyPress-'+key+'>','-when','tail');tk.call('event','generate',target,'<KeyRelease-'+key+'>','-when','tail');return
        raise ValueError('Unsupported dialog input')


def install(app,root):
    root=Path(root).resolve()
    native=os.environ.pop('PORTALAI_NATIVE_STATE','')
    module=os.environ.pop('PORTALAI_PROJECTION_HOME','')
    scope=os.environ.pop('PORTALAI_PROJECTION_INPUT','')
    if not module:return None
    base=Path(module).resolve()
    if not (base/'app/projection_worker.py').is_file():raise ValueError('Invalid projection module')
    folder=Path(scope)
    if not scope or not folder.is_dir() or folder.is_symlink() or folder.resolve().parent!=(base/'state/input').resolve():raise ValueError('Invalid projection input scope')
    adapter=InputAdapter(app,folder)
    if native=='2':
        app._portalai_projection_adapter=adapter
        app._portalai_native_state_folder=folder
        from native_workflow import install_public
        install_public(app,root,adapter)
    return adapter
