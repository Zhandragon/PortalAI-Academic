"""Read-only device authority/cache. No HA token, service API, or command path."""
import base64
import copy
import secrets
import time
from .schema import PROTOCOL, MAX_BYTES, fields, opaque, binding, snapshot, encode

LEASE_SECONDS=10
SCOPE='native.state.read'

class NativeHub:
    def __init__(self, approved, grants, clock=time.monotonic):
        self.approved=approved; self.grants=grants; self.clock=clock; self.devices={}

    def permitted(self, identity):
        entry=self.approved.get(identity)
        return bool(entry and self.grants.get(identity)==entry.get('fingerprint'))

    def authenticate(self, identity, nonce, signature):
        if not self.permitted(identity) or not isinstance(signature,str) or len(signature)>256: raise PermissionError('refused')
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key=serialization.load_der_public_key(base64.b64decode(self.approved[identity]['public_key'],validate=True))
        if not isinstance(key,ec.EllipticCurvePublicKey) or not isinstance(key.curve,ec.SECP256R1): raise PermissionError('refused')
        key.verify(base64.b64decode(signature,validate=True),f'PortalAI-Native-State-v2:{identity}:{nonce}'.encode(),ec.ECDSA(hashes.SHA256()))

    def attach(self, identity):
        if not self.permitted(identity): raise PermissionError('refused')
        connection=secrets.token_hex(16)
        self.devices[identity]={'connection':connection,'binding':None,'snapshot':None,'at':0,'last_revision':None,'last_binding':None,'locked':False}
        return connection

    def current(self, identity, connection=None):
        if not self.permitted(identity): raise PermissionError('revoked')
        state=self.devices.get(identity)
        if state is None or (connection is not None and state['connection']!=connection): raise PermissionError('stale_connection')
        return state

    def bind(self, identity, connection, value):
        binding(value); state=self.current(identity,connection)
        if value==state['binding'] or value==state['last_binding']: raise ValueError('fresh_binding_required')
        state.update(binding=copy.deepcopy(value),last_binding=copy.deepcopy(value),snapshot=None,at=self.clock(),last_revision=None,locked=False)

    def publish(self, identity, connection, value):
        snapshot(value); state=self.current(identity,connection)
        if self.clock()-state['at']>=LEASE_SECONDS:
            self.invalidate(identity,connection); raise PermissionError('expired_binding')
        if state['locked'] or state['binding']!={'view':value['view'],'epoch':value['epoch']}: raise PermissionError('wrong_binding')
        previous=state['last_revision']
        if previous is not None and value['revision']!=previous+1: raise ValueError('revision_gap')
        # Reserve envelope space with worst-case bounded browser generation.
        encode({'protocol':PROTOCOL,'generation':'x'*80,'kind':'snapshot','snapshot':value})
        state['last_revision']=value['revision']
        if value['account']['state']!='ready':
            state.update(snapshot=None,at=0,locked=True)
            return False
        state.update(snapshot=copy.deepcopy(value),at=self.clock())
        return True

    def invalidate(self, identity, connection=None):
        state=self.devices.get(identity)
        if state is not None and (connection is None or connection==state['connection']):
            state.update(binding=None,snapshot=None,at=0,locked=True)
            return True
        return False

    def detach(self, identity, connection):
        state=self.devices.get(identity)
        if state is not None and state['connection']==connection:
            self.devices.pop(identity,None); return True
        return False

    def read(self, identity):
        state=self.current(identity)
        if self.clock()-state['at']>=LEASE_SECONDS:
            self.invalidate(identity); raise PermissionError('unavailable')
        if state['snapshot'] is None: raise PermissionError('unavailable')
        return state

    def handshake(self, identity, generation):
        opaque(generation); state=self.read(identity)
        return {'protocol':PROTOCOL,'kind':'handshake','generation':generation,'binding':copy.deepcopy(state['binding']),
                'capabilities':[SCOPE],'maxFrameBytes':MAX_BYTES,'leaseSeconds':LEASE_SECONDS}
