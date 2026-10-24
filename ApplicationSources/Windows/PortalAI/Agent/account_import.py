"""Explicit OpenClaw credential migration. No discovery, logging, or effects."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import re
import subprocess


def source_file(value, maximum=256*1024):
    path=Path(value)
    if not path.is_absolute() or not path.is_file():raise ValueError('Select an existing absolute credential source file')
    for node in (path,*path.parents):
        if node.is_symlink() or getattr(node.lstat(),'st_file_attributes',0)&0x400:
            raise PermissionError('Linked credential sources are not supported')
    if path.stat().st_size>maximum:raise ValueError('Credential source exceeds its limit')
    return path


def dpapi_text(path):
    if os.name!='nt':raise RuntimeError('This source uses Windows CurrentUser protection; import it on its original Windows account')
    class Blob(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    raw=bytes.fromhex(source_file(path).read_text(encoding='utf-8-sig').strip())
    array=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    incoming=Blob(len(raw),array);out=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    crypt.CryptUnprotectData.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not crypt.CryptUnprotectData(ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(out)):
        raise PermissionError('Windows could not unlock this source for the current user')
    try:return ctypes.string_at(out.data,out.size).decode('utf-16-le')
    finally:
        if out.data:
            ctypes.memset(out.data,0,out.size);kernel.LocalFree(out.data)


def github_token(source):
    exe=source_file(source['executable'],100*1024*1024)
    if exe.name.casefold() not in ('gh.exe','gh'):raise ValueError('Select the installed GitHub CLI executable')
    config=source_file(str(Path(source['config_dir'])/'account-binding.json'))
    binding=json.loads(config.read_text(encoding='utf-8-sig'))
    login=source['login']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}',login) or str(binding.get('login','')).casefold()!=login.casefold():
        raise PermissionError('GitHub account binding does not match the requested login')
    if type(binding.get('id')) is not int:raise ValueError('Invalid GitHub account binding')
    env=dict(os.environ)
    for key in ('GH_TOKEN','GITHUB_TOKEN','GH_ENTERPRISE_TOKEN','GITHUB_ENTERPRISE_TOKEN','GH_DEBUG'):
        env.pop(key,None)
    env.update(GH_CONFIG_DIR=str(config.parent),GH_PROMPT_DISABLED='1')
    # `auth token` reads the already configured OS credential store; stdout is
    # captured in memory and never sent to a terminal, log, argv or temp file.
    try:
        result=subprocess.run([str(exe),'auth','token','--hostname','github.com','--user',login],
            env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            timeout=20,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        token=result.stdout.decode().strip()
        if result.returncode or not re.fullmatch(r'(?:gh[oopsur]_|github_pat_)[A-Za-z0-9_]{20,240}',token):raise ValueError()
    except Exception:raise PermissionError('The explicitly selected GitHub account token could not be imported') from None
    return binding,token


def collect(root, sources):
    """Return only to the encrypted importer; callers must never serialize it."""
    from mission_accounts import activate,address
    profiles={};secrets={}
    for source in sources:
        name=source['name'];kind=source['kind']
        if not re.fullmatch('[a-z][a-z0-9_-]{0,47}',name) or name in profiles:raise ValueError('Invalid or duplicate connection name')
        if kind=='business-dpapi':
            data=json.loads(dpapi_text(source['path']))
            google=data['google'];ethereum=data['ethereum']
            username=address(google['username'])
            password=google.get('appPassword','').replace(' ','')
            if not re.fullmatch(r'[A-Za-z]{16}',password):raise ValueError('The Google source has no valid mail app password')
            profiles[name]={'backend':'imap-smtp','enabled':True,'permissions':['email_list','email_read','email_send'],
                'username':username,'imap_host':'imap.gmail.com','imap_port':993,'smtp_host':'smtp.gmail.com','smtp_port':465}
            if data.get('reportTo'):profiles[name]['report_to']=address(data['reportTo'])
            secrets[name]={'password':password,'login_password':google.get('password','')}
            wallet=source['wallet_name']
            if not re.fullmatch('[a-z][a-z0-9_-]{0,47}',wallet) or wallet==name or wallet in profiles:raise ValueError('Invalid wallet connection name')
            activate(root)
            from eth_account import Account
            Account.enable_unaudited_hdwallet_features()
            account=Account.from_mnemonic(ethereum['mnemonic'],account_path="m/44'/60'/0'/0/0")
            profiles[wallet]={'backend':'evm','enabled':True,'permissions':['wallet_balance','wallet_receipt'],
                'address':account.address,'chain_id':1,'rpc_url':'https://ethereum-rpc.publicnode.com'}
            secrets[wallet]={'private_key':account.key.hex(),'mnemonic':ethereum['mnemonic']}
        elif kind=='moltbook-dpapi':
            token=dpapi_text(source['path']).strip()
            if not re.fullmatch(r'moltbook_[A-Za-z0-9_-]{16,240}',token):raise ValueError('Invalid Moltbook source format')
            profiles[name]={'backend':'moltbook','enabled':True,'permissions':['moltbook_status','moltbook_home','moltbook_feed','moltbook_comments','moltbook_comment','moltbook_verify']}
            secrets[name]={'token':token}
        elif kind=='github-cli':
            binding,token=github_token(source)
            from account_services import OPERATIONS
            profiles[name]={'backend':'github','enabled':True,'permissions':sorted(op for op in OPERATIONS if op.startswith('github_')),
                'login':binding['login'],'account_id':binding['id']}
            secrets[name]={'token':token}
        else:raise ValueError('Unsupported credential source type')
    return profiles,secrets
