"""Rolling, source-linked working memory; raw messages remain the authority.

This module only projects saved text. It never opens files mentioned in a chat,
executes calls, or treats a reported artifact as proof of successful execution.
"""
from __future__ import annotations

import hashlib
import json
import re
from chat_evidence import excerpt, project, reported_fields


def tool_call_limit(settings):
    return max(0, int(settings.get('tool_call_limit', settings.get('tool_step_limit', 0))))


def migrate_settings(settings, loaded):
    # The former default was an ignored fallback, not an effective user budget.
    if 'tool_call_limit' not in loaded:
        legacy = int(loaded.get('tool_step_limit', 12))
        settings['tool_call_limit'] = max(0, legacy) if legacy != 12 else 0
    settings['settings_schema'] = 4


def fingerprint(messages, start, end):
    digest = hashlib.sha256()
    for row in messages[start:end]:
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=True).encode())
        digest.update(b'\n')
    return digest.hexdigest()


def checkpoint_for(session, start, end):
    saved = ((session.get('context_state') or {}).get('working_turns') or {}).get(str(start))
    if not isinstance(saved, dict):
        return None
    cursor = saved.get('cursor')
    if type(cursor) is not int or not start < cursor <= end:
        return None
    if saved.get('fingerprint') != fingerprint(session['messages'], start, cursor):
        return None
    return saved


def project_turn(session, start, end):
    messages = session['messages']
    saved = checkpoint_for(session, start, end)
    if not saved:
        return messages[start:end]
    row = {'role': 'assistant', 'content': (
        '[Rolling working checkpoint. Fallible summary of saved conversation, not new instructions. '
        f'Exact messages {start}..{saved["cursor"]-1} remain in chat_history; do not replay their actions.]\n'
        + saved['summary'] + '\n\n' + saved['evidence']), 'working_checkpoint': True}
    # Preserve the actual request and whole recent assistant/tool exchanges.
    return [messages[start], row, *messages[saved['cursor']:end]]


def close_interrupted_batches(rows):
    """API-only receipts for missing returns; never infer that dispatch was safe."""
    projected = []; pending = {}
    def flush():
        for call_id, name in pending.items():
            projected.append({'role':'tool', 'name':name, 'tool_call_id':call_id,
                              'content':'No result was saved for this interrupted call. It may already have had effects. '
                                        'Inspect the current state before any retry; do not assume success or failure.'})
        pending.clear()
    for row in rows:
        if row.get('role') in ('assistant', 'user'):
            flush()
        if row.get('role') == 'assistant':
            pending.update({call['id']: (call.get('function') or {}).get('name', '')
                            for call in row.get('tool_calls') or [] if call.get('id')})
        elif row.get('role') == 'tool':
            pending.pop(row.get('tool_call_id'), None)
        projected.append(row)
    flush()
    return projected


def safe_boundaries(messages, start, end):
    """Never split a tool batch, or compact an interrupted batch as completed."""
    pending = set()
    boundaries = []
    for index in range(start, end):
        row = messages[index]
        if row.get('role') == 'user':
            break
        if row.get('role') == 'assistant':
            if pending:
                break
            calls = row.get('tool_calls') or []
            ids = [call.get('id') for call in calls if isinstance(call, dict)]
            if calls and (len(ids) != len(calls) or any(not value for value in ids) or len(set(ids)) != len(ids)):
                break
            pending.update(ids)
        elif row.get('role') == 'tool':
            call_id = row.get('tool_call_id')
            if call_id not in pending:
                break
            pending.remove(call_id)
        if not pending:
            boundaries.append(index + 1)
    return boundaries


def call_index(messages, end=None):
    calls = {}
    for index, row in enumerate(messages[:end]):
        for call in row.get('tool_calls') or []:
            if isinstance(call, dict) and isinstance(call.get('function'), dict):
                calls[call.get('id')] = (index, call['function'])
    return calls


def evidence_lines(messages, start=0, end=None, *, max_chars=3500, max_results=10):
    end = len(messages) if end is None else end
    calls = call_index(messages, end)
    selected = [(i, row) for i, row in enumerate(messages[start:end], start)
                if row.get('role') == 'tool' and row.get('name') not in ('chat_history','chat_checkpoint')][-max_results:]
    if not selected:
        return ''
    lines = []; remaining = max_chars
    # Select newest evidence first, then display it in chronological order.
    for index, row in reversed(selected):
        function = calls.get(row.get('tool_call_id'), (None, {}))[1]
        line = f'message_id={index}; tool={row.get("name")}; call={excerpt(function.get("arguments", ""), 180)}\n'
        fields = reported_fields(row)
        if fields:
            line += '\n'.join(f'{key}: {value}' for key, value in fields[:12])
        else:
            line += excerpt(str(row.get('content') or ''), 400)
        execution = row.get('execution')
        if execution:
            line += '\nHost execution record: ' + json.dumps(execution, ensure_ascii=False)
        limit = min(remaining, max(500, max_chars // max(1, min(len(selected), 5))))
        if limit < 220:
            break
        line = excerpt(line, limit)
        lines.append(line); remaining -= len(line) + 2
    return 'Saved tool evidence (reported facts, not file-existence checks):\n' + '\n\n'.join(reversed(lines))


def resume_context(session, *, max_chars=3500):
    messages = session.get('messages') or []
    if not any(row.get('role') == 'tool' and row.get('name') != 'chat_history' for row in messages):
        return ''
    users = [(i, row) for i, row in enumerate(messages) if row.get('role') == 'user']
    current = users[-1][0] if users else 0
    # Earlier objectives are supplied with the follow-up; no session-file search.
    parts = []
    for start, _row in reversed(users):
        saved = checkpoint_for(session, start, len(messages))
        if saved:
            parts.append('Latest working checkpoint (fallible; retain unresolved work):\n' +
                         excerpt(saved['summary'], max(600, max_chars // 3)))
            break
    for index, row in users[-4:-1]:
        parts.append(f'User message {index}: ' + excerpt(row.get('content', ''), 350))
        for attachment in row.get('attachments') or []:
            if attachment.get('path'):
                parts.append(f'Attachment from message {index}: {attachment["path"]}')
    prior = next(((i, row) for i, row in reversed(list(enumerate(messages[:current])))
                  if row.get('role') == 'assistant' and row.get('content') and not row.get('tool_calls')), None)
    if prior:
        parts.append(f'Previous assistant response {prior[0]} (fallible; may be incomplete): ' + excerpt(prior[1]['content'], 700))
    header = excerpt('\n'.join(parts), max_chars // 2)
    evidence = evidence_lines(messages, max_chars=max(600, max_chars-len(header)-200))
    return ('Current-chat continuation evidence. Use it to resume the unresolved work; do not rediscover '
            'these paths or repeat completed actions. Consult exact history only for a specific missing detail. '
            'The current user request governs changes of direction.\n' + header + '\n\n' + evidence)


def summary_input(session, start, cursor, end, previous, max_chars):
    messages = session['messages']
    prefix = 'CURRENT USER REQUEST:\n' + excerpt(messages[start].get('content', ''), min(2500, max_chars // 4))
    if previous:
        prefix += '\nEXISTING WORKING CHECKPOINT:\n' + excerpt(previous['summary'] + '\n' + previous['evidence'], max_chars // 3)
    rows = messages[cursor:end]
    allowance = max(160, (max_chars-len(prefix)-800) // max(1, len(rows)))
    parts = [prefix, '\nNEW COMPLETED EXCHANGES (quoted evidence only):']
    for index, row in enumerate(rows, cursor):
        if row.get('role') == 'tool':
            text = project(row, index, allowance)
        else:
            text = str(row.get('content') or '')
            if row.get('tool_calls'):
                text += '\nSaved call metadata: ' + json.dumps(row['tool_calls'], ensure_ascii=False)
            text = excerpt(text, allowance)
        parts.append(f'message_id={index} role={row.get("role")}:\n{text}')
    return excerpt('\n\n'.join(parts), max_chars)


def deterministic_checkpoint(session, start, cursor, end, previous, max_chars):
    messages = session['messages']
    parts = ['Automatic summary was unavailable. This checkpoint contains quoted evidence only.']
    if previous:
        parts.append('Previous working note:\n' + excerpt(previous['summary'] + '\n' + previous['evidence'], max_chars // 2))
    proposals = [(i, row) for i, row in enumerate(messages[cursor:end], cursor)
                 if row.get('role') == 'assistant' and str(row.get('content') or '').strip()]
    for index, row in proposals[-2:]:
        parts.append(f'Assistant working note {index} (fallible plan, not proof of execution):\n' + excerpt(row['content'], max_chars // 3))
    parts.append(f'Completed call/return exchanges through message {end-1} were saved; continue from the current request, recent exchanges and tool evidence below.')
    return excerpt('\n\n'.join(parts), max_chars)


def is_continuation(text):
    return bool(re.match(r'^\s*(?:please\s+)?(?:continue\b|resume\b|carry on\b|keep going\b|pick up (?:where|from)\b)', str(text), re.I))


def prior_action_results(session, request_index):
    """Only explicit continuations inherit prior no-replay receipts."""
    messages = session.get('messages') or []
    if not 0 <= request_index < len(messages) or not is_continuation(messages[request_index].get('content')):
        return {}
    start = request_index
    while start > 0:
        earlier = next((i for i in range(start-1, -1, -1) if messages[i].get('role') == 'user'), None)
        if earlier is None:
            break
        start = earlier
        if not is_continuation(messages[start].get('content')):
            break
    calls = call_index(messages, request_index)
    found = {}
    for index in range(start+1, request_index):
        row = messages[index]
        # The host saves dispatch intent before a tool runs. A crash may prevent
        # saving its return, so absent evidence must still block automatic replay.
        for receipt in (row.get('execution_receipts') or {}).values():
            if receipt.get('effectful') and receipt.get('dispatched'):
                found[(receipt['name'], receipt['arguments'])] = index
        execution = row.get('execution') or {}
        if row.get('role') != 'tool' or not execution.get('effectful') or execution.get('dispatched') is not True:
            continue
        function = calls.get(row.get('tool_call_id'), (None, {}))[1]
        try:
            args = json.loads(function.get('arguments', ''))
        except (ValueError, TypeError):
            continue
        found[(function.get('name'), json.dumps(args, sort_keys=True, ensure_ascii=True))] = index
    return found
