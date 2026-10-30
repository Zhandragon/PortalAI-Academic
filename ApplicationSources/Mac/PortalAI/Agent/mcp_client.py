"""Bounded MCP tools client: stdio and Streamable HTTP, with explicit tool grants."""
import http.client
import json
from pathlib import Path
import queue
import re
import ssl
import subprocess
import threading
import time
import urllib.parse

from workspace_store import Workspace, identifier, read_json, encoded, digest

VERSIONS=('2025-11-25','2025-06-18','2025-03-26','2024-11-05')
LIMIT=2*1024**2


class Transport:
    def __init__(self,root,config,check):
        self.root=Path(root);self.config=config;self.check=check;self.process=None;self.job=None;self.conn=None;self.socket=None
        self.messages=queue.Queue(maxsize=128);self.session=None;self.version=VERSIONS[0];self.sequence=0;self.closed=False;self.diagnostic=b''

    def close(self):
        self.closed=True
        if self.socket:
            try:
                import socket
                self.socket.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.socket=None
        if self.conn:
            try:
                if self.conn.sock:
                    import socket
                    self.conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:pass
            self.conn.close()
        if self.job:
            try:self.job.close()
            finally:self.job=None
        if self.process:
            if self.process.poll() is None:self.process.kill()
            self.process.wait(timeout=10)
            for s in (self.process.stdin,self.process.stdout,self.process.stderr):
                if s:s.close()
            self.process=None

    def _start(self):
        from platform_runtime import python_path,worker_process_options
        from mission_supervisor import WorkerJob
        from runtime_policy import portable_env
        command=[]
        for i,arg in enumerate(self.config['command']):
            if i==0:
                if arg=='{python}':arg=str(python_path(self.root))
                else:
                    from profile_paths import _relative,_contained
                    arg=str(_contained(self.root,self.root/_relative(arg)))
                if not Path(arg).is_file():raise FileNotFoundError('Configured portable MCP executable is missing')
            else:arg=arg.replace('{root}',str(self.root))
            command.append(arg)
        env=portable_env(self.root)
        # Server receives only a small OS/portable environment, never the login
        # identity or account unlock state. Explicit connection env is private.
        keep={'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','LANG','LC_ALL','LD_LIBRARY_PATH','SSL_CERT_FILE'}
        env={k:v for k,v in env.items() if k.upper() in keep}
        env.update(self.config.get('env',{}));env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
        from profile_paths import private_path
        cwd=private_path(self.root,'Data/Connections/Working/'+self.config['id']);cwd.mkdir(parents=True,exist_ok=True)
        temp=cwd/'tmp';temp.mkdir(exist_ok=True)
        env.update(TEMP=str(temp),TMP=str(temp),TMPDIR=str(temp),HOME=str(cwd),USERPROFILE=str(cwd))
        self.check()
        p=subprocess.Popen([str(python_path(self.root)),'-B','-I',str(self.root/'Agent/mcp_launch.py')],cwd=self.root,
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),**worker_process_options())
        self.process=p
        def diagnostics():
            while not self.closed:
                data=p.stderr.read1(1024)
                if not data:break
                self.diagnostic=(self.diagnostic+data)[-8192:]
        threading.Thread(target=diagnostics,daemon=True,name='PortalAI-MCP-diagnostic').start()
        try:
            self.job=WorkerJob(p);self.job.limit_memory(1024*1024**2);self.check()
            p.stdin.write(encoded({'command':command,'environment':env,'cwd':str(cwd)})+b'\n');p.stdin.flush()
        except BaseException:self.close();raise
        def reader():
            try:
                while not self.closed:
                    line=p.stdout.readline(LIMIT+1)
                    if not line:raise EOFError('MCP server ended: '+self.diagnostic.decode('utf-8',errors='replace'))
                    if len(line)>LIMIT:raise ValueError('MCP response exceeds 2 MiB')
                    value=json.loads(line)
                    try:self.messages.put(value,timeout=.5)
                    except queue.Full:raise RuntimeError('MCP server flooded the client')
            except Exception as exc:
                try:self.messages.put(exc,timeout=.5)
                except queue.Full:pass
        threading.Thread(target=reader,daemon=True,name='PortalAI-MCP-reader').start()

    def _headers(self):
        headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':self.version}
        headers.update(self.config.get('headers',{}))
        if self.session:headers['Mcp-Session-Id']=self.session
        return headers

    def _http(self,message):
        target=urllib.parse.urlsplit(self.config['url']);context=ssl.create_default_context()
        conn=(http.client.HTTPSConnection(target.hostname,target.port,timeout=60,context=context) if target.scheme=='https'
              else http.client.HTTPConnection(target.hostname,target.port,timeout=60))
        self.conn=conn;result=queue.Queue(1)
        def request():
            try:
                conn.connect();self.socket=conn.sock
                conn.request('POST',target.path+('?' +target.query if target.query else ''),encoded(message),self._headers())
                response=conn.getresponse()
                if response.status==202 and 'id' not in message:result.put([]);return
                if response.status!=200:raise RuntimeError('MCP endpoint returned HTTP '+str(response.status))
                sid=response.getheader('Mcp-Session-Id')
                if sid:
                    if not re.fullmatch(r'[\x21-\x7e]{1,256}',sid):raise ValueError('Invalid MCP session ID')
                    self.session=sid
                if 'text/event-stream' in response.getheader('Content-Type',''):
                    data=[];size=0;events=[]
                    while True:
                        line=response.readline(LIMIT+1);size+=len(line)
                        if size>LIMIT:raise ValueError('MCP stream exceeds 2 MiB')
                        if not line:break
                        if line.startswith(b'data:'):data.append(line[5:].lstrip().decode('utf-8').rstrip('\r\n'))
                        elif not line.strip() and data:
                            item=json.loads('\n'.join(data));data=[];events.append(item)
                            if item.get('id')==message.get('id') and ('result' in item or 'error' in item):break
                            if len(events)>128:raise ValueError('Too many MCP stream events')
                    result.put(events)
                else:
                    raw=response.read(LIMIT+1)
                    if len(raw)>LIMIT:raise ValueError('MCP response exceeds 2 MiB')
                    result.put([json.loads(raw)])
            except Exception as exc:result.put(exc)
            finally:conn.close()
        thread=threading.Thread(target=request,daemon=True,name='PortalAI-MCP-http');thread.start()
        deadline=time.monotonic()+65;completed=False
        try:
            while True:
                self.check()
                if self.closed:raise RuntimeError('MCP call cancelled; outcome may be uncertain')
                if time.monotonic()>deadline:raise TimeoutError('MCP endpoint timed out; no automatic replay')
                try:value=result.get(timeout=.1);break
                except queue.Empty:continue
            if isinstance(value,Exception):raise value
            completed=True
            return value
        finally:
            if not completed:self.close()
            thread.join(1);self.conn=None;self.socket=None

    def send(self,message):
        if len(encoded(message))>LIMIT:raise ValueError('MCP request exceeds 2 MiB')
        self.check()
        if self.closed:raise RuntimeError('MCP connection is closed')
        if self.config['transport']=='http':return self._http(message)
        if self.process is None:self._start()
        self.process.stdin.write(encoded(message)+b'\n');self.process.stdin.flush()
        return []

    def request(self,method,params=None):
        self.sequence+=1;mid=self.sequence
        immediate=self.send({'jsonrpc':'2.0','id':mid,'method':method,'params':params or {}})
        deadline=time.monotonic()+60;seen=0
        while time.monotonic()<deadline:
            self.check();seen+=1
            if seen>512:raise RuntimeError('MCP message limit exceeded')
            if immediate:value=immediate.pop(0)
            elif self.config['transport']=='http':raise RuntimeError('MCP endpoint returned no matching response')
            else:
                try:value=self.messages.get(timeout=.2)
                except queue.Empty:seen-=1;continue
            if isinstance(value,Exception):raise value
            if not isinstance(value,dict) or value.get('jsonrpc')!='2.0':raise ValueError('Invalid MCP JSON-RPC message')
            if 'method' in value:
                if 'id' in value:
                    reply={'jsonrpc':'2.0','id':value['id']}
                    reply.update({'result':{}} if value['method']=='ping' else {'error':{'code':-32601,'message':'Client capability not supported'}})
                    self.send(reply)
                continue
            if value.get('id')!=mid:continue
            if 'error' in value:raise RuntimeError('MCP server error: '+str(value['error'])[:2000])
            if not isinstance(value.get('result'),dict):raise ValueError('Invalid MCP result')
            return value['result']
        raise TimeoutError('MCP request timed out; no automatic replay')

    def initialize(self):
        value=self.request('initialize',{'protocolVersion':VERSIONS[0],'capabilities':{},'clientInfo':{'name':'PortalAI','version':'workspace-1'}})
        if value.get('protocolVersion') not in VERSIONS:raise ValueError('MCP protocol version is not supported')
        self.version=value['protocolVersion']
        if 'tools' not in value.get('capabilities',{}):raise ValueError('This MCP server does not expose tools')
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})

    def tools(self):
        result=[];cursor=None;seen=set()
        while True:
            page=self.request('tools/list',{'cursor':cursor} if cursor else {})
            tools=page.get('tools')
            if not isinstance(tools,list):raise ValueError('Invalid MCP tools list')
            result.extend(tools)
            if len(result)>256:raise ValueError('MCP server exceeds 256 tools')
            cursor=page.get('nextCursor')
            if not cursor:break
            if not isinstance(cursor,str) or cursor in seen:raise ValueError('MCP pagination cycle')
            seen.add(cursor)
        names=set()
        for row in result:
            if not isinstance(row,dict) or not isinstance(row.get('name'),str) or row['name'] in names or len(row['name'])>200:raise ValueError('Invalid or duplicate MCP tool name')
            names.add(row['name'])
            if not isinstance(row.get('inputSchema'),dict):raise ValueError('MCP tool input schema is missing')
        return result


class Connections(Workspace):
    def __init__(self,root,check=None):super().__init__(root,'Connections',check)

    def load(self,cid):
        row=read_json(self.path('Servers/'+identifier(cid)+'.json'))
        if row.get('id')!=cid:raise ValueError('Connection identity mismatch')
        return row

    def list(self):
        return [{'id':r['id'],'name':r['name'],'transport':r['transport'],'enabled':r['enabled'],
                 'tools':list(r.get('grants',{}))} for r in (self.load(cid) for cid in self.records('Servers'))]

    def create(self,name,transport,*,command=None,url=None,env=None,headers=None):
        if not isinstance(name,str) or not 1<=len(name.strip())<=120:raise ValueError('Choose a connection name of 1–120 characters')
        if transport not in ('stdio','http'):raise ValueError('Choose stdio or http')
        if transport=='stdio':
            if not isinstance(command,list) or not 1<=len(command)<=64 or any(not isinstance(x,str) or len(x)>8000 or '\0' in x for x in command):raise ValueError('Command must be an executable and argument list')
            if command[0]!='{python}':
                from profile_paths import _relative
                _relative(command[0])
        else:
            parsed=urllib.parse.urlsplit(str(url))
            if parsed.username or parsed.password or parsed.fragment or not parsed.hostname:raise ValueError('Invalid MCP URL; use private headers for credentials')
            if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('localhost','127.0.0.1','::1')):raise ValueError('MCP needs HTTPS, or HTTP on loopback')
        for mapping in (env or {},headers or {}):
            if not isinstance(mapping,dict) or any(not isinstance(k,str) or not isinstance(v,str) or '\n' in k+v or '\r' in k+v for k,v in mapping.items()):raise ValueError('Environment and headers must be text mappings')
        reserved={'content-type','accept','mcp-protocol-version','mcp-session-id','host','content-length'}
        if any(k.lower() in reserved for k in (headers or {})):raise ValueError('Protocol headers are managed by PortalAI')
        row={'id':self.new_id(),'name':name.strip(),'transport':transport,'command':command,'url':url,'env':env or {},'headers':headers or {},'enabled':False,'grants':{}}
        self.save('Servers/'+row['id']+'.json',row);return {'id':row['id'],'name':row['name']}

    def discover(self,cid):
        t=Transport(self.root,self.load(cid),self.check)
        try:t.initialize();return t.tools()
        finally:t.close()

    def grant(self,cid,tools,*,enabled=True,read_only=()):
        """Only the authenticated management UI calls this method; hints do not grant access."""
        with self.lock(cid):
            row=self.load(cid)
            row['enabled']=bool(enabled)
            row['grants']={tool['name']:{'schema':tool['inputSchema'],'schema_hash':digest(tool['inputSchema']),
                 'read_only':tool['name'] in read_only,'description':str(tool.get('description',''))[:2000]} for tool in tools}
            self.save('Servers/'+cid+'.json',row)

    def call(self,cid,tool,arguments,operation_id=None):
        from knowledge_embeddings import packages
        packages(self.root)
        from jsonschema import Draft202012Validator
        row=self.load(cid);grant=row.get('grants',{}).get(tool)
        if not row['enabled'] or not grant:raise PermissionError('Enable this connection and approve the tool in Workspace > Connections')
        if not isinstance(arguments,dict):raise ValueError('Tool arguments must be an object')
        # Remote schema references could cause hidden network access. Local
        # fragment references remain supported by the JSON Schema validator.
        def refs(value):
            if isinstance(value,dict):
                for k,v in value.items():
                    if k in ('$ref','$dynamicRef') and (not isinstance(v,str) or not v.startswith('#')):raise ValueError('External schema references are not supported')
                    refs(v)
            elif isinstance(value,list):
                for v in value:refs(v)
        refs(grant['schema']);Draft202012Validator.check_schema(grant['schema']);Draft202012Validator(grant['schema']).validate(arguments)
        action={'connection':cid,'tool':tool,'arguments':arguments};signature=digest(action)
        # Serialize dispatch and the write-ahead receipt; no concurrent duplicate
        # can pass the uncertainty fence while another call is still in flight.
        with self.lock('calls'):
            for rid in self.records('Receipts'):
                saved=read_json(self.path('Receipts/'+rid+'.json'))
                if saved.get('operation_id')==operation_id and operation_id is not None:
                    if saved['signature']!=signature:raise ValueError('Operation ID was reused with different arguments')
                    if saved['state']=='complete':return saved['result']
                    if saved.get('decision')=='confirmed':return {'content':[{'type':'text','text':'Human review confirmed the earlier action. No stored result is available; it was not executed again.'}],'reviewed':True}
                if saved['signature']==signature and saved['state']=='pending':raise RuntimeError('An earlier call has an uncertain outcome; review its receipt before repeating')
            t=Transport(self.root,row,self.check)
            try:
                t.initialize();current={r['name']:r for r in t.tools()}
                if tool not in current or digest(current[tool]['inputSchema'])!=grant['schema_hash']:raise PermissionError('Server tool schema changed; review and approve it again')
                latest=self.load(cid)
                if not latest['enabled'] or latest.get('grants',{}).get(tool)!=grant:raise PermissionError('MCP permission changed before dispatch')
                rid=self.new_id();receipt={'id':rid,'signature':signature,'operation_id':operation_id,'connection':cid,'tool':tool,
                    'arguments':arguments,'state':'pending','at':time.time(),'read_only':grant['read_only']}
                self.save('Receipts/'+rid+'.json',receipt);self.check()
                result=t.request('tools/call',{'name':tool,'arguments':arguments})
                self.check();receipt.update(state='complete',result=result);self.save('Receipts/'+rid+'.json',receipt)
                return result
            finally:t.close()

    def receipts(self):return [read_json(self.path('Receipts/'+rid+'.json')) for rid in self.records('Receipts')]

    def resolve(self,rid,decision):
        if decision not in ('confirmed','allow_retry'):raise ValueError('Choose confirmed or allow_retry after checking the external outcome')
        with self.lock('calls'):
            path='Receipts/'+identifier(rid)+'.json';row=read_json(self.path(path))
            if row['state']!='pending':raise ValueError('Receipt does not require review')
            row.update(state='reviewed',decision=decision,reviewed_at=time.time());self.save(path,row)
