"""Verified encrypted profile snapshots, independent of model/runtime directories.

Workspace files are plaintext while their account is in use. Sealing requires all
writers to have stopped. A crash leaves a recovery marker and must never allow a
different account to open before recovery; this is not filesystem/OS isolation.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import PurePosixPath
from portable_fs import Path, walk, raise_walk_error
import re
import secrets
import sys
import uuid
import threading
import time
from contextlib import contextmanager
from functools import wraps

from profile_paths import workspace_root, _contained, is_private
from profile_lazy_state import is_deferred_path
from runtime_policy import atomic_json, require_space

CHUNK = 1024 * 1024
MAGIC = b'PORTAL-PROFILE-1\n'
MAX_MANIFEST = 32 * 1024 * 1024
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()
_HELD = threading.local()


def exclusive(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        with self.transaction():
            return function(self, *args, **kwargs)
    return wrapped


def _crypto():
    # Dependencies are always loaded from the bundle that owns this module,
    # including when tests use isolated temporary profile roots.
    from local_accounts import _crypto as activate_crypto
    activate_crypto()  # Also checks interpreter and dependency origin.
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return Cipher, algorithms, modes, AESGCM


def digest(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def _relative(value):
    value = str(value)
    parts = PurePosixPath(value).parts
    if (not parts or '\\' in value or ':' in value or value.startswith('/') or
            '..' in parts or '.' in parts or not is_private(value)):
        raise ValueError('Invalid private workspace filename')
    return '/'.join(parts)


def _fsync_dir(path):
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
        try: os.fsync(fd)
        finally: os.close(fd)


def _atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(data); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path); _fsync_dir(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class ProfileWorkspace:
    def __init__(self, root, session, *, on_progress=None):
        self.root = Path(root).resolve()
        self.session = session
        self.uid = session.user_id
        self.workspace = workspace_root(self.root, self.uid)
        self.base = self.workspace.parent
        self.vault = self.base / 'Vault'
        self.on_progress = on_progress
        self._progress_stage = None
        self._progress_time = 0.0
        _contained(self.root, self.vault)

    def _progress(self, stage, message, *, completed=None, total=None):
        """Presentation gets only aggregate counts, never filenames or keys."""
        callback = self.on_progress
        if not callable(callback): return
        now = time.monotonic()
        if (stage == self._progress_stage and completed not in (0, total)
                and now-self._progress_time < .1): return
        self._progress_stage, self._progress_time = stage, now
        event = {'stage': stage, 'message': message}
        if completed is not None: event['completed'] = completed
        if total is not None: event['total'] = total
        try: callback(event)
        except Exception: pass  # A broken progress display grants no authority.

    @contextmanager
    def transaction(self):
        """Serialize mutations across threads, instances and recipient processes."""
        identity = os.path.normcase(str(self.base))
        with _LOCKS_GUARD:
            lock = _LOCKS.setdefault(identity, threading.RLock())
        with lock:
            held = getattr(_HELD, 'profiles', set())
            if identity in held:
                yield
                return
            from mission_runner import process_lock
            path = self.base / 'workspace.lock'
            _contained(self.root, path)
            with process_lock(path):
                _HELD.profiles = held | {identity}
                try: yield
                finally: _HELD.profiles = held

    def _key(self):
        key = self.session.profile_key
        if not isinstance(key, bytes) or len(key) != 32:
            raise PermissionError('A valid unlocked profile key is required')
        return key

    def _aad(self, relative):
        return ('PortalAI-profile-v1\0' + self.uid + '\0' + relative).encode('utf-8')

    def inventory(self):
        _contained(self.root, self.workspace)
        self.root.stat()  # A missing/disconnected drive is never an empty profile.
        rows = []
        if not self.workspace.exists(): return rows
        # walk without following any link; links and hard-linked files must be
        # reviewed, not silently copied or removed as private profile data.
        for directory, names, files in walk(self.workspace, followlinks=False, onerror=raise_walk_error):
            for name in names + files:
                _contained(self.root, Path(directory) / name)
            for name in files:
                path = Path(directory) / name
                stat = path.stat()
                if not path.is_file() or stat.st_nlink != 1:
                    raise ValueError('Linked or nonregular workspace files need manual review')
                relative = _relative(path.relative_to(self.workspace).as_posix())
                rows.append({'path': relative, 'bytes': stat.st_size, 'sha256': digest(path)})
        self.root.stat()
        return sorted(rows, key=lambda row: row['path'])

    def _encrypt_file(self, source, target, relative, key):
        Cipher, algorithms, modes, _ = _crypto()
        nonce = secrets.token_bytes(12)
        encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
        encryptor.authenticate_additional_data(self._aad(relative))
        hasher = hashlib.sha256(); count = 0
        with source.open('rb') as src, target.open('xb') as dst:
            dst.write(MAGIC + nonce)
            while block := src.read(CHUNK):
                # Hash the exact bytes entering encryption, not a later read of
                # a source that may have changed in the meantime.
                hasher.update(block); count += len(block)
                dst.write(encryptor.update(block))
            dst.write(encryptor.finalize()); dst.write(encryptor.tag)
            dst.flush(); os.fsync(dst.fileno())
        return count, hasher.hexdigest()

    def _decrypt_file(self, source, relative, key, target=None, *, created=None):
        Cipher, algorithms, modes, _ = _crypto()
        minimum = len(MAGIC) + 12 + 16
        size = source.stat().st_size
        if size < minimum: raise ValueError('Truncated encrypted profile file')
        hasher = hashlib.sha256(); count = 0
        destination = target.open('xb') if target is not None else None
        try:
            if destination is not None and callable(created): created(destination)
            with source.open('rb') as src:
                if src.read(len(MAGIC)) != MAGIC: raise ValueError('Unsupported profile file format')
                nonce = src.read(12)
                src.seek(-16, os.SEEK_END); tag = src.read(16)
                src.seek(len(MAGIC) + 12)
                decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
                decryptor.authenticate_additional_data(self._aad(relative))
                remaining = size - minimum
                while remaining:
                    block = src.read(min(CHUNK, remaining))
                    if not block: raise ValueError('Truncated encrypted profile file')
                    remaining -= len(block)
                    plain = decryptor.update(block)
                    hasher.update(plain); count += len(plain)
                    if destination is not None: destination.write(plain)
                last = decryptor.finalize()
                hasher.update(last); count += len(last)
                if destination is not None:
                    destination.write(last); destination.flush(); os.fsync(destination.fileno())
            return count, hasher.hexdigest()
        finally:
            if destination is not None: destination.close()

    @exclusive
    def snapshot(self):
        """Non-destructive, byte-verified recovery copy. Never deletes input files."""
        if _contained(self.root,self.base/'seal-pending.json').exists():
            raise RuntimeError('Interrupted sealing must finish before another snapshot')
        if _contained(self.root,self.base/'restore-inflight.enc').exists():
            raise RuntimeError('Interrupted restoration must finish before another snapshot')
        key = self._key()
        hydration = self._hydration()
        if hydration is not None: hydration.recover()
        rows = self._snapshot_inventory(hydration)
        previous = {}
        if (self.vault/'current.enc').exists():
            current=self.manifest()
            previous = {row['path']: (current, row) for row in current['files']}
            saved=[{name:row[name] for name in ('path','bytes','sha256')} for row in current['files']]
            if rows==saved:
                # Logging in and out without changes must not duplicate every
                # video and old recovery archive. Authenticate all saved bytes
                # before reusing the current generation, then recheck writers.
                self.verify(current['generation'])
                if self._snapshot_inventory(hydration)!=rows:raise RuntimeError('Workspace changed during snapshot verification')
                return {'verified':True,'generation':current['generation'],'files':len(rows),
                        'bytes':sum(row['bytes'] for row in rows),'reused':True,
                        'encrypted_files':0,'reused_files':len(rows)}
        if hydration is not None:
            for row in hydration.pending():
                previous[row['path']] = (hydration.manifest, row)
        unchanged = {}
        for row in rows:
            candidate = previous.get(row['path'])
            if candidate and all(candidate[1][name] == row[name] for name in ('path','bytes','sha256')):
                unchanged[row['path']] = candidate
        # Keep space for original workspace, new encrypted snapshot, and the
        # existing recoverable snapshot. Never prune generations implicitly.
        if (self.root / 'Agent/hardware_profiles.json').exists():
            require_space(self.root, sum(row['bytes'] for row in rows if row['path'] not in unchanged) +
                          max(1024**2, len(rows)*1024), for_outputs=True)
        generation = uuid.uuid4().hex
        folder = self.vault / generation
        _contained(self.root, folder); folder.mkdir(parents=True)
        manifest = {'version': 2, 'user_id': self.uid, 'generation': generation, 'files': []}
        encrypted = 0
        for row in rows:
            if row['path'] in unchanged:
                old_manifest, old = unchanged[row['path']]
                # Immutable same-profile references, never hard links. verify()
                # authenticates every reused ciphertext before pointer commit.
                self.blob_path(old_manifest, old)
                manifest['files'].append({**row, 'blob':old['blob'],
                    'blob_generation':old.get('blob_generation',old_manifest['generation'])
                        if old_manifest['version']==2 else old_manifest['generation']})
                continue
            source = self.workspace / row['path']
            _contained(self.root, source)
            blob = uuid.uuid4().hex + '.enc'
            size, sha = self._encrypt_file(source, folder / blob, row['path'], key)
            if (size, sha) != (row['bytes'], row['sha256']):
                raise RuntimeError('Workspace changed while creating its recovery copy')
            manifest['files'].append({**row, 'blob': blob, 'blob_generation':generation})
            encrypted += 1
        if self._snapshot_inventory(hydration) != rows:
            raise RuntimeError('Workspace changed while creating its recovery copy')
        _, _, _, AESGCM = _crypto()
        nonce = secrets.token_bytes(12)
        payload = json.dumps(manifest, ensure_ascii=True, separators=(',', ':')).encode()
        if len(payload) > MAX_MANIFEST: raise ValueError('Profile manifest exceeds limit')
        _atomic_bytes(folder / 'manifest.enc', nonce + AESGCM(key).encrypt(nonce, payload, self._aad('manifest')))
        # Authenticate generation pointer; a swapped/truncated pointer fails closed.
        pointer_nonce = secrets.token_bytes(12)
        pointer = pointer_nonce + AESGCM(key).encrypt(pointer_nonce, generation.encode(), self._aad('current'))
        # Independently reread and authenticate every encrypted blob before
        # publishing the pointer. The streaming check above avoids another
        # immediate decrypt/source reread without weakening this commit gate.
        self.verify(generation)
        _atomic_bytes(self.vault / 'current.enc', pointer)
        return {'verified': True, 'generation': generation, 'files': len(rows), 'bytes': sum(row['bytes'] for row in rows),
                'encrypted_files':encrypted, 'reused_files':len(rows)-encrypted}

    def _blob_reference(self, manifest, row):
        """Validate authenticated metadata without touching unrelated blobs."""
        if manifest.get('user_id') != self.uid or manifest.get('version') not in (1,2):
            raise ValueError('Encrypted blob manifest identity is invalid')
        own_generation = manifest.get('generation')
        generation = row.get('blob_generation') if manifest['version']==2 else own_generation
        if (not isinstance(own_generation,str) or not re.fullmatch('[a-f0-9]{32}',own_generation) or
                not isinstance(generation,str) or not re.fullmatch('[a-f0-9]{32}',generation) or
                not isinstance(row.get('blob'),str) or not re.fullmatch('[a-f0-9]{32}\\.enc',row['blob'])):
            raise ValueError('Invalid encrypted blob reference')
        return generation, row['blob']

    def blob_path(self, manifest, row):
        """Resolve v1/v2 immutable ciphertext only within this profile's vault."""
        generation, blob = self._blob_reference(manifest,row)
        return _contained(self.root,self.vault/generation/blob)

    def _hydration(self):
        from profile_lazy_state import HydrationState
        path = _contained(self.root,self.base/'hydration.enc')
        return HydrationState(self) if path.exists() else None

    def _snapshot_inventory(self, hydration):
        present = self.inventory()
        if hydration is None: return present
        if not hydration.ready: hydration.verify_initial_inventory()
        hydration.observe(present)
        combined = {row['path']:row for row in present}
        for row in hydration.pending():
            combined.setdefault(row['path'],{name:row[name] for name in ('path','bytes','sha256')})
        return sorted(combined.values(),key=lambda row:row['path'])

    @exclusive
    def pending(self):
        """Authenticated metadata for the controller; never a plaintext ledger."""
        self._key()
        hydration = self._hydration()
        rows = hydration.pending() if hydration is not None else []
        return {'active':hydration is not None,
                'generation':hydration.manifest['generation'] if hydration is not None else None,
                'files':len(rows),'bytes':sum(row['bytes'] for row in rows),
                'paths':[row['path'] for row in rows]}

    @exclusive
    def materialize(self, relative=None, recursive=False, check=None):
        """Authenticate requested dormant files; deleted hydrated files stay deleted."""
        self._key()
        if _contained(self.root,self.base/'seal-pending.json').exists():
            raise RuntimeError('Interrupted sealing must finish before file restoration')
        if callable(check): check()
        hydration = self._hydration()
        if hydration is None:
            if callable(check): check()
            return {'ready':True,'user_id':self.uid,'materialized':0,'pending_files':0}
        hydration.recover()
        if not hydration.ready:
            raise RuntimeError('Initial lazy restore must finish before on-demand restoration')
        if relative is not None:
            relative = _relative(relative)
        normalize = str.casefold if os.name=='nt' else lambda value:value
        requested = normalize(relative) if relative is not None else None
        rows = [row for row in hydration.pending() if requested is None or normalize(row['path'])==requested or
                (recursive and normalize(row['path']).startswith(requested+'/'))]
        if (self.root/'Agent/hardware_profiles.json').exists():
            require_space(self.root,sum(row['bytes'] for row in rows)+1024**2,for_outputs=True)
        count = hydration.materialize(rows,check=check)
        if callable(check): check()
        return {'ready':True,'user_id':self.uid,'materialized':count,'pending_files':len(hydration.pending())}

    def manifest(self, generation=None):
        key = self._key(); _, _, _, AESGCM = _crypto()
        if generation is None:
            pointer = self.vault / 'current.enc'
            _contained(self.root, pointer)
            data = pointer.read_bytes()
            if not 28 <= len(data) <= 512: raise ValueError('Invalid encrypted profile pointer')
            generation = AESGCM(key).decrypt(data[:12], data[12:], self._aad('current')).decode('ascii')
        if not re.fullmatch('[a-f0-9]{32}', generation): raise ValueError('Invalid snapshot generation')
        path = self.vault / generation / 'manifest.enc'
        _contained(self.root, path)
        if path.stat().st_size > MAX_MANIFEST + 28: raise ValueError('Oversized profile manifest')
        data = path.read_bytes()
        manifest = json.loads(AESGCM(key).decrypt(data[:12], data[12:], self._aad('manifest')))
        if manifest.get('version') not in (1,2) or manifest.get('user_id') != self.uid or manifest.get('generation') != generation:
            raise ValueError('Profile identity does not match encrypted manifest')
        seen = set()
        for row in manifest['files']:
            relative = _relative(row['path'])
            if relative != row['path'] or relative.casefold() in seen or not re.fullmatch(r'[a-f0-9]{32}\.enc', row['blob']):
                raise ValueError('Invalid or duplicate encrypted profile entry')
            seen.add(relative.casefold())
            self._blob_reference(manifest,row)
            if (not isinstance(row['bytes'], int) or row['bytes'] < 0 or
                    not re.fullmatch('[a-f0-9]{64}', row['sha256'])):
                raise ValueError('Invalid profile content metadata')
        return manifest

    def verify(self, generation=None):
        key = self._key(); manifest = self.manifest(generation)
        total = len(manifest['files'])
        self._progress('restore-verify', 'Verifying encrypted recovery files...', completed=0, total=total)
        for index, row in enumerate(manifest['files'], 1):
            path = self.blob_path(manifest,row)
            size, sha = self._decrypt_file(path, row['path'], key)
            if (size, sha) != (row['bytes'], row['sha256']):
                raise ValueError('Encrypted profile content does not match its manifest')
            self._progress('restore-verify', 'Verifying encrypted recovery files...', completed=index, total=total)
        return manifest

    @exclusive
    def seal(self, *, writers_stopped=False):
        """Remove only verified workspace plaintext, after a caller-owned stop gate.

        A failed/partial seal keeps its encrypted snapshot and journal. Callers
        must not grant a new login until the same profile is fully sealed.
        """
        if writers_stopped is not True:
            raise RuntimeError('Stop and verify every profile writer before sealing')
        hydration = self._hydration()
        if hydration is not None: hydration.recover()
        journal = self.base / 'seal-pending.json'
        _contained(self.root, journal)
        if journal.exists():
            state = json.loads(journal.read_text(encoding='utf-8'))
            if state.get('user_id') != self.uid: raise ValueError('Seal recovery identity mismatch')
            manifest = self.verify(state['generation'])
            result = {'verified': True, 'generation': manifest['generation'], 'files': len(manifest['files']),
                      'bytes': sum(row['bytes'] for row in manifest['files'])}
            allowed = {row['path']: row for row in manifest['files']}
            for row in self.inventory():
                if row != {key: allowed.get(row['path'], {}).get(key) for key in ('path', 'bytes', 'sha256')}:
                    raise RuntimeError('New or changed files prevent interrupted-seal recovery')
        else:
            result = self.snapshot()
            manifest = self.verify(result['generation'])
            atomic_json(journal, {'version': 1, 'generation': result['generation'], 'user_id': self.uid})
        for row in manifest['files']:
            path = self.workspace / row['path']; _contained(self.root, path)
            if not path.exists(): continue  # Already removed before an interrupted seal.
            if path.stat().st_nlink != 1 or digest(path) != row['sha256']:
                raise RuntimeError('A file changed after the encrypted recovery copy was verified')
            path.unlink()
        if self.inventory(): raise RuntimeError('A writer created new files while sealing')
        # Empty directory names may also contain user-chosen labels. Remove
        # only empty directories inside this exact verified workspace.
        directories = (walk(self.workspace, topdown=False, followlinks=False, onerror=raise_walk_error)
                       if self.workspace.exists() else ())
        for directory, names, _ in directories:
            for name in names:
                path=_contained(self.root,Path(directory)/name)
                try:
                    before=path.stat(follow_symlinks=False)
                    try:path.rmdir()
                    except PermissionError:
                        # Lazy import avoids the workspace/migration module cycle.
                        # Only the same verified empty directory's Windows
                        # READONLY bit may change; no ACL changes or broad chmod.
                        from profile_migration import _windows_clear_readonly_empty_directory
                        if not _windows_clear_readonly_empty_directory(self.root,path,before):
                            raise
                        _contained(self.root,path)
                        path.rmdir()
                except OSError:
                    raise RuntimeError('A directory changed while sealing; recovery remains pending') from None
        if hydration is not None:
            _contained(self.root,hydration.path); hydration.path.unlink()
        journal.unlink(); _fsync_dir(self.base)
        return {**result, 'sealed': True}

    def _save_restore_intent(self, manifest, relative, temporary, identity=None):
        """Authenticate the exact temporary file before writing any plaintext."""
        _, _, _, AESGCM = _crypto()
        value = {'version': 1, 'generation': manifest['generation'], 'path': relative,
                 'temporary': temporary.relative_to(self.workspace).as_posix(), 'identity': identity}
        payload = json.dumps(value).encode()
        if len(payload) > 1024**2: raise ValueError('Oversized restore intent')
        nonce = secrets.token_bytes(12)
        path = _contained(self.root, self.base/'restore-inflight.enc')
        _atomic_bytes(path, nonce+AESGCM(self._key()).encrypt(
            nonce, payload, self._aad('restore-inflight')))

    def _recover_restore_intent(self, manifest):
        """Reconcile an interrupted eager restore without adopting arbitrary .part files."""
        import stat
        intent_path = _contained(self.root, self.base/'restore-inflight.enc')
        if not intent_path.exists(): return
        if intent_path.stat().st_size > 1024**2+28: raise ValueError('Oversized restore intent')
        raw = intent_path.read_bytes()
        _, _, _, AESGCM = _crypto()
        value = json.loads(AESGCM(self._key()).decrypt(raw[:12], raw[12:], self._aad('restore-inflight')))
        row = next((row for row in manifest['files'] if row['path'] == value.get('path')), None)
        if value.get('version') != 1 or value.get('generation') != manifest['generation'] or row is None:
            raise ValueError('Restore intent does not match its authenticated generation')
        name = value.get('temporary')
        if not isinstance(name, str) or not re.fullmatch(re.escape(row['path'])+r'\.[a-f0-9]{32}\.part', name):
            raise ValueError('Invalid restore temporary filename')
        identity = value.get('identity')
        if identity is not None and (not isinstance(identity, list) or len(identity) != 2 or
                                    any(type(v) is not int or v < 0 for v in identity)):
            raise ValueError('Invalid restore temporary identity')
        temporary = _contained(self.root, self.workspace/name)
        target = _contained(self.root, self.workspace/row['path'])
        for path in (target, temporary):
            if not path.exists(): continue
            info = path.stat(follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                (identity is None and (path == target or info.st_size != 0)) or
                (identity is not None and [info.st_dev, info.st_ino] != identity)):
                raise ValueError('Restore file identity changed; explicit recovery is required')
            if path == target:
                if (info.st_size, digest(path)) != (row['bytes'], row['sha256']):
                    raise ValueError('Restored file changed before recovery')
            else:
                path.unlink(); _fsync_dir(path.parent)
        self.root.stat()
        intent_path.unlink(); _fsync_dir(self.base)

    @exclusive
    def recover_for_seal(self, *, writers_stopped=False):
        """Keep untouched recovery files encrypted instead of restoring to delete.

        Authenticate the complete generation and every existing plaintext file.
        The ordinary hydration ledger preserves all unmaterialized files during
        snapshot/seal; no format change, skipped verification or dropped file.
        """
        if writers_stopped is not True:
            raise RuntimeError('Verified writer shutdown is required before recovery for sealing')
        self._key()
        journal = _contained(self.root, self.base/'restore-pending.json')
        intent = _contained(self.root, self.base/'restore-inflight.enc')
        hydration = self._hydration()
        if journal.exists():
            if journal.stat().st_size > 16384:
                raise ValueError('Oversized restore recovery journal')
            state = json.loads(journal.read_text(encoding='utf-8'))
            if state.get('version') != 1 or state.get('user_id') != self.uid:
                raise ValueError('Restore recovery identity mismatch')
            manifest = self.verify(state['generation'])
        else:
            if intent.exists():
                raise RuntimeError('Restore journal is missing; explicit verified recovery is required')
            if hydration is not None or self.inventory():
                raise RuntimeError('Sealed recovery staging requires an empty workspace')
            manifest = self.verify()
        if hydration is not None:
            # A crash can leave both journals after the authenticated ledger is
            # durable but before the old journal is removed. Accept only that
            # exact transition; never merge different generations or intents.
            if (hydration.manifest['generation'] != manifest['generation'] or
                    hydration.inflight is not None or intent.exists()):
                raise ValueError('Hydration and eager recovery journals do not match')
            hydration.verify_initial_inventory()
        else:
            self._recover_restore_intent(manifest)
            present = self.inventory()
            expected = {row['path']: {k: row[k] for k in ('path','bytes','sha256')}
                        for row in manifest['files']}
            if any(row != expected.get(row['path']) for row in present):
                raise RuntimeError('Unexpected workspace files prevent restore recovery')
            from profile_lazy_state import HydrationState
            hydration = HydrationState(self, manifest=manifest)
            for row in present:
                hydration.mark(row['path'])
            hydration.verify_initial_inventory()
            # Closing is still the authoritative runtime state. Mark this
            # verified partial inventory ready so subsequent crash-log harvest
            # can add legitimate files before snapshot/seal. No UI opens here.
            hydration.ready = True
            # This durable authenticated bitmap is committed before retiring
            # the eager journal. Existing plaintext remains untouched.
            hydration.save()
            hydration.verify_initial_inventory()
        if not hydration.ready:
            hydration.ready = True
            hydration.save()
        if journal.exists():
            journal.unlink(); _fsync_dir(self.base)
        return {'verified': True, 'generation': manifest['generation'],
                'materialized_files': len(hydration.materialized),
                'kept_encrypted_files': len(hydration.pending()),
                'restored_bytes': 0}

    @exclusive
    def restore(self, *, lazy=False):
        """Restore a verified snapshot only into an empty, unlinked workspace."""
        if (self.base / 'seal-pending.json').exists():
            raise RuntimeError('Interrupted sealing requires owner/admin recovery first')
        if (self.base/'restore-inflight.enc').exists() and not (self.base/'restore-pending.json').exists():
            raise RuntimeError('Restore journal is missing; explicit verified recovery is required')
        hydration = self._hydration()
        if hydration is not None:
            hydration.recover()
            if not hydration.ready:
                # Recovery authenticates even already-published ciphertext;
                # existing plaintext must never hide a damaged vault blob.
                self.verify(hydration.manifest['generation'])
                hydration.verify_initial_inventory()
            return self._restore_hydration(hydration,lazy=lazy)
        if lazy and not (self.base/'restore-pending.json').exists():
            from profile_lazy_state import HydrationState
            self._key()
            if self.inventory(): raise RuntimeError('Existing plaintext workspace requires owner/admin recovery')
            manifest = self.manifest()
            hydration = HydrationState(self,manifest=manifest)
            hydration.save()  # Durable authenticated intent before any plaintext.
            return self._restore_hydration(hydration,lazy=True)
        key = self._key()
        journal = self.base / 'restore-pending.json'
        _contained(self.root, journal)
        self._progress('restore-check', 'Checking the authenticated workspace snapshot...')
        resuming = journal.exists()
        if resuming:
            state = json.loads(journal.read_text(encoding='utf-8'))
            if state.get('user_id') != self.uid: raise ValueError('Restore recovery identity mismatch')
            manifest = self.verify(state['generation'])
            self._recover_restore_intent(manifest)
        else:
            if (self.base/'restore-inflight.enc').exists():
                raise RuntimeError('Restore journal is missing; explicit verified recovery is required')
            if self.inventory(): raise RuntimeError('Existing plaintext workspace requires owner/admin recovery')
            # A fresh restore authenticates the manifest here and every blob
            # while writing its temporary output below. Decrypting every blob
            # twice adds avoidable SSD work. Interrupted restores retain full
            # verification above, including blobs whose plaintext already exists.
            manifest = self.manifest()
        expected = {row['path']: row for row in manifest['files']}
        existing = self.inventory()
        if existing and not resuming:
            raise RuntimeError('Another writer created workspace files before restore')
        for row in existing:
            if row != {key: expected.get(row['path'], {}).get(key) for key in ('path', 'bytes', 'sha256')}:
                raise RuntimeError('Unexpected workspace files prevent restore recovery')
        if (self.root / 'Agent/hardware_profiles.json').exists():
            require_space(self.root, sum(row['bytes'] for row in manifest['files']), for_outputs=True)
        atomic_json(journal, {'version': 1, 'user_id': self.uid, 'generation': manifest['generation']})
        restored = {row['path'] for row in existing}
        total = len(manifest['files'])
        self._progress('restore', 'Restoring and authenticating account files...', completed=0, total=total)
        for index, row in enumerate(manifest['files'], 1):
            path = self.workspace / row['path']; _contained(self.root, path)
            if path.exists():
                if row['path'] not in restored:
                    raise FileExistsError('Another writer created a workspace file during restore')
                self._progress('restore', 'Restoring and authenticating account files...', completed=index, total=total)
                continue  # Verified above; preserve already-restored bytes.
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.part')
            self._save_restore_intent(manifest, row['path'], temporary)
            def created(handle):
                info = os.fstat(handle.fileno())
                self._save_restore_intent(manifest, row['path'], temporary, [info.st_dev, info.st_ino])
            try:
                source = self.blob_path(manifest,row)
                size, sha = self._decrypt_file(source, row['path'], key, temporary, created=created)
                if (size, sha) != (row['bytes'], row['sha256']): raise ValueError('Profile restore verification failed')
                if path.exists(): raise FileExistsError('Another writer created a workspace file during restore')
                from profile_lazy_state import publish_no_replace
                publish_no_replace(temporary, path); _fsync_dir(path.parent)
                # The stream and final inventory authenticate normal restoration;
                # reread the individual published file only on interrupted recovery.
                _contained(self.root, self.base/'restore-inflight.enc').unlink()
                _fsync_dir(self.base)
            finally:
                self._recover_restore_intent(manifest)
            self._progress('restore', 'Restoring and authenticating account files...', completed=index, total=total)
        expected = [{key: row[key] for key in ('path', 'bytes', 'sha256')} for row in manifest['files']]
        self._progress('restore-final', 'Verifying the complete restored workspace...', completed=total, total=total)
        if self.inventory() != expected: raise RuntimeError('Restored profile failed final verification')
        journal.unlink(); _fsync_dir(self.base)
        return {'ready': True, 'user_id': self.uid, 'files': len(expected)}

    def _restore_hydration(self, hydration, *, lazy):
        # Old generations need one transcript-only pass to build the small history
        # catalog. Media stays dormant even on this first upgraded login.
        cataloged = 'Data/Chat/session_catalog.json' in hydration.rows
        rows = [row for row in hydration.pending() if not lazy or not is_deferred_path(row['path']) or
                (not cataloged and row['path'].startswith('Data/Chat/Sessions/'))]
        if (self.root/'Agent/hardware_profiles.json').exists():
            require_space(self.root,sum(row['bytes'] for row in rows)+1024**2,for_outputs=True)
        self._progress('restore','Restoring and authenticating account files...',completed=0,total=len(rows))
        hydration.materialize(rows)
        if not hydration.ready:
            self._progress('restore-final','Verifying the restored working files...',completed=len(rows),total=len(rows))
            hydration.verify_initial_inventory()
            hydration.ready = True
            hydration.save()
        return {'ready':True,'user_id':self.uid,'files':len(hydration.manifest['files']),
                'lazy':bool(lazy),'pending_files':len(hydration.pending())}

    @exclusive
    def file_names(self, relative, check=None, metadata=False):
        """Authenticated dormant names plus present files, without decrypting bodies."""
        self._key()
        relative = _relative(relative)
        if callable(check): check()
        hydration = self._hydration()
        if hydration is not None:
            hydration.recover()
            if not hydration.ready: raise RuntimeError('Initial restoration is incomplete')
        prefix = relative.rstrip('/') + '/'
        names = {row['path'] for row in hydration.pending()
                 if row['path'] == relative or row['path'].startswith(prefix)} if hydration else set()
        folder = _contained(self.root, self.workspace/relative)
        self.root.stat()
        if folder.is_file(): names.add(relative)
        elif folder.is_dir():
            for directory, dirs, files in walk(folder, followlinks=False, onerror=raise_walk_error):
                for name in dirs + files: _contained(self.root, Path(directory)/name)
                for name in files:
                    path = Path(directory)/name
                    if path.stat().st_nlink != 1: raise ValueError('Linked private file refused')
                    names.add(path.relative_to(self.workspace).as_posix())
        if callable(check): check()
        if metadata:
            return {'names': sorted(names), 'pending_hashes': {
                row['path']: row['sha256'] for row in hydration.pending() if row['path'] in names}
                if hydration else {}}
        return sorted(names)

    @exclusive
    def export_file(self, relative, destination):
        """Explicit single-file export; does not unlock another profile or overwrite."""
        relative = _relative(relative)
        destination = Path(destination).resolve()
        if destination.is_relative_to(self.root / 'Private'):
            raise ValueError('Choose an export destination outside private profile storage')
        if destination.exists(): raise FileExistsError('Export destination already exists')
        manifest = self.manifest()
        row = next((item for item in manifest['files'] if item['path'] == relative), None)
        if row is None: raise FileNotFoundError(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.part')
        try:
            size, sha = self._decrypt_file(self.blob_path(manifest,row), relative, self._key(), temporary)
            if (size, sha) != (row['bytes'], row['sha256']): raise ValueError('Export integrity failed')
            if destination.exists(): raise FileExistsError('Export destination already exists')
            # Exclusive creation avoids POSIX rename silently replacing a file
            # created after the initial check. No host file is overwritten.
            with temporary.open('rb') as source, destination.open('xb') as output:
                while block := source.read(CHUNK): output.write(block)
                output.flush(); os.fsync(output.fileno())
        finally:
            temporary.unlink(missing_ok=True)
        return {'exported': True, 'bytes': row['bytes']}
