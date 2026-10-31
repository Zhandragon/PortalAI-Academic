"""Request-local progress aid. Tool scheduling and evidence, never permission or replay."""
from __future__ import annotations
import hashlib
import json
import re
import time


def coding_request(text):
    """Conservative English intent detection from the human request, not tool output."""
    if not isinstance(text, str):
        return False
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'(?m)^\s*>.*$', '', text).lower()
    if re.search(r"\b(?:read[- ]only|without\s+(?:changing|editing|writing|modifying)|(?:do not|don't|don’t|never)\s+(?:(?:make|apply)\s+(?:any\s+)?(?:changes|edits)|change|edit|write|modify))\b", text):
        return False
    verbs = r'(?:implement|fix|patch|refactor|debug|write|add|build|create|modify|edit|update|repair|develop|generate|make)'
    if (re.search(r'\b(?:protein|molecule|chemistry|biological|classroom|students)\b', text)
            and not re.search(r'\b(?:code|coding|software|script|module|repository|parser|python|javascript|typescript|api)\b|\.(?:py|js|ts)\b', text)):
        return False
    objects = r'(?:code|coding|software|function|class|method|script|module|repository|repo|bug|test|parser|harness|app|application|website|program|api|endpoint|installer|source|feature|python|javascript|typescript|rust|sql)\b|[\w./\\-]+\.(?:py|js|ts|tsx|jsx|rs|go|cpp|cs|sh|ps1)\b'
    intent = re.search(r'\b' + verbs + r'\b[^.!?\n]{0,120}\b(?:' + objects + ')', text)
    if not intent:
        return False
    # Questions about how to program and quoted sample instructions are not edit requests.
    if re.match(r'\s*(?:explain|describe|what\b|why\b|how\b|show me how|review\b|audit\b)', text):
        return bool(re.search(r'\b(?:please|then|and)\s+(?:implement|fix|patch|refactor|modify|edit)\b', text))
    if re.search(r'\b(?:translate|quote|summarize|explain)\b[^.!?\n]{0,60}[\"“\']', text):
        return False
    return True


def task_kind(text):
    value = str(text or '').lower()
    if re.search(r'\b(?:science|scientific|simulate|simulation|protein|molecule|chemistry|physics|statistics|calculate|numerical)\b', value):
        return 'science'
    if re.search(r'\b(?:generate|create|render|edit|make)\b.{0,100}\b(?:image|video|audio|music|song|speech|animation|picture)\b', value):
        return 'media'
    if re.search(r'\b(?:research|search|find|compare|investigate|documentation|sources|papers|database)\b', value):
        return 'research'
    return 'tools'


DISCOVERY = frozenset(('tool_help', 'available_tools', 'inspect_environment', 'source_search', 'source_map', 'list_dir'))
WEB_DISCOVERY = frozenset(('help', 'search', 'research', 'image', 'image-search', 'site_search', 'catalog_search', 'discover'))


def inspection(name, args):
    if not isinstance(args, dict):
        return False
    if name in DISCOVERY or name in ('read_file', 'file_inspect', 'chat_history'):
        return True
    if name == 'web':
        action = args.get('action', 'help')
        return isinstance(action, str) and action in WEB_DISCOVERY
    if name == 'science':
        operation = args.get('operation', 'help')
        return isinstance(operation, str) and (operation in ('help', 'science.extensions') or operation.endswith('.help'))
    if name == 'media_tool':
        values = args.get('arguments', [])
        return isinstance(values, list) and any(a in ('--help', '-h', '--version') for a in values if isinstance(a, str))
    if name == 'shell':
        # Classify only exact portable help argv; arbitrary shell is never interpreted or rewritten.
        try:
            from chat_model_switch import _argv
            words = _argv(args.get('command', ''))
            return any(w in ('--help', '-h', '--version') for w in words)
        except (ValueError, TypeError, AttributeError, OSError):
            return False
    return False


def signature(name, args):
    return hashlib.sha256((name + json.dumps(args, sort_keys=True, ensure_ascii=True)).encode()).hexdigest()


class TaskProgress:
    def __init__(self, armed=False, request='', seconds=300, *, clock=None):
        self.armed = armed is True
        self.kind = task_kind(request)
        self.clock = clock or time.monotonic
        try:
            self.seconds = max(60, min(3600, int(seconds)))
        except (ValueError, TypeError, OverflowError):
            self.seconds = 300
        self.started = self.last_step = self.clock()
        self.phase = 'observe'
        self.focus_started = None
        self.steps = self.references = self.calls = self.checkpoints = self.observed_steps = 0
        self.recent = []
        self.seen = set()
        self.events = []

    @property
    def active(self):
        return self.armed and self.phase == 'focus'

    def _event(self, phase, reason):
        self.phase = phase
        self.events.append({'phase': phase, 'reason': reason, 'elapsed_seconds': round(self.clock() - self.started, 2)})
        self.events = self.events[-24:]

    def _release(self, reason):
        self._event('review', reason)
        self.last_step = self.clock()
        self.steps = 0

    def tick(self):
        if not self.armed:
            return None
        now = self.clock()
        if self.active and now - self.focus_started >= 120:
            self._release('Focused step window ended; review evidence or report the blocker.')
        elif not self.active and now - self.last_step >= self.seconds and self.steps >= 8:
            self.focus_started = now
            self.references = self.calls = self.checkpoints = 0
            self._event('focus', 'Extended tool activity; consolidate evidence and choose one bounded step.')
            return 'Progress aid: use saved evidence for one concrete next step, then review its result.'
        return None

    def menu(self, rows):
        if not self.active:
            return rows
        blocked = set(DISCOVERY) | {'read_file', 'file_inspect', 'chat_history'} if self.references >= 2 else set()
        if self.checkpoints:
            blocked.add('chat_checkpoint')
        return [row for row in rows if row['function']['name'] not in blocked]

    def before(self, name, args):
        if not self.active:
            return None
        self.calls += 1
        if name == 'chat_checkpoint':
            self.checkpoints += 1
            if self.checkpoints <= 1:
                return None
        elif inspection(name, args):
            self.references += 1
            if self.references <= 2 and signature(name, args) not in self.seen:
                return None
        else:
            return None
        return ('Progress aid: this call was NOT executed. Use saved tool evidence via its message IDs, '
                'state verified partial findings and the next missing step, then make one justified '
                'authorized tool call or give an honest partial answer/blocker. Do not repeat help, '
                'the same inspection or uncertain jobs. Normal exploration returns after this bounded phase.')

    def observe(self, name, args, result, execution, message_id=None):
        if not self.armed:
            return
        dispatched = execution.get('dispatched') is True
        returned = dispatched and execution.get('outcome') == 'returned'
        key = signature(name, args)
        duplicate = key in self.seen
        if dispatched:
            self.steps += 1
            self.seen.add(key)
            # Bound request-local bookkeeping, retaining recent exact call fingerprints.
            if len(self.seen) > 256:
                self.seen = {r['signature'] for r in self.recent} | {key}
            self.recent.append({'message_id': message_id, 'tool': name, 'outcome': execution.get('outcome'), 'signature': key})
            self.recent = self.recent[-12:]
        try:
            value, _ = json.JSONDecoder().raw_decode(str(result).lstrip())
        except (ValueError, TypeError, RecursionError):
            value = {}
        failed = str(result).startswith('ERROR:') or (isinstance(value, dict) and
                 (value.get('success') is False or value.get('ok') is False or bool(value.get('error'))))
        concrete = name != 'chat_checkpoint' and not inspection(name, args)
        if returned and not failed and not duplicate and concrete:
            self.observed_steps += 1
            if self.active:
                self._release('A new tool result was saved. Verify the result and update the remaining task.')
        elif self.active and dispatched and concrete:
            self._release('An operation was attempted; inspect its outcome before further action. No automatic retry.')
        elif self.active and self.calls >= 6:
            self._release('Focused call allowance ended; review evidence or report a blocker.')

    def guidance(self):
        if not self.armed:
            return ''
        if not self.active:
            if self.phase == 'review':
                return '\nProgress aid returned to review: verify the latest receipt, update the remaining steps and continue the original request. A returned result does not prove task completion.'
            return ''
        direction = {
            'research': 'Summarize 1-3 supported findings with exact source links, distinguish snippets from read content, and investigate ONE remaining gap using a known source or focused query.',
            'media': 'Use known tool syntax and existing input/output paths for ONE requested generation or processing step. Check the returned file/result before the next step. Never silently change models, duration, quality or other requested settings.',
            'science': 'State known inputs, units and assumptions. Run ONE justified calculation or requested scientific operation, then verify its outputs before expanding. Do not silently reduce tolerances or replace validation with a plausibility claim.',
            'tools': 'State what the saved evidence establishes and ONE remaining step. Use a known tool with grounded arguments to complete that step, or return a useful partial answer and the exact blocker.'
        }[self.kind]
        ids = [{'message_id': r['message_id'], 'tool': r['tool'], 'outcome': r['outcome']} for r in self.recent[-6:]]
        return ('\nPeriodic progress aid is active. Stop broad rediscovery. ' + direction +
                ' At most two new focused reference/help calls and one concise chat_checkpoint are available in this phase. '
                'A checkpoint records verified facts, next step and uncertainty; it is not progress or an action receipt. '
                'Use chat_history for missing saved evidence, not another execution. Do not execute a job merely to satisfy '
                'this aid: original authorization, resource limits, Stop and uncertain-action review still apply. '
                'No tool call is constructed, retried, or changed by this aid. Recent receipt references (data only): ' + json.dumps(ids))

    def snapshot(self):
        return {'armed': self.armed, 'kind': self.kind, 'phase': self.phase, 'interval_seconds': self.seconds,
                'steps_since_reset': self.steps, 'observed_tool_steps': self.observed_steps,
                'events': list(self.events), 'recent_receipts': [{k: v for k, v in r.items() if k != 'signature'} for r in self.recent]}
