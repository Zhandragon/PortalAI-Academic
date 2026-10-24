"""Read-only mission progress and results, shared by missions and schedules."""
from datetime import datetime
import json
import time
import tkinter as tk

from rounded_text import RoundedText
from mission_review_issue import SECTION as REVIEW_SECTION, needs_attention, summary as review_summary

SECTIONS=('Overview',REVIEW_SECTION,'Live activity','Results','Action history','Details')


def when(value):
    try:return datetime.fromtimestamp(float(value)).strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError,ValueError,OSError,OverflowError):return 'Not recorded'


def readable(value, depth=0):
    if value is None or value=='':return 'Nothing found to report.'
    if isinstance(value,str):
        try:parsed=json.loads(value)
        except (ValueError,TypeError):return value
        if isinstance(parsed,(dict,list)):return readable(parsed,depth)
        return value
    if depth>4:return str(value)
    if isinstance(value,dict):
        return '\n\n'.join(str(k).replace('_',' ').capitalize()+':\n'+readable(v,depth+1) for k,v in value.items())
    if isinstance(value,list):return '\n\n'.join('• '+readable(v,depth+1) for v in value) or 'Nothing found to report.'
    return str(value)


def controller_status(store):
    from mission_supervisor import running
    result={'alive':running(store.root) if (store.base/'supervisor.lock').exists() else False}
    path=store.base/'supervisor-status.json'
    try:
        if path.exists():
            if path.stat().st_size>65536:raise ValueError('Oversized supervisor status')
            saved=json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(saved,dict):raise ValueError('Invalid supervisor status')
            result.update({key:value for key,value in saved.items() if key not in ('alive','fresh')})
        result['fresh']=bool(result['alive'] and time.time()-float(result.get('updated_at',0))<20)
    except (ValueError,OSError,TypeError) as exc:result.update(fresh=False,error=str(exc))
    if not result['alive']:
        log=store.base/'supervisor-error.log'
        try:
            if log.exists():
                with log.open('rb') as f:
                    f.seek(max(0,log.stat().st_size-3000));result['error_log']=f.read(3000).decode('utf-8',errors='replace')
        except OSError as exc:result['error_log']=str(exc)
    return result


def mission_enabled(store, mission, summaries=None):
    """Children share their root's arming and durable schedule epoch."""
    from mission_supervisor import read_policy
    root=mission;seen=set()
    while root.get('parent'):
        if root['id'] in seen:raise ValueError('Invalid mission ancestry')
        seen.add(root['id']);root=summaries[root['parent']] if summaries is not None else store.load(root['parent'])
    policy=read_policy(store,root['id'])
    if not policy.get('enabled'):return False
    if store.stopped(mission):return False
    if policy.get('schedule_id'):
        from mission_schedule import Schedules,epoch
        schedules=Schedules(store.root)
        return policy.get('schedule_epoch')==epoch(store.root) and schedules.enabled(schedules.load(policy['schedule_id']))
    return True


def live_state(mission, activity, controller, *, enabled=None):
    if not mission:return 'No run has started'
    state=mission.get('status','Unknown')
    if state not in ('queued','running','waiting'):return state.replace('_',' ').capitalize()
    if enabled is False:return 'Paused; automatic continuation is disabled'
    if not controller.get('alive'):return 'Controller stopped; this run is not executing'
    if not controller.get('fresh'):return 'Controller status is stale; execution is not confirmed'
    if controller.get('state') in ('paused_for_chat','checkpointing_for_chat'):return 'Paused for direct chat'
    if controller.get('mission')!=mission['id']:
        if mission.get('next_run_at',0)>time.time():return 'Waiting until '+when(mission['next_run_at'])
        return 'Queued for the supervisor'
    if activity.get('pid')!=controller.get('worker_pid'):
        return 'Starting LLM engine' if controller.get('state')=='starting_model' else 'Starting mission worker'
    return {'preparing_model':'Preparing LLM engine','preparing_context':'Preparing model context',
            'planning':'LLM planning; waiting for output','generating':'LLM is generating',
            'executing':'Executing action','checkpointed':'Action saved; continuing','retrying':'Waiting to retry planning',
            'paused_for_chat':'Paused for direct chat'}.get(activity.get('phase'),activity.get('message') or 'Worker active')


def render(section, mission, activity, controller, *, details='', schedule=None, enabled=None, historical=False):
    m=mission or {};s=schedule
    state=live_state(m,activity,controller,enabled=enabled)
    if section=='Details':return details
    if section==REVIEW_SECTION:return review_summary(m,activity,schedule=s,historical=historical)
    if section=='Overview':
        if not m and not s:return details
        if s and not m:
            state=('Paused; Enable starts automatic scheduling' if not enabled else
                   'Controller stopped; no run is executing' if not controller.get('alive') else
                   'Controller status is stale; execution is not confirmed' if not controller.get('fresh') else
                   'Waiting until '+when(s.get('next_run_at')) if s.get('next_run_at',0)>time.time() else
                   'Waiting for the supervisor to start this run')
        objective=(s or m).get('objective','')
        rows=['CURRENT ACTIVITY',state,'Mission ID: '+str(m.get('id') or 'No run yet'),
              *(['Schedule ID: '+str(s.get('id'))] if s else [])]
        if needs_attention(m,s if not historical else None):
            rows+=['',review_summary(m,activity,schedule=s,historical=historical)]
        rows+=['','OBJECTIVE',objective,'','PROGRESS',
              'Actions used / allowed: '+(str(m.get('steps',0))+' / '+str(m.get('max_steps',0)) if m else 'No run yet'),
              'Action awaiting execution or review: '+((m.get('pending_action') or {}).get('action') or 'Nothing found to report.')]
        if s:
            interval=s.get('interval_seconds',0)
            rows+=['','SCHEDULE','Enabled to start runs: '+('Yes' if enabled else 'No; paused'),
                   'Repeat interval: '+('Once only' if not interval else f'Every {interval/60:g} minutes'),
                   'Next planned run: '+when(s.get('next_run_at')),
                   'Run limit: '+(str(s.get('max_runs')) if s.get('max_runs') else 'Until stopped'),
                   f"Runs completed / started: {s.get('runs_completed',0)} / {s.get('runs_started',0)}",
                   'Autonomous recovery: '+('On; failed attempts use this run’s budget' if s.get('autonomous_recovery') else 'Off')]
        if (m.get('error') or (s or {}).get('error')) and not needs_attention(m,s):
            rows+=['','Use Most Recent Review Issue for a short explanation; Details retains the full error.']
        if m.get('review_instructions'):rows+=['','CURRENT REVIEW INSTRUCTIONS',m['review_instructions']]
        if controller.get('error_log'):rows+=['','SUPERVISOR ERROR',controller['error_log']]
        if controller.get('error'):rows+=['','STATUS ERROR',controller['error']]
        if m.get('status')=='complete' and m.get('history'):rows+=['','MODEL-REPORTED RESULT',readable(m['history'][-1].get('result'))]
        rows+=['','Use Live activity to follow planning, Results for findings, or Action history for each recorded step.']
        return '\n'.join(rows)
    if not m:return 'No run selected. Choose a current or previous run to inspect its activity and results.'
    if section=='Live activity':
        rows=['CURRENT ACTIVITY',state,'','Last recorded activity: '+activity.get('message','No live activity has been recorded for this run.'),
              'Last activity: '+when(activity.get('updated_at')),
              'Generated response characters: '+str(activity.get('generated_chars',0))]
        if activity.get('started_at') and controller.get('fresh') and controller.get('worker_pid')==activity.get('pid'):
            rows.append(f"Worker elapsed: {max(0,int(time.time()-activity['started_at']))} seconds")
        if activity.get('error'):rows+=['Activity record: '+activity['error']]
        if activity.get('preview'):
            rows+=['','MODEL RESPONSE PREVIEW','Uncommitted model output; actions run only after a complete, validated response.',activity['preview']]
        rows+=['','ACTIVITY TIMELINE']
        for event in activity.get('events',[]):rows.append(when(event.get('at'))+'  '+str(event.get('message','')))
        return '\n'.join(rows)
    history=m.get('history',[])
    if section=='Results':
        rows=['RESULTS', 'Run ended after the model reported completion. Check the recorded actions in Action history to assess the outcome.' if m.get('status')=='complete' else 'Findings so far; this run has not completed.']
        selected=[(i,r) for i,r in enumerate(history,1) if r.get('action',{}).get('action') in ('note','remember','complete','pause')]
        if not selected:selected=list(enumerate(history,1))[-5:]
        if not selected:rows+=['','No completed action results yet. Live activity shows what the worker is doing.']
        for i,row in selected:
            action=row['action'];kind=action.get('action')
            result=action.get('text') if kind=='note' else row.get('result')
            label='MODEL-REPORTED COMPLETION' if kind=='complete' else str(kind or 'Action').upper()
            rows+=['',f"STEP {i} · {label}"]
            if kind=='remember':rows+=['Requested memory key: '+str(action.get('key','')),'Requested value',readable(action.get('text')),'Recorded result']
            rows.append(readable(result))
        if m.get('recovery_history'):
            rows+=['','AUTONOMOUS RECOVERY','Failed attempts; no successful result was recorded.',readable(m['recovery_history'][-3:])]
        return '\n'.join(rows)
    rows=['ACTION HISTORY','These are saved action outcomes. Model previews are shown separately in Live activity.']
    if not history:rows+=['','No actions have finished.']
    for i,row in enumerate(history,1):
        action=row.get('action',{})
        rows+=['',f"STEP {i} · {str(action.get('action','Action')).upper()} · {when(row.get('at'))}",
               'Request',readable({k:v for k,v in action.items() if k!='action'}),'Result',readable(row.get('result'))]
    if m.get('recovery_history'):
        rows+=['','FAILED ATTEMPTS / AUTONOMOUS RECOVERY','These consumed budget but did not complete an action.',readable(m['recovery_history'])]
    return '\n'.join(rows)


class RunViewer(tk.Frame):
    def __init__(self,parent,skin,store,*,height=7):
        super().__init__(parent,bg=skin.colors['panel'])
        self.store=store;self.skin=skin;self.context={};self.run_ids={};self.identity=None
        bar=skin.frame(self);bar.pack(fill='x',pady=(0,3))
        self.section=tk.StringVar(self,value='Overview')
        self.sections=skin.combo(bar,self.section,SECTIONS);self.sections.configure(width=26)
        self.sections.pack(side='left',padx=(0,4))
        self.run=tk.StringVar(self,value='Selected mission')
        self.runs=skin.combo(bar,self.run,['Selected mission']);self.runs.configure(width=12)
        self.runs.pack(side='left',fill='x',expand=True)
        self.text=RoundedText(self,palette=skin.colors,scrollbars=True,horizontal=False,height=height,
                              font=('Segoe UI',9),wrap='word',bg=skin.colors['panel'],fg=skin.colors['text'],state='disabled')
        self.text.pack(fill='both',expand=True)
        self.sections.bind('<<ComboboxSelected>>',lambda _event:self.draw(reset=True))
        self.runs.bind('<<ComboboxSelected>>',lambda _event:self.draw(reset=True))

    def update_view(self,mission=None,*,details='',schedule=None,enabled=None):
        identity=(schedule or mission or {}).get('id')
        changed=identity!=self.identity;self.identity=identity
        attention=needs_attention(mission,schedule)
        focus_issue=attention and (changed or not needs_attention(self.context.get('mission'),self.context.get('schedule')) and self.section.get()=='Overview')
        if focus_issue:
            self.section.set(REVIEW_SECTION)
        self.context=dict(mission=mission,details=details,schedule=schedule,enabled=enabled)
        options={}
        if schedule:
            if schedule.get('active_run'):options['Current run']=schedule['active_run']
            elif schedule.get('status')=='needs_review':options['Schedule issue']=None
            history=schedule.get('history',[])
            for i,row in reversed(list(enumerate(history,1))):
                if isinstance(row,dict) and isinstance(row.get('mission'),str):
                    options[f"Run {i} · {when(row.get('finished_at'))}"]=row['mission']
        elif mission:options['Selected mission']=mission['id']
        self.run_ids=options;choices=list(options) or ['No runs yet']
        self.runs.configure(values=choices,state='readonly' if len(choices)>1 else 'disabled')
        if changed or self.run.get() not in options:self.run.set(choices[0])
        self.draw(reset=changed or focus_issue)

    def draw(self,*,reset=False):
        from mission_activity import read
        context=dict(self.context);mission=context.get('mission');activity={};controller={}
        try:
            mid=self.run_ids.get(self.run.get())
            if mid:mission=self.store.load(mid);activity=read(self.store,mid)
            elif self.run.get()=='Schedule issue':mission=None
            controller=controller_status(self.store)
            historical=bool(context.get('schedule') and mid and mid!=context['schedule'].get('active_run'))
            text=render(self.section.get(),mission,activity,controller,historical=historical,**{k:v for k,v in context.items() if k!='mission'})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            text=(review_summary({'id':mid} if mid else None,schedule=context.get('schedule'),unavailable=exc)
                  if self.section.get()==REVIEW_SECTION else 'Run details unavailable: '+str(exc))
        if len(text)>160000:text=text[:160000]+'\n\nDisplay limit reached. The complete records remain in the mission folder.'
        if self.text.get('1.0','end-1c')==text:return
        position=0 if reset else self.text.yview()[0]
        self.text.configure(state='normal');self.text.delete('1.0','end');self.text.insert('1.0',text)
        self.text.tag_configure('section',font=('Segoe UI',10,'bold'))
        for i,line in enumerate(text.splitlines(),1):
            if line and len(line)<100 and line.isupper():self.text.tag_add('section',f'{i}.0',f'{i}.end')
        self.text.configure(state='disabled');self.text.yview_moveto(position)
