"""Bounded, local coding-task routing. Never reads tool output or edits preferences."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

MODEL_ID = 'swift27-abliterated-q4'
GENERAL_IDS = frozenset(('qwen27-q4', 'qwen27-q5'))
_CODE = re.compile(r'```|\b(?:debug|refactor|unittest|pytest|traceback|stack trace|pull request|codebase|repository|javascript|typescript|python|powershell|sql query|segfault|compiler|unit tests?)\b|\b(?:write|fix|review|implement|optimize|explain|build|create|edit|test)\b.{0,100}\b(?:code|script|function|class|api|app|website|program|algorithm|regex|software|bug)\b', re.I | re.S)
_FOLLOWUP = re.compile(r'^(?:yes|ok(?:ay)?|continue|go ahead|do (?:it|that)|try again|that (?:failed|worked)|still (?:broken|failing)|now (?:fix|test|run)|add |change |make it |use |also )', re.I)


def register_installed(root, policy, catalog):
    """Version-aware discovery without writing over saved choices on upgrade."""
    if any(m.get('id') == MODEL_ID for m in policy.get('models', [])):
        return
    if (Path(root)/'Agent/academic_policy.py').is_file():
        return
    if catalog.stat().st_size > 16384:
        raise ValueError('Coding model catalog exceeds the bounded size')
    model = json.loads(catalog.read_text(encoding='utf-8'))
    if model.get('id') != MODEL_ID:
        raise ValueError('Unexpected coding model catalog identifier')
    from runtime_policy import portable_path
    if all(portable_path(Path(root), model[key]).is_file() for key in ('path', 'projector')):
        policy.setdefault('models', []).append(model)


def _text(message):
    content = message.get('content', '')
    if isinstance(content, list):
        content = '\n'.join(str(row.get('text', ''))[:4096] for row in content[:16]
                            if isinstance(row, dict) and row.get('type') == 'text')
    value = str(content)[:12000]
    for item in (message.get('attachments') or [])[:12]:
        if isinstance(item, dict) and Path(str(item.get('path', ''))).suffix.lower() in (
                '.py', '.js', '.ts', '.tsx', '.jsx', '.rs', '.go', '.cpp', '.c', '.cs', '.java', '.ps1', '.sh', '.sql'):
            value += '\n``` source attachment'
    return value


def coding_request(messages):
    users = [m for m in (messages or [])[-40:] if isinstance(m, dict) and m.get('role') == 'user'][-3:]
    if not users:
        return False
    current = _text(users[-1]).strip()
    if _CODE.search(current):
        return True
    return bool(len(current) < 700 and _FOLLOWUP.search(current) and
                any(_CODE.search(_text(m)) for m in users[:-1]))


def route_policy(root, policy, profile, messages):
    """Return a request-only override; small/manual/standard choices stay pinned."""
    if policy.get('coding_routing', 'off') != 'automatic' or not coding_request(messages):
        return None
    selection = policy.get('selection', 'auto')
    if selection not in GENERAL_IDS and not (selection == 'auto' and profile == 'deep' and
                                             policy.get('variant_preference') == 'uncensored'):
        return None
    if policy.get('weight_edit_profile', 'original') != 'original':
        return None
    model = next((m for m in policy.get('models', []) if m.get('id') == MODEL_ID), None)
    if not model or not model.get('coding_route_validated'):
        return None
    from runtime_policy import portable_path
    for value in [model.get('path')] + ([model['projector']] if model.get('projector') else []):
        if not value or not portable_path(Path(root), value).is_file():
            return None
    routed = copy.deepcopy(policy)
    routed.update(selection=MODEL_ID, weight_edit_profile='original')
    return routed
