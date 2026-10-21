"""Outbound HTTPS projection channel; no HA password or API token."""
import base64
import http.client
import json
import ssl
import time
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from connection_vault import url
from viewer_demand import ViewerDemand


class Client:
    def __init__(self,connection,ca_file):
        self.url=url(connection['url']);self.address=urlsplit(self.url)
        self.identity=connection['device_id'];self.key=serialization.load_pem_private_key(connection['private_key'].encode(),password=None)
        self.context=ssl.create_default_context(cafile=str(ca_file));self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.session=None;self.sequence=0;self.demand=ViewerDemand();self.frame_uploads=0;self.connection=None
    def close(self):
        conn=self.connection;self.connection=None
        if conn is not None:conn.close()
    def request(self,body):
        # Reuse verified TLS to this fixed origin/path only. No proxy environment,
        # redirect, cookies or HA Authorization. A failed POST is NEVER retried.
        if self.connection is None:
            self.connection=http.client.HTTPSConnection(self.address.hostname,self.address.port or 443,timeout=10,context=self.context)
        conn=self.connection
        try:
            data=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode('utf-8')
            if len(data)>5700000:raise ValueError('Projection upload too large')
            headers={'Content-Type':'application/json','Cache-Control':'no-store'}
            if self.session:headers['X-PortalAI-Session']=self.session
            conn.request('POST','/api/portalai_projection/v1',data,headers)
            response=conn.getresponse();raw=response.read(2097153)
            if len(raw)>2097152 or response.getheader('Content-Encoding'):raise RuntimeError('Invalid receiver response')
            if response.status!=200:raise RuntimeError('Receiver refused the connection. Check HTTPS URL, receiver installation and approved pairing.')
            value=json.loads(raw)
            if not isinstance(value,dict):raise RuntimeError('Invalid receiver response')
            return value
        except BaseException:
            self.close()
            raise
    def authenticate(self):
        self.session=None;self.sequence=0;self.demand.reset()
        result=self.request({'action':'challenge','device_id':self.identity});challenge=result.get('challenge')
        if not isinstance(challenge,str) or len(challenge)!=64 or any(c not in '0123456789abcdef' for c in challenge):raise ValueError('Invalid pairing challenge')
        signature=self.key.sign(('PortalAI-Projection-v1:'+self.identity+':'+challenge).encode(),ec.ECDSA(hashes.SHA256()))
        result=self.request({'action':'authenticate','device_id':self.identity,'challenge':challenge,'signature':base64.b64encode(signature).decode()})
        token=result.get('session')
        if not isinstance(token,str) or not 32<=len(token)<=128:raise ValueError('Invalid projection session')
        self.session=token
    def poll(self,frame,status,replies):
        self.sequence+=1
        started=time.monotonic()
        try:
            # Recheck at the network boundary, after potentially slow status work.
            if not self.demand.active('screen'):frame=None
            if frame is not None:self.frame_uploads+=1
            result=self.request({'action':'poll','sequence':self.sequence,'frame':frame,'status':status,'replies':replies})
            commands=result.get('commands')
            if not isinstance(commands,list) or len(commands)>32:raise ValueError('Invalid command batch')
            self.demand.update(result.get('viewer_demand'),started)
            return commands
        except Exception:
            self.demand.reset()
            raise
