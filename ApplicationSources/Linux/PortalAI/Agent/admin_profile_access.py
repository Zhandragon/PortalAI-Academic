"""Administrator read/export of a sealed profile without opening its workspace.

Exports are explicitly selected plaintext copies. Keys and authenticated sessions
remain process-local; target profiles are never activated or mounted by this API.
"""
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import zipfile

from local_accounts import LocalAccounts, Session, AuthorizationError
from profile_paths import _contained
from profile_workspace import ProfileWorkspace, _crypto, MAGIC, CHUNK


@contextmanager
def _sealed(accounts, admin, target_user_id):
    if not isinstance(accounts, LocalAccounts) or not isinstance(admin, Session):
        raise AuthorizationError('A trusted administrator account is required')
    with accounts._lock(): accounts._validate(admin, accounts._read(), admin=True)
    delegated = accounts.profile_session(admin,target_user_id)
    try:
        store = ProfileWorkspace(accounts.root,delegated)
        with store.transaction():
            if store.inventory() or any((store.base/name).exists() for name in
                    ('seal-pending.json','restore-pending.json','restore-inflight.enc','harvest-pending.json','hydration.enc')):
                raise RuntimeError('Recover and seal this profile before administrator inspection or export')
            pointer = store.vault/'current.enc'
            if not pointer.exists():
                if store.vault.exists() and any(store.vault.iterdir()):
                    raise RuntimeError('Encrypted profile pointer is missing; recovery is required')
                manifest = {'generation':None,'files':[]}
            else:
                manifest = store.manifest()
            yield store, manifest, delegated
    finally:
        accounts.logout(delegated)


def _stream_file(store, manifest, row, destination):
    """Decrypt bounded chunks into a caller-selected stream, then verify GCM/hash."""
    source = store.blob_path(manifest, row)
    info = source.stat(); overhead = len(MAGIC)+28
    if info.st_nlink != 1 or info.st_size != row['bytes']+overhead:
        raise ValueError('Encrypted profile entry size or ownership is invalid')
    Cipher, algorithms, modes, _ = _crypto()
    hasher = hashlib.sha256(); count = 0
    with source.open('rb') as stream:
        if stream.read(len(MAGIC)) != MAGIC: raise ValueError('Unsupported profile entry')
        nonce = stream.read(12); stream.seek(-16,os.SEEK_END); tag = stream.read(16)
        stream.seek(len(MAGIC)+12)
        decryptor = Cipher(algorithms.AES(store._key()),modes.GCM(nonce,tag)).decryptor()
        decryptor.authenticate_additional_data(store._aad(row['path']))
        remaining = row['bytes']
        while remaining:
            store._key()  # Revalidate the authorizing admin after logout/revocation.
            block = stream.read(min(CHUNK,remaining))
            if not block: raise ValueError('Truncated encrypted profile entry')
            remaining -= len(block); plain = decryptor.update(block)
            hasher.update(plain); count += len(plain); destination.write(plain)
        last = decryptor.finalize(); destination.write(last); hasher.update(last); count += len(last)
    if (count,hasher.hexdigest()) != (row['bytes'],row['sha256']):
        raise ValueError('Profile content does not match its authenticated manifest')
    store._key()


def inspect_profile(accounts, admin, target_user_id):
    """Return authenticated snapshot metadata; payload hashes verify on read/export."""
    with _sealed(accounts,admin,target_user_id) as (store,manifest,delegated):
        rows = [{key:row[key] for key in ('path','bytes','sha256')} for row in manifest['files']]
        return {'verified_manifest':True,'user_id':delegated.user_id,'username':delegated.username,
                'generation':manifest['generation'],'state':'sealed snapshot','files':rows,
                'bytes':sum(row['bytes'] for row in rows)}


def preview_text(accounts, admin, target_user_id, relative, *, max_bytes=65536):
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1024**2:
        raise ValueError('Text preview limit must be between 1 byte and 1 MiB')
    with _sealed(accounts,admin,target_user_id) as (store,manifest,delegated):
        row = next((row for row in manifest['files'] if row['path'] == relative),None)
        if row is None: raise FileNotFoundError(relative)
        if row['bytes'] > max_bytes: raise ValueError('This file exceeds the bounded text preview; export it explicitly')
        stream = io.BytesIO(); _stream_file(store,manifest,row,stream)
        text = stream.getvalue().decode('utf-8')
        if '\0' in text: raise ValueError('Binary files require an explicit export')
        return {'verified':True,'user_id':delegated.user_id,'path':row['path'],'text':text,'bytes':row['bytes']}


def export_profile(accounts, admin, target_user_id, kind, destination):
    """Create and re-read a new plaintext ZIP; never replace another file."""
    if kind not in ('history','outputs','all'): raise ValueError('Unknown profile export selection')
    destination = Path(destination).absolute()
    from native_export_grants import permitted,finish
    native=permitted(accounts.root,admin,destination)
    if (destination.resolve().is_relative_to(accounts.root/'Private') and not native) or destination.exists():
        raise ValueError('Choose a new plaintext export outside Private account storage')
    if not destination.parent.is_dir(): raise ValueError('Choose an existing export directory')
    with _sealed(accounts,admin,target_user_id) as (store,manifest,delegated):
        prefixes = ('Data/Chat/','Data/Memory/') if kind == 'history' else ('Outputs/','User Folder/','Benchmarks/','Patch/Videos/')
        rows = [row for row in manifest['files'] if kind == 'all' or row['path'].startswith(prefixes)]
        if native:permitted(accounts.root,admin,destination,sum(row['bytes'] for row in rows)+len(rows)*2048+4096)
        needed = sum(row['bytes'] for row in rows)+8*1024**2
        if destination.parent.stat().st_dev == accounts.root.stat().st_dev and (accounts.root/'Agent/hardware_profiles.json').exists():
            from runtime_policy import require_space
            require_space(accounts.root,needed,for_outputs=True)
        elif shutil.disk_usage(destination.parent).free < needed+64*1024**2:
            raise RuntimeError('Export destination has insufficient free space')
        created_identity = None
        try:
            with destination.open('xb') as output:
                info = os.fstat(output.fileno()); created_identity = (info.st_dev,info.st_ino)
                with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
                    for row in rows:
                        with archive.open(row['path'],'w',force_zip64=True) as member:
                            _stream_file(store,manifest,row,member)
                    metadata = {'version':1,'user_id':delegated.user_id,'kind':kind,'generation':manifest['generation'],
                                'files':[{key:row[key] for key in ('path','bytes','sha256')} for row in rows]}
                    archive.writestr('PortalAI-export-manifest.json',json.dumps(metadata,ensure_ascii=True))
                output.flush(); os.fsync(output.fileno())
            with zipfile.ZipFile(destination) as archive:
                if set(archive.namelist()) != {row['path'] for row in rows}|{'PortalAI-export-manifest.json'}:
                    raise RuntimeError('Export archive entries do not match their manifest')
                for row in rows:
                    store._key(); hasher = hashlib.sha256(); count = 0
                    with archive.open(row['path']) as member:
                        while block := member.read(CHUNK): hasher.update(block); count += len(block)
                    if (count,hasher.hexdigest()) != (row['bytes'],row['sha256']): raise RuntimeError('Export readback did not verify')
            store._key()
            return finish(accounts.root,admin,destination,{'verified':True,'path':str(destination),'files':len(rows),'bytes':sum(row['bytes'] for row in rows),
                    'user_id':delegated.user_id,'plaintext':True})
        except BaseException:
            if created_identity is not None and destination.exists():
                info = destination.stat()
                if not destination.is_symlink() and (info.st_dev,info.st_ino) == created_identity:
                    destination.unlink()
            raise
