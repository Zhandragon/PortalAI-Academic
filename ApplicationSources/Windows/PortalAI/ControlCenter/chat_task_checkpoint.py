"""Model-requested checkpoints inside one active chat; no background wakeups."""
from __future__ import annotations
import hashlib
import json
import re

NAME = 'chat_checkpoint'
TOOL = {'type': 'function', 'function': {
    'name': NAME,
    'description': 'Before reasoning runs out, save a concise task checkpoint and automatically continue with a fresh cycle. Call alone, between completed tool batches. State results, next step and uncertainty, not private reasoning. Cannot override Stop, login, tool budget or authorize/replay actions.',
    'parameters': {'type': 'object', 'additionalProperties': False, 'properties': {
        'summary': {'type': 'string', 'maxLength': 1800},
        'next_step': {'type': 'string', 'maxLength': 500},
        'uncertainty': {'type': 'string', 'maxLength': 500},
        'evidence_ids': {'type': 'array', 'maxItems': 12, 'items': {'type': 'integer'},
                         'description': 'Optional saved message IDs listed by the host. Omit if none apply; these are not tool-call IDs.'}},
        'required': ['summary', 'next_step']}}}


def validate(args, messages):
    if set(args) - {'summary', 'next_step', 'uncertainty', 'evidence_ids'}:
        raise ValueError('Unknown checkpoint fields')
    for key, cap in [('summary',1800), ('next_step',500), ('uncertainty',500)]:
        value=args.get(key, '')
        if not isinstance(value,str) or len(value)>cap or (key!='uncertainty' and not value.strip()):
            raise ValueError('Checkpoint '+key+' must be concise nonempty text' if key!='uncertainty' else 'Invalid uncertainty text')
    ids=args.get('evidence_ids', [])
    if not isinstance(ids,list) or len(ids)>12 or any(type(i) is not int or not 0<=i<len(messages)
            or messages[i].get('role')!='tool' or messages[i].get('name') in (NAME,'chat_history') for i in ids):
        raise ValueError('Evidence IDs must refer to saved non-checkpoint tool results')
    return {'summary':args['summary'].strip(), 'next_step':args['next_step'].strip(),
            'uncertainty':args.get('uncertainty','').strip(), 'evidence_ids':list(dict.fromkeys(ids))}


def evidence_catalog(messages):
    """Recent usable IDs and tool names only; never quote retrieved source prose."""
    rows=[]
    for index,row in enumerate(messages or ()):
        if not isinstance(row,dict) or row.get('role')!='tool' or row.get('name') in (NAME,'chat_history'):
            continue
        name=row.get('name')
        label=name if isinstance(name,str) and re.fullmatch(r'[A-Za-z][A-Za-z_0-9]{0,63}',name) else 'tool'
        rows.append(f'{index} ({label})')
    return ', '.join(rows[-12:]) or 'none yet'


def guidance(output, budget, estimated_input, settings, usage, messages=()):
    limit=max(0,int(settings.get('tool_call_limit',0)))
    remaining=str(max(0,limit-int(usage.get('calls',0)))) if limit else 'unlimited'
    checkpoints=max(0,int(settings.get('checkpoint_no_tool_limit',4)))
    checkpoint_left=str(max(0,checkpoints-int(usage.get('checkpoints_since_tool',0)))) if checkpoints else 'unlimited'
    return (f'Cycle allowance: {output} generated tokens (thinking + answer/tool call); '
            f'context {budget}, estimated input {estimated_input}; tool calls left {remaining}; '
            f'checkpoints before a new tool result {checkpoint_left}. '
            'No live remaining-token counter is available while thinking. Choose a useful step that fits; '
            'reserve room for an answer or chat_checkpoint. At a completed step or before a long reasoning phase, '
            'call chat_checkpoint alone with concise progress, next step and uncertainties. '
            'evidence_ids is optional; cite only applicable saved message IDs, or omit it. '
            'Recent valid saved result IDs: '+evidence_catalog(messages)+'. '
            'Record outcomes, '
            'not private reasoning. The host saves/compacts it and automatically starts the next cycle of this '
            'same task. Answer when done; report a real blocker. Stop/logout end continuation. '
            'Checkpoints never reset tool limits or authorize/replay actions; repeated idle checkpoints stop.')


class Cycle:
    def __init__(self, no_tool_limit=4):
        self.no_tool_limit=max(0,int(no_tool_limit))
        self.since_progress=0
        self.notes=set()
        self.results=set()

    def checkpoint(self, note):
        signature=json.dumps(note,sort_keys=True,ensure_ascii=True).casefold()
        if signature in self.notes:
            return 'The same checkpoint was repeated without a new tool result. Give the current result or blocker.'
        if self.no_tool_limit and self.since_progress>=self.no_tool_limit:
            return 'The configured checkpoint allowance without a new tool result was reached. Give the current result or blocker.'
        self.notes.add(signature);self.since_progress+=1
        return ''

    def progress(self, name, args, result):
        if name in (NAME,'chat_history','tool_help'):return
        signature=hashlib.sha256(json.dumps([name,args,result],sort_keys=True,ensure_ascii=True).encode()).hexdigest()
        if signature not in self.results:
            self.results.add(signature);self.since_progress=0;self.notes.clear()


def commit(session, start, note, budget):
    from chat_working_memory import evidence_lines, fingerprint, safe_boundaries
    messages=session['messages'];end=len(messages)
    if not 0<=start<end or messages[start].get('role')!='user' or end not in safe_boundaries(messages,start+1,end):
        raise RuntimeError('Checkpoint boundary contains an unfinished tool batch')
    summary=('Model-written task checkpoint (fallible; not evidence of actions):\n'+note['summary']+
             '\nNext step (proposal): '+note['next_step']+'\nUncertain/blocked: '+(note['uncertainty'] or 'None reported; verify results.')+
             '\nReferenced saved tool messages: '+json.dumps(note['evidence_ids']))
    # Leave the checkpoint call/result pair visible so the model receives the
    # host's actual acceptance status as well as its own fallible note.
    cursor=end-2
    record={'cursor':cursor,'summary':summary,
            'evidence':evidence_lines(messages,start+1,cursor,max_chars=min(2200,max(600,budget//4))),
            'fingerprint':fingerprint(messages,start,cursor),'model_requested':True}
    return record
