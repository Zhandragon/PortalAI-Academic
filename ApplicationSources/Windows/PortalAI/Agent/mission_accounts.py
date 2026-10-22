"""Explicit dedicated accounts for full missions; simulations are clearly labelled.

No personal-account discovery. Credentials live in a portable encrypted vault,
unlocked for the current session. Effect journals survive lost replies and never
automatically replay an uncertain email or transaction.
"""
import base64
from email.message import EmailMessage
from email.parser import BytesParser
from email.policy import default as email_policy
from email.utils import parseaddr, make_msgid
import hashlib
import imaplib
import json
import os
from pathlib import Path
import re
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request

from runtime_policy import ROOT, atomic_json, require_space
from profile_paths import private_path

OPERATIONS={'email_list','email_read','email_send','wallet_balance','wallet_send','wallet_receipt'}
EFFECTS={'email_send','wallet_send'}


def activate(root=ROOT):
    if sys.version_info[:2] != (3,12):raise RuntimeError('Portable account libraries require bundled Python 3.12')
    if os.name=='nt':relative='Runtime/AccountPython/packages'
    elif sys.platform.startswith('linux'):relative='Runtime/AccountPython/linux-packages'
    else:raise RuntimeError('Portable account libraries are available for Windows/Linux x64 only')
    packages=Path(root)/relative
    if not (packages/'eth_account/__init__.py').is_file():raise RuntimeError('Portable account libraries are not installed')
    if str(packages) not in sys.path:sys.path.insert(0,str(packages))


def vault_write(root, secrets, password):
    if len(password)<12:raise ValueError('Use an account-vault passphrase of at least 12 characters')
    if len(json.dumps(secrets).encode())>64000:raise ValueError('Account secrets exceed the vault budget')
    activate(root)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    salt=os.urandom(16);nonce=os.urandom(12)
    key=Scrypt(salt=salt,length=32,n=131072,r=8,p=1).derive(password.encode('utf-8'))
    ciphertext=AESGCM(key).encrypt(nonce,json.dumps(secrets).encode(),b'PortalAI-accounts-v1')
    encode=lambda b:base64.b64encode(b).decode('ascii')
    require_space(Path(root),1024**2,for_outputs=True)
    atomic_json(private_path(root,'Data/Accounts/vault.json'),{'version':1,'salt':encode(salt),'nonce':encode(nonce),'ciphertext':encode(ciphertext)})


def vault_read(root=ROOT):
    password=os.environ.get('PORTALAI_ACCOUNT_UNLOCK','')
    if not password:raise PermissionError('Unlock the dedicated account vault for this session before using a live account')
    activate(root)
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
    path=private_path(root,'Data/Accounts/vault.json')
    if path.stat().st_size>256*1024:raise ValueError('Account vault exceeds its size limit')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data.get('version')!=1:raise ValueError('Unsupported account vault version')
    decode=lambda field:base64.b64decode(data[field],validate=True)
    try:
        key=Scrypt(salt=decode('salt'),length=32,n=131072,r=8,p=1).derive(password.encode('utf-8'))
        return json.loads(AESGCM(key).decrypt(decode('nonce'),decode('ciphertext'),b'PortalAI-accounts-v1'))
    except Exception:raise PermissionError('Account vault could not be unlocked') from None


def address(value):
    value=str(value)
    if len(value)>254 or any(c in value for c in '\r\n') or parseaddr(value)[1]!=value or '@' not in value:
        raise ValueError('Expected one plain email address')
    return value


def uint(value, label):
    if isinstance(value,bool) or not re.fullmatch(r'\d{1,78}',str(value)):
        raise ValueError(label+' must be a nonnegative integer, in base units')
    result=int(value)
    if result>=2**256:raise ValueError(label+' exceeds uint256')
    return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise RuntimeError('Account RPC redirects are disabled')


class Accounts:
    def __init__(self,root=ROOT):
        self.root=Path(root).resolve();self.base=private_path(self.root,'Data/Accounts')

    def profiles(self):
        path=self.base/'profiles.json'
        if not path.is_file():return {}
        if path.stat().st_size>64*1024:raise ValueError('Account profile file exceeds limit')
        profiles=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(profiles,dict) or len(profiles)>64:raise ValueError('Expected at most 64 named account profiles')
        for name,item in profiles.items():
            if not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}',name) or not isinstance(item,dict):
                raise ValueError('Malformed account profile')
            permissions=item.get('permissions',[])
            if not isinstance(permissions,list) or any(not isinstance(p,str) or p not in OPERATIONS for p in permissions):
                raise ValueError('Account permissions must be a list of supported operations')
        return profiles

    def profile(self,name):
        if not isinstance(name,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}',name):raise ValueError('Invalid account profile name')
        profiles=self.profiles()
        if not profiles:raise RuntimeError('No dedicated accounts configured; use Tools/configure_accounts.py')
        item=profiles.get(name)
        if not isinstance(item,dict) or item.get('enabled') is not True:raise PermissionError('Account profile is not enabled')
        if item.get('backend') not in ('mock','imap-smtp','evm'):raise ValueError('Unsupported account backend')
        return item

    def call(self,mission,profile,operation,parameters=None):
        if mission.get('mode')!='full':raise PermissionError('Dedicated accounts require a full host mission; observe/VM have no account access')
        if operation=='profiles':
            profiles=self.profiles()
            return {'profiles':[{'name':name,'backend':cfg.get('backend'),'enabled':cfg.get('enabled') is True,
                'permissions':cfg.get('permissions',[])} for name,cfg in profiles.items()],
                'unlock_secret_present_in_session':bool(os.environ.get('PORTALAI_ACCOUNT_UNLOCK'))}
        if operation not in OPERATIONS:raise ValueError('Unknown account operation')
        if parameters is None:parameters={}
        if not isinstance(parameters,dict) or len(json.dumps(parameters).encode())>64000:raise ValueError('Account parameters exceed limit')
        cfg=self.profile(profile)
        op_family={'imap-smtp':'email_','evm':'wallet_'}.get(cfg['backend'])
        if op_family and not operation.startswith(op_family):
            raise ValueError('Operation does not belong to this account backend')
        if operation not in cfg.get('permissions',[]):raise PermissionError('Operation is not enabled for this dedicated account')
        require_space(self.root,1024**2,for_outputs=True)
        from mission_runner import process_lock
        with process_lock(self.base/(profile+'.lock')):
            if operation not in EFFECTS:return self.dispatch(cfg,profile,operation,parameters,None)
            identity=json.dumps({'mission':mission['id'],'step':mission['steps'],'profile':profile,
                                 'operation':operation,'parameters':parameters},sort_keys=True,separators=(',',':'))
            key=hashlib.sha256(identity.encode()).hexdigest()
            journal=self.base/'Journal'/(key+'.json')
            if journal.exists():
                saved=json.loads(journal.read_text(encoding='utf-8'))
                if saved.get('status')=='confirmed':return saved['receipt']
                raise RuntimeError('Account action has an uncertain outcome; inspect journal '+key+' before any manual resolution')
            state={'id':key,'mission':mission['id'],'step':mission['steps'],'profile':profile,'operation':operation,
                   'status':'pending','simulated':cfg['backend']=='mock','started_at':time.time()}
            atomic_json(journal,state)  # Durable before an external effect.
            def prepared(**fields):
                state.update(fields);atomic_json(journal,state)
            try:
                receipt=self.dispatch(cfg,profile,operation,parameters,(key,prepared))
            except Exception:
                # Never infer that a timeout means the server did nothing.
                raise RuntimeError('Account action did not return a confirmed result; review journal '+key) from None
            state.update(status='confirmed',receipt=receipt,finished_at=time.time());atomic_json(journal,state)
            return receipt

    def dispatch(self,cfg,name,op,params,effect):
        if cfg['backend']=='mock':return self.mock(name,op,params,effect)
        if cfg['backend']=='imap-smtp' and op.startswith('email_'):return self.email(cfg,name,op,params,effect)
        if cfg['backend']=='evm' and op.startswith('wallet_'):return self.wallet(cfg,name,op,params,effect)
        raise ValueError('Operation does not belong to this account backend')

    def mock(self,name,op,p,effect):
        path=self.base/'Simulated'/(name+'.json')
        state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'inbox':[],'outbox':[], 'balance_wei':'0','transactions':[]}
        if op=='email_list':result={'messages':[{'id':m['id'],'subject':m['subject']} for m in state['inbox'][-10:]]}
        elif op=='email_read':
            result=next((m for m in state['inbox'] if m['id']==str(p.get('id'))),None)
            if result is None:raise ValueError('Simulated message does not exist')
        elif op=='email_send':
            recipient=address(p.get('to',''));key=effect[0]
            result={'message_id':'<'+key+'@portalai.simulated>','to':recipient,'accepted':True}
            state['outbox'].append({**result,'subject':str(p.get('subject','')),'body':str(p.get('body',''))})
        elif op=='wallet_balance':result={'balance_wei':state['balance_wei']}
        elif op=='wallet_send':
            value=uint(p.get('value_wei',''),'value_wei');balance=uint(state['balance_wei'],'balance')
            if value>balance:raise ValueError('Insufficient simulated funds')
            if not re.fullmatch(r'0x[0-9a-fA-F]{40}',str(p.get('to',''))):raise ValueError('Invalid EVM destination')
            result={'transaction_hash':'0x'+effect[0],'to':p['to'],'value_wei':str(value),'status':'simulated-confirmed'}
            state['balance_wei']=str(balance-value);state['transactions'].append(result)
        elif op=='wallet_receipt':result=next((t for t in state['transactions'] if t['transaction_hash']==p.get('transaction_hash')),{'status':'not_found'})
        else:raise ValueError('Unsupported simulated operation')
        if op in EFFECTS:atomic_json(path,state)
        return {'simulated':True,**result}

    def email(self,cfg,name,op,p,effect):
        secret=vault_read(self.root)[name];username=address(cfg['username'])
        password=secret['password'];tls=ssl.create_default_context()
        if op=='email_send':
            message=EmailMessage();message['From']=username;message['To']=address(p.get('to',''))
            subject=str(p.get('subject',''))
            if '\r' in subject or '\n' in subject or len(subject)>998:raise ValueError('Invalid email subject')
            message['Subject']=subject;message['Message-ID']='<'+effect[0]+'@portalai.local>'
            message.set_content(str(p.get('body','')))
            effect[1](message_id=message['Message-ID'])
            with smtplib.SMTP_SSL(cfg['smtp_host'],int(cfg.get('smtp_port',465)),timeout=30,context=tls) as smtp:
                smtp.login(username,password)
                rejected=smtp.send_message(message)
            if rejected:raise RuntimeError('SMTP rejected the message recipient')
            return {'simulated':False,'message_id':message['Message-ID'],'accepted_by_smtp':True,'delivery_confirmed':False}
        with imaplib.IMAP4_SSL(cfg['imap_host'],int(cfg.get('imap_port',993)),ssl_context=tls,timeout=30) as mail:
            mail.login(username,password);status,_=mail.select('INBOX',readonly=True)
            if status!='OK':raise RuntimeError('Cannot open the dedicated inbox')
            validity=(mail.response('UIDVALIDITY')[1] or [b''])[0].decode('ascii')
            if op=='email_list':
                status,data=mail.uid('search',None,'ALL')
                if status!='OK':raise RuntimeError('Inbox query failed')
                uids=data[0].split()[-10:]
                return {'simulated':False,'messages':[{'id':validity+':'+uid.decode('ascii')} for uid in uids],
                        'source':'dedicated inbox; untrusted message content'}
            parts=str(p.get('id','')).split(':')
            if len(parts)!=2 or parts[0]!=validity or not parts[1].isdigit():raise ValueError('Message UID/UIDVALIDITY changed; list the inbox again')
            status,data=mail.uid('fetch',parts[1],'(RFC822.SIZE)')
            size=re.search(rb'RFC822.SIZE (\d+)',b' '.join(x for x in data if isinstance(x,bytes)))
            if status!='OK' or not size or int(size[1])>256*1024:raise RuntimeError('Message missing or exceeds 256 KiB limit')
            status,data=mail.uid('fetch',parts[1],'(BODY.PEEK[])')
            if status!='OK':raise RuntimeError('Message fetch failed')
            raw=next(item[1] for item in data if isinstance(item,tuple))
            if len(raw)>256*1024:raise RuntimeError('Message exceeded declared size')
            msg=BytesParser(policy=email_policy).parsebytes(raw)
            part=msg.get_body(preferencelist=('plain',)) if msg.is_multipart() else msg
            body=part.get_content() if part and part.get_content_type()=='text/plain' else '[No plain-text body; attachments/HTML are not executed]'
            return {'simulated':False,'id':p['id'],'from':str(msg.get('From',''))[:1000],
                    'subject':str(msg.get('Subject',''))[:1000],'body':str(body)[:12000],'untrusted_content':True}

    def rpc(self,cfg,method,params):
        url=cfg['rpc_url'];parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Wallet RPC requires HTTPS without embedded credentials')
        request=urllib.request.Request(url,json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.build_opener(NoRedirect).open(request,timeout=30) as response:raw=response.read(1024**2+1)
        if len(raw)>1024**2:raise RuntimeError('Wallet RPC response exceeds limit')
        data=json.loads(raw)
        if data.get('error') or 'result' not in data:raise RuntimeError('Wallet RPC rejected '+method)
        return data['result']

    def wallet(self,cfg,name,op,p,effect):
        activate(self.root)
        from eth_account import Account
        from eth_utils import to_checksum_address
        chain=uint(cfg['chain_id'],'chain_id');owner=to_checksum_address(cfg['address'])
        if int(self.rpc(cfg,'eth_chainId',[]),16)!=chain:raise RuntimeError('Wallet RPC chain differs from the configured chain')
        if op=='wallet_balance':return {'simulated':False,'address':owner,'chain_id':chain,'balance_wei':str(int(self.rpc(cfg,'eth_getBalance',[owner,'latest']),16))}
        if op=='wallet_receipt':
            tx=str(p.get('transaction_hash',''))
            if not re.fullmatch(r'0x[0-9a-fA-F]{64}',tx):raise ValueError('Invalid transaction hash')
            receipt=self.rpc(cfg,'eth_getTransactionReceipt',[tx])
            if receipt is not None and (not isinstance(receipt,dict) or str(receipt.get('transactionHash','')).lower()!=tx.lower()):
                raise RuntimeError('RPC receipt differs from the requested transaction')
            # Inclusion in a block alone does not mean the transfer/contract call
            # succeeded. A reverted transaction can still have consumed gas.
            succeeded=None
            if receipt is not None and receipt.get('status') is not None:
                status=int(receipt['status'],16)
                if status not in (0,1):raise RuntimeError('Invalid transaction execution status')
                succeeded=status==1
            return {'simulated':False,'transaction_hash':tx,'receipt':receipt,
                    'status':'pending_or_unknown' if receipt is None else 'mined',
                    'execution_succeeded':succeeded,'finality_confirmed':False}
        value=uint(p.get('value_wei',''),'value_wei');target=to_checksum_address(p['to'])
        data=str(p.get('data','0x'))
        if not re.fullmatch(r'0x(?:[0-9a-fA-F]{2}){0,16000}',data):raise ValueError('Invalid transaction calldata')
        price=uint(p['gas_price_wei'],'gas_price_wei') if 'gas_price_wei' in p else int(self.rpc(cfg,'eth_gasPrice',[]),16)
        nonce=int(self.rpc(cfg,'eth_getTransactionCount',[owner,'pending']),16)
        tx={'chainId':chain,'nonce':nonce,'to':target,'value':value,'data':data,'gasPrice':price}
        gas=uint(p['gas_limit'],'gas_limit') if 'gas_limit' in p else int(self.rpc(cfg,'eth_estimateGas',[{'from':owner,'to':target,'value':hex(value),'data':data}]),16)
        tx['gas']=gas
        if 'max_value_wei' in cfg and value>uint(cfg['max_value_wei'],'max_value_wei'):raise PermissionError('Transfer exceeds configured value limit')
        if 'max_fee_wei' in cfg and gas*price>uint(cfg['max_fee_wei'],'max_fee_wei'):raise PermissionError('Transfer exceeds configured fee limit')
        secret=vault_read(self.root)[name]
        try:account=Account.from_key(secret['private_key'])
        except Exception:raise ValueError('Invalid key in the dedicated wallet vault') from None
        if account.address!=owner:raise PermissionError('Wallet vault key does not match the configured address')
        signed=account.sign_transaction(tx);txhash='0x'+signed.hash.hex().removeprefix('0x')
        effect[1](transaction_hash=txhash,chain_id=chain,nonce=nonce)
        returned=self.rpc(cfg,'eth_sendRawTransaction',['0x'+signed.raw_transaction.hex().removeprefix('0x')])
        if str(returned).lower()!=txhash.lower():raise RuntimeError('RPC transaction hash differs from signed transaction')
        return {'simulated':False,'transaction_hash':txhash,'chain_id':chain,'status':'submitted','mined':False}
