"""Per-profile foreground chat priority, with OS-owned crash-released leases.

Chat first blocks new background work, then waits for the current admitted action
to checkpoint. It never clears STOP, arms a mission, or retries a pending effect.
"""
from contextlib import ExitStack
import http.client
import json
from pathlib import Path
import queue
import socket
import threading
import time
import urllib.parse


class YieldToChat(Exception):
    """Planning can be discarded: no action from this response was executed."""


def base(root):
    from profile_paths import private_path
    return private_path(root,'Data/Missions')


def active(root):
    from mission_runner import process_lock
    path=base(root)/'direct-chat.lock'
    if not path.exists():return False
    try:
        with process_lock(path):return False
    except OSError:return True


class Foreground:
    def __init__(self,root):
        self.root=Path(root);self.stack=ExitStack();self.acquired=False

    def acquire(self,cancel,check_login,notify):
        from mission_runner import process_lock
        folder=base(self.root)
        announced=False
        for name in ('direct-chat.lock','execution.lock'):
            while not cancel.is_set():
                check_login()
                lease=process_lock(folder/name)
                try:lease.__enter__()
                except OSError:
                    if not announced:notify('Pausing background work at its next safe checkpoint…');announced=True
                    cancel.wait(.05);continue
                self.stack.callback(lease.__exit__,None,None,None);break
            else:return False
        self.acquired=True
        if announced:notify('Background work checkpointed. Preparing your reply…')
        return True

    def close(self):
        self.stack.close();self.acquired=False


def planning_json(root,url,payload=None,timeout=180,*,on_delta=None,on_reasoning=None,check_cancel=None):
    """Interrupt only a model-planning HTTP call when direct chat takes priority.

    The socket is shut down, including while waiting for response headers. No
    arbitrary mission tool or account operation is sent through this helper.
    """
    if active(root):raise YieldToChat()
    if check_cancel:check_cancel()
    target=urllib.parse.urlsplit(url)
    if target.scheme!='http' or target.hostname not in ('127.0.0.1','localhost','::1') or target.username or target.password:
        raise ValueError('Mission planning requires the local model endpoint')
    connection=http.client.HTTPConnection(target.hostname,target.port,timeout=timeout)
    result=queue.Queue(1);cancelled=threading.Event();transport=[None]
    def request():
        try:
            connection.connect();transport[0]=connection.sock
            if cancelled.is_set():raise YieldToChat()
            request_payload={**payload,'stream':True} if on_delta is not None and payload is not None else payload
            body=json.dumps(request_payload).encode('utf-8') if request_payload is not None else None
            connection.request('POST' if body is not None else 'GET',target.path+('?' +target.query if target.query else ''),body=body,headers={'Content-Type':'application/json'})
            response=connection.getresponse()
            if response.status!=200:raise RuntimeError('Model endpoint returned HTTP '+str(response.status))
            if on_delta is not None and 'text/event-stream' in response.getheader('Content-Type',''):
                content=[];received=0;finished=None;done=False
                while True:
                    line=response.readline(1024*1024+1);received+=len(line)
                    if len(line)>1024*1024 or received>8*1024**2:raise ValueError('Model response exceeds limit')
                    if not line:break
                    if not line.startswith(b'data:'):continue
                    value=line[5:].strip()
                    if value==b'[DONE]':done=True;break
                    event=json.loads(value)
                    if event.get('error'):raise RuntimeError('Model stream reported an error')
                    for choice in event.get('choices',[]):
                        if choice.get('index',0)!=0:continue
                        delta=choice.get('delta') or {}
                        reasoning=delta.get('reasoning_content') or ''
                        if not isinstance(reasoning,str):raise ValueError('Invalid model reasoning text')
                        if reasoning and on_reasoning:on_reasoning(reasoning)
                        text=delta.get('content') or ''
                        if not isinstance(text,str):raise ValueError('Invalid model stream text')
                        content.append(text)
                        if text:on_delta(text)
                        if choice.get('finish_reason') is not None:finished=choice['finish_reason']
                if not done or finished!='stop':raise RuntimeError('Model planning response was incomplete; no action executed')
                result.put((True,{'choices':[{'message':{'content':''.join(content)},'finish_reason':finished}]}))
            else:
                data=response.read(8*1024**2+1)
                if len(data)>8*1024**2:raise ValueError('Model response exceeds limit')
                parsed=json.loads(data)
                if on_delta is not None:
                    choice=parsed['choices'][0]
                    if choice.get('finish_reason')!='stop':raise RuntimeError('Model planning response was incomplete; no action executed')
                    reasoning=choice['message'].get('reasoning_content') or ''
                    if not isinstance(reasoning,str):raise ValueError('Invalid model reasoning text')
                    if reasoning and on_reasoning:on_reasoning(reasoning)
                    on_delta(choice['message']['content'])
                result.put((True,parsed))
        except Exception as exc:result.put((False,exc))
        finally:connection.close()
    worker=threading.Thread(target=request,name='PortalAI-Mission-Planning',daemon=True);worker.start()
    deadline=time.monotonic()+timeout
    try:
        while True:
            if active(root):raise YieldToChat()
            if check_cancel:check_cancel()
            if time.monotonic()>=deadline:raise TimeoutError('Mission model request timed out')
            try:ok,value=result.get(timeout=.05)
            except queue.Empty:continue
            if active(root):raise YieldToChat()
            if check_cancel:check_cancel()
            if not ok:raise value
            return value
    finally:
        cancelled.set();sock=transport[0] or connection.sock
        if sock is not None:
            try:sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
        # Only the request thread closes the HTTPConnection: clearing its socket
        # here could make request() reconnect after cancellation raced connect().
        worker.join(.25)


def checkpoint(store,mission):
    """Compact completed evidence into the existing mission-family memory."""
    from mission_context import clip,digest,encoded,rolling_index
    from mission_memory import Memory
    if mission.get('pending_action'):raise RuntimeError('Pending action requires outcome review before yielding')
    if mission.get('chat_paused'):return mission
    history=mission['history'];rolling_index(store,mission)
    evidence={'reason':'Direct chat took priority; continue from completed evidence, never replay it.',
        'mission':mission['id'],'objective_excerpt':clip(mission['objective'],600),'mode':mission['mode'],
        'completed_records':len(history),'history_sha256':digest(history),'steps_remaining':mission['max_steps']-mission['steps'],
        'recent_records':[{'step':i+1,'action':clip(row['action'],350),'result':clip(row.get('result',''),650)} for i,row in list(enumerate(history))[-4:]],
        'children':mission['children'][:16],'full_history':'Preserved in mission.json; use history(start,count) for exact records.'}
    # One replaceable key per mission; repeated chat interruptions do not grow
    # the memory table indefinitely. The execution ledger remains authoritative.
    key='direct-chat-checkpoint-'+mission['id']
    Memory(store,mission).remember(key,encoded(evidence))
    mission['chat_checkpoint']={'memory_key':key,'completed_records':len(history),'history_sha256':digest(history)}
    mission['chat_paused']=True
    if mission['status'] in ('queued','running','waiting'):mission['status']='waiting'
    store.save(mission);return mission
