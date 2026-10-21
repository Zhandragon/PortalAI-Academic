"""Independent projection host; unlocked key enters only through a private pipe."""
from pathlib import Path
import concurrent.futures
import json
import os
import queue
import sys
import threading
import time
from collections import OrderedDict

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
from host_runtime import package_paths,target_valid,input_owner,resolve_target
sys.path[:0]=package_paths()


def media_reply(item):
    result=item.get('result',{}) if isinstance(item,dict) else {}
    return (isinstance(result,dict) and result.get('operation')=='rich_media_batch'
            and isinstance(result.get('rich'),dict) and result['rich'].get('protocol')==2)


class ReplyQueue(queue.Queue):
    def __init__(self,wake):super().__init__(64);self.wake=wake
    def _put(self,item):super()._put(item);self.wake.set()


class PollPacer:
    """Short active-media bursts; never accelerate a disconnected/idle viewer."""
    def __init__(self,clock=time.monotonic):self.clock=clock;self.until=0.
    def command(self,item):
        if item.get('action')=='native_ui' and item.get('payload',{}).get('operation') in ('rich_media','rich_media_batch','rich_preview','file_begin','file_chunk','file_chunk_v2','file_commit'):
            self.until=self.clock()+2
    def delay(self,phase,native_active):
        if phase!='active':return 2
        return .05 if native_active and self.clock()<self.until else .65


def poll_ready(client, manager, frame, replies, status_provider=None, frame_guard=None):
    # Collect status first: even a slow inventory must not strand a reply that
    # completed while status was being collected until the following poll.
    status=(status_provider or manager.status)()
    batch=[]
    budget=512000-2
    # Peek and remove under the Queue mutex. A reply which doesn't fit stays
    # at the head for the next poll; it must never be dropped or reordered.
    with replies.mutex:
        while replies.queue and len(batch)<32:
            item=replies.queue[0]
            # Match the receiver's decoded-JSON accounting, including spaces.
            length=len(json.dumps(item,ensure_ascii=False).encode('utf-8'))
            if length>(361000 if media_reply(item) else 65000):
                item={'id':item.get('id'),'error':'Reply exceeds protocol limit; do not replay automatically'}
                length=len(json.dumps(item).encode())
            needed=length+(2 if batch else 0)
            if needed>budget:break
            replies._get();replies.not_full.notify()
            batch.append(item);budget-=needed
    if frame_guard is not None and not frame_guard():frame=None
    # Preserve bounded uploads and deliver acknowledgements before an unusually
    # large screenshot. Capture/viewer demand remain independently gated.
    if frame is not None and len(json.dumps({'frame':frame,'status':status,'replies':batch},ensure_ascii=False,separators=(',',':')).encode('utf-8'))>5690000:
        frame=None
    return client.poll(frame,status,batch)


def priority_command(item):
    payload=item.get('payload',{})
    if not isinstance(payload,dict):return False
    return ((item.get('action')=='native_chat' and payload.get('operation')=='stop') or
            (item.get('action')=='native_ui' and payload.get('operation')=='invoke' and
             payload.get('action') in ('controls_stop','controls_exit','chat_stop','account_close')))


class NativeStatusReporter:
    """Best-effort diagnostics, never account/recovery or transport authority.

    Coalesce all intermediate phases, including reconnect flapping. A storage
    failure latches this optional writer off until a new worker is started;
    reconnecting to HA must not repeatedly write to a failing portable volume.
    The supplied durable writer retains its normal flush/replace guarantees.
    """
    def __init__(self,path,write,on_error,*,clock=time.monotonic,wall_clock=time.time):
        self.path=path;self.write=write;self.on_error=on_error
        self.clock=clock;self.wall_clock=wall_clock
        self.next_write=None;self.accepted=0;self.disabled=False;self.stopped=False

    def __call__(self,phase):
        if phase=='publishing':self.accepted+=1
        if self.disabled or self.stopped:return
        now=self.clock()
        if phase!='stopped' and self.next_write is not None and now<self.next_write:return
        self.next_write=now+30
        self.stopped=phase=='stopped'
        try:
            self.write(self.path,{'protocol':'portalai-native-state/2',
                'state':phase,'updated_unix':self.wall_clock(),
                'receiver_acknowledgements':self.accepted,
                'private_payloads_logged':False,'effects_performed':False})
        except (OSError,ValueError):
            self.disabled=True
            # No raw exception/path/private payload enters the status channel.
            # Reporting itself must not turn optional telemetry into a failure.
            try:self.on_error()
            except Exception:pass


def main():
    connection=json.loads(sys.stdin.readline(32769))
    if not isinstance(connection,dict):raise ValueError('Connection required')
    target=resolve_target(connection['target'])
    if not target_valid(target):raise ValueError('Select the PortalAI portable root')
    import portalai_target
    portalai_target.configure(target)
    from projection_client import Client
    from mission_runner import process_lock
    if os.name!='nt':
        from linux_job import prepare_delegation,preflight
        prepare_delegation();preflight()
    client=Client(connection,MODULE/'Runtime/cacert.pem');manager=portalai_target.Manager(target)
    import hashlib
    sid=input_owner()
    scope=MODULE/'state/input'/hashlib.sha256(sid.encode()).hexdigest()[:32]
    if scope.is_symlink():raise RuntimeError('Linked input scope refused')
    scope.mkdir(mode=0o700,exist_ok=True)
    manager.endpoint_dir=scope
    stop=threading.Event();wake=threading.Event();replies=ReplyQueue(wake);pacer=PollPacer();mutex=threading.Lock()
    state={'frame':None,'frame_at':0,'frame_token':None,'window':None,'captured':0};last='';storage_warning=''
    def report(message):
        nonlocal last
        message=storage_warning+message
        if message!=last:print(json.dumps({'status':message}),flush=True);last=message
    def storage_error():
        nonlocal storage_warning
        storage_warning='Storage warning: projection diagnostic writes are paused after a drive error. '
        report('Check the portable drive connection before restarting projection.')
    def stdin_watch():
        try:
            for line in sys.stdin:
                value=json.loads(line)
                if value.get('command')=='open':
                    import uuid
                    manager.lifecycle('start',{'request_id':uuid.uuid4().hex})
                    report('Opening PortalAI. Use its real sign-in screen locally or through HA.')
                elif value.get('command')=='stop':break
        finally:stop.set();wake.set()
    def capture():
        while not stop.is_set():
            token=client.demand.token('screen')
            if token is None:
                with mutex:state.update(frame=None,frame_at=0,frame_token=None)
                stop.wait(1)
                continue
            try:
                with mutex:selected=state['window']
                frame=manager.frame({'window':selected},background=True)
                with mutex:
                    state['captured']+=1
                    # A completed capture may belong to a disconnected viewer.
                    if client.demand.valid('screen',token):
                        state.update(frame=frame,frame_at=time.monotonic(),frame_token=token)
            except Exception:pass # Failure clears the remote image after its age limit.
            stop.wait(.65)
    status_cache={'value':None,'at':0.}
    def demand_status():
        now=time.monotonic();phase=client.demand.status()
        if status_cache['value'] is None or now-status_cache['at']>=(.65 if phase=='active' else 5):
            status_cache.update(value=manager.status(),at=now)
        value=dict(status_cache['value'])
        with mutex:
            value.update(viewer_demand_protocol=1,viewer_demand_state=phase,
                         captured_frames=state['captured'],screen_upload_attempts=client.frame_uploads)
        return value
    slots=threading.BoundedSemaphore(32)
    control_slots=threading.BoundedSemaphore(4)
    priority_slots=threading.BoundedSemaphore(4)
    workflow_slots=threading.BoundedSemaphore(8)
    def command(item):
        key=item.get('id');action=item.get('action');payload=item.get('payload',{})
        try:
            if stop.is_set() or time.monotonic()>item['_deadline']:raise TimeoutError('Expired input was not executed')
            if not isinstance(key,str) or len(key)!=32 or not isinstance(payload,dict):raise ValueError('Invalid command')
            if action=='input':result=manager.input(payload,deadline=item['_deadline'])
            elif action=='native_chat':result=manager.native_chat(payload,deadline=item['_deadline'])
            elif action=='native_ui':
                if (payload.get('operation')=='describe' or str(payload.get('operation','')).startswith('rich_')) and not client.demand.active('native'):
                    raise RuntimeError('Native controls are paused without a viewer')
                token=client.demand.token('native') if str(payload.get('operation','')).startswith('rich_') else None
                if str(payload.get('operation','')).startswith('rich_') and token is None:
                    raise PermissionError('Native viewer disconnected before read')
                result=manager.native_ui(payload,deadline=item['_deadline'])
                if token is not None and not client.demand.valid('native',token):raise PermissionError('Native viewer disconnected')
            elif action in ('start','restart','force_shutdown'):result=manager.lifecycle(action,payload)
            elif action=='select_window':
                selected=payload.get('window')
                with manager.lock:
                    if selected not in manager.windows:raise ValueError('Window no longer available')
                with mutex:state['window']=selected
                result={'accepted':True}
            else:raise ValueError('Unsupported projection command')
            replies.put_nowait({'id':key,'result':result})
        except Exception as exc:
            try:replies.put_nowait({'id':key,'error':action+'_refused_or_uncertain; do not replay automatically' if action in ('native_chat','native_ui') else str(exc)[:300]})
            except queue.Full:pass
        finally:item['_slots'].release()
    # A hung capture cannot block network status or the independent lifecycle
    # lane. Input remains ordered and is never replayed after reconnecting.
    inputs=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    lifecycle=concurrent.futures.ThreadPoolExecutor(max_workers=1)
    priority=concurrent.futures.ThreadPoolExecutor(max_workers=2)
    workflows=concurrent.futures.ThreadPoolExecutor(max_workers=4)
    seen=OrderedDict()
    with process_lock(MODULE/'state/projection.lock'):
        # No local launch, capture or receiver session before exclusive ownership.
        threading.Thread(target=stdin_watch,daemon=True).start()
        threading.Thread(target=capture,daemon=True).start()
        # A separate outbound, read-only lane cannot wait on screenshot/input
        # acknowledgements. It shares the existing device identity, but the HA
        # receiver must separately authorize native.state.read before GUI reads.
        native=None;native_thread=None
        try:
            from native_transport import NativeTransport
            from runtime_policy import atomic_json
            native_report=NativeStatusReporter(MODULE/'state/native-status.json',atomic_json,storage_error)
            native_manager=portalai_target.Manager(target);native_manager.endpoint_dir=scope
            native=NativeTransport(connection,native_manager,stop,native_report,demand=client.demand)
            native_thread=threading.Thread(target=native.run,name='PortalAI-native-outbound',daemon=True)
            native_thread.start()
        except Exception:
            report('Native read-only transport unavailable. Projection can continue.')
        try:
            while not stop.is_set():
                try:
                    wake.clear()  # Replies already queued are drained by this poll.
                    if not client.session:client.authenticate();report('Paired receiver connected. Use HA to open and sign in to PortalAI.')
                    with mutex:
                        frame_token=state['frame_token']
                        frame=state['frame'] if (time.monotonic()-state['frame_at']<5 and
                            client.demand.valid('screen',frame_token)) else None
                    commands=poll_ready(client,manager,frame,replies,demand_status,
                                        lambda:client.demand.valid('screen',frame_token))
                    phase=client.demand.status()
                    report({'active':'HA viewer connected. Requested streams are active.',
                            'standby':'Connected to HA. Standby: no screen capture or native state upload.',
                            'receiver_update_required':'Connected to HA. Receiver viewer-demand update required; streams are paused.',
                            'waiting_for_receiver':'Waiting for HA viewer demand; streams are paused.'}[phase])
                    for item in commands:
                        key=item.get('id')
                        if key in seen:continue
                        if not isinstance(key,str) or len(key)!=32:raise ValueError('Invalid command identity')
                        seen[key]=True
                        if len(seen)>2048:seen.popitem(last=False)
                        ttl=max(0,min(5,float(item.get('ttl',0))))
                        control=item.get('action') in ('start','restart','force_shutdown')
                        urgent=priority_command(item)
                        workflow=item.get('action')=='native_ui'
                        lane=priority_slots if urgent else control_slots if control else workflow_slots if workflow else slots
                        if not lane.acquire(False):
                            try:replies.put_nowait({'id':key,'error':'Local input queue full; command was not executed'})
                            except queue.Full:pass
                            continue
                        item['_deadline']=time.monotonic()+ttl
                        item['_slots']=lane
                        pacer.command(item)
                        (priority if urgent else lifecycle if control else workflows if workflow else inputs).submit(command,item)
                    wake.wait(pacer.delay(phase,client.demand.active('native')))
                except Exception as exc:
                    client.session=None;client.demand.reset()
                    with mutex:state.update(frame=None,frame_at=0,frame_token=None)
                    report(str(exc)[:300]+' No input is automatically replayed.');stop.wait(3)
        finally:
            stop.set()
            client.close()
            if native is not None:native.close()
            if native_thread is not None:native_thread.join(timeout=5)
            inputs.shutdown(wait=False,cancel_futures=True);lifecycle.shutdown(wait=False,cancel_futures=True)
            priority.shutdown(wait=False,cancel_futures=True);workflows.shutdown(wait=False,cancel_futures=True)
    report('Projection stopped. PortalAI retains its own normal login/shutdown lifecycle.')


if __name__=='__main__':
    try:main()
    except Exception as exc:print(json.dumps({'status':str(exc)[:300]}),flush=True);raise SystemExit(1)
