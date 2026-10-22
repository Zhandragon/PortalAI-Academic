"""Create portable mTLS pairing without any Home Assistant credentials."""
from pathlib import Path
import argparse
import datetime
import hashlib
import ipaddress
import json
import os
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def create(folder, bind_host, ha_host, port):
    sys.path.insert(0,str(ROOT/'Runtime/AccountPython/packages'))
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    ipaddress.IPv4Address(bind_host);ipaddress.IPv4Address(ha_host)
    folder=Path(folder)
    if folder.exists():raise FileExistsError('Pairing already exists; never overwrite a live pairing implicitly')
    folder.mkdir(parents=True,mode=0o700)
    if os.name=='nt':
        # Restrict the new directory BEFORE writing any private key bytes.
        import subprocess
        sid=subprocess.check_output(['whoami','/user','/fo','csv','/nh'],text=True).strip().split(',')[-1].strip('"')
        if not sid.startswith('S-1-'):raise RuntimeError('Cannot identify pairing owner')
        result=subprocess.run(['icacls',str(folder),'/inheritance:r','/grant:r',f'*{sid}:(OI)(CI)F','*S-1-5-18:(OI)(CI)F','*S-1-5-32-544:(OI)(CI)F'],capture_output=True)
        if result.returncode:raise RuntimeError('Cannot restrict pairing credentials')
    now=datetime.datetime.now(datetime.timezone.utc)
    ca_key=ec.generate_private_key(ec.SECP256R1())
    ca_name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'PortalAI dedicated HA pairing')])
    ca=(x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name).public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5))
        .not_valid_after(now+datetime.timedelta(days=1825)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True)
        .add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True).sign(ca_key,hashes.SHA256()))
    files={'ca.crt':ca.public_bytes(serialization.Encoding.PEM)}
    for role in ('server','client'):
        key=ec.generate_private_key(ec.SECP256R1())
        builder=(x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'PortalAI '+role)]))
            .issuer_name(ca_name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now-datetime.timedelta(minutes=5)).not_valid_after(now+datetime.timedelta(days=730))
            .add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH if role=='server' else ExtendedKeyUsageOID.CLIENT_AUTH]),critical=True))
        if role=='server':builder=builder.add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(bind_host))]),critical=False)
        cert=builder.sign(ca_key,hashes.SHA256())
        files[role+'.crt']=cert.public_bytes(serialization.Encoding.PEM)
        files[role+'.key']=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
    files['bridge.json']=(json.dumps({'bind_host':bind_host,'ha_host':ha_host,'port':port},indent=2)+'\n').encode()
    for name,data in files.items():
        with (folder/name).open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.chmod(folder/name,0o600)
    # No CA signing key is persisted. This pair can authenticate only itself.
    return files


def package(destination, pairing):
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    public=destination/'portalai-ha-code.zip'
    paths=[p for p in (ROOT/'HomeAssistant/ha').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    with zipfile.ZipFile(public,'x',zipfile.ZIP_DEFLATED) as z:
        manifest={}
        for p in paths:
            relative=p.relative_to(ROOT/'HomeAssistant/ha').as_posix();data=p.read_bytes()
            z.writestr(relative,data);manifest[relative]=hashlib.sha256(data).hexdigest()
        z.writestr('SHA256SUMS.json',json.dumps(manifest,indent=2))
    private=destination/'portalai-ha-PRIVATE-pairing.zip'
    with zipfile.ZipFile(private,'x',zipfile.ZIP_DEFLATED) as z:
        for name in ('ca.crt','client.crt','client.key'):
            z.write(Path(pairing)/name,'portalai-pairing/'+name)
    for p in (public,private):
        with zipfile.ZipFile(p) as z:
            if z.testzip():raise RuntimeError('Package verification failed')
    return {'code':str(public),'code_sha256':hashlib.sha256(public.read_bytes()).hexdigest(),
            'private_pairing':str(private),'private_pairing_sha256':hashlib.sha256(private.read_bytes()).hexdigest()}


def main():
    raise RuntimeError('Retired LAN prototype. Pair the separate PortalAI-Projection module on a trusted HA device.')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bind-host',default='192.168.9.210');parser.add_argument('--ha-host',default='192.168.8.141')
    parser.add_argument('--port',type=int,default=18791)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:raise ValueError('Invalid port')
    pairing=ROOT/'HomeAssistant/pairing'
    create(pairing,args.bind_host,args.ha_host,args.port)
    result=package(pairing/'transfer-to-ha',pairing)
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
