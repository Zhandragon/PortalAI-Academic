"""Durable, immutable completed confirmation cases; JSON files are mirrors.

A SQLite FULL-synchronous transaction is the checkpoint. A crash between that
transaction and JSON export cannot lose or replay a completed inference case.
This module never loads a model, executes a tool, or changes an experiment gate.
"""
import hashlib
import json
import math
import os
import sqlite3
import time
import uuid
from pathlib import Path


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def request_digest(request):
    return digest(encoded(request))


def check_result(arm, identifier, value):
    if arm not in ('baseline', 'candidate') or value.get('id') != identifier:
        raise ValueError('Case identity mismatch')
    if type(value.get('grading', {}).get('correct')) is not bool:
        raise ValueError('A completed case requires a boolean grade')
    if not isinstance(value.get('text'), str) or value.get('finish') not in ('stop', 'length'):
        raise ValueError('A completed case requires output and a known finish reason')
    if type(value.get('tokens')) is not int or not 0 <= value['tokens'] <= 32768:
        raise ValueError('Invalid token count')
    seconds = value.get('seconds')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError('Invalid elapsed time')


class CaseStore:
    def __init__(self, path, frozen_sha256, *, create=False):
        self.path = Path(path)
        if create == self.path.exists():
            raise ValueError('Case store creation/resume mode does not match the saved state')
        if len(frozen_sha256) != 64 or any(c not in '0123456789abcdef' for c in frozen_sha256):
            raise ValueError('Invalid frozen experiment digest')
        self.db = sqlite3.connect(self.path, timeout=10)
        try:
            self.db.execute('PRAGMA journal_mode=DELETE')
            self.db.execute('PRAGMA synchronous=FULL')
            if create:
                with self.db:
                    self.db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
                    self.db.execute('CREATE TABLE cases (arm TEXT NOT NULL, id TEXT NOT NULL, request_sha256 TEXT NOT NULL, request_json TEXT NOT NULL, payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, completed REAL NOT NULL, PRIMARY KEY (arm,id))')
                    self.db.execute('INSERT INTO metadata VALUES (?,?)', ('frozen_sha256', frozen_sha256))
            if self.db.execute("SELECT value FROM metadata WHERE key='frozen_sha256'").fetchone() != (frozen_sha256,):
                raise ValueError('Frozen experiment changed; completed cases cannot be reused')
            if self.db.execute('PRAGMA integrity_check').fetchone() != ('ok',):
                raise ValueError('Confirmation checkpoint failed database integrity verification')
        except BaseException:
            self.db.close()
            raise

    def save(self, arm, identifier, request, result):
        check_result(arm, identifier, result)
        req = encoded(request)
        req_sha = digest(req)
        value = dict(result, confirmation_request_sha256=req_sha)
        payload = encoded(value)
        with self.db:
            if self.db.execute('SELECT 1 FROM cases WHERE arm=? AND id=?', (arm, identifier)).fetchone():
                raise ValueError('A completed case cannot be overwritten or replayed')
            self.db.execute('INSERT INTO cases VALUES (?,?,?,?,?,?,?)',
                            (arm, identifier, req_sha, req.decode('utf-8'), payload.decode('utf-8'), digest(payload), time.time()))
        return value

    def load(self, requests):
        results = {'baseline': {}, 'candidate': {}}
        for arm, identifier, req_sha, request_json, payload, payload_sha in self.db.execute(
                'SELECT arm,id,request_sha256,request_json,payload,payload_sha256 FROM cases ORDER BY arm,id'):
            if arm not in requests or identifier not in requests[arm]:
                raise ValueError('Unplanned completed case in the checkpoint')
            expected = encoded(requests[arm][identifier])
            if req_sha != digest(expected) or request_json.encode('utf-8') != expected:
                raise ValueError('Case prompt, seed, model, or sampling changed')
            raw = payload.encode('utf-8')
            if digest(raw) != payload_sha:
                raise ValueError('Completed case checksum changed')
            value = json.loads(payload)
            check_result(arm, identifier, value)
            if value.get('confirmation_request_sha256') != req_sha:
                raise ValueError('Case provenance does not match its saved request')
            results[arm][identifier] = value
        return results

    def export(self, destination, *, only=None):
        """Recreate missing JSON mirrors, preserving any conflicting existing file."""
        destination = Path(destination).resolve(strict=True)
        query = 'SELECT arm,id,payload,payload_sha256 FROM cases'
        rows = self.db.execute(query + (' WHERE arm=? AND id=?' if only else ''), only or ())
        for arm, identifier, payload, expected in rows:
            raw = payload.encode('utf-8')
            if digest(raw) != expected or arm not in ('baseline', 'candidate'):
                raise ValueError('Cannot export an invalid checkpoint')
            folder = destination / arm
            folder.mkdir(exist_ok=True)
            if folder.resolve().parent != destination:
                raise ValueError('Result directory resolves outside this experiment')
            target = folder / (digest(identifier.encode('utf-8'))[:20] + '.json')
            if target.exists():
                if target.is_symlink() or digest(target.read_bytes()) != expected:
                    raise ValueError('Existing result mirror differs; preserved for review')
                continue
            temporary = folder / (target.name + '.' + uuid.uuid4().hex + '.writing')
            with temporary.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            if target.exists():
                raise ValueError('A result mirror appeared during export; both files retained')
            # Windows rename refuses an existing destination. The non-Windows
            # branch uses an exclusive link so it also cannot overwrite a file.
            if os.name == 'nt':
                temporary.rename(target)
            else:
                os.link(temporary, target)
                temporary.unlink()
            if digest(target.read_bytes()) != expected:
                raise ValueError('Result mirror readback failed')

    def close(self):
        self.db.close()
