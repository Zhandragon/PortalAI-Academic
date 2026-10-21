"""Independent recovery-only HTTPS lane; no HA password, cookies or API token."""
import base64
import http.client
import json
import math
import re
import ssl
import time
from urllib.parse import urlsplit
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
from connection_vault import url,public_pairing

PROTOCOL='portalai-recovery/1'
OUTCOMES={'idle','recovering','launch_requested','already_running',
          'projection_restored_review_workers','refused_or_uncertain'}

def pairing_request(connection):
    return {**public_pairing(connection),'protocol':PROTOCOL,'capabilities':['recover_apps']}

def identity(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('Invalid identity')
    return value

class RecoveryClient:
    def __init__(self,connection,ca_file):
        self.address=urlsplit(url(connection['url']));self.identity=identity(connection['device_id'])
        self.key=serialization.load_pem_private_key(connection['private_key'].encode(),password=None)
        if not isinstance(self.key,ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve,ec.SECP256R1):raise ValueError('P-256 required')
        self.context=ssl.create_default_context(cafile=str(ca_file));self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.session=None;self.sequence=0;self.connection=None
    def close(self):
        conn=self.connection;self.connection=None
        if conn is not None:conn.close()
    def request(self,body):
        if self.connection is None:
            self.connection=http.client.HTTPSConnection(self.address.hostname,self.address.port or 443,
                timeout=10,context=self.context)
        try:
            data=json.dumps(body,separators=(',',':')).encode()
            if len(data)>8192:raise ValueError('Request limit')
            headers={'Content-Type':'application/json','Cache-Control':'no-store'}
            if self.session:headers['X-PortalAI-Recovery-Session']=self.session
            self.connection.request('POST','/api/portalai_recovery/v1',data,headers)
            response=self.connection.getresponse();raw=response.read(8193)
            if response.status!=200 or len(raw)>8192 or response.getheader('Content-Encoding'):raise ValueError('Receiver refused')
            value=json.loads(raw)
            if not isinstance(value,dict):raise ValueError('Object required')
            return value
        except BaseException:self.close();raise
    def authenticate(self):
        self.session=None;self.sequence=0
        value=self.request({'action':'challenge','device_id':self.identity})
        nonce=value.get('challenge')
        if not isinstance(nonce,str) or not re.fullmatch('[a-f0-9]{64}',nonce):raise ValueError('Challenge refused')
        signed=self.key.sign(('PortalAI-Recovery-v1:'+self.identity+':'+nonce).encode(),ec.ECDSA(hashes.SHA256()))
        value=self.request({'action':'authenticate','device_id':self.identity,'challenge':nonce,
                            'signature':base64.b64encode(signed).decode()})
        token=value.get('session')
        if (value.get('protocol')!=PROTOCOL or value.get('capabilities')!=['recover_apps']
                or not isinstance(token,str) or not re.fullmatch('[A-Za-z0-9_-]{32,128}',token)):
            raise ValueError('Recovery grant refused')
        self.session=token
    def poll(self,status,replies):
        self.sequence+=1;started=time.monotonic()
        value=self.request({'action':'poll','sequence':self.sequence,'status':status,'replies':replies})
        commands=value.get('commands')
        if set(value)!={'commands'} or not isinstance(commands,list) or len(commands)>1:raise ValueError('Command limit')
        parsed=[]
        for command in commands:
            if not isinstance(command,dict) or set(command)!={'id','action','ttl'}:raise ValueError('Invalid command')
            identity(command['id']);ttl=command['ttl']
            if (command['action']!='recover' or type(ttl) not in (int,float)
                    or not math.isfinite(ttl) or not 0<ttl<=30):raise ValueError('Command refused')
            parsed.append({**command,'deadline':started+ttl})
        return parsed
