"""Small, request-scoped coding guidance; never a permission or execution gate."""
from __future__ import annotations

import re

from task_progress import coding_request


GUIDANCE = (
    '\n\nCoding discipline (perf-critical): Preserve requested behavior; avoid worse algorithmic complexity '
    'without an explicit tradeoff. Correctness comes before speed. Choose one acceptance check, inspect the relevant code, '
    'then take the next useful step instead of repeating plans. For requested optimization, measure a '
    'baseline before editing; compare the same inputs/settings afterward. Check correctness, then '
    'time/memory across representative n, 2n, 4n inputs where feasible, with bounded repeats and timeouts. '
    'Timings suggest scaling, not proof of Big-O; justify complexity from the code. Use existing approved '
    'test commands; never self-grant commands or retry uncertain effects. Reuse unchanged evidence. '
    'Once the requested checks pass, finish; repeat only after relevant changes, failures or new evidence. '
    'Report blocked/unrun checks and unmeasured claims honestly. Ordinary edits do not need benchmarks. '
    'Read-only requests stay read-only; this label grants no permissions and never authorizes a commit.'
)

_MARKER = re.compile(r'^\s*(?:\[perf-critical\]|perf-critical\s*:)', re.I)
_PERFORMANCE = re.compile(
    r'^\s*(?:please\s+)?(?:optimi[sz]e|speed up|benchmark)\b[^.!?\n]{0,120}'
    r'\b(?:code|function|script|module|algorithm|parser|app|software|python|javascript|api)\b', re.I)
_FOLLOWUP = re.compile(r'^\s*(?:yes|ok(?:ay)?|continue|go ahead|do (?:it|that)|try again)[.!\s]*$', re.I)


def _text(message):
    content = message.get('content', '')
    if isinstance(content, list):
        content = '\n'.join(row.get('text', '')[:12000] for row in content[:16]
                            if isinstance(row, dict) and row.get('type') == 'text'
                            and isinstance(row.get('text'), str))
    if not isinstance(content, str):
        return ''
    # Never activate from a quoted example or attached source/tool output.
    text = re.sub(r'```.*?(?:```|\Z)', '', content[:12000], flags=re.S)
    return re.sub(r'(?m)^\s*>.*$', '', text).strip()


def _requested(text):
    return bool(coding_request(text) or _MARKER.match(text) or _PERFORMANCE.search(text))


def guidance(messages):
    """Return fixed host text only, based on recent human intent; no I/O or model load."""
    users = [row for row in (messages or [])[-40:]
             if isinstance(row, dict) and row.get('role') == 'user'][-2:]
    if not users:
        return ''
    current = _text(users[-1])
    requested = _requested(current)
    if not requested and len(users) == 2 and _FOLLOWUP.fullmatch(current):
        requested = _requested(_text(users[-2]))
    return GUIDANCE if requested else ''
