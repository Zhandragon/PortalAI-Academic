"""Transactional per-profile privacy conversion, only after verified shutdown.

Never toggles a policy around unreadable files. A complete replacement profile
and registry are validated before publication. Historical file versions are
decoded into a content-addressed history inside the replacement profile, using
its new storage policy. Repeated conversions reuse content hashes instead of
nesting copies of entire vaults. Other accounts' credentials are never archived.
This also encrypts old plaintext recovery copies when encryption
is enabled. No model/runtime trees participate. Outside backups and physical SSD
erasure are outside this conversion's scope.
"""
import base64,hashlib,hmac,json,os,re,secrets,shutil,uuid
from contextlib import contextmanager
from pathlib import Path
from local_accounts import LocalAccounts,RecoveryRequired,_uid,_seal,_open,_slot_aad,_json,_password
from profile_paths import _contained
from profile_workspace import ProfileWorkspace,digest,_fsync_dir,MAGIC,MAX_MANIFEST
from runtime_policy import atomic_json

ACCOUNT_FILES=('registry.json','initialized.json','registry-recovery.json')

def _tree(root,path):
    _contained(root,path);rows=[]
    if not path.exists():return rows
    for directory,dirs,files in os.walk(path,followlinks=False,onerror=lambda e:(_ for _ in ()).throw(e)):
        for name in dirs+files:_contained(root,Path(directory)/name)
        for name in files:
            source=Path(directory)/name;info=source.stat()
            if not source.is_file() or info.st_nlink!=1:raise RecoveryRequired('Linked conversion file refused')
            rows.append({'path':source.relative_to(path).as_posix(),'bytes':info.st_size,'sha256':digest(source)})
    return sorted(rows,key=lambda r:r['path'])

def _signature(rows):return hashlib.sha256(_json(rows)).hexdigest()

def _copy(source,target,expected=None):
    target.parent.mkdir(parents=True,exist_ok=True)
    with source.open('rb') as src,target.open('xb') as dst:
        shutil.copyfileobj(src,dst,1024**2);dst.flush();os.fsync(dst.fileno())
    if digest(target)!=digest(source) or (expected is not None and digest(target)!=expected):
        raise RecoveryRequired('Privacy conversion copy did not verify')

class PrivacyChange:
    def __init__(self,root,*,writer_check,on_progress=None,fault=None):
        self.root=Path(root).resolve();self.writer_check=writer_check;self.progress=on_progress;self.fault=fault
        self.journal=_contained(self.root,self.root/'Private/privacy-change.json')

    def _stage(self,state):
        token=state.get('transaction');_uid(token)
        return _contained(self.root,self.root/'Private/PrivacyChange'/token)

    def _notify(self,stage):
        if callable(self.progress):self.progress({'stage':stage,'message':stage.replace('-',' ').capitalize()+'…'})
        if callable(self.fault):self.fault(stage)

    def _save(self,state,phase):
        state['phase']=phase;atomic_json(self.journal,state);self._notify(phase)

    @contextmanager
    def _closed(self):
        from mission_runner import process_lock
        with process_lock(_contained(self.root,self.root/'Private/profile-runtime.lock')):
            receipt=self.writer_check()
            if not isinstance(receipt,dict) or receipt.get('stopped') is not True:
                raise RuntimeError('Verified writer shutdown is required before changing privacy')
            marker=_contained(self.root,self.root/'Private/active-session.json')
            if marker.exists() and json.loads(marker.read_text()).get('state')!='closed':
                raise RuntimeError('Close and save the open workspace before changing privacy')
            yield

    def _authenticate(self,root,username,password):
        store=LocalAccounts(root);store._privacy_transaction=True
        try:
            actor=store.login(username,password)
            with store._lock():store._validate(actor,store._read(),admin=True)
            return store,actor
        except BaseException:store.logout();raise

    def _read(self):
        if self.journal.stat().st_size>32768:raise RecoveryRequired('Privacy change journal exceeds its limit')
        value=json.loads(self.journal.read_text(encoding='utf-8'))
        if value.get('version')!=1 or value.get('phase') not in ('building','prepared','swapping','committed','cleaning'):
            raise RecoveryRequired('Invalid privacy change journal')
        _uid(value.get('target'));self._stage(value)
        return value

    def _new_registry(self,staged,actor,target,password,encrypted,password_required,anonymous,start_without_account):
        with staged._lock():
            data=staged._read();staged._validate(actor,data,admin=True)
            old_master=bytes(actor._master);private=staged._private(data,old_master);old=data['slots'][target]
            if old['pending'] or old['role']=='guest':raise ValueError('Choose an enrolled named account or the shared workspace')
            if anonymous and old['role']!='admin' and start_without_account is False:
                raise ValueError('An account-free profile must be explicitly selected for shared startup')
            keys={uid:_open(old_master,row['wrapped_dek'],b'PortalAI-profile-key:'+data['instance_id'].encode()+b':'+uid.encode()) for uid,row in private['users'].items()}
            # A formerly public administrator key could expose the old registry
            # master through old backups. Rotate that master too, without changing
            # any other account's profile key/password or storage policy.
            master=secrets.token_bytes(32);key=secrets.token_bytes(32);keys[target]=key
            slot=staged._new_slot(data['instance_id'],old['username'],old['role'],key,master,password,
                                 uid=target,epoch=old['epoch']+1,encrypted=encrypted,password_required=password_required,anonymous=anonymous)
            slot['created_at']=old['created_at'];data['slots'][target]=slot
            for uid,dek in keys.items():
                private['users'][uid]['wrapped_dek']=_seal(master,dek,b'PortalAI-profile-key:'+data['instance_id'].encode()+b':'+uid.encode())
                if data['slots'][uid]['role']=='admin':
                    data['slots'][uid]['master_access']=_seal(dek,master,_slot_aad(data['instance_id'],data['slots'][uid],'master'))
            if start_without_account:
                if not anonymous:raise ValueError('Shared startup requires an account-free profile')
                data['auto_profile']=target
            elif data.get('auto_profile')==target:data.pop('auto_profile')
            data['revision']+=1;staged._save(data,private,master)
            staged.logout()

    def _connections(self,workspace,old_key,new_key,uid,encrypted):
        from local_accounts import _crypto
        from account_connections import RELATIVE,PLAINTEXT_RELATIVE
        old_enc=workspace/RELATIVE;old_plain=workspace/PLAINTEXT_RELATIVE
        if old_enc.exists() and old_plain.exists():raise RecoveryRequired('Conflicting plaintext and encrypted connections require review')
        source=old_enc if old_enc.exists() else old_plain
        if not source.exists():return
        if source.stat().st_size>512*1024:raise ValueError('Connections exceed their limit')
        raw=json.loads(source.read_text(encoding='utf-8'));aad=b'PortalAI/connections/v1/'+uid.encode()
        aes,_=_crypto()
        def connection_key(key):return hmac.new(key,b'PortalAI/connections/v1/'+uid.encode(),hashlib.sha256).digest()
        if source==old_enc:
            data=json.loads(aes(connection_key(old_key)).decrypt(base64.b64decode(raw['nonce'],validate=True),base64.b64decode(raw['ciphertext'],validate=True),aad))
        else:
            if raw.get('format')!='portalai-plaintext-connections-v1' or raw.get('user_id')!=uid:raise ValueError('Plaintext connection identity mismatch')
            data=raw['data']
        if data.get('version')!=1 or any(not isinstance(data.get(k),dict) for k in ('profiles','secrets','setups')):raise ValueError('Invalid connections')
        if encrypted:
            nonce=secrets.token_bytes(12);body=json.dumps(data,separators=(',',':'),ensure_ascii=True).encode()
            cipher=aes(connection_key(new_key)).encrypt(nonce,body,aad)
            if json.loads(aes(connection_key(new_key)).decrypt(nonce,cipher,aad))!=data:raise RuntimeError('Connection conversion failed')
            dest=old_enc;result={'version':1,'nonce':base64.b64encode(nonce).decode(),'ciphertext':base64.b64encode(cipher).decode()}
        else:dest=old_plain;result={'version':1,'format':'portalai-plaintext-connections-v1','user_id':uid,'data':data}
        atomic_json(dest,result)
        if json.loads(dest.read_text())!=result:raise RuntimeError('Connection conversion save failed')
        if source!=dest:source.unlink()

    def _history(self,source,replacement,old_rows,transaction):
        history='Data/PrivacyHistory/'
        old_key=source._key();key_id=hashlib.sha256(old_key).hexdigest()
        key_record={'version':1,'user_id':source.uid,'key':base64.b64encode(old_key).decode(),
                    'purpose':'Historical profile-bound connection bundles only; this is not an administrator master key.'}
        key_path=replacement.workspace/history/'keys'/(key_id+'.json')
        if key_path.exists():
            if json.loads(key_path.read_text())!=key_record:raise RecoveryRequired('Historical key record conflicts')
        else:atomic_json(key_path,key_record)
        stored={source.pointer.relative_to(source.base).as_posix(),'workspace.lock','plain-closed.json','harvest-last.json'}
        # All complete historical generations must verify. Unknown/partial
        # generations need recovery rather than silently losing their contents.
        for folder in sorted(source.vault.iterdir()):
            if folder==source.pointer:continue
            if not folder.is_dir() or not re.fullmatch('[a-f0-9]{32}',folder.name):raise RecoveryRequired('Unknown recovery entry requires review before conversion')
            version=source.verify(folder.name);rows=[]
            stored.add((folder/('manifest.enc' if source.encrypted else 'manifest.json')).relative_to(source.base).as_posix())
            for row in version['files']:
                stored.add(source.blob_path(version,row).relative_to(source.base).as_posix())
                if row['path'].startswith(history):continue
                relative=history+'objects/'+row['sha256']+'.data'
                dest=_contained(replacement.root,replacement.workspace/relative);dest.parent.mkdir(parents=True,exist_ok=True)
                if dest.exists():
                    if dest.stat().st_size!=row['bytes'] or digest(dest)!=row['sha256']:raise RecoveryRequired('Historical content hash collision or corruption')
                else:
                    size,sha=source._decrypt_file(source.blob_path(version,row),row['path'],source._key(),dest)
                    if (size,sha)!=(row['bytes'],row['sha256']):raise RecoveryRequired('Historical file conversion failed')
                rows.append({'path':row['path'],'bytes':row['bytes'],'sha256':row['sha256'],'object':relative})
            record={'version':1,'user_id':source.uid,'source_generation':version['generation'],'profile_key_id':key_id,'files':rows}
            destination=_contained(replacement.root,replacement.workspace/history/'versions'/(version['generation']+'.json'))
            if destination.exists():
                if json.loads(destination.read_text())!=record:raise RecoveryRequired('Historical generation record conflicts')
            else:atomic_json(destination,record)
        if any(r['path'] not in stored and not r['path'].startswith('Workspace/') for r in old_rows):
            raise RecoveryRequired('Unreferenced stored profile files require review before conversion; originals retained')
        inventory=replacement.workspace/history/'inventories'/(transaction+'.json')
        atomic_json(inventory,{'version':1,'files':old_rows,'format':'original-storage-inventory-only'})

    def _inventory_from_archive(self,workspace,manifest,transaction):
        relative='Data/PrivacyHistory/inventories/'+transaction+'.json'
        row=next(r for r in manifest['files'] if r['path']==relative)
        if row['bytes']>MAX_MANIFEST:raise RecoveryRequired('Archived inventory exceeds its limit')
        data=workspace.blob_path(manifest,row).read_bytes()
        if workspace.encrypted:
            from local_accounts import _crypto
            if not data.startswith(MAGIC):raise RecoveryRequired('Invalid archived inventory')
            offset=len(MAGIC);aes,_=_crypto()
            data=aes(workspace._key()).decrypt(data[offset:offset+12],data[offset+12:],workspace._aad(relative))
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise RecoveryRequired('Archived inventory hash mismatch')
        return json.loads(data)['files']

    def apply(self,username,password,target,*,new_password,encrypted,password_required,anonymous=False,start_without_account=False):
        _uid(target)
        if any(type(v) is not bool for v in (encrypted,password_required,anonymous,start_without_account)):raise ValueError('Privacy settings must be booleans')
        if password_required:_password(new_password)
        elif new_password!='':raise ValueError('Clear the password for passwordless mode')
        if anonymous and (encrypted or password_required):raise ValueError('Account-free mode must be unencrypted and passwordless')
        with self._closed():
            if self.journal.exists():raise RecoveryRequired('Resume or roll back the existing privacy change first')
            accounts,actor=self._authenticate(self.root,username,password)
            staged=None;state=None
            try:
                owner=accounts.profile_session(actor,target);source=ProfileWorkspace(self.root,owner)
                if source.encrypted and source.inventory():raise RuntimeError('Save and close the target encrypted profile first')
                if any((source.base/name).exists() for name in ('seal-pending.json','restore-pending.json','restore-inflight.enc','hydration.enc','harvest-pending.json')):
                    raise RuntimeError('Finish target profile recovery before changing privacy')
                if not source.pointer.exists() or not source.encrypted:source.snapshot()
                manifest=source.verify();old_rows=_tree(self.root,source.base)
                logical=sum(r['bytes'] for r in manifest['files']);stored=sum(r['bytes'] for r in old_rows)
                needed=3*(logical+stored)+32*1024**2
                if shutil.disk_usage(self.root).free-needed<80*1024**3:raise RuntimeError('Privacy conversion needs extra verified copies while retaining at least 80 GiB free')
                state={'version':1,'transaction':uuid.uuid4().hex,'target':target,'administrator':actor.username,
                       'old_registry_sha256':digest(accounts.registry_path),'old_tree_sha256':_signature(old_rows),
                       'encrypted':encrypted,'password_required':password_required,'phase':'building'}
                stage=self._stage(state);stage.mkdir(parents=True,exist_ok=False)
                self._save(state,'building')
                new_root=stage/'NewRoot'
                for name in ACCOUNT_FILES:_copy(accounts.base/name,new_root/'Private/Accounts'/name)
                staged,staged_actor=self._authenticate(new_root,username,password)
                self._new_registry(staged,staged_actor,target,new_password,encrypted,password_required,anonymous,start_without_account)
                next_password=new_password if actor.user_id==target else password
                staged_actor=staged.login(username,next_password);new_owner=staged.profile_session(staged_actor,target)
                replacement=ProfileWorkspace(new_root,new_owner)
                old_key=owner.profile_key;new_key=new_owner.profile_key
                for row in manifest['files']:
                    dest=_contained(new_root,replacement.workspace/row['path']);dest.parent.mkdir(parents=True,exist_ok=True)
                    size,sha=source._decrypt_file(source.blob_path(manifest,row),row['path'],old_key,dest)
                    if (size,sha)!=(row['bytes'],row['sha256']):raise RecoveryRequired('Current profile copy failed verification')
                self._connections(replacement.workspace,old_key,new_key,target,encrypted)
                self._history(source,replacement,old_rows,state['transaction'])
                receipt=replacement.seal(writers_stopped=True)
                if not replacement.closed_verified(receipt):raise RecoveryRequired('Replacement profile did not verify')
                if _signature(_tree(self.root,source.base))!=state['old_tree_sha256'] or digest(accounts.registry_path)!=state['old_registry_sha256']:
                    raise RuntimeError('Original account data changed during conversion; original remains authoritative')
                state.update(new_registry_sha256=digest(staged.registry_path),new_tree_sha256=_signature(_tree(new_root,replacement.base)),generation=receipt['generation'])
                self._save(state,'prepared')
                return self._finish(state,actor.username,next_password)
            finally:
                accounts.logout()
                if staged is not None:staged.logout()

    def _finish(self,state,username,password):
        stage=self._stage(state);new_root=stage/'NewRoot'
        current_hash=digest(self.root/'Private/Accounts/registry.json')
        authentication_root=self.root if current_hash==state['new_registry_sha256'] else new_root
        staged,actor=self._authenticate(authentication_root,username,password)
        try:
            if digest(staged.registry_path)!=state['new_registry_sha256']:raise RecoveryRequired('Prepared registry changed')
            if actor.username!=state['administrator']:raise PermissionError('Use the administrator who requested this conversion')
            live=_contained(self.root,self.root/'Private/Users'/state['target'])
            incoming=_contained(self.root,new_root/'Private/Users'/state['target']);old=_contained(self.root,stage/'OldProfile')
            live_accounts=LocalAccounts(self.root);live_accounts._privacy_transaction=True
            current=digest(live_accounts.registry_path)
            if current not in (state['old_registry_sha256'],state['new_registry_sha256']):raise RecoveryRequired('Live registry changed during privacy conversion')
            if current==state['old_registry_sha256']:
                self._save(state,'swapping')
                if not old.exists():
                    if _signature(_tree(self.root,live))!=state['old_tree_sha256']:raise RecoveryRequired('Original profile changed')
                    live.rename(old);_fsync_dir(live.parent);self._notify('old-profile-retained')
                if not live.exists():
                    if _signature(_tree(self.root,incoming))!=state['new_tree_sha256']:raise RecoveryRequired('Prepared profile changed')
                    incoming.rename(live);_fsync_dir(live.parent);self._notify('new-profile-installed')
                if _signature(_tree(self.root,live))!=state['new_tree_sha256']:raise RecoveryRequired('Replacement profile changed before registry commit')
                with live_accounts._lock():
                    if digest(live_accounts.registry_path)!=state['old_registry_sha256']:raise RecoveryRequired('Registry changed before publication; retained original requires recovery')
                    live_accounts._commit_registry(json.loads(staged.registry_path.read_text(encoding='utf-8')))
                self._notify('registry-published')
            self._save(state,'committed')
            verified,admin=self._authenticate(self.root,username,password)
            try:
                if not verified._recovery_current(verified._read()):raise RecoveryRequired('New registry recovery copy must verify before removing conversion staging')
                owner=verified.profile_session(admin,state['target']);workspace=ProfileWorkspace(self.root,owner)
                manifest=workspace.verify(state['generation'])
                archived=self._inventory_from_archive(workspace,manifest,state['transaction'])
                if _signature(archived)!=state['old_tree_sha256']:raise RecoveryRequired('Archived original profile inventory differs')
                if workspace.encrypted and workspace.inventory():raise RecoveryRequired('Encrypted replacement still has plaintext workspace files')
                if not workspace.encrypted and not workspace.closed_verified({'sealed':True,'encrypted':False,'generation':state['generation']}):raise RecoveryRequired('Plaintext replacement does not match its recovery copy')
            finally:verified.logout()
            self._save(state,'cleaning')
            if old.exists():
                # Historical contents were independently decoded and verified
                # under the new policy before any original removal.
                expected={r['path']:r for r in archived}
                if any(expected.get(r['path'])!=r for r in _tree(self.root,old)):raise RecoveryRequired('Retained original changed; cleanup refused')
                self._remove_owned_tree(old,stage)
            if new_root.exists():self._remove_owned_tree(new_root,stage)
            self._notify('staging-removed')
            self.journal.unlink();_fsync_dir(self.journal.parent)
            try:stage.rmdir()
            except OSError:pass
            return {'verified':True,'encrypted':state['encrypted'],'password_required':state['password_required'],'user_id':state['target'],'archived_previous_files':True,'transaction':state['transaction']}
        finally:staged.logout()

    def _remove_owned_tree(self,path,stage):
        actual=path.resolve();base=stage.resolve()
        if actual not in (base/'NewRoot',base/'OldProfile') or not base.is_relative_to((self.root/'Private/PrivacyChange').resolve()):
            raise RecoveryRequired('Privacy cleanup target escapes its transaction')
        _tree(self.root,path) # Reject links/junctions/nonregular files before removal.
        shutil.rmtree(path)

    def recover(self,username,password,*,action):
        if action not in ('finish','rollback'):raise ValueError('Choose finish or rollback')
        with self._closed():
            state=self._read();stage=self._stage(state)
            if action=='finish':
                if state['phase']=='building':raise RecoveryRequired('Preparation was interrupted; roll back with the original administrator credentials')
                return self._finish(state,username,password)
            accounts,actor=self._authenticate(self.root,username,password)
            try:
                if actor.username!=state['administrator'] or digest(accounts.registry_path)!=state['old_registry_sha256']:
                    raise RecoveryRequired('The new registry is already committed; finish using the new administrator credentials')
                live=_contained(self.root,self.root/'Private/Users'/state['target']);old=stage/'OldProfile';new_root=stage/'NewRoot'
                if old.exists():
                    if _signature(_tree(self.root,old))!=state['old_tree_sha256']:raise RecoveryRequired('Original profile no longer matches rollback inventory')
                    if live.exists():
                        if _signature(_tree(self.root,live))!=state.get('new_tree_sha256'):raise RecoveryRequired('Replacement profile changed; rollback refused')
                        incoming=new_root/'Private/Users'/state['target']
                        if incoming.exists():raise RecoveryRequired('Unexpected duplicate replacement')
                        incoming.parent.mkdir(parents=True,exist_ok=True);live.rename(incoming)
                    old.rename(live);_fsync_dir(live.parent)
                if _signature(_tree(self.root,live))!=state['old_tree_sha256']:raise RecoveryRequired('Original profile rollback did not verify')
                if new_root.exists():self._remove_owned_tree(new_root,stage)
                self.journal.unlink();_fsync_dir(self.journal.parent)
                try:stage.rmdir()
                except OSError:pass
                return {'rolled_back':True,'verified':True,'user_id':state['target']}
            finally:accounts.logout()
