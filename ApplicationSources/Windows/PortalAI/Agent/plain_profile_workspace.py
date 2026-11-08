"""Explicit plaintext profiles with verified, incremental plaintext recovery.

No user payload is encrypted in this mode. Workspace files remain in place on
logout. Immutable recovery blobs retain byte verification and reuse unchanged
files; this is corruption detection, not protection from the filesystem owner.
"""
import hashlib,json,os,re,shutil,uuid
from profile_workspace import ProfileWorkspace,exclusive,_relative,_fsync_dir,MAX_MANIFEST,CHUNK
from profile_paths import _contained
from runtime_policy import atomic_json,require_space

class PlainProfileWorkspace(ProfileWorkspace):
    encrypted=False

    def __init__(self,root,session,*,on_progress=None):
        super().__init__(root,session,on_progress=on_progress)
        self.vault=_contained(self.root,self.base/'PlainRecovery')

    @property
    def pointer(self):return _contained(self.root,self.vault/'current.json')

    def _hydration(self):
        if any((self.base/name).exists() for name in ('hydration.enc','restore-pending.json','restore-inflight.enc')):
            raise RuntimeError('Finish encrypted workspace recovery before changing storage mode')
        return None

    def _copy(self,source,target=None,*,created=None):
        _contained(self.root,source);info=source.stat()
        if not source.is_file() or info.st_nlink!=1:raise ValueError('Linked plaintext source refused')
        digest=hashlib.sha256();size=0
        with source.open('rb') as src:
            dst=target.open('xb') if target is not None else None
            try:
                if dst is not None and created is not None:created(dst)
                while chunk:=src.read(CHUNK):
                    self._key();digest.update(chunk);size+=len(chunk)
                    if dst is not None:dst.write(chunk)
                if dst is not None:dst.flush();os.fsync(dst.fileno())
            finally:
                if dst is not None:dst.close()
        return size,digest.hexdigest()

    def _decrypt_file(self,source,relative,key,target=None,*,created=None):
        _relative(relative);self._key()
        return self._copy(source,target,created=created)

    def blob_path(self,manifest,row):
        if manifest.get('format')!='portalai-plaintext-v1' or manifest.get('user_id')!=self.uid:
            raise ValueError('Plaintext recovery identity mismatch')
        generation=row.get('blob_generation',manifest.get('generation'))
        if not isinstance(generation,str) or not re.fullmatch('[a-f0-9]{32}',generation):
            raise ValueError('Invalid plaintext generation')
        blob=row.get('blob')
        if not isinstance(blob,str) or not re.fullmatch(r'[a-f0-9]{32}\.data',blob):
            raise ValueError('Invalid plaintext blob')
        return _contained(self.root,self.vault/generation/blob)

    def manifest(self,generation=None):
        self._key();self.root.stat()
        if generation is None:
            if self.pointer.stat().st_size>4096:raise ValueError('Oversized plaintext pointer')
            pointer=json.loads(self.pointer.read_text(encoding='utf-8'))
            if pointer.get('user_id')!=self.uid or pointer.get('format')!='portalai-plaintext-v1':
                raise ValueError('Invalid plaintext pointer')
            generation=pointer.get('generation')
        if not isinstance(generation,str) or not re.fullmatch('[a-f0-9]{32}',generation):
            raise ValueError('Invalid plaintext generation')
        path=_contained(self.root,self.vault/generation/'manifest.json')
        if path.stat().st_size>MAX_MANIFEST:raise ValueError('Oversized plaintext manifest')
        value=json.loads(path.read_text(encoding='utf-8'))
        if value.get('format')!='portalai-plaintext-v1' or value.get('user_id')!=self.uid or value.get('generation')!=generation:
            raise ValueError('Plaintext manifest identity mismatch')
        if not isinstance(value.get('files'),list):raise ValueError('Invalid plaintext file inventory')
        seen=set()
        for row in value['files']:
            name=_relative(row['path'])
            if name.casefold() in seen or type(row.get('bytes')) is not int or row['bytes']<0 or not re.fullmatch('[a-f0-9]{64}',row.get('sha256','')):
                raise ValueError('Invalid plaintext file entry')
            seen.add(name.casefold());self.blob_path(value,row)
        return value

    def verify(self,generation=None):
        value=self.manifest(generation)
        for row in value['files']:
            if self._copy(self.blob_path(value,row))!=(row['bytes'],row['sha256']):
                raise ValueError('Plaintext recovery file failed checksum verification')
        return value

    @exclusive
    def snapshot(self):
        self._key();self._hydration()
        if (self.base/'seal-pending.json').exists():raise RuntimeError('Complete pending plaintext close first')
        rows=self.inventory();previous={}
        if self.pointer.exists():
            prior=self.manifest()
            previous={r['path']:r for r in prior['files']}
            if rows==[{k:r[k] for k in ('path','bytes','sha256')} for r in prior['files']]:
                self.verify(prior['generation'])
                if self.inventory()!=rows:raise RuntimeError('Plaintext workspace changed during verification')
                return {'verified':True,'generation':prior['generation'],'files':len(rows),'bytes':sum(r['bytes'] for r in rows),'encrypted_files':0,'reused_files':len(rows),'encrypted':False}
        unchanged={r['path']:previous[r['path']] for r in rows if r['path'] in previous and all(previous[r['path']][k]==r[k] for k in ('path','bytes','sha256'))}
        needed=sum(r['bytes'] for r in rows if r['path'] not in unchanged)+max(1024**2,len(rows)*1024)
        if (self.root/'Agent/hardware_profiles.json').exists():
            require_space(self.root,needed,for_outputs=True)
        generation=uuid.uuid4().hex;folder=_contained(self.root,self.vault/generation);folder.mkdir(parents=True)
        value={'format':'portalai-plaintext-v1','version':1,'user_id':self.uid,'generation':generation,'files':[]}
        for row in rows:
            if row['path'] in unchanged:
                value['files'].append(dict(unchanged[row['path']]));continue
            blob=uuid.uuid4().hex+'.data'
            if self._copy(self.workspace/row['path'],folder/blob)!=(row['bytes'],row['sha256']):
                raise RuntimeError('Plaintext workspace changed while copying')
            value['files'].append({**row,'blob':blob,'blob_generation':generation})
        if self.inventory()!=rows:raise RuntimeError('Plaintext workspace changed during snapshot')
        if len(json.dumps(value).encode())>MAX_MANIFEST:raise ValueError('Plaintext manifest exceeds limit')
        atomic_json(folder/'manifest.json',value);self.verify(generation)
        atomic_json(self.pointer,{'format':'portalai-plaintext-v1','user_id':self.uid,'generation':generation})
        return {'verified':True,'generation':generation,'files':len(rows),'bytes':sum(r['bytes'] for r in rows),'encrypted_files':0,'reused_files':len(unchanged),'encrypted':False}

    @exclusive
    def seal(self,*,writers_stopped=False):
        if writers_stopped is not True:raise RuntimeError('Verified writer shutdown is required')
        self._key();self._hydration();journal=_contained(self.root,self.base/'seal-pending.json')
        if journal.exists():
            state=json.loads(journal.read_text(encoding='utf-8'))
            if state.get('user_id')!=self.uid:raise ValueError('Plaintext close identity mismatch')
            value=self.verify(state['generation'])
            expected=[{k:r[k] for k in ('path','bytes','sha256')} for r in value['files']]
            if self.inventory()!=expected:raise RuntimeError('Plaintext files changed during pending close')
            generation=value['generation']
        else:generation=self.snapshot()['generation']
        atomic_json(self.base/'plain-closed.json',{'user_id':self.uid,'generation':generation,'encrypted':False})
        if journal.exists():journal.unlink();_fsync_dir(self.base)
        # "sealed" remains the legacy lifecycle-completion field. encrypted is
        # explicitly false: plaintext has NOT been erased or encrypted.
        return {'sealed':True,'encrypted':False,'plaintext_retained':True,'generation':generation,'user_id':self.uid}

    def closed_verified(self,receipt):
        if receipt.get('sealed') is not True or receipt.get('encrypted') is not False:return False
        value=self.verify(receipt['generation'])
        return self.inventory()==[{k:r[k] for k in ('path','bytes','sha256')} for r in value['files']]

    @exclusive
    def restore(self,*,lazy=False):
        self._key();self._hydration()
        if (self.base/'seal-pending.json').exists():raise RuntimeError('Finish pending plaintext close first')
        # Live plaintext is authoritative, including intentional external edits.
        # Never restore deleted files silently or overwrite newer user changes.
        self.inventory()
        if not self.pointer.exists():self.snapshot()
        else:self.manifest()
        return {'ready':True,'user_id':self.uid,'encrypted':False,'pending_files':0}

    def recover_for_seal(self,*,writers_stopped=False):return self.seal(writers_stopped=writers_stopped)

    def pending(self):self._key();self._hydration();return []

    def materialize(self,relative=None,recursive=False,check=None):
        self._key();self._hydration()
        if relative is not None:_contained(self.root,self.workspace/_relative(relative))
        if callable(check):check()
        return {'materialized':0,'pending_files':0}
