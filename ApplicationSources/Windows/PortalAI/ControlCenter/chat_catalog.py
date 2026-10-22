"""Small per-account history catalog. Raw transcripts and media stay on demand."""
import json
import hashlib
import threading
from pathlib import Path

from profile_hydration import file_listing
from runtime_policy import atomic_json


def message_count(session):
    if isinstance(session.get('messages'), list): return len(session['messages'])
    return max(0, int(session.get('message_count', 0)))


def summary(session):
    return {**{key: session.get(key) for key in ('id', 'title', 'created', 'updated')},
            'message_count': message_count(session)}


def fingerprint(path):
    with path.open('rb') as handle: return hashlib.file_digest(handle, 'sha256').hexdigest()


class ChatCatalog:
    def __init__(self, store):
        self.store = store
        self.path = store.base/'session_catalog.json'
        self.lock = threading.RLock()
        self.rows = None
        self.revision = 0

    def _save(self):
        self.store.profile.check()
        atomic_json(self.path, {'version': 1, 'sessions': self.rows})
        self.store.profile.check()

    def _ensure(self):
        if self.rows is not None: return
        self.store.profile.check()
        try:
            if self.path.stat().st_size > 32*1024*1024: raise ValueError('Oversized chat catalog')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('version') != 1 or not isinstance(data.get('sessions'), dict): raise ValueError('Invalid chat catalog')
            saved = data['sessions']
        except (FileNotFoundError, ValueError, TypeError): saved = {}
        listing = file_listing(self.store.root, 'Data/Chat/Sessions')
        names = listing['names']
        rows = {}
        for name in names:
            path = Path(name)
            if path.parent.as_posix() != 'Data/Chat/Sessions' or path.suffix != '.json': continue
            sid = path.stem
            self.store._valid_id(sid)
            present = self.store.sessions/path.name
            record = saved.get(sid)
            # Read materialized transcripts on startup only: this repairs a crash
            # between saving/deleting a transcript and updating its derived index.
            if (present.is_file() or not isinstance(record, dict) or record.get('id') != sid or
                    record.get('_sha256') != listing['pending_hashes'].get(name)):
                session = self.store._read_session(sid)
                if session is None: continue
                record = {**summary(session), '_sha256': fingerprint(present)}
            else:
                record = {**summary(record), '_sha256': record['_sha256']}
            rows[sid] = record
        self.store.profile.check()
        self.rows = rows
        if rows != saved or not self.path.exists(): self._save()

    def list(self):
        with self.lock:
            self.store.profile.check()
            self._ensure()
            return sorted((dict(row) for row in self.rows.values()),
                          key=lambda row: float(row.get('updated') or 0), reverse=True)

    def put(self, session):
        with self.lock:
            self._ensure()
            self.rows[session['id']] = {**summary(session),
                '_sha256': fingerprint(self.store.sessions/(session['id']+'.json'))}
            self._save()
            self.revision += 1

    def remove(self, sid):
        with self.lock:
            self._ensure()
            self.rows.pop(sid, None)
            self._save()
            self.revision += 1
