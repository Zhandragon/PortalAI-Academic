"""Profile-bound connection bundle. Secrets never form model/tool output.

The controller derives an account-only key from its authenticated profile key.
Owned account workers receive it through a private startup pipe, never argv or
environment variables. The saved bundle remains
encrypted while the profile is open, and is sealed again with the workspace.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from profile_paths import capture, private_path, ProfileLocked
from runtime_policy import atomic_json

ENV = 'PORTALAI_CONNECTION_UNLOCK'
INPUT_FLAG = 'PORTALAI_CONNECTION_INPUT'
RELATIVE = 'Data/Accounts/connections.enc'
_controller_key = None


def clear_session():
    global _controller_key
    _controller_key = None
    os.environ.pop(ENV, None)
    os.environ.pop(INPUT_FLAG, None)


def session_key(root, session):
    if session.role == 'guest' or not session.active:
        raise PermissionError('Dedicated connections require an authenticated non-Guest account')
    context = capture(root)
    if context is None or context[0] != session.user_id:
        raise ProfileLocked('The connection account is not the open profile')
    key = hmac.new(session.profile_key, b'PortalAI/connections/v1/' + session.user_id.encode(), hashlib.sha256).digest()
    return key, context


def unlock_session(root, session):
    global _controller_key
    clear_session()
    if session.role == 'guest':return
    key, context = session_key(root, session)
    _controller_key = (str(Path(root).resolve()), context, key)


def current_key(root, context):
    cached=_controller_key
    if cached is not None and cached[:2]==(str(Path(root).resolve()),context):return cached[2]
    return b''


def unlocked(root):
    context=capture(root)
    return bool(context is not None and current_key(root,context))


def start_account_process(command, root, **options):
    """Send only the account key through this owned child's anonymous stdin pipe."""
    context=capture(root);key=current_key(root,context)
    env=dict(options.get('env',os.environ));env.pop(ENV,None);env.pop(INPUT_FLAG,None)
    packet=None
    if context is not None and key:
        packet=json.dumps({'context':list(context),'key':base64.b64encode(key).decode()}).encode()
        env[INPUT_FLAG]='1';options['stdin']=subprocess.PIPE
    options['env']=env
    process=subprocess.Popen(command,**options)
    if packet is not None:
        try:
            process.stdin.write(packet);process.stdin.flush();process.stdin.close();process.stdin=None
        except (OSError,ValueError):
            # The child is still ours and has not passed its startup/gate yet.
            try:process.terminate();process.wait(timeout=10)
            except (OSError,subprocess.TimeoutExpired):pass
            raise RuntimeError('Account worker startup pipe failed') from None
    return process


def receive_worker_input(root):
    global _controller_key
    if os.environ.pop(INPUT_FLAG,None)!='1':return
    try:
        raw=sys.stdin.buffer.read(4097)
        if len(raw)>4096:raise ValueError()
        data=json.loads(raw);context=capture(root)
        key=base64.b64decode(data['key'],validate=True)
        if context is None or data['context']!=list(context) or len(key)!=32:raise ValueError()
        _controller_key=(str(Path(root).resolve()),context,key)
    except Exception:raise PermissionError('Account worker input does not match this login') from None


def _aad(context):
    if context is None:raise ProfileLocked('Connections require a PortalAI login')
    return b'PortalAI/connections/v1/' + context[0].encode()


def read(root, *, key=None):
    context = capture(root)
    path = private_path(root, RELATIVE, context=context)
    if not path.exists():return {'version': 1, 'profiles': {}, 'secrets': {}, 'setups': {}}
    if path.stat().st_size > 512*1024:raise ValueError('Connection bundle exceeds its limit')
    try:
        from mission_accounts import activate
        activate(root)
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        if key is None:key = current_key(root,context)
        envelope = json.loads(path.read_text(encoding='utf-8'))
        if envelope['version'] != 1:raise ValueError()
        raw = AESGCM(key).decrypt(base64.b64decode(envelope['nonce'],validate=True),
                                  base64.b64decode(envelope['ciphertext'],validate=True), _aad(context))
        data = json.loads(raw)
        if data.get('version') != 1 or any(not isinstance(data.get(k),dict) for k in ('profiles','secrets','setups')):
            raise ValueError()
        if capture(root) != context:raise ProfileLocked('The connection login ended')
        return data
    except Exception:
        raise PermissionError('Connections could not be unlocked for this profile; sign in again or restore the encrypted recovery copy') from None


def write(root, session, data):
    require_session(root,session)
    key, context = session_key(root, session)
    from mission_accounts import activate
    activate(root)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = json.dumps(data,ensure_ascii=True,separators=(',',':')).encode()
    if len(raw) > 256*1024:raise ValueError('Connection bundle exceeds its limit')
    nonce=os.urandom(12)
    encrypted=AESGCM(key).encrypt(nonce,raw,_aad(context))
    if session_key(root,session)[1] != context:raise ProfileLocked('The connection login ended')
    atomic_json(private_path(root,RELATIVE,context=context),{
        'version':1,'nonce':base64.b64encode(nonce).decode(),
        'ciphertext':base64.b64encode(encrypted).decode()})
    # Reopen and authenticate the complete bundle before reporting success.
    if read(root,key=key) != data:raise RuntimeError('Connection save verification failed')


def require_session(root, session):
    from local_accounts import Session
    if not isinstance(session,Session) or not session.active:
        raise PermissionError('Connection setup requires a real authenticated PortalAI session')
    store=session._store()
    if store is None or Path(store.root).resolve()!=Path(root).resolve():
        raise PermissionError('Connection session belongs to another installation')
    store.validate_session(session)


def secret(root, name):
    data=read(root)
    if name in data['profiles']:return data['secrets'][name]
    from mission_accounts import vault_read
    return vault_read(root)[name]


def redact(value, secrets):
    """Remove exact secrets and recognizable token forms from remote results."""
    values=[]
    def collect(v):
        if isinstance(v,dict):
            for item in v.values():collect(item)
        elif isinstance(v,str) and len(v)>=8:values.append(v)
    collect(secrets)
    def clean(v):
        if isinstance(v,str):
            for token in sorted(values,key=len,reverse=True):v=v.replace(token,'[redacted]')
            return re.sub(r'(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|moltbook_(?!verify_)[A-Za-z0-9_-]+)', '[redacted]', v)
        if isinstance(v,list):return [clean(x) for x in v]
        if isinstance(v,dict):return {clean(k):clean(x) for k,x in v.items()}
        return v
    return clean(value)
