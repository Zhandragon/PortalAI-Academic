"""Recovery-only public-key protocol. No shell, input, credentials or HA APIs."""
import base64
import hashlib
import re
import secrets
import time
import uuid
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec

PROTOCOL='portalai-recovery/1'
OUTCOMES={'idle','recovering','launch_requested','already_running',
          'projection_restored_review_workers','refused_or_uncertain'}

def identity(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value):raise ValueError('Invalid identity')
    return value

def pairing(value):
    if not isinstance(value,dict) or set(value)!={'device_id','name','public_key','fingerprint','protocol','capabilities'}:raise ValueError('Invalid pairing')
    if value['protocol']!=PROTOCOL or value['capabilities']!=['recover_apps']:raise ValueError('Separate recovery approval required')
    key_id=identity(value['device_id']);encoded=value['public_key']
    if not isinstance(encoded,str) or len(encoded)>512:raise ValueError('Key limit')
    der=base64.b64decode(encoded,validate=True);key=serialization.load_der_public_key(der)
    if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1):raise ValueError('P-256 required')
    if hashlib.sha256(der).hexdigest()!=value['fingerprint']:raise ValueError('Fingerprint differs')
    if not isinstance(value['name'],str) or len(value['name'])>80:raise ValueError('Name limit')
    return key_id,dict(value)

class Receiver:
    def __init__(self,approved=None,clock=time.monotonic):
        self.approved=dict(approved or {});self.clock=clock
        self.challenges={};self.sessions={};self.devices={}
    def challenge(self,key_id):
        key_id=identity(key_id)
        if key_id not in self.approved:raise PermissionError('Unapproved')
        old=self.challenges.get(key_id);now=self.clock()
        if old and now<old[1]-58:raise PermissionError('Rate limited')
        nonce=secrets.token_hex(32);self.challenges[key_id]=(nonce,now+60)
        return {'challenge':nonce}
    def authenticate(self,value):
        if set(value)!={'action','device_id','challenge','signature'}:raise ValueError('Invalid authentication')
        key_id=identity(value['device_id']);entry=self.approved.get(key_id)
        nonce=self.challenges.pop(key_id,None)
        if entry is None or nonce is None or self.clock()>=nonce[1] or value['challenge']!=nonce[0]:raise PermissionError('Expired')
        if not isinstance(value['signature'],str) or len(value['signature'])>256:raise ValueError('Signature limit')
        key=serialization.load_der_public_key(base64.b64decode(entry['public_key']))
        key.verify(base64.b64decode(value['signature'],validate=True),
            ('PortalAI-Recovery-v1:'+key_id+':'+nonce[0]).encode(),ec.ECDSA(hashes.SHA256()))
        for token,session in list(self.sessions.items()):
            if session['id']==key_id:self.sessions.pop(token)
        token=secrets.token_urlsafe(32)
        self.sessions[token]={'id':key_id,'sequence':0,'expires':self.clock()+60}
        # Reconnection deliberately drops uncertain/queued operations.
        self.devices[key_id]={'updated':None,'status':'idle','pending':None,'reply':None}
        return {'session':token,'protocol':PROTOCOL,'capabilities':['recover_apps']}
    def poll(self,token,value):
        now=self.clock();session=self.sessions.get(token)
        if not session or now>=session['expires'] or session['id'] not in self.approved:raise PermissionError('Expired session')
        if set(value)!={'action','sequence','status','replies'}:raise ValueError('Invalid poll')
        if type(value['sequence']) is not int or value['sequence']!=session['sequence']+1:raise PermissionError('Repeated poll')
        if value['status'] not in OUTCOMES:raise ValueError('Invalid status')
        replies=value['replies']
        if not isinstance(replies,list) or len(replies)>1:raise ValueError('Reply limit')
        for reply in replies:
            if not isinstance(reply,dict) or set(reply)!={'id','outcome'}:raise ValueError('Invalid reply')
            identity(reply['id'])
            if reply['outcome'] not in OUTCOMES-{'idle','recovering'}:raise ValueError('Invalid outcome')
        state=self.devices[session['id']];pending=state['pending']
        for reply in replies:
            if pending and pending['delivered'] and reply['id']==pending['id']:
                state['reply']=dict(reply);state['pending']=None
        session.update(sequence=value['sequence'],expires=now+60)
        state.update(updated=now,status=value['status'])
        pending=state['pending'];commands=[]
        if pending and not pending['delivered']:
            if now>=pending['expires']:state['pending']=None
            else:
                pending['delivered']=True
                commands=[{'id':pending['id'],'action':'recover','ttl':min(30,pending['expires']-now)}]
        return {'commands':commands}
    def connected(self,key_id):
        state=self.devices.get(identity(key_id))
        if state is None or state['updated'] is None or self.clock()-state['updated']>=15:raise RuntimeError('Recovery helper offline')
        return state
    def enqueue(self,key_id,action='recover'):
        if action!='recover':raise ValueError('Only app recovery is allowed')
        state=self.connected(key_id)
        if state['pending'] is not None or state['status']=='recovering':raise RuntimeError('Recovery already pending; inspect its outcome')
        key=uuid.uuid4().hex
        state.update(pending={'id':key,'expires':self.clock()+30,'delivered':False},reply=None)
        return key
    def cancel_undelivered(self,key_id,key):
        state=self.devices.get(key_id);pending=state['pending'] if state else None
        if pending and pending['id']==key and not pending['delivered']:state['pending']=None
    def revoke(self,key_id):
        self.approved.pop(key_id,None);self.challenges.pop(key_id,None);self.devices.pop(key_id,None)
        for token,session in list(self.sessions.items()):
            if session['id']==key_id:self.sessions.pop(token)
