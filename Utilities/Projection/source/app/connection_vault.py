"""Portable encrypted projection identity. Never accepts HA login credentials."""
import base64
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

AAD=b'PortalAI-Projection connection v1'


def url(value):
    parsed=urlsplit(value.strip())
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
        raise ValueError('Enter only an HTTPS Home Assistant origin, without a path, password or token')
    if parsed.port is not None and not 1<=parsed.port<=65535:raise ValueError('Invalid port')
    return value.strip().rstrip('/')


def new_connection(address,target,name):
    key=ec.generate_private_key(ec.SECP256R1())
    return {'version':1,'url':url(address),'target':target,'name':name[:80],
            'device_id':uuid.uuid4().hex,'private_key':key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()}


def public_pairing(connection):
    key=serialization.load_pem_private_key(connection['private_key'].encode(),password=None)
    public=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
    import hashlib
    return {'device_id':connection['device_id'],'name':connection['name'],'public_key':base64.b64encode(public).decode(),
            'fingerprint':hashlib.sha256(public).hexdigest()}


def _key(password,salt):
    if not isinstance(password,str) or len(password)<12:raise ValueError('Use a projection unlock password of at least 12 characters')
    return Scrypt(salt=salt,length=32,n=32768,r=8,p=1).derive(password.encode())


def save(path,connection,password):
    path=Path(path)
    if path.is_symlink():raise ValueError('Linked connection file refused')
    # No extensible credential bag: only the projection identity and settings.
    if set(connection)!={'version','url','target','name','device_id','private_key'}:raise ValueError('Unexpected connection fields')
    url(connection['url']);public_pairing(connection)
    salt=secrets.token_bytes(16);nonce=secrets.token_bytes(12)
    body=b'PAIP1'+salt+nonce+AESGCM(_key(password,salt)).encrypt(nonce,json.dumps(connection).encode(),AAD)
    stage=path.with_name(path.name+'.'+uuid.uuid4().hex+'.part')
    identity=None
    try:
        with stage.open('xb') as f:
            identity=os.fstat(f.fileno());f.write(body);f.flush();os.fsync(f.fileno())
        os.chmod(stage,0o600);os.replace(stage,path)
    finally:
        if identity is not None and stage.exists():
            current=stage.stat()
            if current.st_dev==identity.st_dev and current.st_ino==identity.st_ino:stage.unlink()


def unlock(path,password):
    path=Path(path)
    if path.is_symlink() or path.stat().st_size>32768:raise ValueError('Invalid connection file')
    data=path.read_bytes()
    if not data.startswith(b'PAIP1') or len(data)<49:raise ValueError('Invalid encrypted connection')
    salt,nonce=data[5:21],data[21:33]
    plain=AESGCM(_key(password,salt)).decrypt(nonce,data[33:],AAD)
    result=json.loads(plain)
    if set(result)!={'version','url','target','name','device_id','private_key'} or result['version']!=1:raise ValueError('Unsupported connection')
    url(result['url']);public_pairing(result)
    return result
