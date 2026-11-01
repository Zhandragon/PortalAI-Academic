"""Small, evidence-linked task plans saved inside the existing chat checkpoint.

This records claims and their sources, not proof that the user's goal is met.
Only returned, non-error tool records qualify as execution evidence.
"""
import json
import re
from workspace_store import digest


def request_index(session):
    messages=session.get('messages',[])
    return next((i for i in range(len(messages)-1,-1,-1) if messages[i].get('role')=='user'),-1)


def success_evidence(session,index):
    if type(index) is not int or not 0<=index<len(session.get('messages',[])):raise ValueError('Evidence must be a saved message ID')
    row=session['messages'][index]
    if row.get('role')!='tool' or row.get('name') in ('task','tool_help','chat_checkpoint','chat_history'):raise ValueError('Use the original execution result, not a plan or quotation')
    execution=row.get('execution',{})
    if execution.get('outcome')!='returned' or not execution.get('dispatched'):raise ValueError('Evidence has no confirmed tool return')
    raw=row.get('content','')
    if not isinstance(raw,str) or not raw.strip() or raw.lstrip().startswith('ERROR:'):raise ValueError('Failed or empty tool results cannot verify completion')
    try:value=json.loads(raw)
    except ValueError:value=None
    if isinstance(value,dict):
        if value.get('success') is False or value.get('isError') is True or value.get('exit_code',0)!=0 or value.get('returncode',0)!=0:
            raise ValueError('Tool returned a failure; preserve it as a blocker instead')
    return {'message_id':index,'tool':row.get('name'),'sha256':digest(row)}


def execute(chat,args):
    chat._check_login()
    if chat.cancel_event.is_set():raise RuntimeError('Task notebook stopped')
    action=args.get('action','read');session=chat.session;key=str(request_index(session));plans=session.get('task_notebooks',{})
    if action=='read':return json.dumps(plans.get(key,{'steps':[],'notice':'No plan for this user turn.'}),ensure_ascii=False)
    if action!='update':raise ValueError('Task actions: read, update')
    steps=args.get('steps')
    if not isinstance(steps,list) or not 1<=len(steps)<=16:raise ValueError('Use 1–16 proportional steps; skip a plan for simple conversation')
    if len(json.dumps(steps,ensure_ascii=False).encode())>12000:raise ValueError('Task notebook exceeds 12 KiB')
    normalized=[];ids=set()
    for row in steps:
        if not isinstance(row,dict) or set(row)-{'id','goal','check','status','evidence','blocker','verification'}:raise ValueError('Invalid task step fields')
        sid=row.get('id');status=row.get('status','pending')
        if not isinstance(sid,str) or not re.fullmatch('[a-zA-Z][a-zA-Z0-9_]{0,31}',sid) or sid in ids:raise ValueError('Steps need distinct short IDs')
        ids.add(sid)
        for field in ('goal','check'):
            if not isinstance(row.get(field),str) or not 1<=len(row[field])<=400:raise ValueError('Each step needs a goal and concrete acceptance check (1–400 characters)')
        if status not in ('pending','active','verified','blocked'):raise ValueError('Use pending, active, verified or blocked status')
        references=row.get('evidence',[])
        if not isinstance(references,list) or len(references)>8 or len(set(map(str,references)))!=len(references):raise ValueError('Use up to eight distinct evidence message IDs')
        evidence=[success_evidence(session,i) for i in references]
        if status=='verified' and not evidence:raise ValueError('A verified step needs actual tool evidence; a plan is not execution')
        if status=='verified':
            from result_verification import Verifications
            verification=Verifications(chat.tool_runtime,chat._check_login).read(row.get('verification',''),fresh=True)
            if not verification['success']:raise ValueError('Acceptance checks did not pass; retain a blocker or run relevant checks')

        blocker=row.get('blocker','')
        if not isinstance(blocker,str) or len(blocker)>600 or (status=='blocked' and not blocker.strip()):raise ValueError('Blocked steps need a short, specific blocker')
        normalized.append({**row,'status':status,'evidence':references,'evidence_records':evidence,'blocker':blocker})
    result={'request_index':int(key),'steps':normalized,'all_verified':all(s['status']=='verified' for s in normalized),
            'notice':'Verified steps require successful, current predicate receipts and execution evidence. Their coverage must match the written requirement; this is not proof of every possible behavior.'}
    # Existing saved plan revisions are retained in ordinary tool messages.
    if not isinstance(plans,dict) or len(plans)>256:raise ValueError('Task notebook history limit reached; start a new chat')
    session.setdefault('task_notebooks',{})[key]=result
    chat._check_login();chat.store.save_session(session)
    return json.dumps(result,ensure_ascii=False)


def guidance(session):
    row=(session or {}).get('task_notebooks',{}).get(str(request_index(session or {})))
    if not row:return ''
    active=[s['id']+': '+s['goal'][:100]+' ['+s['status']+']' for s in row['steps'] if s['status']!='verified']
    return '\nTask notebook: '+('; '.join(active)[:900] if active else 'All planned steps have linked execution evidence; check that it meets each criterion before claiming success.')+' Use task.read for checks and evidence; update the plan when scope changes. Plans do not grant permissions.'


TOOL={'type':'function','function':{'name':'task','description':'For multi-step work, keep a small plan with concrete acceptance checks. update replaces this turn\'s steps; read retrieves them. Mark verified only with original successful tool message IDs and verification (successful verify receipt ID) covering the check. Blockers retain uncertainty. Plans do not execute actions or grant permissions.',
    'parameters':{'type':'object','properties':{'action':{'type':'string','enum':['read','update']},'steps':{'type':'array','maxItems':16,'items':{'type':'object','properties':{
        'id':{'type':'string'},'goal':{'type':'string'},'check':{'type':'string'},'status':{'type':'string','enum':['pending','active','verified','blocked']},'evidence':{'type':'array','items':{'type':'integer'}},'blocker':{'type':'string'},'verification':{'type':'string'}},'required':['id','goal','check','status'],'additionalProperties':False}}},'required':['action'],'additionalProperties':False}}}
