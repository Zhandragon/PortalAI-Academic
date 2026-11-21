"""Account-checked access to real PortalAI navigation and Projection controls."""
from pathlib import Path
import queue
import threading
import time
import uuid

_endpoints={}


class Navigation:
    def __init__(self, root, events, state, navigate, utilities, locked):
        self.events=events;self.state=state;self.navigate=navigate
        self.utilities=utilities;self.locked=locked;self.dialog=None;self.token=None;self.last_snapshot=None
        _endpoints[str(Path(root).resolve())]=self

    def snapshot(self):
        self.token=uuid.uuid4().hex
        result={**self.state(),'observation':self.token}
        if self.dialog is not None and not self.dialog.closed:
            result['buttons']=['PortalAI Home Assistant Projection','Close utilities']
            result['utility_status']=self.dialog.status.get()
        else:result['buttons']=['Utilities']
        self.last_snapshot=result
        return result

    def execute(self,args,check):
        check()
        if self.locked():raise PermissionError('PortalAI is locked or exiting')
        action=args.get('action','state')
        if action=='state':return self.snapshot()
        if args.get('observation')!=self.token or self.token is None:
            raise ValueError('Read fresh portal_ui state before acting')
        self.token=None
        if action=='navigate':
            page=args.get('page')
            if page not in self.state()['pages']:raise ValueError('Select a page returned by state')
            self.navigate(page)
        elif action=='click':
            name=args.get('button')
            if name=='Utilities':
                if self.dialog is None or self.dialog.closed:self.dialog=self.utilities()
            elif name=='Close utilities' and self.dialog is not None:self.dialog.close()
            elif name=='PortalAI Home Assistant Projection' and self.dialog is not None and not self.dialog.closed:
                matches=[b for b,_ in self.dialog.buttons if str(b.cget('text'))==name]
                if len(matches)!=1:raise RuntimeError('Projection button is unavailable')
                matches[0].invoke()
            else:raise ValueError('Select a button returned by portal_ui state')
        else:raise ValueError('portal_ui actions: state, navigate, click')
        check()
        return {**self.snapshot(),'performed':True}

    def dispatch(self,request):
        args,check,cancelled,reply=request
        if cancelled.is_set():return
        try:reply.put((True,self.execute(args,check)))
        except Exception as exc:reply.put((False,exc))


def call(root,args,check):
    endpoint=_endpoints.get(str(Path(root).resolve()))
    if endpoint is None:raise RuntimeError('PortalAI UI navigation is available only in the running local Control Center')
    check();reply=queue.Queue(1);cancelled=threading.Event()
    endpoint.events.put(('portal_navigation',(endpoint,(args,check,cancelled,reply))))
    deadline=time.monotonic()+20
    try:
        while time.monotonic()<deadline:
            check()
            try:ok,result=reply.get(timeout=.05)
            except queue.Empty:continue
            if not ok:raise result
            return result
        raise TimeoutError('PortalAI UI did not respond; read state before retrying')
    finally:cancelled.set()


def observed(root):
    endpoint=_endpoints.get(str(Path(root).resolve()))
    return endpoint.last_snapshot if endpoint is not None and endpoint.token is not None else None


def configure(root,app,events,state,navigate,utilities,locked):
    endpoint=Navigation(root,events,state,navigate,utilities,locked)
    def close(event):
        key=str(Path(root).resolve())
        if event.widget is app and _endpoints.get(key) is endpoint:_endpoints.pop(key,None)
    app.bind('<Destroy>',close,add='+')
    return endpoint
