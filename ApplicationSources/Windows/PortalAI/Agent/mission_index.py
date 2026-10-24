"""Derived list summaries, bound to exact checkpoint bytes; never execution input.

Checkpoint loaders remain authoritative for every action. Missing/stale summaries
repair only their own record. Dormant names/hashes come from the authenticated
profile inventory, so an absent plaintext file is not treated as deletion.
"""
import hashlib
import json
import re
from pathlib import Path

from profile_paths import private_path, ProfileLocked
from profile_hydration import file_listing
from runtime_policy import atomic_json

COMMON = ('id', 'objective', 'mode', 'status', 'created_at', 'updated_at')
FIELDS = {
    'mission': COMMON + ('steps', 'max_steps', 'next_run_at', 'depth', 'parent',
                        'children', 'schedule_id', 'chat_paused'),
    'schedule': COMMON + ('enabled', 'epoch', 'max_steps', 'interval_seconds',
                         'max_runs', 'runs_started', 'runs_completed', 'active_run',
                         'source_mission', 'next_run_at', 'origin', 'classification',
                         'autonomous_recovery', 'removed_at'),
}


def relative(kind, mid):
    if kind not in FIELDS or not isinstance(mid, str) or not re.fullmatch('[a-f0-9]{32}', mid):
        raise ValueError('Invalid checkpoint index identity')
    return f'Data/Missions/{mid}/mission.json' if kind == 'mission' else f'Data/Missions/Schedules/{mid}.json'


def check(store, mid):
    (store if hasattr(store, 'folder') else store.store).folder(mid)


def index_path(store, kind, mid):
    relative(kind, mid); check(store, mid)
    return private_path(store.root, f'Data/MissionIndex/{kind}/{mid}.json')


def summary(kind, record, raw):
    result = {key: record[key] for key in FIELDS[kind] if key in record}
    # Keep a canonical fingerprint for reversible deletion visibility. This is
    # presentation evidence only; deletion/review/execution reread checkpoints.
    result['_checkpoint_fingerprint'] = hashlib.sha256(json.dumps(record,
        sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    result['_sha256'] = hashlib.sha256(raw).hexdigest()
    result['_summary'] = True
    return result


def remember(store, kind, record):
    """A failed derived-index write must not turn a saved action into a retry."""
    mid = record['id']; check(store, mid)
    try:
        path = private_path(store.root, relative(kind, mid), hydrate=False)
        raw = path.read_bytes()
        if json.loads(raw) != record: return  # A newer writer owns this version.
        value = {'version': 1, 'kind': kind, 'row': summary(kind, record, raw)}
        destination = index_path(store, kind, mid)
        if destination.exists() and destination.read_bytes() == json.dumps(value, indent=2).encode(): return
        atomic_json(destination, value)
    except ProfileLocked:
        raise
    except (OSError, ValueError, TypeError):
        check(store, mid)  # Never hide an ended login.


def listing(store, kind):
    probe = '0' * 32; check(store, probe)
    folder = 'Data/Missions' if kind == 'mission' else 'Data/Missions/Schedules'
    inventory = file_listing(store.root, folder)
    rows = []
    pattern = (r'Data/Missions/([a-f0-9]{32})/mission\.json' if kind == 'mission'
               else r'Data/Missions/Schedules/([a-f0-9]{32})\.json')
    for name in inventory['names']:
        match = re.fullmatch(pattern, name)
        if match: rows.append((match[1], name))
    return sorted(rows), inventory['pending_hashes']


def read_summary(store, kind, mid, pending_hash=None):
    path = index_path(store, kind, mid)
    try:
        if path.stat().st_size > 256 * 1024: raise ValueError('Oversized checkpoint index')
        value = json.loads(path.read_text(encoding='utf-8'))
        row = value['row']
        if (value.get('version') != 1 or value.get('kind') != kind or
                not isinstance(row, dict) or row.get('id') != mid or row.get('_summary') is not True or
                not isinstance(row.get('objective'), str) or not isinstance(row.get('status'), str)):
            raise ValueError('Invalid checkpoint index')
        if pending_hash is None:
            source = private_path(store.root, relative(kind, mid), hydrate=False)
            with source.open('rb') as handle: pending_hash = hashlib.file_digest(handle, 'sha256').hexdigest()
        if row.get('_sha256') != pending_hash: raise ValueError('Stale checkpoint index')
        check(store, mid)
        return row
    except ProfileLocked:
        raise
    except (OSError, ValueError, KeyError, TypeError):
        record = store.load(mid)
        remember(store, kind, record)
        source = private_path(store.root, relative(kind, mid), hydrate=False)
        raw = source.read_bytes()
        if json.loads(raw) != record: raise ValueError('Checkpoint changed while listing; refresh')
        check(store, mid)
        return summary(kind, record, raw)
