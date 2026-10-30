"""Authenticated hydration bookkeeping; called under ProfileWorkspace's lock."""
from __future__ import annotations

import ctypes
import errno
import json
import os
from portable_fs import Path
import re
import secrets
import stat
import uuid

from profile_paths import _contained

DEFERRED_PREFIXES = ('Outputs', 'User Folder', 'Data/LegacyRecovery', 'Data/SessionRecovery',
                     'Data/Chat/Sessions', 'Data/Chat/Attachments', 'Data/Chat/Recordings',
                     'Data/Chat/Thumbnails','Data/Knowledge','Data/Workflows/Runs')


def is_deferred_path(relative):
    value = str(relative).replace('\\', '/').strip('/')
    # Full run histories are loaded on selection/execution; small policies,
    # Stop fences, indexes and memory remain available immediately.
    if re.fullmatch(r'Data/Missions/[a-f0-9]{32}/mission(?:\.previous)?\.json', value, re.I): return True
    if re.fullmatch(r'Data/Missions/Schedules/[a-f0-9]{32}\.json', value, re.I): return True
    return any(value.casefold() == prefix.casefold() or
               value.casefold().startswith(prefix.casefold() + '/') for prefix in DEFERRED_PREFIXES)


def publish_no_replace(source, destination):
    """Atomically publish without overwriting a late independent writer."""
    if os.name == 'nt':
        os.rename(source, destination)  # Windows rename refuses an existing target.
        return
    if os.name != 'posix':
        raise RuntimeError('Atomic exclusive hydration publication is unavailable')
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise RuntimeError('Linux renameat2 is required for exclusive hydration publication')
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError('Another writer created the hydration destination')
        raise OSError(error, os.strerror(error))


class HydrationState:
    def __init__(self, store, *, manifest=None):
        from profile_workspace import _crypto, MAX_MANIFEST
        self.store = store
        self.path = _contained(store.root, store.base/'hydration.enc')
        self.materialized = set()
        self.inflight = None
        self.ready = False
        self.mask = 0
        if manifest is None:
            if self.path.stat().st_size > MAX_MANIFEST + 28:
                raise ValueError('Oversized authenticated hydration state')
            raw = self.path.read_bytes()
            _, _, _, AESGCM = _crypto()
            value = json.loads(AESGCM(store._key()).decrypt(raw[:12], raw[12:], store._aad('hydration')))
            if value.get('version') != 1 or value.get('user_id') != store.uid:
                raise ValueError('Hydration identity mismatch')
            manifest = store.manifest(value['generation'])
            encoded = value.get('materialized', '')
            if (not isinstance(encoded, str) or not re.fullmatch('[0-9a-f]+', encoded) or
                    len(encoded) > max(1, (len(manifest['files'])+3)//4)):
                raise ValueError('Invalid hydration bitmap')
            mask = int(encoded, 16)
            if mask.bit_length() > len(manifest['files']):
                raise ValueError('Hydration bitmap exceeds its authenticated manifest')
            self.materialized = {row['path'] for index, row in enumerate(manifest['files']) if mask & (1 << index)}
            self.mask = mask
            self.ready = value.get('ready')
            if type(self.ready) is not bool:
                raise ValueError('Invalid hydration readiness state')
            self.inflight = value.get('inflight')
        self.manifest = manifest
        self.rows = {row['path']: row for row in manifest['files']}
        self.indices = {row['path']: index for index, row in enumerate(manifest['files'])}
        if self.inflight is not None:
            intent = self.inflight
            if not isinstance(intent, dict) or intent.get('path') not in self.rows:
                raise ValueError('Invalid hydration intent')
            relative = intent['path']
            temporary = intent.get('temporary')
            if not isinstance(temporary, str) or not re.fullmatch(re.escape(relative)+r'\.[a-f0-9]{32}\.part', temporary):
                raise ValueError('Invalid hydration temporary filename')
            identity = intent.get('identity')
            if identity is not None and (not isinstance(identity, list) or len(identity) != 2 or
                                         any(not isinstance(v, int) or v < 0 for v in identity)):
                raise ValueError('Invalid hydration temporary identity')

    def save(self):
        from profile_workspace import _atomic_bytes, _crypto, MAX_MANIFEST
        value = {'version': 1, 'user_id': self.store.uid,
                 'generation': self.manifest['generation'], 'materialized': format(self.mask, 'x'),
                 'ready': self.ready, 'inflight': self.inflight}
        data = json.dumps(value, separators=(',', ':'), ensure_ascii=True).encode()
        if len(data) > MAX_MANIFEST:
            raise ValueError('Hydration state exceeds its limit')
        _, _, _, AESGCM = _crypto()
        nonce = secrets.token_bytes(12)
        _contained(self.store.root, self.path)
        _atomic_bytes(self.path, nonce+AESGCM(self.store._key()).encrypt(nonce, data, self.store._aad('hydration')))

    def pending(self):
        return [row for row in self.manifest['files'] if row['path'] not in self.materialized]

    def mark(self, relative):
        self.materialized.add(relative)
        self.mask |= 1 << self.indices[relative]

    def verify_initial_inventory(self):
        """Before first readiness, missing published files are not user deletions."""
        expected = [{key: row[key] for key in ('path', 'bytes', 'sha256')}
                    for row in self.manifest['files'] if row['path'] in self.materialized]
        if self.store.inventory() != sorted(expected, key=lambda row: row['path']):
            raise RuntimeError('Restored profile failed final verification')

    def _regular(self, path):
        _contained(self.store.root, path)
        info = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Hydration recovery found a linked or nonregular file')
        return info

    def recover(self):
        """Reconcile only an authenticated in-flight attempt, never ordinary deletions."""
        if self.inflight is None:
            return
        from profile_workspace import digest, _fsync_dir
        intent = self.inflight
        row = self.rows[intent['path']]
        target = _contained(self.store.root, self.store.workspace/row['path'])
        temporary = _contained(self.store.root, self.store.workspace/intent['temporary'])
        if target.exists():
            info = self._regular(target)
            if (info.st_size, digest(target)) != (row['bytes'], row['sha256']):
                raise ValueError('Published hydration file changed before recovery')
            self.mark(row['path'])
        if temporary.exists():
            info = self._regular(temporary)
            identity = intent.get('identity')
            # Between exclusive create and its durable identity record, only
            # an empty file can exist: no plaintext is written before that save.
            if ((identity is None and info.st_size != 0) or
                    (identity is not None and [info.st_dev, info.st_ino] != identity)):
                raise ValueError('Hydration temporary identity changed; manual recovery is required')
            temporary.unlink(); _fsync_dir(temporary.parent)
        self.inflight = None
        self.save()

    def observe(self, rows):
        """A pending name explicitly created by a writer becomes materialized."""
        appeared = {row['path'] for row in rows} & set(self.rows)
        if appeared - self.materialized:
            for relative in appeared: self.mark(relative)
            self.save()

    def materialize(self, rows, check=None):
        from profile_workspace import _fsync_dir
        count = 0
        self.store._progress('restore','Restoring and authenticating account files...',completed=0,total=len(rows))
        for row in rows:
            if callable(check): check()
            target = _contained(self.store.root, self.store.workspace/row['path'])
            if target.exists():
                raise FileExistsError('A writer already created the deferred workspace file')
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name+'.'+uuid.uuid4().hex+'.part')
            self.inflight = {'path': row['path'], 'temporary': temporary.relative_to(self.store.workspace).as_posix(), 'identity': None}
            self.save()
            def created(handle):
                info = os.fstat(handle.fileno())
                self.inflight['identity'] = [info.st_dev, info.st_ino]
                self.save()
            source = self.store.blob_path(self.manifest, row)
            size, sha = self.store._decrypt_file(source, row['path'], self.store._key(), temporary, created=created)
            if (size, sha) != (row['bytes'], row['sha256']):
                raise ValueError('Deferred file authentication failed')
            if callable(check): check()
            _contained(self.store.root, temporary); _contained(self.store.root, target)
            publish_no_replace(temporary, target); _fsync_dir(target.parent)
            # Cancellation after publication leaves its authenticated intent so
            # seal/recovery can prove publication before treating it as present.
            if callable(check): check()
            self.mark(row['path']); self.inflight = None; self.save()
            count += 1
            self.store._progress('restore','Restoring and authenticating account files...',completed=count,total=len(rows))
            if callable(check): check()
        if callable(check): check()
        return count
