"""Application API v1 adapters; no Tk calls or arbitrary host-shell endpoint."""
import base64
import json
import re
import threading
import time
from pathlib import Path
from application_api import APIState,APIError,Server
from workspace_store import identifier,read_json,digest

ROUTES=[
 ('GET','/v1/status',None),('GET','/v1/openapi.json',None),
 ('GET','/v1/chats','chats:read'),('POST','/v1/chats','chats:write'),
 ('GET','/v1/chats/{id}','chats:read'),('POST','/v1/chats/{id}/messages','chats:write'),
 ('GET','/v1/jobs',None),('GET','/v1/jobs/{id}',None),('POST','/v1/jobs/{id}/cancel',None),
 ('POST','/v1/structured','structured:generate'),
 ('GET','/v1/missions','missions:read'),('POST','/v1/missions','missions:write'),
 ('GET','/v1/missions/{id}','missions:read'),('POST','/v1/missions/{id}/start','missions:write'),('POST','/v1/missions/{id}/stop','missions:write'),
 ('GET','/v1/knowledge/collections','knowledge:read'),('POST','/v1/knowledge/collections','knowledge:write'),
 ('POST','/v1/knowledge/collections/{id}/sync','knowledge:write'),('POST','/v1/knowledge/search','knowledge:read'),('GET','/v1/knowledge/citation','knowledge:read'),
 ('GET','/v1/outputs','outputs:read'),('GET','/v1/outputs/content','outputs:read'),
 ('GET','/v1/artifacts','artifacts:read'),('POST','/v1/artifacts','artifacts:write'),
 ('GET','/v1/artifacts/{id}','artifacts:read'),('GET','/v1/artifacts/{id}/history','artifacts:read'),
 ('POST','/v1/artifacts/{id}/revisions','artifacts:write'),('POST','/v1/artifacts/{id}/restore','artifacts:write'),('POST','/v1/artifacts/{id}/export','artifacts:write')]


def fields(value,allowed,required=()):
    if set(value)-set(allowed) or set(required)-set(value):raise APIError(400,'INVALID_ARGUMENT','Expected fields: '+', '.join(allowed))


def integer(value,low,high):
    if isinstance(value,str) and value.isdecimal():value=int(value)
    if type(value) is not int or not low<=value<=high:raise APIError(400,'INVALID_ARGUMENT',f'Expected an integer in {low}..{high}')
    return value


def page(rows,query):
    fields(query,('offset','limit'));offset=integer(query.get('offset',0),0,100000);limit=integer(query.get('limit',50),1,200)
    return {'items':rows[offset:offset+limit],'offset':offset,'next_offset':offset+limit if offset+limit<len(rows) else None,'total':len(rows)}


def openapi():
    from application_api_contract import REQUESTS,QUERIES,obj
    paths={}
    for method,path,scope in ROUTES:
        operation={'operationId':method.lower()+'_'+path[4:].replace('/','_').replace('{id}','id').replace('.','_'),
                   'security':[{'bearer':[]}],'description':'Required scope: '+(scope or 'authenticated token; job access limited to its creator'),
                   'responses':{'200':{'description':'Versioned JSON envelope containing data'},'400':{'description':'Invalid request'},'401':{'description':'Invalid/expired token'},'403':{'description':'Insufficient scope or ended login'},'409':{'description':'Conflict, uncertain outcome or required review'}}}
        parameters=[]
        if '{id}' in path:parameters.append({'in':'path','name':'id','required':True,'schema':{'type':'string','pattern':'^[a-f0-9]{32}$'}})
        if method=='POST':
            parameters.append({'in':'header','name':'Idempotency-Key','required':True,'schema':{'type':'string','minLength':8,'maxLength':120}})
            operation['requestBody']={'required':True,'content':{'application/json':{'schema':REQUESTS.get(path,obj({}))}}}
        else:
            for name,value in QUERIES.get(path,{}).items():parameters.append({'in':'query','name':name,'required':name in ('citation','path'),'schema':value})
        if parameters:operation['parameters']=parameters
        paths.setdefault(path,{})[method.lower()]=operation
    return {'openapi':'3.1.0','info':{'title':'PortalAI Application API','version':'1.0.0'},'servers':[{'url':'http://127.0.0.1:{port}','variables':{'port':{'default':'0','description':'Copy the live port from Workspace > API'}}}],
            'paths':paths,'components':{'securitySchemes':{'bearer':{'type':'http','scheme':'bearer'}}}}


class ApplicationAPI:
    def __init__(self,runtime,jobs,check):
        self.runtime=runtime;self.root=runtime.root;self.jobs=jobs;self.authorized=check
        self.state=APIState(self.root,check);self.active={};self.lock=threading.RLock();self.slots=threading.BoundedSemaphore(4)
        self.server=Server(self.root,jobs,check,self)
        # Unfinished jobs are never silently replayed after a crash/relaunch.
        for jid in self.state.records('Jobs'):
            row=self.job(jid)
            if row['state'] in ('queued','running'):
                row.update(state='needs_review',error='Previous API process ended before completion was recorded',retry_safe=False)
                self.state.save('Jobs/'+jid+'.json',row)

    def start(self):return self.server.start()
    def close(self):self.server.close()
    def check(self):self.server.check()
    def cancel_all(self):
        with self.lock:
            for event in self.active.values():event.set()

    def match(self,method,path):
        for verb,pattern,scope in ROUTES:
            if verb!=method:continue
            matched=re.fullmatch(re.escape(pattern).replace(r'\{id\}',r'([a-f0-9]{32})'),path)
            if matched:return pattern,matched.groups()[0] if matched.groups() else None,scope
        raise APIError(404,'NOT_FOUND','Unknown API v1 route')

    def scope(self,method,path):return self.match(method,path)[2]
    def validate(self,path,body):
        from application_api_contract import REQUESTS,obj
        from knowledge_embeddings import packages
        packages(self.root)
        from jsonschema import Draft202012Validator
        route=self.match('POST',path)[0]
        errors=sorted(Draft202012Validator(REQUESTS.get(route,obj({}))).iter_errors(body),key=lambda e:str(list(e.path)))
        if errors:raise APIError(400,'INVALID_ARGUMENT',errors[0].message[:500])
    def job(self,jid):return read_json(self.state.path('Jobs/'+identifier(jid)+'.json'))

    def submit(self,kind,body,token,scope):
        self.check()
        if not self.slots.acquire(False):raise APIError(409,'BUSY','At most four API jobs may be active')
        jid=self.state.new_id();event=threading.Event();now=time.time()
        row={'id':jid,'kind':kind,'state':'queued','token':token['id'],'created':now,'updated':now,'input':body,'retry_safe':False}
        try:
            self.state.save('Jobs/'+jid+'.json',row)
            with self.lock:self.active[jid]=event
            deadline=time.monotonic()+600
            def check():
                self.check()
                credential=read_json(self.state.path('Tokens/'+token['id']+'.json'))
                if credential['revoked'] or credential['expires']<=time.time() or scope not in credential['scopes']:raise PermissionError('API grant ended')
                if event.is_set():raise RuntimeError('API job cancelled; completed effects are not undone')
                if time.monotonic()>deadline:raise TimeoutError('API job exceeded ten minutes')
            def run():
                try:
                    check();row.update(state='running',updated=time.time());self.state.save('Jobs/'+jid+'.json',row)
                    result=self.work(kind,body,check,event)
                    check();row.update(state='complete',result=result,updated=time.time())
                except Exception as exc:row.update(state='cancelled' if event.is_set() or self.server.stopped.is_set() else 'failed',error=str(exc)[:1500],updated=time.time())
                finally:
                    try:self.state.save('Jobs/'+jid+'.json',row)
                    finally:
                        with self.lock:self.active.pop(jid,None)
                        self.slots.release()
            self.jobs.thread(target=run,name='PortalAI-API-'+kind).start()
        except BaseException:
            with self.lock:self.active.pop(jid,None)
            self.slots.release();raise
        return {'job_id':jid,'state':'queued','status_path':'/v1/jobs/'+jid}

    def work(self,kind,body,check,event):
        if kind=='structured':
            from structured_generation import generate
            return generate(self.root,body['question'],body.get('context',''),body['schema'],check,max_tokens=body.get('max_tokens',1024))
        if kind=='knowledge_sync':
            from knowledge_base import Knowledge
            return Knowledge(self.root,check).sync(body['collection'])
        if kind=='chat':
            from structured_generation import request_json
            from chat_priority import Foreground
            from native_chat import estimate_tokens
            cid=identifier(body['chat']);relative='Chats/'+cid+'.json'
            with self.state.lock('chat-'+cid):
                saved=read_json(self.state.path(relative));before=digest(saved)
                messages=[{'role':'system','content':'You are PortalAI. Answer the user directly. This API chat channel has no tool access; do not claim actions were performed. Use the application API resources for documents, missions and artifacts.'},*saved['messages'],{'role':'user','content':body['message']}]
                props=request_json(self.root,'/props',check=check,timeout=10)
                capacity=int(props.get('default_generation_settings',{}).get('n_ctx',0));maximum=body.get('max_tokens',1024)
                if capacity<2048 or estimate_tokens(messages)+maximum+256>capacity:raise ValueError('API chat context is full; start a new chat or shorten the request')
                foreground=Foreground(self.root)
                try:
                    if not foreground.acquire(event,check,lambda _:None):raise RuntimeError('Chat cancelled')
                    value=request_json(self.root,'/v1/chat/completions',{'messages':messages,'max_tokens':maximum,'temperature':.2,'stream':False,'chat_template_kwargs':{'enable_thinking':False}},check)
                finally:foreground.close()
                choices=value.get('choices',[])
                if not choices or choices[0].get('finish_reason')!='stop':raise RuntimeError('API chat returned an incomplete answer')
                answer=choices[0].get('message',{}).get('content')
                if not isinstance(answer,str) or choices[0]['message'].get('tool_calls'):raise ValueError('API chat did not return plain text')
                check()
                if digest(read_json(self.state.path(relative)))!=before:raise RuntimeError('Conversation changed while the model was answering')
                saved['messages'].extend([{'role':'user','content':body['message']},{'role':'assistant','content':answer}]);saved['updated']=time.time()
                self.state.save(relative,saved)
                return {'chat':cid,'message':answer,'usage':value.get('usage',{})}
        raise ValueError('Unknown API job')

    def handle(self,method,path,query,body,token):
        self.check();route,rid,scope=self.match(method,path)
        if route=='/v1/status':return {'version':'1.0','running':True,'scopes':token['scopes'],'active_jobs':len(self.active)}
        if route=='/v1/openapi.json':return openapi()
        if route=='/v1/jobs':
            rows=[self.job(i) for i in self.state.records('Jobs')];return page([{k:v for k,v in r.items() if k not in ('input','result')} for r in rows if r['token']==token['id']],query)
        if route.startswith('/v1/jobs/'):
            row=self.job(rid)
            if row['token']!=token['id']:raise APIError(403,'ACCESS_REFUSED','This token did not create that job')
            if method=='POST':
                fields(body,());fields(query,())
                with self.lock:
                    if rid in self.active:self.active[rid].set()
                return {'job_id':rid,'cancellation_requested':rid in self.active,'state':row['state']}
            fields(query,());return {k:v for k,v in row.items() if k not in ('input','token')}
        if route=='/v1/chats' and method=='GET':
            rows=[read_json(self.state.path('Chats/'+i+'.json')) for i in self.state.records('Chats')]
            return page([{k:v for k,v in r.items() if k!='messages'} for r in rows],query)
        if route=='/v1/chats' and method=='POST':
            fields(body,('title',));title=body.get('title','API chat')
            if not isinstance(title,str) or not title.strip() or len(title)>160:raise ValueError('Title must contain 1..160 characters')
            cid=self.state.new_id();row={'id':cid,'title':title,'created':time.time(),'updated':time.time(),'messages':[]}
            self.state.save('Chats/'+cid+'.json',row);return row
        if route=='/v1/chats/{id}':fields(query,());return read_json(self.state.path('Chats/'+rid+'.json'))
        if route=='/v1/chats/{id}/messages':
            fields(body,('message','max_tokens'),('message',))
            if not isinstance(body['message'],str) or not body['message'].strip() or len(body['message'])>32000:raise ValueError('Message must contain 1..32000 characters')
            integer(body.get('max_tokens',1024),64,4096)
            read_json(self.state.path('Chats/'+rid+'.json'))
            return self.submit('chat',{'chat':rid,**body},token,scope)
        if route=='/v1/structured':
            fields(body,('question','context','schema','max_tokens'),('question','schema'))
            from structured_generation import schema
            schema(body['schema'],self.root);integer(body.get('max_tokens',1024),64,4096)
            return self.submit('structured',body,token,scope)
        if route.startswith('/v1/missions'):
            from mission_runner import Missions
            from mission_supervisor import arm,disarm
            store=Missions(self.root)
            if route=='/v1/missions' and method=='GET':return page([{k:v for k,v in row.items() if k not in ('history','objective','pending_action')} for row in store.list()],query)
            if route=='/v1/missions' and method=='POST':
                fields(body,('objective','mode','max_steps','armed'),('objective',))
                if type(body.get('armed',False)) is not bool:raise ValueError('armed must be boolean')
                if not isinstance(body['objective'],str):raise ValueError('Objective must be text')
                row=store.create(body['objective'],body.get('mode','observe'),integer(body.get('max_steps',12),1,100))
                if body.get('armed'):arm(self.root,row['id']);self.runtime._agents_used=True
                return {'id':row['id'],'status':row['status'],'armed':body.get('armed',False)}
            if method=='GET':
                fields(query,('history_offset','history_limit'));row=store.load(rid)
                offset=integer(query.get('history_offset',0),0,100000);limit=integer(query.get('history_limit',20),1,100);history=row.get('history',[])
                return {**row,'history':history[offset:offset+limit],'history_total':len(history),'history_offset':offset}
            fields(body,());row=store.load(rid)
            if route.endswith('/start'):
                if row.get('pending_action') or row['status']=='needs_review':raise APIError(409,'NEEDS_REVIEW','Review uncertain mission effects in the native mission panel')
                arm(self.root,rid);self.runtime._agents_used=True
            else:disarm(self.root,rid)
            return {'id':rid,'status':store.load(rid)['status'],'armed':route.endswith('/start')}
        if route.startswith('/v1/knowledge'):
            from knowledge_base import Knowledge
            kb=Knowledge(self.root,self.check)
            if route=='/v1/knowledge/collections':
                if method=='GET':return page(kb.list(),query)
                fields(body,('name','folder','ocr'),('name','folder'));return kb.create(body['name'],body['folder'],ocr=body.get('ocr',True))
            if route.endswith('/sync'):fields(body,());return self.submit('knowledge_sync',{'collection':rid},token,scope)
            if route.endswith('/search'):
                fields(body,('query','collection','limit'),('query',));return kb.search(body['query'],body.get('collection'),body.get('limit',6))
            fields(query,('citation',),('citation',));return kb.read(query['citation'])
        if route.startswith('/v1/artifacts'):
            from artifacts import Artifacts
            store=Artifacts(self.root,self.check)
            if route=='/v1/artifacts' and method=='GET':return page(store.list(),query)
            if route=='/v1/artifacts' or route.endswith('/revisions'):
                fields(body,('title','kind','content','expected_revision'),('title','kind','content'))
                return store.save(body['title'],body['kind'],body['content'],artifact=rid,expected_revision=body.get('expected_revision'))
            if route.endswith('/history'):fields(query,());return store.history(rid)
            if route.endswith('/restore'):
                fields(body,('revision','expected_revision'),('revision','expected_revision'));return store.restore(rid,body['revision'],body['expected_revision'])
            if route.endswith('/export'):fields(body,('revision',));return store.export(rid,body.get('revision'))
            fields(query,('revision',));return store.read(rid,query.get('revision'))
        if route.startswith('/v1/outputs'):
            from profile_hydration import file_listing
            from profile_paths import private_path,_relative
            if route=='/v1/outputs':return page(file_listing(self.root,'Outputs')['names'],query)
            fields(query,('path','offset','limit','identity'),('path',));relative=_relative(query['path'])
            if relative.startswith('Outputs/'):relative=relative[8:]
            target=private_path(self.root,'Outputs/'+relative);before=target.stat()
            identity=digest({'size':before.st_size,'mtime_ns':before.st_mtime_ns,'inode':before.st_ino})
            if query.get('identity') and query['identity']!=identity:raise APIError(409,'OUTPUT_CHANGED','Output changed during transfer')
            offset=integer(query.get('offset',0),0,before.st_size);limit=integer(query.get('limit',1024**2),1,1024**2)
            with target.open('rb') as stream:stream.seek(offset);data=stream.read(limit)
            self.check();after=target.stat()
            if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):raise APIError(409,'OUTPUT_CHANGED','Output changed during transfer')
            return {'path':'Outputs/'+relative,'identity':identity,'size':before.st_size,'offset':offset,'next':offset+len(data),'eof':offset+len(data)==before.st_size,'data':base64.b64encode(data).decode()}
        raise APIError(404,'NOT_FOUND','Unknown API route')
