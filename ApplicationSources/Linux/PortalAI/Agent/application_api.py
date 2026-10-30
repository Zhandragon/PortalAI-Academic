"""Versioned loopback HTTP boundary, scoped bearer grants and write receipts."""
import hashlib
import hmac
import http.server
import json
import re
import secrets
import threading
import time
import urllib.parse
from workspace_store import Workspace,identifier,read_json,digest,encoded

SCOPES={'chats:read','chats:write','missions:read','missions:write','knowledge:read',
        'knowledge:write','outputs:read','artifacts:read','artifacts:write','structured:generate'}


class APIError(Exception):
    def __init__(self,status,code,message):super().__init__(message);self.status=status;self.code=code


class APIState(Workspace):
    def __init__(self,root,check=None):super().__init__(root,'ApplicationAPI',check)

    def tokens(self):
        rows=[read_json(self.path('Tokens/'+i+'.json')) for i in self.records('Tokens')]
        return [{k:v for k,v in row.items() if k!='secret_hash'} for row in rows]

    def issue(self,name,scopes,hours=24):
        if not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('Token name must contain 1..100 characters')
        if not isinstance(scopes,list) or not scopes or any(s not in SCOPES for s in scopes):raise ValueError('Choose explicit supported API scopes')
        if type(hours) is not int or not 1<=hours<=720:raise ValueError('Token lifetime must be 1..720 hours')
        with self.lock('tokens'):
            if len(self.records('Tokens'))>=128:raise ValueError('Token catalogue limit reached')
            tid=self.new_id();secret=secrets.token_urlsafe(32)
            row={'id':tid,'name':name.strip(),'scopes':sorted(set(scopes)),'expires':time.time()+hours*3600,'revoked':False,
                 'secret_hash':hashlib.sha256(secret.encode()).hexdigest()}
            self.save('Tokens/'+tid+'.json',row)
        return {'id':tid,'token':'pai_'+tid+'.'+secret,'scopes':row['scopes'],'expires':row['expires'],'note':'Copy this token now; only its hash is stored.'}

    def revoke(self,tid):
        with self.lock('tokens'):
            path='Tokens/'+identifier(tid)+'.json';row=read_json(self.path(path));row['revoked']=True;self.save(path,row)

    def authenticate(self,value,scope=None):
        self.check()
        if not isinstance(value,str) or not re.fullmatch(r'Bearer pai_[a-f0-9]{32}\.[A-Za-z0-9_-]{43}',value):raise APIError(401,'UNAUTHORIZED','A valid bearer token is required')
        tid,secret=value[11:].split('.',1)
        try:row=read_json(self.path('Tokens/'+identifier(tid)+'.json'))
        except (FileNotFoundError,ValueError):raise APIError(401,'UNAUTHORIZED','A valid bearer token is required') from None
        valid=hmac.compare_digest(row['secret_hash'],hashlib.sha256(secret.encode()).hexdigest())
        if not valid or row['revoked'] or row['expires']<=time.time():raise APIError(401,'UNAUTHORIZED','Token is revoked, expired or invalid')
        if scope and scope not in row['scopes']:raise APIError(403,'SCOPE_REQUIRED','This operation requires '+scope)
        return row

    def receipt(self,token,key,method,path,body,operation):
        if not isinstance(key,str) or not re.fullmatch('[A-Za-z0-9_.:-]{8,120}',key):raise APIError(400,'IDEMPOTENCY_KEY_REQUIRED','POST requests require an Idempotency-Key of 8..120 safe characters')
        rid=hashlib.sha256((token['id']+':'+key).encode()).hexdigest()[:32]
        fingerprint=digest({'method':method,'path':path,'body':body});relative='Receipts/'+rid+'.json'
        with self.lock('receipts'):
            current=read_json(self.path(relative)) if self.path(relative).exists() else None
            if current:
                if current['fingerprint']!=fingerprint:raise APIError(409,'IDEMPOTENCY_CONFLICT','This key was used for a different request')
                if current['state']=='complete':return current['result']
                if current['state']!='retry_allowed':raise APIError(409,'NEEDS_REVIEW','The prior outcome is uncertain; review its receipt in Workspace')
            rows=self.records('Receipts')
            if len(rows)>=10000:raise APIError(409,'RECEIPT_LIMIT','Receipt retention needs review before more API writes')
            for other in rows:
                if other==rid:continue
                row=read_json(self.path('Receipts/'+other+'.json'))
                if row['fingerprint']==fingerprint and row['state']=='pending':raise APIError(409,'NEEDS_REVIEW','An equivalent request has an uncertain outcome; a new key cannot bypass review')
            row={'id':rid,'token':token['id'],'fingerprint':fingerprint,'method':method,'path':path,'state':'pending','created':time.time()}
            self.save(relative,row)
            try:result=operation()
            except Exception:
                # The process may already have published a local/external effect.
                # Retain pending; never convert an exception to permission to retry.
                raise
            row.update(state='complete',result=result);self.save(relative,row);return result

    def pending(self):
        rows=[read_json(self.path('Receipts/'+i+'.json')) for i in self.records('Receipts')]
        return [row for row in rows if row['state']=='pending']

    def resolve(self,rid,decision,result=None):
        if decision not in ('confirmed','allow_retry'):raise ValueError('Review decision must be confirmed or allow_retry')
        with self.lock('receipts'):
            relative='Receipts/'+identifier(rid)+'.json';row=read_json(self.path(relative))
            if row['state']!='pending':raise ValueError('Receipt is not pending review')
            row.update(state='complete' if decision=='confirmed' else 'retry_allowed',reviewed_at=time.time(),reviewed=True)
            if decision=='confirmed':row['result']=result
            self.save(relative,row)
        return {'id':rid,'state':row['state']}


class Server:
    def __init__(self,root,jobs,check,backend):
        self.root=root;self.jobs=jobs;self.authorized=check;self.backend=backend
        self.state=APIState(root,check);self.stopped=threading.Event();self.http=None;self.worker=None;self.slots=threading.BoundedSemaphore(8)

    def check(self):
        self.authorized()
        if self.stopped.is_set():raise APIError(503,'STOPPED','Application API is stopped')

    def start(self):
        self.check();service=self
        class HTTP(http.server.HTTPServer):
            allow_reuse_address=False
            def process_request(self,request,address):
                if not service.slots.acquire(False):self.shutdown_request(request);return
                def handle():
                    try:self.finish_request(request,address)
                    finally:self.shutdown_request(request);service.slots.release()
                try:service.jobs.thread(target=handle,name='PortalAI-API-request').start()
                except BaseException:self.shutdown_request(request);service.slots.release();raise
        class Handler(http.server.BaseHTTPRequestHandler):
            server_version='PortalAI-API/1';sys_version='';protocol_version='HTTP/1.0'
            def log_message(self,*args):pass
            def setup(self):super().setup();self.connection.settimeout(5)
            def do_GET(self):self.execute()
            def do_POST(self):self.execute()
            def execute(self):
                status=200
                try:
                    service.check()
                    if self.headers.get('Host')!='127.0.0.1:'+str(service.http.server_port) or self.headers.get_all('Origin'):
                        raise APIError(403,'ORIGIN_REFUSED','Only direct loopback application clients are accepted')
                    if self.headers.get_all('Transfer-Encoding'):raise APIError(400,'INVALID_BODY','Chunked requests are not accepted')
                    if len(self.path)>4096:raise APIError(400,'INVALID_PATH','Request path exceeds limit')
                    parsed=urllib.parse.urlsplit(self.path)
                    if parsed.scheme or parsed.netloc or parsed.fragment:raise APIError(400,'INVALID_PATH','Use an API-relative path')
                    path=parsed.path;query=urllib.parse.parse_qs(parsed.query,strict_parsing=True,keep_blank_values=True)
                    if any(len(v)!=1 for v in query.values()):raise APIError(400,'INVALID_QUERY','Duplicate query fields are not accepted')
                    query={k:v[0] for k,v in query.items()}
                    headers=self.headers.get_all('Authorization') or []
                    if len(headers)!=1:raise APIError(401,'UNAUTHORIZED','A valid bearer token is required')
                    token=service.state.authenticate(headers[0],service.backend.scope(self.command,path))
                    body={}
                    if self.command=='POST':
                        lengths=self.headers.get_all('Content-Length') or []
                        if len(lengths)!=1 or not lengths[0].isdigit() or not 0<=int(lengths[0])<=2*1024**2:raise APIError(400,'INVALID_BODY','A bounded Content-Length is required')
                        if self.headers.get_content_type()!='application/json':raise APIError(400,'INVALID_BODY','Use application/json')
                        raw=self.rfile.read(int(lengths[0]))
                        if len(raw)!=int(lengths[0]):raise APIError(400,'INVALID_BODY','Request body was truncated')
                        def pairs(items):
                            value={}
                            for key,item in items:
                                if key in value:raise ValueError('Duplicate request field')
                                value[key]=item
                            return value
                        body=json.loads(raw or b'{}',object_pairs_hook=pairs)
                        encoded(body)
                        if query:raise ValueError('POST requests do not accept query fields')
                        if not isinstance(body,dict):raise APIError(400,'INVALID_BODY','Body must be a JSON object')
                    invoke=lambda:service.backend.handle(self.command,path,query,body,token)
                    if self.command=='POST':
                        service.backend.validate(path,body)
                        keys=self.headers.get_all('Idempotency-Key') or []
                        result=service.state.receipt(token,keys[0] if len(keys)==1 else None,self.command,self.path,body,invoke)
                    else:result=invoke()
                    service.check();payload={'api_version':'1.0','data':result}
                except APIError as exc:status=exc.status;payload={'api_version':'1.0','error':{'code':exc.code,'message':str(exc)}}
                except (ValueError,TypeError,KeyError) as exc:status=400;payload={'api_version':'1.0','error':{'code':'INVALID_ARGUMENT','message':str(exc)[:500]}}
                except FileNotFoundError:status=404;payload={'api_version':'1.0','error':{'code':'NOT_FOUND','message':'The requested record does not exist'}}
                except PermissionError:status=403;payload={'api_version':'1.0','error':{'code':'ACCESS_ENDED','message':'The account session or grant is no longer active'}}
                except Exception as exc:status=409;payload={'api_version':'1.0','error':{'code':'INCOMPLETE','message':str(exc)[:500],'retry_safe':False}}
                data=encoded(payload)
                if len(data)>2*1024**2:status=413;data=encoded({'api_version':'1.0','error':{'code':'RESULT_LIMIT','message':'Narrow or paginate the result'}})
                try:
                    self.send_response(status);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Connection','close');self.end_headers();self.wfile.write(data)
                except (OSError,TimeoutError):pass
        self.http=HTTP(('127.0.0.1',0),Handler);self.http.timeout=.2
        from workspace_services import register
        register(self.root,self)
        def run():
            try:
                while not self.stopped.is_set():self.check();self.http.handle_request()
            except (OSError,RuntimeError,PermissionError,ValueError,APIError):pass
            finally:self.close()
        self.worker=self.jobs.thread(target=run,name='PortalAI-application-API')
        try:self.worker.start()
        except BaseException:self.close();raise
        return {'api_version':'1.0','base_url':'http://127.0.0.1:'+str(self.http.server_port)+'/v1','binding':'loopback only','authentication':'scoped bearer token'}

    def close(self):
        self.stopped.set();self.backend.cancel_all()
        if self.http:self.http.server_close()
        from workspace_services import unregister
        unregister(self.root,self)
