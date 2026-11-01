"""Explicit corrections and conservative same-key conflict handling; no extra model."""
import copy
import re
import time


def timestamp(value):
    try: return max(0.0, float(value or 0))
    except (ValueError, TypeError, OverflowError): return 0.0


def source_time(session, chosen):
    # Never use the distillation/save time as the time a fact was stated.
    times = [timestamp(row.get('created')) for row in chosen if row.get('role') == 'user']
    return max(times or [0]) or timestamp(session.get('created'))


def eligible(memory, record, current_sid):
    now = time.time(); rows = []
    for obs in record.get('observations') or []:
        sid = str(obs.get('session_id') or '')
        if sid == current_sid or obs.get('superseded_at'): continue
        if obs.get('expires_at') and timestamp(obs['expires_at']) <= now: continue
        if sid == '__manual__' or memory.chat_included(sid): rows.append(obs)
    if not rows: return None
    manual = [r for r in rows if r.get('session_id') == '__manual__']
    selected = max(manual or rows, key=lambda r: (timestamp(r.get('source_at')), timestamp(r.get('updated')) if r.get('source_at') else 0))
    normalized = lambda v: re.sub(r'\s+', ' ', str(v).strip()).casefold()
    alternatives = [r for r in rows if normalized(r.get('value')) != normalized(selected.get('value'))]
    result = dict(selected)
    if alternatives:
        # Different wording may be compatible. Never pretend to infer negation reliably.
        other = max(alternatives, key=lambda r: timestamp(r.get('source_at')))
        result['value'] = (str(selected.get('value', ''))[:350] + ' [Possible same-key conflict: ' +
                           str(other.get('value', ''))[:250] + '. Ask if material; wording differences are not proof of contradiction.]')
        result['conflict'] = True
    return result


def status(obs):
    if obs.get('superseded_at'): return 'superseded'
    if obs.get('expires_at') and timestamp(obs['expires_at']) <= time.time(): return 'expired'
    if obs.get('expires_at'): return 'temporary'
    return 'corrected' if obs.get('session_id') == '__manual__' else 'durable'


def correct(memory, item, value, *, hours=None):
    """UI action; stale selections fail, in-flight distillation cannot overwrite it."""
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 700: raise ValueError('Use 1–700 characters')
    if hours is not None and (type(hours) is not int or not 1 <= hours <= 8760): raise ValueError('Temporary lifetime: 1–8760 hours')
    memory.profile.check(); memory.cancel_active()
    with memory.lock:
        fresh = next((entry for entry in memory.retained_items() if all(entry.get(k) == item.get(k) for k in ('kind', 'key', 'index', 'signature', 'text'))), None)
        if fresh is None or fresh['kind'] != 'fact': raise ValueError('Select a current fact; refresh if it changed')
        before = copy.deepcopy(memory.data); memory._generation += 1
        record = memory.data['facts'][fresh['key']]; now = time.time()
        history = record.setdefault('corrections', [])
        history.append({'at': now, 'previous': fresh['text'], 'replacement': value.strip(), 'expires_at': now + hours * 3600 if hours else None})
        record['corrections'] = history[-12:]
        for observation in record['observations']: observation['superseded_at'] = now
        record['observations'] = [r for r in record['observations'] if r.get('session_id') != '__manual__']
        record['observations'].append({'session_id': '__manual__', 'value': value.strip(), 'importance': 5,
            'tags': [], 'source_at': now, 'updated': now, 'expires_at': now + hours * 3600 if hours else None})
        # Older backfilled chats cannot resurrect a superseded observation.
        record['corrected_at'] = now
        from runtime_policy import require_space
        from workspace_store import encoded
        try:
            require_space(memory.root,len(encoded(memory.data))*2,for_outputs=True)
            memory.save()
        except Exception: memory.data = before; raise
    return {'corrected': True, 'temporary_hours': hours, 'notice': 'Previous observations retained as superseded. Expiry does not revive the old fact.'}
