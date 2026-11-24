"""Projection-only protocol state. No Home Assistant object or service API."""
import base64
import hashlib
import json
import re
import secrets
import time
import uuid
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec

MAX_FRAME=5600000
# Leave room for viewer_demand and envelopes under the host's 2 MiB read cap.
MAX_COMMAND_BYTES=1800000


def device_id(value):
    if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{32}',value):raise ValueError('Invalid device identity')
    return value


def pairing(value):
    identity=device_id(value['device_id'])
    encoded=value['public_key']
    if not isinstance(encoded,str) or len(encoded)>512:raise ValueError('Invalid public key')
    der=base64.b64decode(encoded,validate=True);key=serialization.load_der_public_key(der)
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('P-256 key required')
    fingerprint=hashlib.sha256(der).hexdigest()
    if value.get('fingerprint')!=fingerprint:raise ValueError('Public key fingerprint differs')
    return identity,{'name':str(value.get('name','PortalAI'))[:80],'public_key':encoded,'fingerprint':fingerprint}


def frame(value):
    if value is None:return None
    if not isinstance(value,dict):raise ValueError('Invalid screen')
    if not value.get('png'):return {'windows':[]}
    width,height=value.get('width'),value.get('height');png=value.get('png')
    if type(width)!=int or type(height)!=int or not 80<=width<=2560 or not 30<=height<=1600:raise ValueError('Invalid dimensions')
    if not isinstance(png,str) or not 20<=len(png)<=MAX_FRAME or not re.fullmatch('iVBORw0KGgo[A-Za-z0-9+/=]+',png):raise ValueError('Invalid PNG')
    import struct
    header=base64.b64decode(png[:64],validate=True)
    if len(header)<33 or header[12:16]!=b'IHDR' or struct.unpack('>II',header[16:24])!=(width,height):raise ValueError('PNG dimensions differ')
    window=device_id(value['window']);windows=[]
    for row in value.get('windows',[])[:20]:windows.append({'id':device_id(row['id']),'title':str(row['title'])[:160]})
    return {'window':window,'windows':windows,'width':width,'height':height,'png':png,
            'native_dialog':value.get('native_dialog') is True,'profile_open':value.get('profile_open') is True}


class Receiver:
    def __init__(self,approved=None):
        self.approved=approved or {};self.challenges={};self.sessions={};self.devices={}
    def challenge(self,identity):
        identity=device_id(identity)
        if identity not in self.approved:raise PermissionError('Approve this device in Home Assistant first')
        previous=self.challenges.get(identity)
        if previous and previous[1]>time.monotonic()+58:raise PermissionError('Pairing request rate limited')
        nonce=secrets.token_hex(32);self.challenges[identity]=(nonce,time.monotonic()+60)
        return {'challenge':nonce}
    def authenticate(self,value):
        identity=device_id(value['device_id']);entry=self.approved.get(identity)
        challenge=self.challenges.pop(identity,None)
        if entry is None or not challenge or challenge[1]<time.monotonic() or value.get('challenge')!=challenge[0]:raise PermissionError('Expired challenge')
        key=serialization.load_der_public_key(base64.b64decode(entry['public_key']))
        key.verify(base64.b64decode(value['signature'],validate=True),('PortalAI-Projection-v1:'+identity+':'+challenge[0]).encode(),ec.ECDSA(hashes.SHA256()))
        token=secrets.token_urlsafe(32)
        # Replacing a session drops old queued input, never replays it.
        for old,session in list(self.sessions.items()):
            if session['device_id']==identity:self.sessions.pop(old)
        self.sessions[token]={'device_id':identity,'sequence':0,'expires':time.monotonic()+60}
        self.devices[identity]={'frame':None,'updated':0,'frame_at':0,'queue':[],'replies':{},'reply_limits':{},'viewer':None,'status':{}}
        return {'session':token}
    def poll(self,token,value):
        now=time.monotonic();session=self.sessions.get(token)
        if not session or session['expires']<now or session['device_id'] not in self.approved:raise PermissionError('Projection session expired')
        sequence=value.get('sequence')
        if type(sequence)!=int or sequence!=session['sequence']+1:raise PermissionError('Out-of-order or repeated poll')
        screen=frame(value.get('frame'))
        status=value.get('status',{})
        if not isinstance(status,dict) or len(json.dumps(status))>4096:raise ValueError('Invalid status')
        replies=value.get('replies',[])
        if not isinstance(replies,list) or len(replies)>32 or len(json.dumps(replies,ensure_ascii=False).encode('utf-8'))>512000:raise ValueError('Invalid acknowledgements')
        state=self.devices[session['device_id']]
        for reply in replies:
            if not isinstance(reply,dict):raise ValueError('Invalid acknowledgement')
            key=device_id(reply.get('id'))
            # Larger bounds belong only to this exact dispatched read request,
            # never to a device's self-declared operation or another command.
            limit=state.get('reply_limits',{}).get(key,65000)
            if len(json.dumps(reply,ensure_ascii=False).encode('utf-8'))>limit:raise ValueError('Acknowledgement too large')
        session['sequence']=sequence;session['expires']=now+60
        if screen is not None:state['frame']=screen;state['frame_at']=now
        state['updated']=now
        state['status']=status
        for reply in replies:
            key=device_id(reply['id'])
            # A device may answer only requests actually dispatched to it.
            if key in state['replies']:state['replies'][key]=reply
        commands=[];deferred=[];used=32
        for item in state['queue']:
            if item['expires']>now:
                command={**{k:item[k] for k in ('id','action','payload')},'ttl':min(5,item['expires']-now)}
                cost=len(json.dumps(command,ensure_ascii=False).encode('utf-8'))+2
                if deferred or used+cost>MAX_COMMAND_BYTES:
                    deferred.append(item);continue
                used+=cost;commands.append(command);state['replies'][item['id']]=None
                if item['action']=='native_ui' and item['payload'].get('operation')=='rich_media_batch' and item['payload'].get('protocol')==2:
                    state.setdefault('reply_limits',{})[item['id']]=361000
        state['queue']=deferred
        return {'commands':commands}
    def connected(self,identity):
        state=self.devices.get(identity)
        if state is None or time.monotonic()-state['updated']>15:raise RuntimeError('Projection offline or screen stale')
        return state
    def lease(self,identity,viewer):
        state=self.connected(identity);now=time.monotonic();old=state['viewer']
        if old and old[0]!=viewer and old[1]>now:raise PermissionError('Another viewer controls this desktop')
        state['viewer']=(viewer,now+30);return state
    def enqueue(self,identity,action,payload):
        state=self.connected(identity)
        if action not in ('input','start','restart','force_shutdown','select_window','disconnect','native_chat','native_ui'):raise ValueError('Unsupported projection command')
        safety=action=='native_ui' and payload.get('operation')=='invoke' and payload.get('action') in ('controls_stop','chat_stop','controls_exit','account_close')
        # Leave two transport slots for Stop/Exit, including queued future replies.
        if len(state['queue'])>=(32 if safety else 30) or len(state['queue'])+len(state['replies'])>=(64 if safety else 62):raise RuntimeError('Projection input queue full')
        bulk=action=='native_ui' and payload.get('operation')=='file_chunk_v2' and type(payload.get('protocol')) is int and payload['protocol']==2
        if bulk and state.get('status',{}).get('native_file_upload_protocol')!=2:raise ValueError('Upload v2 unavailable')
        if len(json.dumps(payload,ensure_ascii=False).encode('utf-8'))>(1400000 if bulk else 56000):raise ValueError('Command too large')
        key=uuid.uuid4().hex;item={'id':key,'action':action,'payload':payload,'expires':time.monotonic()+8}
        if safety:
            state['queue'].insert(0,item)
        else:state['queue'].append(item)
        return key
    def forget(self,identity,key):
        state=self.devices.get(identity)
        if state:
            state['queue']=[item for item in state['queue'] if item['id']!=key]
            state['replies'].pop(key,None)
            state.get('reply_limits',{}).pop(key,None)
    def revoke(self,identity):
        self.approved.pop(identity,None);self.devices.pop(identity,None);self.challenges.pop(identity,None)
        for token,session in list(self.sessions.items()):
            if session['device_id']==identity:self.sessions.pop(token)
