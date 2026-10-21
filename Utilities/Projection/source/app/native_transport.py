"""Outbound native v2 read-only publisher; existing device key, no HA credentials.

Wire API: NATIVE_V2_IMPLEMENTED_TRANSPORT.txt (receiver 0.2.0).
No commands, projection input calls, account logins, private disk cache or retries
of saved payloads. The independent GUI reader rechecks real account authority.
"""
import base64
import copy
import hashlib
import logging
from pathlib import Path
import re
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit, urlunsplit

from connection_vault import url
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from native_state_client import NativeStateClient
from viewer_demand import ViewerDemand
from native_receiver_schema import PROTOCOL, MAX_BYTES, decode, encode, fields, snapshot as validate_wire

MODULE=Path(__file__).resolve().parents[1]
WHEEL='websockets-15.0.1-py3-none-any.whl'
WHEEL_SHA256='f7a866fbc1e97b5c617ee4116daaa09b722101d4a3c170c787450ba409f9736f'


def socket_factory(address, context):
    wheel=MODULE/'Runtime/NativeState'/WHEEL
    if wheel.is_symlink() or wheel.stat().st_size!=169743 or hashlib.sha256(wheel.read_bytes()).hexdigest()!=WHEEL_SHA256:
        raise RuntimeError('native_dependency_integrity')
    if str(wheel) not in sys.path: sys.path.insert(0,str(wheel))
    import websockets
    if websockets.__version__!='15.0.1' or not str(websockets.__file__).replace('\\','/').startswith(str(wheel).replace('\\','/')+'/'):
        raise RuntimeError('native_dependency_origin')
    from websockets.sync.client import connect
    # A dedicated logger cannot inherit debug logging of private frames.
    logger=logging.Logger('PortalAI-native-private-channel',level=logging.CRITICAL+1)
    logger.addHandler(logging.NullHandler());logger.propagate=False
    # The synchronous implementation never follows redirects. No environment
    # proxy, compression, cookies, Authorization, Origin or alternate destination.
    ws=connect(address,ssl=context,proxy=None,origin=None,additional_headers=None,
        compression=None,user_agent_header=None,open_timeout=4,close_timeout=1,
        ping_interval=2,ping_timeout=2,max_size=MAX_BYTES,max_queue=2,logger=logger)
    # Bound sendall as well as application acknowledgements. Keepalive traffic
    # is more frequent than this timeout even while the account is locked.
    ws.socket.settimeout(4)
    return ws


def catalog_id(value, prefix):
    # Public catalog keys contain dots but receiver 0.2.0 requires opaque IDs.
    # Full SHA-256 with domain separation gives stable, bounded display IDs.
    return prefix+'_'+hashlib.sha256(value.encode('utf-8')).hexdigest()


def wire_snapshot(local, revision):
    value=copy.deepcopy(local);value['revision']=revision
    if value['account']['state']=='ready':
        for row in value['models']:
            row['id']=catalog_id(row['id'],'model')
            if row['state']=='unknown':row['state']='unavailable'
        for row in value['packages']:row['id']=catalog_id(row['id'],'package')
        selection=value['settings']['selection']
        if selection!='auto':value['settings']['selection']=catalog_id(selection,'model')
    validate_wire(value)
    # Receiver reserves a worst-case browser subscription generation too.
    encode({'protocol':PROTOCOL,'generation':'x'*80,'kind':'snapshot','snapshot':value})
    return value


class NativeTransport:
    def __init__(self,connection,manager,stop,report=None,*,connect=socket_factory,clock=time.monotonic,demand=None):
        address=urlsplit(url(connection['url']))
        self.address=urlunsplit(('wss',address.netloc,'/api/portalai_native/v2','',''))
        self.identity=connection['device_id']
        if not isinstance(self.identity,str) or not re.fullmatch('[0-9a-f]{32}',self.identity):raise ValueError('device')
        self.key=serialization.load_pem_private_key(connection['private_key'].encode(),password=None)
        if not isinstance(self.key,ec.EllipticCurvePrivateKey) or not isinstance(self.key.curve,ec.SECP256R1):raise ValueError('device_key')
        self.context=ssl.create_default_context(cafile=str(MODULE/'Runtime/cacert.pem'))
        self.context.minimum_version=ssl.TLSVersion.TLSv1_2
        self.local=NativeStateClient(manager);self.stop=stop;self.report=report or (lambda _:None)
        self.connect=connect;self.clock=clock;self.ws=None;self.binding=None;self.revision=0
        self.socket_lock=threading.Lock();self.acked=False
        self.demand=demand if demand is not None else ViewerDemand(clock)

    def wanted(self, token=None):
        return self.demand.active('native') if token is None else self.demand.valid('native',token)

    def standby(self):
        self.invalidate()
        self.local.endpoint=None
        self.report('standby')
        return False

    def receive(self,kind,names):
        raw=self.ws.recv(timeout=2)
        if not isinstance(raw,str):raise ValueError('text_required')
        value=decode(raw);fields(value,('protocol','kind',*names))
        if value['protocol']!=PROTOCOL or value['kind']!=kind:raise ValueError('receiver_response')
        return value

    def send(self,kind,**body):
        self.ws.send(encode({'protocol':PROTOCOL,'kind':kind,**body}).decode('utf-8'))

    def authenticate(self):
        hello=self.receive('hello',('maxFrameBytes','leaseSeconds'))
        if type(hello['maxFrameBytes']) is not int or hello['maxFrameBytes']!=MAX_BYTES or type(hello['leaseSeconds']) is not int or hello['leaseSeconds']!=10:raise ValueError('receiver_limits')
        self.send('hello',device_id=self.identity)
        challenge=self.receive('challenge',('challenge',))['challenge']
        if not isinstance(challenge,str) or not re.fullmatch('[0-9a-f]{64}',challenge):raise ValueError('challenge')
        signature=self.key.sign(('PortalAI-Native-State-v2:'+self.identity+':'+challenge).encode(),ec.ECDSA(hashes.SHA256()))
        self.send('authenticate',signature=base64.b64encode(signature).decode())
        result=self.receive('authenticated',('capabilities','leaseSeconds'))
        if result['capabilities']!=['native.state.read'] or type(result['leaseSeconds']) is not int or result['leaseSeconds']!=10:raise PermissionError('native_read_grant_required')
        # No GUI state was read before the receiver proved the separate grant.

    def invalidate(self):
        if self.binding is not None:
            self.send('invalidate');self.receive('invalidated',())
        self.binding=None;self.revision=0;self.local.binding=None

    def step(self):
        """One fresh account-checked snapshot, one acknowledgement, no replay."""
        token=self.demand.token('native')
        if token is None:return self.standby()
        try:
            if self.local.binding is None:self.local.bind(fresh=True)
            local=self.local.snapshot()['snapshot']
        except (OSError,ValueError,TypeError,KeyError,RuntimeError):
            self.invalidate();self.report('waiting_for_GUI');return False
        if local['account']['state']!='ready':
            self.invalidate();self.report('waiting_for_account');return False
        binding={k:local[k] for k in ('view','epoch')}
        if self.binding!=binding:
            self.invalidate()
            # invalidate clears the local binding; restore only the exact GUI
            # handshake we just authenticated, never one inferred from remote JSON.
            self.local.binding=dict(binding)
            self.send('bind',binding=binding)
            result=self.receive('bound',('binding',))
            if result['binding']!=binding:raise ValueError('binding_ack')
            self.binding=binding;self.revision=0
        # Fetch again after any network wait, so a logout during bind cannot
        # publish the pre-bind private snapshot. Failure clears the receiver.
        if not self.wanted(token):return self.standby()
        try:local=self.local.snapshot()['snapshot']
        except (OSError,ValueError,TypeError,KeyError,RuntimeError):
            self.invalidate();self.report('waiting_for_GUI');return False
        if local['account']['state']!='ready' or any(local[k]!=v for k,v in self.binding.items()):
            self.invalidate();self.report('waiting_for_account');return False
        at=self.clock();wire=wire_snapshot(local,self.revision)
        if self.stop.is_set() or self.clock()-at>=1 or not self.wanted(token): self.invalidate();return False
        self.send('snapshot',snapshot=wire)
        reply=self.receive('accepted',('revision',))
        if type(reply['revision']) is not int or reply['revision']!=self.revision:raise ValueError('revision_ack')
        self.revision+=1;self.acked=True;self.report('publishing')
        return True

    def close(self):
        with self.socket_lock:
            ws=self.ws;self.ws=None
        if ws is not None:
            try:ws.close()
            except Exception:pass
        self.binding=None;self.revision=0;self.local.binding=None;self.local.endpoint=None

    def run(self):
        backoff=3
        try:
            while not self.stop.is_set():
                self.acked=False
                try:
                    self.report('connecting')
                    ws=self.connect(self.address,self.context)
                    with self.socket_lock:self.ws=ws
                    if self.stop.is_set():break
                    self.authenticate();self.report('authenticated')
                    while not self.stop.is_set():
                        ready=self.step()
                        self.stop.wait(.5 if ready else 1)
                    if self.binding is not None:self.invalidate()
                except Exception:
                    # Never emit exception text, WebSocket bodies or key material.
                    self.report('unavailable')
                finally:self.close()
                if self.acked:backoff=3
                self.stop.wait(backoff);backoff=min(30,backoff*2)
        finally:self.close();self.report('stopped')
