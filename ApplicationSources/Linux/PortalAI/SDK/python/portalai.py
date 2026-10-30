"""PortalAI application API v1 client. Standard library only; no implicit retries."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


class APIError(RuntimeError):
    def __init__(self,status,error):
        super().__init__(error.get('message','API error'));self.status=status;self.code=error.get('code');self.error=error


class Client:
    def __init__(self,base_url,token,timeout=15):
        parsed=urllib.parse.urlsplit(base_url)
        if parsed.scheme!='http' or parsed.hostname!='127.0.0.1' or parsed.path.rstrip('/')!='/v1' or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('Copy the loopback /v1 URL from Workspace > API')
        self.base_url=base_url.rstrip('/');self.token=token;self.timeout=timeout
        self.transport=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self,method,path,body=None,*,key=None,query=None):
        if not path.startswith('/') or '..' in path or '?' in path or '#' in path:raise ValueError('Use a v1-relative resource path')
        if method not in ('GET','POST'):raise ValueError('API v1 supports GET and POST')
        if method=='POST' and not key:raise ValueError('Pass a stable idempotency key for every POST; retain it until the outcome is known')
        url=self.base_url+path+('?' + urllib.parse.urlencode(query) if query else '')
        headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'}
        if key:headers['Idempotency-Key']=key
        data=json.dumps(body if body is not None else {},allow_nan=False).encode() if method=='POST' else None
        try:
            with self.transport.open(urllib.request.Request(url,data,headers,method=method),timeout=self.timeout) as response:raw=response.read(2*1024**2+1)
        except urllib.error.HTTPError as exc:
            raw=exc.read(2*1024**2+1)
            try:error=json.loads(raw)['error']
            except (ValueError,KeyError):error={'code':'HTTP_ERROR','message':str(exc)}
            raise APIError(exc.code,error) from None
        if len(raw)>2*1024**2:raise ValueError('API result exceeded its limit')
        result=json.loads(raw)
        if result.get('api_version')!='1.0':raise ValueError('Unexpected API version')
        return result['data']

    @staticmethod
    def new_key():return uuid.uuid4().hex
    def status(self):return self.request('GET','/status')
    def create_chat(self,title,*,key):return self.request('POST','/chats',{'title':title},key=key)
    def message(self,chat,text,*,key,max_tokens=1024):return self.request('POST','/chats/'+chat+'/messages',{'message':text,'max_tokens':max_tokens},key=key)
    def structured(self,question,schema,context='',*,key,max_tokens=1024):return self.request('POST','/structured',{'question':question,'schema':schema,'context':context,'max_tokens':max_tokens},key=key)
    def job(self,jid):return self.request('GET','/jobs/'+jid)
    def cancel(self,jid,*,key):return self.request('POST','/jobs/'+jid+'/cancel',{},key=key)
    def wait(self,jid,timeout=600,interval=.25):
        deadline=time.monotonic()+timeout
        while True:
            row=self.job(jid)
            if row['state'] not in ('queued','running'):return row
            if time.monotonic()>=deadline:raise TimeoutError('Polling deadline reached; the job may still be active. Cancel explicitly if needed.')
            time.sleep(interval)
