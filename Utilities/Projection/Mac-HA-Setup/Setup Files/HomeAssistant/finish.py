"""Optional administrator-authorized HA validation/restart/initial pairing.

Token is entered privately, used only for this HA origin, never saved or printed.
No projection, recovery or PortalAI launch command is invoked.
"""
import json
import time
import urllib.request
import urllib.parse
import urllib.error

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('HA redirected the request. Enter its final trusted URL; token was not forwarded.')

class HomeAssistant:
    def __init__(self,url,token):
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('Enter only the trusted HA origin, for example https://ha.example.org')
        self.url=url.rstrip('/');self.token=token
        self.opener=urllib.request.build_opener(NoRedirect)
    def request(self,path,data=None):
        req=urllib.request.Request(self.url+path,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        with self.opener.open(req,timeout=20) as response:
            return json.loads(response.read(1024*1024))
    def check(self):
        result=self.request('/api/config/core/check_config',{})
        if result.get('result')!='valid':raise ValueError('HA rejected the configuration. Inspect HA logs; this installer will restore its changed files.')
    def restart(self):
        try:self.request('/api/services/homeassistant/restart',{})
        except (TimeoutError,ConnectionError,urllib.error.URLError):
            # The socket may close during restart. Never replay the restart.
            print('Restart response interrupted; checking readiness without replaying the command.')
        deadline=time.monotonic()+180
        time.sleep(5)
        while time.monotonic()<deadline:
            try:
                services=self.request('/api/services')
                if {'portalai_projection','portalai_native','portalai_recovery'}<={r['domain'] for r in services}:return
            except (OSError,ValueError):pass
            time.sleep(3)
        raise ValueError('HA readiness not confirmed. Inspect HA; restart was not repeated.')
    def pair_projection(self,request,device_id):
        # Passing a file is the owner's explicit request for initial pairing.
        # Existing approvals are never silently replaced or removed.
        if request.get('device_id')!=device_id:raise ValueError('Public pairing ID differs from the installed device ID.')
        self.request('/api/services/portalai_projection/pair_device',{'pairing_request':json.dumps(request)})
        self.request('/api/services/portalai_native/allow_state',{'device_id':device_id})
