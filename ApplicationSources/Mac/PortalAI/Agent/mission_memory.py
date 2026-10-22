"""Bounded, searchable mission memory on the SSD; no shared account memory."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time

from runtime_policy import require_space


def scope_for(store, mission):
    current = mission
    seen = set()
    while current.get('parent'):
        if current['id'] in seen:
            raise ValueError('Mission parent cycle')
        seen.add(current['id'])
        parent = store.load(current['parent'])
        if parent['mode'] != mission['mode']:
            raise PermissionError('Memory cannot cross mission access modes')
        current = parent
    scope = current.get('schedule_id') or current['id']
    if not re.fullmatch(r'[a-f0-9]{32}', scope):
        raise ValueError('Invalid memory scope')
    return scope, mission['mode']


class Memory:
    MAX_BYTES = 2 * 1024**2
    MAX_ENTRIES = 512

    def __init__(self, store, mission):
        self.root = store.root
        self.scope, self.mode = scope_for(store, mission)
        self.mission = mission['id']
        self.step = mission['steps']
        self.path = store.base/'Memory'/self.scope/'memory.sqlite3'

    @contextmanager
    def connection(self):
        require_space(self.root, 32*1024**2, for_outputs=True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('PRAGMA max_page_count=4096')  # Bound the database and its rollback journal.
            db.execute('BEGIN IMMEDIATE')
            with db:
                db.execute('CREATE TABLE IF NOT EXISTS metadata (mode TEXT NOT NULL)')
                row = db.execute('SELECT mode FROM metadata').fetchone()
                if row and row[0] != self.mode:
                    raise PermissionError('Memory scope belongs to another access mode')
                if not row:
                    db.execute('INSERT INTO metadata VALUES (?)', (self.mode,))
                db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS entries USING fts5(key, text, provenance UNINDEXED, updated UNINDEXED)')
            yield db
        finally:
            db.close()

    def remember(self, key, text):
        key, text = str(key).strip(), str(text).strip()
        if not key or len(key) > 120 or not text or len(text.encode('utf-8')) > 8000:
            raise ValueError('Memory needs a key (1–120 characters) and text (1–8000 UTF-8 bytes)')
        provenance = json.dumps({'mission': self.mission, 'step': self.step, 'kind': 'agent_note', 'verified': False})
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with db:
                old = db.execute('SELECT rowid, text FROM entries WHERE key=?', (key,)).fetchone()
                count, size = db.execute('SELECT count(*), coalesce(sum(length(cast(text AS BLOB))),0) FROM entries').fetchone()
                if (not old and count >= self.MAX_ENTRIES) or size - (len(old[1].encode()) if old else 0) + len(text.encode()) > self.MAX_BYTES:
                    raise RuntimeError('Mission memory budget reached; review and consolidate memory before continuing')
                if old:
                    db.execute('UPDATE entries SET text=?, provenance=?, updated=? WHERE rowid=?', (text, provenance, time.time(), old[0]))
                else:
                    db.execute('INSERT INTO entries VALUES (?,?,?,?)', (key, text, provenance, time.time()))
        return {'saved': key, 'scope': self.scope, 'provenance': json.loads(provenance)}

    def recall(self, query='', limit=5):
        if not self.path.exists():
            return []
        limit = max(1, min(10, int(limit)))
        terms = re.findall(r'\w+', str(query), re.UNICODE)[:8]
        with self.connection() as db:
            if terms:
                match = ' OR '.join('"'+term+'"' for term in terms)
                rows = db.execute('SELECT key,text,provenance,updated FROM entries WHERE entries MATCH ? ORDER BY rank LIMIT ?', (match,limit)).fetchall()
            else:
                rows = db.execute('SELECT key,text,provenance,updated FROM entries ORDER BY updated DESC LIMIT ?', (limit,)).fetchall()
        return [{'key':key,'text':text,'provenance':json.loads(source),'updated_at':float(at)} for key,text,source,at in rows]
