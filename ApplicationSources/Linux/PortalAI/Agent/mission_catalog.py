"""Private mission presentation metadata; never an execution or Stop policy.

Delete is reversible removal from the working list. Original checkpoints,
history, memory, child links and generated files retain their existing paths.
Changed or re-armed records always become visible again.
"""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from mission_runner import Missions, ACTIVE, process_lock
from mission_supervisor import read_policy
from profile_paths import capture, _contained, ProfileLocked
from runtime_policy import require_space


VIEWS = ('User & unclassified', 'All records', 'Validation tests', 'Deleted (recoverable)')
LEGACY_TEST_PREFIXES = (
    'Perform this exact bounded installation self-test.',
    'Self-test the offline VM.',
    'Bounded execution-mode routing self-test',
    'This is a compaction self-test. Thirty note actions have already run.',
    'Stop lifecycle test: do not execute any model actions',
    'Bounded schedule regression test ',
)


def fingerprint(mission):
    return hashlib.sha256(json.dumps(mission, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


def visible(row, view):
    if view == 'All records': return True
    if view == 'Deleted (recoverable)': return row['deleted']
    if row['deleted']: return False
    if view == 'Validation tests': return row['origin']['kind'] in {'validation', 'legacy_validation'}
    # A legacy heuristic never hides an unknown user mission by default.
    return row['origin']['kind'] != 'validation'


class MissionCatalog:
    def __init__(self, root, *, store=None):
        self.store = store or Missions(root)
        self.root = self.store.root
        if Path(root).resolve() != self.root: raise ValueError('Mission store belongs to another portable root')
        self.context = capture(self.root)
        self.base = self.store.base / 'Catalog'
        self.errors = []

    def check(self, path=None):
        if capture(self.root) != self.context:
            raise ProfileLocked('The mission catalogue login ended')
        return _contained(self.root, path or self.base)

    def path(self, mid):
        self.store.folder(mid)
        return self.check(self.base / (mid + '.json'))

    def read(self, mid):
        path = self.path(mid)
        if not path.exists(): return {'version': 1, 'mission_id': mid}
        if path.stat().st_size > 128 * 1024: raise ValueError('Oversized mission catalogue entry; original preserved')
        data = json.loads(path.read_text(encoding='utf-8'))
        self.check(path)
        if not isinstance(data, dict) or data.get('version') != 1 or data.get('mission_id') != mid:
            raise ValueError('Invalid mission catalogue entry; original preserved')
        return data

    def _write(self, mid, entry):
        path = self.path(mid)
        encoded = json.dumps(entry, indent=2, ensure_ascii=True)
        if len(encoded.encode('utf-8')) > 128 * 1024: raise ValueError('Mission catalogue entry is too large')
        require_space(self.root, len(encoded.encode('utf-8')) + 4096)
        self.check(path.parent).mkdir(parents=True, exist_ok=True)
        part = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        identity = None
        published = False
        try:
            self.check(part)
            with part.open('x', encoding='utf-8') as output:
                stat = os.fstat(output.fileno()); identity = (stat.st_dev, stat.st_ino)
                output.write(encoded)
                output.flush(); os.fsync(output.fileno())
            self.check(path); self.check(part)
            os.replace(part, path)
            published = True
            self.check(path)
        except BaseException:
            if published:
                self._remove_owned(path, identity)
            raise
        finally:
            self._remove_owned(part, identity)

    def _remove_owned(self, path, identity):
        # Cleanup only this writer's own newly created inode, even on logout.
        _contained(self.root, path)
        try: stat = path.lstat()
        except FileNotFoundError: return
        if identity and (stat.st_dev, stat.st_ino) == identity and path.is_file(): path.unlink()

    def mark_origin(self, mid, kind='user', source='Controls'):
        if kind not in {'user', 'validation'} or not isinstance(source, str) or len(source) > 160:
            raise ValueError('Invalid mission origin metadata')
        self.store.load(mid)
        with process_lock(self.check(self.base / 'catalog.lock')):
            entry = self.read(mid)
            entry['origin'] = {'kind': kind, 'source': source, 'recorded_at': time.time()}
            self._write(mid, entry)

    @staticmethod
    def origin(mission, entry):
        explicit = entry.get('origin', {})
        if isinstance(explicit, dict) and explicit.get('kind') in {'user', 'validation'}:
            return {**explicit, 'label': 'User mission' if explicit['kind'] == 'user' else 'Validation test',
                    'confirmed': True}
        if any(mission['objective'].startswith(prefix) for prefix in LEGACY_TEST_PREFIXES):
            return {'kind': 'legacy_validation', 'label': 'Legacy test?', 'confirmed': False,
                    'source': 'Matches known validation-script wording; original origin was not recorded'}
        return {'kind': 'unknown', 'label': 'Unclassified', 'confirmed': False,
                'source': 'Legacy mission without recorded origin; treated as user work'}

    def _family(self, mid, missions):
        if mid not in missions: raise ValueError('Mission checkpoint is missing or unreadable')
        if missions[mid].get('parent'): raise ValueError('Select the top-level mission; its subtasks are kept together')
        family = {}
        def visit(current, parent=None):
            if current in family: raise ValueError('Duplicate/cyclic mission link; review required')
            row = missions.get(current)
            if row is None or row.get('parent') != parent:
                raise ValueError('Broken child/parent reference; review required')
            if len(family) >= 128: raise ValueError('Mission family is too large for this operation')
            family[current] = row
            for child in row['children']: visit(child, current)
        visit(mid)
        for key, row in missions.items():
            if key not in family and (row.get('parent') in family or any(child in family for child in row['children'])):
                raise ValueError('A mission outside this family references it; review the links first')
        return family

    def _stopped_family(self, family):
        for mid, mission in family.items():
            if mission['status'] in ACTIVE:
                raise ValueError('Stop the mission family and wait for its worker to finish before deleting')
            if read_policy(self.store, mid).get('enabled'):
                raise ValueError('This mission family is still armed. Stop it before deleting')
            if mission.get('schedule_id'):
                raise ValueError('Scheduled run records are retained with their schedule; they cannot be deleted here')
        from mission_schedule import Schedules
        for schedule in Schedules(self.root).list():
            if schedule.get('error') and 'active_run' not in schedule:
                raise ValueError('An unreadable schedule may reference this mission; review it first')
            if schedule.get('active_run') in family:
                raise ValueError('A schedule still references this mission as its active run')

    def _deletion_current(self, entry, missions):
        deletion = entry.get('deleted')
        if not isinstance(deletion, dict): return False
        fingerprints = deletion.get('checkpoints')
        if not isinstance(fingerprints, dict) or not fingerprints: return False
        try:
            family = self._family(entry['mission_id'], missions)
            if set(family) != set(fingerprints): return False
            if any(fingerprint(row) != fingerprints[mid] for mid, row in family.items()): return False
            self._stopped_family(family)
        except ProfileLocked: raise
        except (OSError, ValueError, KeyError, TypeError): return False
        return True

    def rows(self, view='All records'):
        self.check()
        missions = {row['id']: row for row in self.store.list()}
        self.errors = list(getattr(self.store, 'load_errors', []))
        entries = {}
        deleted_by = {}
        for mid in missions:
            try: entry = self.read(mid)
            except ProfileLocked: raise
            except (OSError, ValueError, TypeError) as exc:
                self.errors.append({'mission': mid, 'error': str(exc)})
                entry = {}
            entries[mid] = entry
            if self._deletion_current(entry, missions):
                for child in entry['deleted']['checkpoints']: deleted_by[child] = mid
        result = []
        for mid, mission in missions.items():
            origin = self.origin(mission, entries[mid])
            parent = mission.get('parent'); seen = {mid}
            while origin['kind'] == 'unknown' and parent in missions and parent not in seen:
                seen.add(parent)
                origin = self.origin(missions[parent], entries[parent])
                parent = missions[parent].get('parent')
            row = {'mission': mission, 'origin': origin,
                   'deleted': mid in deleted_by, 'deleted_root': deleted_by.get(mid)}
            if visible(row, view): result.append(row)
        self.check()
        return result

    def delete(self, mid):
        """Reversibly hide one stopped family; do not erase or move any records."""
        self.check()
        with ExitStack() as locks:
            locks.enter_context(process_lock(self.check(self.store.base / 'execution.lock')))
            locks.enter_context(process_lock(self.check(self.store.base / 'schedules.lock')))
            locks.enter_context(process_lock(self.check(self.base / 'catalog.lock')))
            missions = {row['id']: row for row in self.store.list()}
            if self.store.load_errors: raise ValueError('Unreadable mission checkpoints need review before deleting any family')
            family = self._family(mid, missions)
            for member in sorted(family): locks.enter_context(self.store.lock(member))
            # Re-read while worker locks are held; never archive stale UI data.
            missions = {row['id']: row for row in self.store.list()}
            if self.store.load_errors: raise ValueError('Mission checkpoints changed; review before deleting')
            family = self._family(mid, missions)
            self._stopped_family(family)
            entry = self.read(mid)
            entry['deleted'] = {'at': time.time(), 'checkpoints': {key: fingerprint(value) for key, value in family.items()},
                                'behavior': 'Hidden from working list; original records and file references retained'}
            self._write(mid, entry)
            # Concurrent arming does not share this presentation lock. A changed
            # run is never hidden: both this check and every list revalidate it.
            if not self._deletion_current(entry, {row['id']: row for row in self.store.list()}):
                raise ValueError('Mission state changed; it remains visible. Stop/review it before deleting')
            return {'mission': mid, 'records_retained': len(family), 'reversible': True, 'files_erased': 0}

    def restore(self, mid):
        self.store.load(mid)
        with process_lock(self.check(self.base / 'catalog.lock')):
            entry = self.read(mid)
            if 'deleted' not in entry: raise ValueError('This root mission has no deleted-list entry')
            entry.pop('deleted')
            entry['restored_at'] = time.time()
            self._write(mid, entry)
        return {'mission': mid, 'restored_to_list': True, 'started': False}
