"""OAuth authorization-code/PKCE for pre-registered public MCP clients.

Uses stdlib HTTPS and a temporary loopback callback. No client secret, hosted
proxy, token forwarding, automatic effect retry, or additional service.
"""
import base64
import hashlib
import http.client
import http.server
import json
import secrets
import re
import ssl
import time
import urllib.parse as url

LIMIT = 256*1024


def endpoint(value):
    p = url.urlsplit(value)
    if not p.hostname or p.username or p.password or p.fragment:
        raise ValueError('Invalid OAuth endpoint')
    if p.scheme != 'https' and not (p.scheme == 'http' and p.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise ValueError('OAuth requires HTTPS except on loopback')
    return p


def request_json(target, check, fields=None, *, json_fields=None):
    p = endpoint(target); check()
    conn = (http.client.HTTPSConnection(p.hostname,p.port,timeout=15,context=ssl.create_default_context())
            if p.scheme=='https' else http.client.HTTPConnection(p.hostname,p.port,timeout=15))
    try:
        if fields is not None and json_fields is not None:raise ValueError('Choose one OAuth request format')
        body = json.dumps(json_fields).encode() if json_fields is not None else url.urlencode(fields).encode() if fields is not None else None
        conn.request('POST' if body is not None else 'GET', (p.path or '/')+('?' + p.query if p.query else ''), body,
                     {'Accept':'application/json', **({'Content-Type':'application/json' if json_fields is not None else 'application/x-www-form-urlencoded'} if body is not None else {})})
        response=conn.getresponse(); data=response.read(LIMIT+1); check()
        if response.status not in (200,201): raise RuntimeError('OAuth endpoint returned HTTP '+str(response.status))
        if len(data)>LIMIT: raise ValueError('OAuth response exceeds 256 KiB')
        result=json.loads(data)
        if not isinstance(result,dict):raise ValueError('Invalid OAuth metadata/response')
        return result
    finally:conn.close()


def validate_config(config):
    if not isinstance(config,dict) or set(config)-{'issuer','client_id','scope','callback_port','client_mode'}:
        raise ValueError('OAuth fields: issuer, client_id, scope, callback_port, client_mode')
    mode=config.get('client_mode','registered')
    if mode not in ('registered','dynamic','metadata'):raise ValueError('Choose registered, dynamic or metadata client mode')
    issuer=config.get('issuer','').rstrip('/')
    if issuer:endpoint(issuer)
    if url.urlsplit(issuer).query:raise ValueError('OAuth issuer cannot contain a query')
    client=config.get('client_id','');scope=config.get('scope','');port=config.get('callback_port',0)
    if not isinstance(client,str) or not (0 if mode=='dynamic' else 1)<=len(client)<=1000 or any(c in client for c in '\r\n'):
        raise ValueError('Provide the public client ID registered with this provider')
    if mode=='metadata':
        p=endpoint(client)
        if p.scheme!='https' or p.query or not p.path:raise ValueError('Client metadata ID must be a public HTTPS document URL')
    if not isinstance(scope,str) or len(scope)>2000 or any(c in scope for c in '\r\n'):
        raise ValueError('Invalid OAuth scope')
    if type(port) is not int or not (port==0 or 1024<=port<=65535):raise ValueError('Callback port must be 0 (automatic) or 1024–65535')
    value={'issuer':issuer,'client_id':client,'scope':scope,'callback_port':port}
    if mode!='registered':value['client_mode']=mode
    return value


def protected_metadata_url(resource,check):
    """Probe headers only; never send a tool call or follow a redirect."""
    p=endpoint(resource);check()
    conn=(http.client.HTTPSConnection(p.hostname,p.port,timeout=10,context=ssl.create_default_context())
          if p.scheme=='https' else http.client.HTTPConnection(p.hostname,p.port,timeout=10))
    try:
        conn.request('GET',(p.path or '/')+('?' +p.query if p.query else ''),headers={'Accept':'application/json, text/event-stream'})
        response=conn.getresponse();check()
        if response.status!=401:return None
        header=response.getheader('WWW-Authenticate','')
        if len(header)>8192:raise ValueError('MCP authentication challenge exceeds its limit')
        matches=re.findall(r'\bresource_metadata\s*=\s*"([^"\r\n]+)"',header,re.I)
        if len(matches)>1:raise ValueError('Ambiguous MCP resource metadata challenge')
        if matches:endpoint(matches[0]);return matches[0]
        return None
    finally:conn.close()


def metadata(config,resource,check):
    """Bind the configured issuer to this exact protected resource before login."""
    p=endpoint(resource);origin=url.urlunsplit((p.scheme,p.netloc,'','',''))
    protected=None
    targets=[origin+'/.well-known/oauth-protected-resource'+suffix for suffix in (p.path.rstrip('/'),'')]
    for target in dict.fromkeys(targets):
        try: protected=request_json(target,check);break
        except RuntimeError:continue
    if protected is None:
        challenged=protected_metadata_url(resource,check)
        if challenged:protected=request_json(challenged,check)
    if protected is None:raise ValueError('Server must expose protected-resource metadata for OAuth sign-in')
    if str(protected.get('resource','')).rstrip('/')!=resource.rstrip('/'):
        raise ValueError('OAuth resource metadata does not match this MCP connection')
    issuers=protected.get('authorization_servers',[])
    if not isinstance(issuers,list) or not 1<=len(issuers)<=16:raise ValueError('MCP resource must advertise bounded authorization servers')
    issuer=config['issuer'] or str(issuers[0]).rstrip('/')
    if issuer not in [str(v).rstrip('/') for v in issuers]:
        raise ValueError('Configured issuer is not advertised by this MCP resource')
    ip=endpoint(issuer);base=url.urlunsplit((ip.scheme,ip.netloc,'','',''));path=ip.path.rstrip('/')
    doc=None
    for target in (base+'/.well-known/oauth-authorization-server'+path,
                   base+'/.well-known/openid-configuration'+path,issuer+'/.well-known/openid-configuration'):
        try:doc=request_json(target,check);break
        except RuntimeError:continue
    if doc is None or str(doc.get('issuer','')).rstrip('/')!=issuer:raise ValueError('OAuth issuer metadata mismatch')
    if 'S256' not in doc.get('code_challenge_methods_supported',[]):raise ValueError('OAuth provider must support PKCE S256')
    endpoint(doc.get('authorization_endpoint',''));endpoint(doc.get('token_endpoint',''))
    return doc


def client_for_redirect(config,doc,redirect,check):
    mode=config.get('client_mode','registered')
    if mode=='registered':return config['client_id']
    if mode=='metadata':
        if doc.get('client_id_metadata_document_supported') is not True:raise ValueError('Provider does not advertise client metadata documents')
        meta=request_json(config['client_id'],check)
        if meta.get('client_id')!=config['client_id'] or redirect not in meta.get('redirect_uris',[]):
            raise ValueError('Client metadata must identify itself and list the exact configured callback; use a fixed callback port')
        if meta.get('token_endpoint_auth_method','none')!='none':raise ValueError('PortalAI uses public clients without secrets')
        return config['client_id']
    registration=doc.get('registration_endpoint')
    if not registration:raise ValueError('Provider does not advertise dynamic registration; configure a registered client or metadata URL')
    endpoint(registration)
    value=request_json(registration,check,json_fields={'client_name':'PortalAI portable','redirect_uris':[redirect],
        'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'token_endpoint_auth_method':'none'})
    client=value.get('client_id')
    if not isinstance(client,str) or not 1<=len(client)<=1000 or any(c in client for c in '\r\n') or value.get('client_secret'):
        raise ValueError('Dynamic registration did not return a public client')
    if value.get('token_endpoint_auth_method','none')!='none' or redirect not in value.get('redirect_uris',[redirect]):
        raise ValueError('Provider changed the public-client callback or authentication method')
    return client


def token_result(value,old_refresh=None):
    token=value.get('access_token');refresh=value.get('refresh_token',old_refresh)
    if value.get('token_type','').lower()!='bearer' or not isinstance(token,str) or not 1<=len(token)<=16384 or any(c in token for c in '\r\n'):
        raise ValueError('OAuth provider did not return a bounded bearer token')
    if refresh is not None and (not isinstance(refresh,str) or len(refresh)>16384):raise ValueError('Invalid refresh token')
    ttl=value.get('expires_in',3600)
    if type(ttl) not in (int,float) or not 0<ttl<=366*86400:raise ValueError('Invalid OAuth token lifetime')
    return {'access_token':token,'refresh_token':refresh,'expires_at':time.time()+ttl}


def authorize(config,resource,check,on_url):
    config=validate_config(config);doc=metadata(config,resource,check)
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    result={};callback_path='/portalai-oauth/callback'
    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            parsed=url.urlsplit(self.path)
            try:params=url.parse_qs(parsed.query,max_num_fields=12)
            except ValueError:self.send_error(400,'Invalid query');return
            valid=(len(self.path)<8192 and parsed.path==callback_path and self.headers.get('Host')==f'127.0.0.1:{self.server.server_port}'
                   and len(params.get('state',[]))==1 and secrets.compare_digest(params['state'][0],state))
            if not valid:self.send_error(400,'Invalid callback');return
            if result:self.send_error(409,'Callback already received');return
            if 'error' in params:result['error']='Provider declined authorization'
            elif len(params.get('code',[]))==1:result['code']=params['code'][0]
            else:self.send_error(400,'Missing code');return
            body=b'PortalAI received the sign-in response. You may close this tab.'
            self.send_response(200);self.send_header('Content-Type','text/plain; charset=utf-8');self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('Content-Security-Policy',"default-src 'none'");self.end_headers();self.wfile.write(body)
    class LoopbackServer(http.server.HTTPServer):
        def get_request(self):
            sock,address=super().get_request();sock.settimeout(1);return sock,address
    server=LoopbackServer(('127.0.0.1',config['callback_port']),Callback);server.timeout=.2
    try:
        redirect=f'http://127.0.0.1:{server.server_port}'+callback_path
        client=client_for_redirect(config,doc,redirect,check)
        fields={'response_type':'code','client_id':client,'redirect_uri':redirect,'state':state,
                'code_challenge':challenge,'code_challenge_method':'S256','resource':resource}
        if config['scope']:fields['scope']=config['scope']
        endpoint_url=doc['authorization_endpoint'];on_url(endpoint_url+('&' if '?' in endpoint_url else '?')+url.urlencode(fields))
        deadline=time.monotonic()+180
        while not result:
            check()
            if time.monotonic()>deadline:raise TimeoutError('OAuth sign-in expired; start sign-in again')
            server.handle_request()
        check()
        if 'error' in result:raise RuntimeError(result['error'])
        value=request_json(doc['token_endpoint'],check,{'grant_type':'authorization_code','code':result['code'],
            'client_id':client,'redirect_uri':redirect,'code_verifier':verifier,'resource':resource})
        return {**token_result(value),'token_endpoint':doc['token_endpoint'],'resource':resource,'client_id':client,'issuer':doc['issuer']}
    finally:server.server_close()


def refresh(config,token,check):
    if not token.get('refresh_token'):raise RuntimeError('MCP sign-in expired; sign in again in Workspace')
    value=request_json(token['token_endpoint'],check,{'grant_type':'refresh_token','refresh_token':token['refresh_token'],
        'client_id':token.get('client_id',config['client_id']),'resource':token['resource']})
    return {**token,**token_result(value,token['refresh_token'])}
