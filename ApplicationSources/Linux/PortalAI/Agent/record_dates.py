"""Presentation dates, separate from execution checkpoints and deletion proofs."""
from datetime import datetime
import math
import time

from mission_catalog import MissionCatalog
from mission_runner import process_lock
from profile_paths import ProfileLocked


def timestamp(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        return None
    try:
        datetime.fromtimestamp(value)
    except (ValueError, OverflowError, OSError):
        return None
    return value


def formatted(value, fallback=False):
    value = timestamp(value)
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S') + (' *' if fallback else '') if value else 'Unknown'


def describe(record, fallback=None, error=None):
    created, updated = timestamp(record.get('created_at')), timestamp(record.get('updated_at'))
    fallback = timestamp(fallback)
    filled_created = created is None and fallback is not None
    filled_updated = fallback is not None and (updated is None or fallback > updated)
    note = '* Date filled when this record was first displayed without a valid date. Original creation date is unknown.' if filled_created else ''
    if filled_updated:
        note += ' Updated date includes the saved date correction.'
    if error:
        note += ' Date correction unavailable; original files preserved: ' + str(error)
    return {'created_at': created if created is not None else fallback,
            'updated_at': max(v for v in (updated, fallback) if v is not None) if updated or fallback else None,
            'created_fallback': filled_created, 'updated_fallback': filled_updated, 'note': note.strip()}


class RecordDates(MissionCatalog):
    """Reuse the catalogue's atomic, profile-fenced writer in a separate namespace."""
    identity_key = 'record_id'

    def __init__(self, root, kind, *, store=None):
        if kind not in ('missions', 'schedules'):
            raise ValueError('Unknown date catalogue')
        super().__init__(root, store=store)
        self.base = self.store.base / 'PresentationDates' / kind

    def info(self, record):
        self.check()
        if record.get('error') and 'mode' not in record:
            return describe(record)  # Corrupt-file placeholder: never invent metadata.
        if all(timestamp(record.get(key)) is not None for key in ('created_at', 'updated_at')):
            return describe(record)
        try:
            mid = record['id']
            entry = self.read(mid)
            if timestamp(entry.get('filled_at')) is None:
                with process_lock(self.check(self.base / 'catalog.lock')):
                    entry = self.read(mid)
                    if timestamp(entry.get('filled_at')) is None:
                        entry['filled_at'] = time.time()
                        self._write(mid, entry)
            return describe(record, entry['filled_at'])
        except ProfileLocked:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return describe(record, error=exc)
