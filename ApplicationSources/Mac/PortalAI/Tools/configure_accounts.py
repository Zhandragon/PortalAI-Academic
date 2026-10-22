"""Interactive dedicated-account setup. Never pass passwords or keys in argv/chat.

Profiles and an encrypted vault live on the SSD. This does not contact a mail
server, send a message, broadcast a transaction or activate a mission.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import urllib.parse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_accounts import activate,vault_read,vault_write,address
from runtime_policy import atomic_json,require_space
from profile_paths import private_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kind',choices=['email','wallet','mock'])
    parser.add_argument('name',help='A dedicated profile name, e.g. mission-mail or mission-wallet')
    args=parser.parse_args()
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,47}',args.name):raise ValueError('Invalid profile name')
    base=private_path(ROOT,'Data/Accounts');path=base/'profiles.json'
    profiles=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    if args.name in profiles:raise ValueError('Profile already exists; review it instead of overwriting credentials')
    if args.kind=='mock':
        profiles[args.name]={'backend':'mock','enabled':True,
            'permissions':['email_list','email_read','email_send','wallet_balance','wallet_send','wallet_receipt']}
        require_space(ROOT,1024**2,for_outputs=True);atomic_json(path,profiles)
        print('Created a simulated account with an empty inbox and zero simulated funds. No live account was connected.')
        return
    password=getpass.getpass('Portable account-vault passphrase (12+ characters): ')
    if (base/'vault.json').exists():
        previous=os.environ.get('PORTALAI_ACCOUNT_UNLOCK')
        try:os.environ['PORTALAI_ACCOUNT_UNLOCK']=password;secrets=vault_read(ROOT)
        finally:
            if previous is None:os.environ.pop('PORTALAI_ACCOUNT_UNLOCK',None)
            else:os.environ['PORTALAI_ACCOUNT_UNLOCK']=previous
    else:
        if password!=getpass.getpass('Repeat passphrase: '):raise ValueError('Passphrases differ')
        secrets={}
    if args.kind=='email':
        username=address(input('Dedicated email address: ').strip())
        imap=input('IMAP TLS hostname: ').strip();smtp=input('SMTP implicit-TLS hostname (port 465): ').strip()
        if any(not re.fullmatch(r'[A-Za-z0-9.-]+',host) for host in (imap,smtp)):raise ValueError('Invalid mail hostname')
        secret={'password':getpass.getpass('Dedicated account app password: ')}
        cfg={'backend':'imap-smtp','username':username,'imap_host':imap,'imap_port':993,
             'smtp_host':smtp,'smtp_port':465,'permissions':['email_list','email_read','email_send']}
    else:
        activate(ROOT)
        from eth_account import Account
        key=getpass.getpass('Private key for the isolated EVM wallet (not a personal wallet): ')
        try:account=Account.from_key(key)
        except Exception:raise ValueError('Invalid EVM private key') from None
        chain=int(input('EVM chain ID: ').strip());rpc=input('HTTPS RPC endpoint: ').strip()
        parsed=urllib.parse.urlsplit(rpc)
        if chain<1 or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('Invalid chain/RPC configuration')
        secret={'private_key':key}
        cfg={'backend':'evm','address':account.address,'chain_id':chain,'rpc_url':rpc,
             'permissions':['wallet_balance','wallet_send','wallet_receipt']}
        print('Configured wallet address: '+account.address)
    cfg['enabled']=True
    require_space(ROOT,1024**2,for_outputs=True)
    # Preserve encrypted recovery copies; never write plaintext secrets to disk.
    recovery=base/'Recovery'/str(time.time_ns());recovery.mkdir(parents=True)
    for old in (path,base/'vault.json'):
        if old.exists():shutil.copy2(old,recovery/old.name)
    secrets[args.name]=secret;vault_write(ROOT,secrets,password)
    profiles[args.name]=cfg;atomic_json(path,profiles)
    print('Saved dedicated profile and encrypted vault. No external action was performed.')
    print('Use Tools/unlock_accounts.py to launch PortalAI with this vault unlocked for that process session.')


if __name__=='__main__':main()
