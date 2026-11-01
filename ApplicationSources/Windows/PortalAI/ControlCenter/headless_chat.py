"""API adapter for Nice's actual chat harness, checkpoints and effect receipts."""
from collections import deque
import json
import time
from types import SimpleNamespace
from profile_context import CapturedProfile


class EventSink:
    def __init__(self):self.events=deque(maxlen=32);self.error=None
    def put(self,item,*args,**kwargs):
        name,value=item
        if name=='error':self.error=str(value)[:1500]
        if name in ('progress','error','connection_status','done'):self.events.append({'event':name,'detail':str(value)[:500]})


class APIChatStore:
    def __init__(self,state,cid,check):self.state=state;self.cid=cid;self.profile=CapturedProfile(state.root);self.check=check
    def save_session(self,session):
        self.check()
        if session.get('id')!=self.cid:raise ValueError('API chat identity changed')
        self.state.save('Chats/'+self.cid+'.json',session)
    def custom_instructions(self):
        self.check();p=self.profile.private('Data/Chat/custom_instructions.txt')
        return p.read_text(encoding='utf-8') if p.is_file() else ''


def run(api,body,check,event):
    import native_chat as native
    from chat_tool_menu import Selection
    from effort_policy import load_preferences
    from chat_effort_ui import ChatEffortControls
    from workspace_store import read_json
    cid=body['chat'];allowed=set(body['tools'])
    def grant_check():
        check()
        current=read_json(api.state.path('Tokens/'+body['token']+'.json'))
        if not allowed.issubset(set(current.get('tools',[]))):raise PermissionError('API tool grant changed')
    class GrantedRuntime(native.ToolRuntime):
        def execute(self,name,args):
            grant_check()
            if name not in allowed:raise PermissionError('This API token has no grant for '+name)
            return super().execute(name,args)
    with api.state.lock('chat-'+cid):
        session=read_json(api.state.path('Chats/'+cid+'.json'))
        if session.get('pending_agent_job'):raise RuntimeError('This chat has an unfinished agent turn; inspect saved execution receipts before starting a new conversation')
        # Record the turn before preparation; a crash cannot silently replay it.
        session['pending_agent_job']=True;session.setdefault('messages',[]).append({'role':'user','content':body['message'],'attachments':[],'created':time.time()})
        store=APIChatStore(api.state,cid,grant_check);store.save_session(session)
        panel=native.NativeChat.__new__(native.NativeChat);panel.root=api.root;panel.session=session;panel.store=store
        panel.settings={**native.DEFAULT_SETTINGS,'max_output_tokens':body.get('max_tokens',1024),'tool_call_limit':body.get('max_tool_calls',12),
                        'temperature':.2,'auto_title_chats':False,'coding_stall_auto':False,'task_progress_enabled':True}
        panel.ev=EventSink();panel.cancel_event=event;panel.active_http=native.ActiveHTTP();panel._tool_selection=Selection()
        panel._api_allowed_tools=allowed|{'chat_history','chat_checkpoint','task'}
        panel.tool_runtime=GrantedRuntime(api.root,panel.settings)
        account=getattr(api.runtime,'_account_session',None)
        if account is not None:panel.tool_runtime.bind_account(account)
        panel.tool_runtime._operation_check=grant_check
        panel._check_login=grant_check
        # API conversations do not silently import memory from unrelated GUI chats.
        panel.memory=SimpleNamespace(context_for=lambda *a,**kw:'');panel._persistent_memory_query=lambda:''
        panel._runtime_session_context=lambda memory:('API chat runtime: '+json.dumps({'chat':cid,'application_root':str(api.root),'working_directory':str(panel.tool_runtime._working_directory()),'account_role':panel.tool_runtime._account_role(),'granted_tools':sorted(allowed),'prior_chat_memory':False})+'. Saved chat_history results and checkpoints remain available. No permission beyond the listed grants is conferred.')
        panel.prepare_media_from_tool_result=lambda text:[]
        prefs=load_preferences(api.root);effort=ChatEffortControls.__new__(ChatEffortControls);effort.panel=panel
        effort.profile=prefs['chat'];effort.tools_profile=prefs['tools'];effort.active_tools_profile=prefs['tools'];effort.session_unlocked=False;effort.active_options={};effort.active_plan=None
        panel.effort=effort
        try:
            panel.agent_worker(cid)
            grant_check()
            last=session['messages'][-1]
            complete=(not event.is_set() and panel.ev.error is None and last.get('role')=='assistant' and not last.get('tool_calls')
                      and not any(last.get(k) for k in ('incomplete','cancelled','tool_validation_error')))
            if complete:session.pop('pending_agent_job',None)
            store.save_session(session)
            return {'chat':cid,'state':'complete' if complete else 'needs_review','message':last.get('content',''),
                    'events':list(panel.ev.events),'tool_messages':[{'message_id':i,'name':r.get('name'),'execution':r.get('execution')} for i,r in enumerate(session['messages']) if r.get('role')=='tool'][-32:]}
        finally:panel.cancel_http()
