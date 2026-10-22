"""Recovery cues for repeated discovery; never block reads or dispatch actions."""
from __future__ import annotations
import json


def recovery_context(session):
    messages = (session or {}).get('messages') or []
    start = next((i for i in range(len(messages)-1,-1,-1) if messages[i].get('role')=='user'), 0)
    calls = {}; reads = []; known = {}
    for row in messages:
        for call in row.get('tool_calls') or []:
            function = call.get('function') or {}
            if function.get('name') not in {'chat_history','available_tools'}:continue
            try:
                args = json.loads(function.get('arguments','{}'))
            except (ValueError, TypeError):
                continue
            if isinstance(args, dict):calls[call.get('id')] = (function.get('name'),args)
    for row in messages[start:]:
        if row.get('role') != 'tool':continue
        name,args = calls.get(row.get('tool_call_id'),(row.get('name'),{}))
        if name == 'chat_history':
            reads.append(args)
        else:
            # A new non-history tool is progress; do not nag after moving on.
            reads = []
            if name == 'available_tools' and isinstance(args.get('command'),str):
                command=args['command'];known[command] = known.get(command,0)+1
            else:
                known = {}
    if len(reads) < 2 and not any(count >= 2 for count in known.values()):return ''
    from tool_contracts import execution_help
    contracts = []
    for read in reads:
        index = read.get('message_id')
        if type(index) is int and 0 <= index < len(messages):
            source = messages[index]
            if source.get('name') == 'available_tools':
                _name, args = calls.get(source.get('tool_call_id'),('',{}))
                command = args.get('command')
                if isinstance(command,str):known.setdefault(command,1)
    for command in known:
        help_text = execution_help(command)
        if help_text and help_text not in contracts:contracts.append(help_text)
    if not contracts:return ''
    return ('\nHost discovery recovery: repeated catalog lookup or ' + str(len(reads)) + ' consecutive history reads. '
            'Current installed execution help is supplied completely below. If the reads were only to learn syntax, '
            'use this help for the authorized task once its inputs are known. Further lookup is for a specific '
            'missing argument or requested audit, not a prerequisite. This does not authorize an action or replay.\n'
            + '\n'.join(contracts))
