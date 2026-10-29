"""Request-scoped, bounded recovery from inspection-only coding loops.

This is a workflow gate, never a writer, permission grant or success grader.
The host arms it for detected coding requests or a one-request override.
No background timer runs, and intent detection never grants permission.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import time

CODE_SUFFIXES = frozenset(('.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css',
    '.c', '.h', '.cc', '.cpp', '.hpp', '.cs', '.go', '.rs', '.java', '.kt',
    '.swift', '.sh', '.ps1', '.bat', '.cmd', '.sql', '.rb', '.php', '.lua',
    '.r', '.m', '.vue', '.svelte'))
INSPECTIONS = frozenset(('read_file', 'source_search', 'source_map', 'list_dir',
                         'inspect_environment', 'web'))
WRITES = frozenset(('edit_file', 'write_file'))


def write_receipt(path, before):
    """Describe observed bytes, including no-op writes; no correctness claim."""
    after = path.read_bytes()
    return json.dumps({'path': str(path), 'success': True, 'changed': before != after,
        'bytes': len(after), 'before_sha256': hashlib.sha256(before).hexdigest() if before is not None else None,
        'sha256': hashlib.sha256(after).hexdigest(),
        'notice': 'File bytes observed after writing. Correctness still requires review and tests.'})


def _object(result):
    try:
        value = json.loads(result)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


class CodingStall:
    def __init__(self, armed=False, seconds=300, *, clock=None):
        self.armed = armed is True
        self.clock = clock or time.monotonic
        try: self.seconds = max(60, min(3600, int(seconds)))
        except (TypeError, ValueError, OverflowError): self.seconds = 300
        self.started = self.clock()
        self.last_progress = self.started
        self.inspections = 0
        self.paths = []
        self.phase = 'observe'
        self.burst_started = None
        self.reads = self.attempts = self.calls = self.changed_writes = 0
        self.events = []

    @property
    def implementing(self):
        return self.armed and self.phase == 'implement'

    def _event(self, phase, reason):
        self.phase = phase
        self.events.append({'phase': phase, 'reason': reason,
                            'elapsed_seconds': round(self.clock()-self.started, 2)})
        self.events = self.events[-24:]

    def tick(self):
        """Run only at a completed model/tool boundary, never interrupt a call."""
        if not self.armed: return None
        now = self.clock()
        if self.implementing and now-self.burst_started >= 120:
            self._release('Implementation window elapsed; return to review or report a blocker.')
        elif (not self.implementing and now-self.last_progress >= self.seconds
              and self.inspections >= 8 and self.paths):
            self.burst_started = now
            self.reads = self.attempts = self.calls = 0
            self._event('implement', 'Prolonged inspection without an observed code change.')
            return 'Coding stall detected: trying one small implementation step, then returning to review.'
        return None

    def _release(self, reason):
        self._event('review', reason)
        # Cooldown is not counted as productive progress in the saved metrics.
        self.last_progress = self.clock()
        self.inspections = 0

    def menu(self, rows):
        if not self.implementing: return rows
        names = WRITES | ({'read_file', 'chat_history'} if self.reads < 2 else set())
        return [row for row in rows if row['function']['name'] in names]

    def before(self, name, args):
        if not self.implementing: return None
        self.calls += 1
        if name in WRITES:
            self.attempts += 1
            return None
        if name in ('read_file', 'chat_history') and self.reads < 2:
            self.reads += 1
            return None
        return ('Coding recovery: this call was NOT executed. Make one small grounded code/test change '
                'using edit_file or write_file, or give a final blocker if the request is read-only or '
                'no safe change is justified. Broad inspection resumes after this bounded burst.')

    def observe(self, name, args, result, execution):
        if not self.armed: return
        returned = execution.get('dispatched') is True and execution.get('outcome') == 'returned'
        obj = _object(result) if returned else {}
        failed = str(result).startswith('ERROR:') or obj.get('success') is False or obj.get('ok') is False
        if returned and not failed and name in INSPECTIONS:
            self.inspections += 1
            if name == 'read_file' and obj.get('text') and isinstance(obj.get('path'), str):
                path = obj['path']
                if len(path) <= 600 and Path(path).suffix.lower() in CODE_SUFFIXES:
                    self.paths = [p for p in self.paths if p != path][-3:] + [path]
        # Only structured file tools produce this host-owned receipt. Tool
        # prose, checkpoints and arbitrary shell output cannot spoof progress.
        if (returned and name in WRITES and obj.get('success') is True
                and obj.get('changed') is True and isinstance(obj.get('bytes'), int) and obj['bytes'] > 0
                and isinstance(obj.get('path'), str)
                and Path(obj['path']).suffix.lower() in CODE_SUFFIXES
                and isinstance(obj.get('sha256'), str) and len(obj['sha256']) == 64
                and obj['sha256'] != obj.get('before_sha256')):
            self.changed_writes += 1
            self._release('Observed changed code bytes; review and test this increment next.')
        elif self.implementing and (self.attempts >= 2 or self.calls >= 6):
            self._release('Bounded implementation attempts ended; review failures before further work.')

    def guidance(self):
        if not self.armed: return ''
        if self.implementing:
            return ('\nCoding stall recovery is active for this authorized task. Stop broad exploration. '
                'Choose ONE smallest useful change from code already inspected: a focused regression test, '
                'helper or partial implementation. Use edit_file with exact observed old text, or write_file '
                'for a new draft/test. You have at most two focused file/history reads and two write attempts. '
                'Do not replace working behavior with placeholders or claim a draft is complete. '
                'If the user requested read-only work, or no grounded change is justified, answer with that blocker; '
                'this mode grants no additional authority. After a real change, review and test it before expanding. '
                'Recently observed code paths (data): '+json.dumps(self.paths[-3:]))
        if self.phase == 'review':
            return '\nCoding recovery returned to review. Inspect the saved write/error receipt and run the relevant test. A changed file is progress, not proof of correctness. Follow the original task and report unfinished work honestly.'
        return '\nCoding recovery is armed for this request only. Work normally; prolonged inspection without a code change may trigger a short implementation burst. It never authorizes work beyond the user request.'

    def snapshot(self):
        return {'armed': self.armed, 'phase': self.phase, 'stall_seconds': self.seconds,
                'inspections_since_reset': self.inspections, 'changed_writes': self.changed_writes,
                'events': list(self.events)}
