# PORTABLEAI_MEMORY_LIFECYCLE_v15_127B
from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url

import http.client
import copy
import hashlib
import json
import math
import re
import threading
import time
from pathlib import Path
from profile_context import CapturedProfile

API_HOST = "127.0.0.1"
API_PORT = _instance_port('qwen')
API_BASE = "/v1"
SCHEMA = 2

DEFAULT_CONFIG = {
    "enabled": True,
    "auto_distill": True,
    "context_tokens": 700,
    "max_facts": 10,
    "max_capsules": 2,
    "distill_batch_chars": 14000,
    "distill_capsule_chars": 1800,
}

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "from", "have", "has", "had", "are", "was", "were",
    "you", "your", "our", "but", "not", "can", "could", "would", "should", "about", "into", "than", "then",
    "what", "when", "where", "which", "while", "how", "why", "who", "will", "just", "also", "use", "using",
    "make", "want", "need", "like", "some", "more", "most", "very", "all", "any", "its", "it's", "they",
    "them", "their", "there", "here", "been", "being", "does", "did", "doing", "get", "got", "much", "many",
}


def _load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return default


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9_+.-]{2,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS and not w.isdigit()}


def _slug(value: str, fallback: str = "memory.item") -> str:
    value = re.sub(r"[^a-z0-9]+", ".", (value or "").lower()).strip(".")
    value = re.sub(r"\.+", ".", value)
    return value[:120] or fallback


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: max(0, n - 1)].rstrip() + "…"


class PersistentMemory:
    """Small, source-aware rolling memory for PortableAI Native Chat.

    Raw chats stay in Data/Chat/Sessions. This index stores only compact capsules and
    keyed observations. Every learned observation retains its source session ID, so
    excluding a chat immediately removes that source from retrieval without rewriting
    raw history or rebuilding the complete database.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self.profile = CapturedProfile(self.root)
        self.base = self.profile.private('Data/Memory')
        self.path = self.base / "memory_index.json"
        self.lock = threading.RLock()
        self._active_conn: http.client.HTTPConnection | None = None
        self._cancel = threading.Event()
        self._generation = 0
        self.data = self._load()
        self.prune_orphans_from_disk()
        self.compact_index(max_fact_keys=2048, invalidate=False)

    def _load(self) -> dict:
        self.profile.check()
        raw = _load_json(self.path, {})
        if not isinstance(raw, dict):
            raw = {}
        raw.setdefault("schema", SCHEMA)
        cfg = raw.get("config") if isinstance(raw.get("config"), dict) else {}
        raw["config"] = DEFAULT_CONFIG | cfg
        raw.setdefault("chats", {})
        raw.setdefault("facts", {})
        raw.setdefault("updated", time.time())
        return raw

    @property
    def config(self) -> dict:
        self.profile.check()
        return self.data["config"]

    def save(self) -> None:
        self.profile.check()
        with self.lock:
            self.data["updated"] = time.time()
            _write_json(self.path, self.data)

    def update_config(self, **changes) -> None:
        self.profile.check()
        with self.lock:
            self._generation += 1
            cfg = self.data.setdefault("config", DEFAULT_CONFIG.copy())
            cfg.update(changes)
            cfg["context_tokens"] = max(128, min(2400, int(cfg.get("context_tokens") or 700)))
            cfg["max_facts"] = max(2, min(40, int(cfg.get("max_facts") or 10)))
            cfg["max_capsules"] = max(0, min(8, int(cfg.get("max_capsules") or 2)))
            cfg["distill_batch_chars"] = max(4000, min(30000, int(cfg.get("distill_batch_chars") or 14000)))
            cfg["distill_capsule_chars"] = max(600, min(5000, int(cfg.get("distill_capsule_chars") or 1800)))
            self.save()

    def _chat_state(self, sid: str) -> dict:
        self.profile.check()
        sid = str(sid or "")
        chats = self.data.setdefault("chats", {})
        state = chats.get(sid)
        if not isinstance(state, dict):
            state = {
                "included": True,
                "recall_enabled": True,
                "cursor": 0,
                "capsule": "",
                "tags": [],
                "updated": 0.0,
            }
            chats[sid] = state
        state.setdefault("included", True)
        state.setdefault("recall_enabled", True)
        state.setdefault("cursor", 0)
        state.setdefault("capsule", "")
        state.setdefault("tags", [])
        state.setdefault("updated", 0.0)
        return state

    def chat_included(self, sid: str) -> bool:
        self.profile.check()
        with self.lock:
            return bool(self._chat_state(sid).get("included", True))

    def set_chat_included(self, sid: str, included: bool) -> None:
        self.set_chats_included([sid], included)

    def set_chats_included(self, sids, included: bool) -> None:
        self.profile.check()
        included = bool(included)
        with self.lock:
            before = copy.deepcopy(self.data)
            for sid in set(sids):
                st = self._chat_state(sid)
                if bool(st.get('included', True)) != included: self._generation += 1
                st['included'] = included; st['updated'] = time.time()
            try: self.save()
            except Exception: self.data = before; raise
        if not included:
            self.cancel_active()

    def chat_recall_enabled(self, sid: str) -> bool:
        self.profile.check()
        with self.lock:
            return bool(self._chat_state(sid).get("recall_enabled", True))


    def set_chat_recall_enabled(self, sid: str, enabled: bool) -> None:
        self.profile.check()
        with self.lock:
            self._generation += 1
            st = self._chat_state(sid)
            st["recall_enabled"] = bool(enabled)
            st["updated"] = time.time()
            self.save()

    def reset_chat(self, sid: str, *, clear_observations: bool = True) -> None:
        self.profile.check()
        sid = str(sid or "")
        with self.lock:
            self._generation += 1
            st = self._chat_state(sid)
            included = bool(st.get("included", True))
            recall_enabled = bool(st.get("recall_enabled", True))
            self.data["chats"][sid] = {
                "included": included,
                "recall_enabled": recall_enabled,
                "cursor": 0,
                "capsule": "",
                "tags": [],
                "updated": time.time(),
            }
            if clear_observations:
                for key in list(self.data.get("facts", {})):
                    rec = self.data["facts"].get(key)
                    if not isinstance(rec, dict):
                        continue
                    obs = [o for o in (rec.get("observations") or []) if str(o.get("session_id") or "") != sid]
                    if obs:
                        rec["observations"] = obs
                    else:
                        self.data["facts"].pop(key, None)
            self.save()

    def clear(self, *, keep_config: bool = True) -> None:
        self.profile.check()
        with self.lock:
            self._generation += 1
            cfg = dict(self.config) if keep_config else DEFAULT_CONFIG.copy()
            self.data = {"schema": SCHEMA, "config": cfg, "chats": {}, "facts": {}, "updated": time.time()}
            self.save()

    def clear_for_sessions(self, sessions: list[dict], *, keep_config: bool = True, exclude_sources=False) -> None:
        """Clear learned memory while preserving per-chat privacy controls.

        Existing raw history remains on disk, but each current session's cursor advances
        to its present end so an idle backfill cannot immediately recreate the memory
        the user just cleared. Rebuild current remains the explicit way to re-distill an
        old chat later.
        """
        self.profile.check()
        self.cancel_active()
        now = time.time()
        with self.lock:
            cfg = dict(self.config) if keep_config else DEFAULT_CONFIG.copy()
            old_chats = self.data.get("chats", {}) if isinstance(self.data.get("chats"), dict) else {}
            sources = {sid for sid, state in old_chats.items() if isinstance(state, dict) and state.get('capsule')}
            sources.update(str(obs.get('session_id') or '') for record in self.data.get('facts', {}).values()
                           if isinstance(record, dict) for obs in record.get('observations') or [] if isinstance(obs, dict))
            chats = {}
            for session in sessions or []:
                if not isinstance(session, dict):
                    continue
                sid = str(session.get("id") or "")
                if not sid:
                    continue
                old = old_chats.get(sid) if isinstance(old_chats.get(sid), dict) else {}
                from chat_catalog import message_count
                count = message_count(session)
                chats[sid] = {
                    "included": False if exclude_sources and sid in sources else bool(old.get("included", True)),
                    "recall_enabled": bool(old.get("recall_enabled", True)),
                    "cursor": count,
                    "capsule": "",
                    "tags": [],
                    "title": str(session.get("title") or "Untitled")[:140],
                    "updated": now,
                    "message_count": count,
                }
            self._generation += 1
            before = self.data
            self.data = {
                "schema": SCHEMA,
                "config": cfg,
                "chats": chats,
                "facts": {},
                "suppressed_items": self.data.get('suppressed_items', {}),
                "updated": now,
            }
            try: self.save()
            except Exception: self.data = before; raise

    def rebuild_included(self, sessions):
        """Explicitly rebuild included sources; per-item exclusions remain active."""
        self.profile.check(); self.cancel_active()
        with self.lock:
            before = copy.deepcopy(self.data)
            included = {row['id'] for row in sessions if self.chat_included(row['id'])}
            self._generation += 1
            for sid in included:
                state = self._chat_state(sid)
                state.update(cursor=0, capsule='', tags=[], updated=time.time())
            for key in list(self.data.get('facts', {})):
                record = self.data['facts'][key]
                record['observations'] = [obs for obs in record.get('observations') or []
                                          if obs.get('session_id') not in included]
                if not record['observations']: self.data['facts'].pop(key)
            try: self.save()
            except Exception: self.data = before; raise
            return len(included)

    def blocked_items(self):
        self.profile.check()
        with self.lock:
            return [{'block_id': key, **copy.deepcopy(value)} for key, value in
                    self.data.get('suppressed_items', {}).items()]

    def regenerate_included(self, store, cancel):
        """Stage a fresh rebuild; cancellation/failure leaves existing memory intact."""
        self.profile.check()
        if cancel.is_set(): raise RuntimeError('Memory rebuild cancelled')
        with self.lock:
            generation = self._generation
            draft = copy.copy(self)
            draft.data = copy.deepcopy(self.data)
            draft.lock = threading.RLock(); draft._cancel = threading.Event(); draft._active_conn = None
            draft.save = lambda: None
            draft._complete = self._complete
        rows = store.list_sessions()
        included = {row['id'] for row in rows if draft.chat_included(row['id'])}
        draft.rebuild_included(rows)
        self._cancel.clear()
        def check():
            self.profile.check()
            if cancel.is_set() or self._cancel.is_set(): raise RuntimeError('Memory rebuild cancelled')
            if self._generation != generation: raise RuntimeError('Memory changed during rebuild; original memory retained')
        for row in rows:
            check()
            if row['id'] not in included: continue
            session = store.load_session(row['id'])
            if session is None: raise RuntimeError('A source chat disappeared during rebuild')
            while draft.needs_distill(session):
                check()
                result = draft.distill_session(session)
                if not result.get('updated'): raise RuntimeError('Memory rebuild made no progress: '+str(result.get('reason')))
        with self.lock:
            check()
            before = self.data
            # Preserve harmless default states added by history-list presentation.
            for sid, state in before.get('chats', {}).items():
                draft.data['chats'].setdefault(sid, state)
            self.data = draft.data
            try: self.save()
            except Exception: self.data = before; raise
            self._generation += 1
        return {'updated': True, 'backlog': 0, 'rebuilt_chats': len(included)}

    def allow_item(self, block_id):
        self.profile.check()
        with self.lock:
            before = copy.deepcopy(self.data)
            self._generation += 1
            self.data.setdefault('suppressed_items', {}).pop(block_id, None)
            try: self.save()
            except Exception: self.data = before; raise


    def forget_chat(self, sid: str) -> None:
        """Remove every persistent-memory reference derived from one chat."""
        self.profile.check()
        sid = str(sid or "")
        if not sid:
            return
        self.cancel_active()
        with self.lock:
            self._generation += 1
            self.data.setdefault("chats", {}).pop(sid, None)
            facts = self.data.setdefault("facts", {})
            for key in list(facts):
                rec = facts.get(key)
                if not isinstance(rec, dict):
                    facts.pop(key, None)
                    continue
                obs = [
                    o for o in (rec.get("observations") or [])
                    if isinstance(o, dict) and str(o.get("session_id") or "") != sid
                ]
                if obs:
                    rec["observations"] = obs
                else:
                    facts.pop(key, None)
            self.save()

    @staticmethod
    def _item_signature(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True).encode()).hexdigest()

    def retained_items(self):
        """Stable selections for every retained observation and chat capsule."""
        self.profile.check()
        items = []
        with self.lock:
            for key, record in sorted(self.data.get('facts', {}).items()):
                if not isinstance(record, dict): continue
                signature = self._item_signature(record)
                for index, observation in enumerate(record.get('observations') or []):
                    if not isinstance(observation, dict): continue
                    source = str(observation.get('session_id') or '')
                    items.append({'kind': 'fact', 'key': key, 'index': index, 'signature': signature,
                                  'text': str(observation.get('value') or ''), 'source': source,
                                  'title': str(self.data.get('chats', {}).get(source, {}).get('title') or source)})
            for sid, state in sorted(self.data.get('chats', {}).items()):
                if not isinstance(state, dict) or not str(state.get('capsule') or '').strip(): continue
                items.append({'kind': 'capsule', 'key': sid, 'index': 0,
                              'signature': self._item_signature(state), 'text': str(state['capsule']),
                              'source': sid, 'title': str(state.get('title') or sid)})
        return items

    def delete_retained(self, item, sessions, *, span=None):
        """Delete a selected entry or exact text fragment; stale UI fails closed.

        Advance only its source's cursor to the current end so old undistilled
        text is not immediately replayed. Other retained entries stay untouched.
        Source/key exclusions survive rebuilding; capsule fragments use exact text
        matching, so differently worded statements are not semantically blocked.
        """
        self.profile.check()
        self.cancel_active()
        from chat_catalog import message_count
        with self.lock:
            fresh = next((entry for entry in self.retained_items() if
                          all(entry.get(k) == item.get(k) for k in ('kind', 'key', 'index', 'signature', 'text'))), None)
            if fresh is None: raise ValueError('This memory changed. Refresh the list before deleting it.')
            text = fresh['text']
            replacement = ''
            if span is not None:
                start, end = span
                if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text):
                    raise ValueError('Select a nonempty fragment in the retained text.')
                replacement = (text[:start] + text[end:]).strip()
            before = copy.deepcopy(self.data)
            self._generation += 1  # Invalidate already-running distillation commits.
            rule = {'kind': fresh['kind'], 'source': fresh['source'], 'key': fresh['key'],
                    'text': text[span[0]:span[1]] if span else text,
                    'whole': span is None, 'title': fresh['title']}
            self.data.setdefault('suppressed_items', {})[self._item_signature(rule)] = rule
            if fresh['kind'] == 'fact':
                record = self.data['facts'][fresh['key']]
                if replacement: record['observations'][fresh['index']]['value'] = replacement
                else: record['observations'].pop(fresh['index'])
                if not record['observations']: self.data['facts'].pop(fresh['key'])
            else:
                self.data['chats'][fresh['key']]['capsule'] = replacement
            source = fresh['source']
            row = next((row for row in sessions if row.get('id') == source), None)
            if row is not None:
                state = self._chat_state(source)
                state['cursor'] = max(int(state.get('cursor') or 0), message_count(row))
            try: self.save()
            except Exception:
                self.data = before
                raise
        return {'deleted': not bool(replacement), 'fragment_removed': span is not None}


    def prune_orphans_from_disk(self) -> dict:
        """Drop memory whose source session no longer exists, if Sessions is mounted."""
        self.profile.check()
        sessions_dir = self.profile.private('Data/Chat/Sessions')
        if not sessions_dir.is_dir():
            return {"changed": False, "reason": "sessions directory unavailable"}
        try:
            from profile_hydration import file_names
            valid = {Path(name).stem for name in file_names(self.root, 'Data/Chat/Sessions')
                     if Path(name).parent.as_posix() == 'Data/Chat/Sessions' and Path(name).suffix == '.json'}
        except OSError:
            return {"changed": False, "reason": "sessions directory unreadable"}

        changed = False
        removed_chats = 0
        removed_observations = 0
        with self.lock:
            chats = self.data.setdefault("chats", {})
            for sid in list(chats):
                if sid not in valid:
                    chats.pop(sid, None)
                    removed_chats += 1
                    changed = True
            facts = self.data.setdefault("facts", {})
            for key in list(facts):
                rec = facts.get(key)
                if not isinstance(rec, dict):
                    facts.pop(key, None)
                    changed = True
                    continue
                old = list(rec.get("observations") or [])
                kept = []
                for obs in old:
                    if not isinstance(obs, dict):
                        removed_observations += 1
                        changed = True
                        continue
                    source = str(obs.get("session_id") or "")
                    if source == "__manual__" or source in valid:
                        kept.append(obs)
                    else:
                        removed_observations += 1
                        changed = True
                if kept:
                    rec["observations"] = kept
                else:
                    facts.pop(key, None)
                    if old:
                        changed = True
            if changed:
                self._generation += 1
                self.save()
        return {
            "changed": changed,
            "removed_chats": removed_chats,
            "removed_observations": removed_observations,
        }


    def _compact_locked(self, max_fact_keys: int = 2048) -> dict:
        """Compact derived memory without changing raw chat history or chat privacy state.

        The compactor intentionally does NOT merge different semantic keys. It removes
        malformed observations, keeps only the newest observation per source session for
        each key, and bounds only non-manual derived fact keys. Manual facts are never
        evicted by the automatic ceiling.
        """
        max_fact_keys = max(256, int(max_fact_keys or 2048))
        facts = self.data.setdefault("facts", {})
        changed = False
        removed_observations = 0
        removed_keys = 0

        for key in list(facts):
            rec = facts.get(key)
            if not isinstance(rec, dict):
                facts.pop(key, None)
                removed_keys += 1
                changed = True
                continue
            newest_by_source = {}
            for obs in list(rec.get("observations") or []):
                if not isinstance(obs, dict):
                    removed_observations += 1
                    changed = True
                    continue
                source = str(obs.get("session_id") or "").strip()
                value = str(obs.get("value") or "").strip()
                if not source or not value:
                    removed_observations += 1
                    changed = True
                    continue
                prev = newest_by_source.get(source)
                if prev is None:
                    newest_by_source[source] = obs
                else:
                    try:
                        prev_rank = (float(prev.get("updated") or 0), int(prev.get("importance") or 0))
                        new_rank = (float(obs.get("updated") or 0), int(obs.get("importance") or 0))
                    except Exception:
                        prev_rank = (0.0, 0); new_rank = (0.0, 0)
                    if new_rank >= prev_rank:
                        newest_by_source[source] = obs
                    removed_observations += 1
                    changed = True
            kept = list(newest_by_source.values())
            kept.sort(key=lambda o: float(o.get("updated") or 0))
            kept = kept[-24:]
            if not kept:
                facts.pop(key, None)
                removed_keys += 1
                changed = True
                continue
            if kept != list(rec.get("observations") or []):
                rec["observations"] = kept
                changed = True
            if rec.get("key") != key:
                rec["key"] = key
                changed = True

        if len(facts) > max_fact_keys:
            manual = set()
            ranked = []
            for key, rec in facts.items():
                obs = list(rec.get("observations") or []) if isinstance(rec, dict) else []
                if any(str(o.get("session_id") or "") == "__manual__" for o in obs if isinstance(o, dict)):
                    manual.add(key)
                    continue
                importance = max([int(o.get("importance") or 0) for o in obs if isinstance(o, dict)] or [0])
                updated = max([float(o.get("updated") or 0) for o in obs if isinstance(o, dict)] or [0.0])
                ranked.append((importance, updated, key))
            quota = max(0, max_fact_keys - len(manual))
            ranked.sort(key=lambda row: (-row[0], -row[1], row[2]))
            keep_nonmanual = {row[2] for row in ranked[:quota]}
            for _importance, _updated, key in ranked[quota:]:
                facts.pop(key, None)
                removed_keys += 1
                changed = True

        return {
            "changed": changed,
            "removed_observations": removed_observations,
            "removed_keys": removed_keys,
            "fact_keys": len(facts),
            "ceiling": max_fact_keys,
        }


    def compact_index(self, max_fact_keys: int = 2048, *, invalidate: bool = True) -> dict:
        """Safely compact only the derived memory index."""
        self.profile.check()
        if invalidate:
            self.cancel_active()
        with self.lock:
            if invalidate:
                self._generation += 1
            stats = self._compact_locked(max_fact_keys=max_fact_keys)
            if stats.get("changed"):
                self.save()
            return stats

    def cancel_active(self) -> None:
        self._cancel.set()
        conn = self._active_conn
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    def _model_id(self) -> str:
        self.profile.check()
        conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=3)
        try:
            conn.request("GET", API_BASE + "/models", headers={"Accept": "application/json"})
            r = conn.getresponse()
            data = json.loads(r.read().decode("utf-8", errors="replace"))
            rows = data.get("data") or []
            return str(rows[0].get("id") or "local-model") if rows else "local-model"
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _complete(self, messages: list[dict], *, max_tokens: int = 650) -> str:
        self.profile.check()
        if self._cancel.is_set():
            raise RuntimeError("memory update cancelled")
        payload = {
            "model": self._model_id(), "messages": messages,
            "temperature": 0.1, "max_tokens": max_tokens, "stream": False,
        }
        conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=120)
        self._active_conn = conn
        try:
            conn.request(
                "POST", API_BASE + "/chat/completions",
                body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            r = conn.getresponse()
            raw = r.read().decode("utf-8", errors="replace")
            if self._cancel.is_set():
                raise RuntimeError("memory update cancelled")
            if r.status >= 300:
                raise RuntimeError(f"memory HTTP {r.status}: {raw[:900]}")
            data = json.loads(raw)
            self.profile.check()
            choices = data.get("choices") or []
            msg = choices[0].get("message") if choices else {}
            return str((msg or {}).get("content") or "").strip()
        finally:
            try:
                conn.close()
            except Exception:
                pass
            if self._active_conn is conn:
                self._active_conn = None

    def _render_message(self, msg: dict) -> str:
        role = str(msg.get("role") or "").upper()
        if role == "USER":
            text = str(msg.get("content") or "")
            atts = [str(a.get("name") or a.get("path") or "") for a in (msg.get("attachments") or [])]
            if atts:
                text += "\nAttachments: " + ", ".join(atts[:8])
            return "USER:\n" + text[:7000]
        if role == "ASSISTANT":
            return "ASSISTANT:\n" + str(msg.get("content") or "")[:7000]
        if role == "TOOL":
            body = str(msg.get("content") or "")
            return f"TOOL {msg.get('name') or ''}:\n" + body[:1400]
        return ""

    def _batch(self, session: dict, cursor: int) -> tuple[list[dict], int, str]:
        msgs = list(session.get("messages") or [])
        if cursor >= len(msgs):
            return [], cursor, ""
        limit = int(self.config.get("distill_batch_chars") or 14000)
        chosen: list[dict] = []
        parts: list[str] = []
        chars = 0
        user_turns = 0
        for idx in range(max(0, cursor), len(msgs)):
            m = msgs[idx]
            rendered = self._render_message(m)
            if not rendered:
                chosen.append(m)
                continue
            extra = len(rendered) + 2
            if parts and chars + extra > limit and user_turns >= 2:
                break
            chosen.append(m)
            parts.append(rendered)
            chars += extra
            if m.get("role") == "user":
                user_turns += 1
            if user_turns >= 6 and chars >= int(limit * 0.65):
                break
        end = cursor + len(chosen)
        return chosen, end, "\n\n".join(parts)

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = (text or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
            text = re.sub(r"\s*```$", "", text)
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            m = re.search(r"\{.*\}", text, flags=re.S)
            if not m:
                return {}
            try:
                obj = json.loads(m.group(0))
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}

    def needs_distill(self, session: dict) -> bool:
        self.profile.check()
        sid = str(session.get("id") or "")
        if not sid or not self.chat_included(sid):
            return False
        with self.lock:
            cursor = int(self._chat_state(sid).get("cursor") or 0)
        from chat_catalog import message_count
        return cursor < message_count(session)

    def distill_session(self, session: dict) -> dict:
        self.profile.check()
        sid = str(session.get("id") or "")
        if not sid:
            return {"updated": False, "reason": "missing session id"}
        if not self.config.get("enabled", True):
            return {"updated": False, "reason": "memory disabled"}
        if not self.chat_included(sid):
            return {"updated": False, "reason": "chat excluded"}
        self._cancel.clear()
        with self.lock:
            generation = int(getattr(self, "_generation", 0))
            st = dict(self._chat_state(sid))
        cursor = int(st.get("cursor") or 0)
        chosen, end, transcript = self._batch(session, cursor)
        if end <= cursor or not transcript.strip():
            return {"updated": False, "reason": "nothing new", "sid": sid}

        existing = str(st.get("capsule") or "")
        cap_limit = int(self.config.get("distill_capsule_chars") or 1800)
        system = (
            "You update a compact private memory index for a local assistant. Return ONLY valid JSON with this schema:\n"
            '{"capsule":"rolling session summary","tags":["tag"],"upserts":['
            '{"key":"stable.dot.key","value":"durable fact","kind":"profile|preference|project|decision|constraint|workflow|relationship|other","importance":1,"tags":["tag"]}]}\n\n'
            "Rules:\n"
            f"- capsule must remain under about {cap_limit} characters and preserve only durable project state, decisions, preferences, constraints, and unresolved work.\n"
            "- Upsert only durable facts that could improve a future conversation. Use stable lowercase dot-delimited keys so later chats can update the same concept.\n"
            "- Prefer facts stated by the user. Assistant claims count only when confirmed by the user or grounded in a concrete tool/result.\n"
            "- Do not infer personality, diagnosis, politics, religion, sexuality, or other sensitive traits. Do not store passwords, API keys, tokens, account numbers, secrets, or transient logs.\n"
            "- Omit greetings, one-off questions, generic knowledge, and verbose reasoning. Never invent information.\n"
            "- importance: 5 = broadly useful and durable; 1 = narrow project detail."
        )
        user = f"CHAT TITLE: {session.get('title') or 'Untitled'}\n"
        if existing:
            user += "\nEXISTING ROLLING CAPSULE:\n" + existing[:cap_limit] + "\n"
        user += "\nNEW CHAT SEGMENT:\n" + transcript
        raw = self._complete(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=760,
        )
        obj = self._parse_json(raw)
        if not obj:
            return {"updated": False, "reason": "invalid distillation JSON", "sid": sid}

        capsule = _clip(str(obj.get("capsule") or existing), cap_limit)
        tags = [_slug(str(x), "") for x in (obj.get("tags") or []) if str(x).strip()][:16]
        now = time.time()
        count = 0
        with self.lock:
            # Clear/delete/exclude operations invalidate any worker that began before
            # them. This check is intentionally inside the final commit lock.
            if generation != int(getattr(self, "_generation", 0)):
                return {"updated": False, "reason": "memory update invalidated", "sid": sid}
            live = self._chat_state(sid)
            if not bool(live.get("included", True)):
                return {"updated": False, "reason": "chat excluded during update", "sid": sid}
            rules = [rule for rule in self.data.get('suppressed_items', {}).values() if rule.get('source') == sid]
            for rule in rules:
                if rule.get('kind') == 'capsule':
                    capsule = '' if rule.get('whole') else capsule.replace(str(rule.get('text') or ''), '')
            live["cursor"] = max(int(live.get("cursor") or 0), end)
            live["capsule"] = capsule
            live["tags"] = tags
            live["title"] = str(session.get("title") or "Untitled")[:140]
            live["updated"] = now
            live["message_count"] = len(session.get("messages") or [])

            facts = self.data.setdefault("facts", {})
            for item in (obj.get("upserts") or [])[:12]:
                if not isinstance(item, dict):
                    continue
                value = _clip(str(item.get("value") or ""), 700)
                if not value:
                    continue
                key = _slug(str(item.get("key") or ""), "")
                if not key:
                    continue
                if any(rule.get('kind') == 'fact' and rule.get('key') == key for rule in rules): continue
                kind = _slug(str(item.get("kind") or "other"), "other").split(".")[0]
                importance = max(1, min(5, int(item.get("importance") or 2)))
                itags = [_slug(str(x), "") for x in (item.get("tags") or []) if str(x).strip()][:12]
                rec = facts.get(key)
                if not isinstance(rec, dict):
                    rec = {"key": key, "kind": kind, "observations": []}
                    facts[key] = rec
                rec["kind"] = kind
                obs = [o for o in (rec.get("observations") or []) if str(o.get("session_id") or "") != sid]
                obs.append({
                    "session_id": sid, "value": value, "importance": importance,
                    "tags": itags, "updated": now,
                })
                rec["observations"] = obs[-24:]
                count += 1
            self._compact_locked(max_fact_keys=2048)
            self.save()
        return {
            "updated": True, "sid": sid, "title": str(session.get("title") or "Untitled"),
            "cursor": end, "message_count": len(session.get("messages") or []),
            "facts": count, "complete": end >= len(session.get("messages") or []),
        }

    def maintenance(self, store, preferred_sid: str | None = None, *, force=False) -> dict:
        self.profile.check()
        if not force and (not self.config.get("enabled", True) or not self.config.get("auto_distill", True)):
            return {"updated": False, "reason": "automatic memory disabled", "backlog": 0}
        rows = store.list_sessions()
        target = None
        if preferred_sid:
            preferred = next((x for x in rows if str(x.get("id")) == str(preferred_sid)), None)
            if preferred and self.needs_distill(preferred):
                target = preferred
        if target is None:
            # Prefer recent chats first: this gives useful cross-session memory quickly,
            # while repeated idle passes progressively backfill the older archive.
            for row in rows:
                if self.needs_distill(row):
                    target = row
                    break
        if target is None:
            return {"updated": False, "reason": "memory caught up", "backlog": 0}
        try:
            if 'messages' not in target:
                target = store.load_session(target['id'])
                if target is None: return {'updated': False, 'reason': 'chat unavailable'}
            result = self.distill_session(target)
        except Exception as exc:
            result = {"updated": False, "reason": f"{type(exc).__name__}: {exc}", "sid": target.get("id")}
        result["backlog"] = self.backlog_count(rows)
        return result

    def backlog_count(self, sessions: list[dict]) -> int:
        self.profile.check()
        return sum(1 for s in sessions if self.needs_distill(s))

    def stats(self, sessions: list[dict] | None = None) -> dict:
        self.profile.check()
        with self.lock:
            included = sum(1 for s in self.data.get("chats", {}).values() if isinstance(s, dict) and s.get("included", True))
            excluded = sum(1 for s in self.data.get("chats", {}).values() if isinstance(s, dict) and not s.get("included", True))
            capsules = sum(1 for s in self.data.get("chats", {}).values() if isinstance(s, dict) and str(s.get("capsule") or "").strip())
            facts = len(self.data.get("facts", {}))
        out = {"facts": facts, "capsules": capsules, "included": included, "excluded": excluded}
        if sessions is not None:
            out["backlog"] = self.backlog_count(sessions)
        return out

    def _eligible_observation(self, rec: dict, current_sid: str) -> dict | None:
        eligible = []
        for obs in rec.get("observations") or []:
            sid = str(obs.get("session_id") or "")
            if sid == current_sid:
                continue
            if sid == "__manual__" or self.chat_included(sid):
                eligible.append(obs)
        if not eligible:
            return None
        return max(eligible, key=lambda o: float(o.get("updated") or 0))

    def context_for(self, current_sid: str, query: str, *, current_title: str = "") -> str:
        self.profile.check()
        if current_sid and hasattr(self, "chat_recall_enabled") and not self.chat_recall_enabled(current_sid):
            return ""
        if not self.config.get("enabled", True):
            return ""

        raw_query = (query or "") + " " + (current_title or "")
        qterms = _tokens(raw_query)
        qlow = re.sub(r"\s+", " ", raw_query.lower()).strip()
        meta_phrases = (
            "what do you remember", "what do you recall", "what can you remember",
            "remember from our", "recall from our", "remember from the rest",
            "past conversations", "previous conversations", "other conversations",
            "older conversations", "past chats", "previous chats", "other chats",
            "older chats", "past sessions", "previous sessions", "other sessions",
            "what do you know about me", "from our conversations", "from our chats",
            "from our sessions", "rest of our conversations", "across our conversations",
            "conversation history", "chat history",
        )
        meta_mode = any(p in qlow for p in meta_phrases)

        now = time.time()
        fact_rows = []
        with self.lock:
            fact_items = list(self.data.get("facts", {}).items())
            chat_items = list(self.data.get("chats", {}).items())

        for key, rec in fact_items:
            if not isinstance(rec, dict):
                continue
            obs = self._eligible_observation(rec, current_sid)
            if not obs:
                continue
            text = f"{key} {obs.get('value') or ''} {' '.join(obs.get('tags') or [])} {rec.get('kind') or ''}"
            terms = _tokens(text)
            overlap = len(qterms & terms)
            importance = int(obs.get("importance") or 2)
            kind = str(rec.get("kind") or "other")
            age_days = max(0.0, (now - float(obs.get("updated") or now)) / 86400.0)
            recency = max(0.0, 2.0 - math.log2(1.0 + age_days / 14.0))
            global_bonus = 3.0 if kind in {"profile", "preference", "constraint", "relationship"} and importance >= 4 else 0.0
            durable_bonus = 1.8 if kind in {"profile","preference","project","decision","constraint","workflow","relationship"} else 0.0
            score = overlap * 5.0 + importance * 1.4 + recency + global_bonus
            if meta_mode:
                score += durable_bonus + importance * 0.8
                fact_rows.append((score, key, rec, obs))
            elif overlap or global_bonus or importance >= 5:
                fact_rows.append((score, key, rec, obs))

        fact_rows.sort(key=lambda x: x[0], reverse=True)
        fact_rows = fact_rows[: int(self.config.get("max_facts") or 10)]

        capsule_rows = []
        for sid, st in chat_items:
            if sid == current_sid or not isinstance(st, dict) or not st.get("included", True):
                continue
            cap = str(st.get("capsule") or "").strip()
            if not cap:
                continue
            text = f"{st.get('title') or ''} {cap} {' '.join(st.get('tags') or [])}"
            terms = _tokens(text)
            overlap = len(qterms & terms)
            age_days = max(0.0, (now - float(st.get("updated") or now)) / 86400.0)
            recency = max(0.0, 2.0 - math.log2(1.0 + age_days / 21.0))
            if meta_mode:
                capsule_rows.append((overlap * 4.0 + recency, sid, st))
            elif overlap:
                capsule_rows.append((overlap * 4.0 + recency, sid, st))

        capsule_rows.sort(key=lambda x: x[0], reverse=True)
        cap_limit = int(self.config.get("max_capsules") or 2)
        if meta_mode:
            cap_limit = max(3, min(6, cap_limit + 2))
        capsule_rows = capsule_rows[:cap_limit]

        if not fact_rows and not capsule_rows:
            return ""

        lines = [
            "Persistent memory overview from prior INCLUDED chats (broad recall request):"
            if meta_mode else
            "Persistent memory from prior chats selected for relevance:"
        ]
        if fact_rows:
            lines.append("Facts:")
            for _score, key, rec, obs in fact_rows:
                lines.append(f"- [{rec.get('kind') or 'memory'}] {key}: {obs.get('value')}")
        if capsule_rows:
            lines.append("Prior chat capsules:")
            for _score, _sid, st in capsule_rows:
                lines.append(f"- {st.get('title') or 'Prior chat'}: {st.get('capsule')}")

        limit = max(512, int(self.config.get("context_tokens") or 700) * 4)
        text = "\n".join(lines)
        if len(text) > limit:
            text = text[:limit].rsplit("\n", 1)[0].rstrip() + "\n- [memory context truncated to budget]"
        return text
