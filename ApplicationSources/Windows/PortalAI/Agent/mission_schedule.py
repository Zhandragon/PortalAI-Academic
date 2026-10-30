"""Durable, non-overlapping mission schedules driven by the existing supervisor."""
import argparse
import json
import math
from pathlib import Path
import time
import uuid

from mission_runner import Missions, ACTIVE, process_lock
from mission_modes import profile
from runtime_policy import ROOT, atomic_json, require_space
from profile_paths import private_path


def epoch(root):
    p = private_path(root,'Data/Missions/schedule-epoch.json')
    value = json.loads(p.read_text(encoding='utf-8'))['epoch'] if p.exists() else 'initial'
    from remote_lifecycle import stop_epoch
    remote = stop_epoch(root)
    return value if remote == 'initial' else value + ':' + remote


def pause_schedules(root):
    # One atomic fence disables every existing schedule, including a concurrent
    # in-flight materialization. Explicitly re-enabling one cannot revive others.
    atomic_json(private_path(root,'Data/Missions/schedule-epoch.json'), {'epoch':uuid.uuid4().hex})


class Schedules:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.store = Missions(self.root)
        self.base = self.store.base/'Schedules'

    def path(self, sid):
        self.store.folder(sid)  # Same strict ID validation as mission folders.
        return private_path(self.root, f'Data/Missions/Schedules/{sid}.json')

    def save(self, schedule):
        if schedule.get('_summary'): raise ValueError('List summaries cannot be saved as schedules')
        schedule['updated_at'] = time.time()
        atomic_json(self.path(schedule['id']),schedule)
        from mission_index import remember
        remember(self, 'schedule', schedule)

    def load(self, sid):
        s=json.loads(self.path(sid).read_text(encoding='utf-8'))
        if not isinstance(s,dict) or s.get('id')!=sid:
            raise ValueError('Invalid schedule identity; original file preserved')
        profile(s.get('mode'))
        integers=('max_steps','interval_seconds','max_runs','runs_started','runs_completed')
        if (not isinstance(s.get('objective'),str) or not s['objective'].strip() or
            type(s.get('enabled')) is not bool or
            any(type(s.get(k)) is not int for k in integers) or
            not 1<=s['max_steps']<=100 or not 0<=s['max_runs']<=10000 or
            not 0<=s['runs_completed']<=s['runs_started'] or
            (s['interval_seconds']!=0 and not 60<=s['interval_seconds']<=365*86400) or
            not isinstance(s.get('next_run_at'),(int,float)) or not math.isfinite(s['next_run_at']) or s['next_run_at']<0 or
            s.get('status') not in {'paused','scheduled','running','complete','needs_review','removed'} or
            ('setup_failures' in s and (type(s['setup_failures']) is not int or not 0<=s['setup_failures']<=1000000)) or
            ('autonomous_recovery' in s and type(s['autonomous_recovery']) is not bool) or
            not isinstance(s.get('history'),list)):
            raise ValueError('Invalid schedule values; original file preserved')
        if s.get('active_run'):self.store.folder(s['active_run'])
        if s.get('source_mission'):self.store.folder(s['source_mission'])
        return s

    def list(self, *, summaries=False):
        from mission_index import listing, read_summary
        records, hashes = listing(self, 'schedule')
        rows=[]
        for sid, name in records:
            try:
                row=read_summary(self, 'schedule', sid, hashes.get(name)) if summaries else self.load(sid)
                profile(row['mode'])
                if row['id'] != sid or not isinstance(row['next_run_at'],(int,float)):
                    raise ValueError('Invalid schedule metadata')
                rows.append(row)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                rows.append({'id':sid,'enabled':False,'status':'needs_review','error':str(exc),'objective':'Unreadable schedule; original file preserved'})
        return rows

    def enabled(self, s):
        return bool(s.get('enabled')) and s.get('epoch') == epoch(self.root)

    def any_enabled(self):
        return any(self.enabled(s) for s in self.list(summaries=True))

    def create(self, objective, mode='observe', max_steps=12, interval_seconds=3600, first_run_at=None, max_runs=0,
               source_mission=None, *, origin=None):
        profile(mode)
        if origin not in (None,'user','diagnostic'):raise ValueError('Invalid schedule origin')
        interval_seconds=int(interval_seconds);max_steps=int(max_steps);max_runs=int(max_runs)
        if not str(objective).strip() or len(str(objective))>16000 or not 1<=max_steps<=100:
            raise ValueError('Objective or per-run action budget is invalid')
        if interval_seconds != 0 and not 60<=interval_seconds<=365*86400:
            raise ValueError('Repeat interval must be 60 seconds to 365 days, or 0 for one run')
        if not 0<=max_runs<=10000:
            raise ValueError('Run limit must be 0 (until stopped) to 10000')
        first=time.time() if first_run_at is None else float(first_run_at)
        if not math.isfinite(first) or first<0:raise ValueError('Invalid first-run timestamp')
        if source_mission is not None:
            source=self.store.load(source_mission)
            if source.get('parent') or source.get('schedule_id'):
                raise ValueError('Choose an unscheduled top-level mission as the schedule template')
        require_space(self.root, 1024**2, for_outputs=True)
        s={'id':uuid.uuid4().hex,'objective':str(objective),'mode':mode,'max_steps':max_steps,
           'interval_seconds':interval_seconds,'max_runs':1 if not interval_seconds else max_runs,
           'next_run_at':first,'runs_started':0,'runs_completed':0,'active_run':None,
           'enabled':False,'status':'paused','history':[],'setup_failures':0,'created_at':time.time()}
        if origin is not None:s['origin']={'kind':origin,'recorded_at':time.time()}
        if source_mission is not None:s['source_mission']=source_mission
        self.save(s);return s

    def enable(self, sid):
        with process_lock(self.store.base/'schedules.lock'):
            s=self.load(sid)
            if s.get('status')=='removed':
                raise ValueError('Restore this removed schedule before enabling it')
            if s.get('active_run'):
                m=self.store.load(s['active_run'])
                if m['status'] not in ACTIVE|{'complete'} or m.get('pending_action') or self.store.stopped(m):
                    raise ValueError('Resume/review the active mission before enabling this schedule')
            if s.get('status')=='complete' or (s['max_runs'] and s['runs_started']>=s['max_runs'] and not s.get('active_run')):
                raise ValueError('Schedule run budget completed; create a new schedule')
            s.update(enabled=True,epoch=epoch(self.root),status='scheduled')
            s.pop('error',None);self.save(s)
            (self.store.base/'supervisor.stop').unlink(missing_ok=True)
            return s

    def classify(self, sid, kind=None):
        """Change only a presentation override under the scheduler's write lock."""
        if kind not in (None, 'user', 'diagnostic', 'legacy'):
            raise ValueError('Invalid schedule classification')
        self.path(sid)  # Check the captured login before opening the lock.
        with process_lock(self.store.base/'schedules.lock'):
            s=self.load(sid)
            if kind is None:
                s.pop('classification',None)
            else:
                s['classification']={'kind':kind,'recorded_at':time.time()}
            self.save(s)
        return s

    def set_autonomous_recovery(self, sid, enabled):
        if type(enabled) is not bool:raise ValueError('Autonomous recovery must be true or false')
        self.path(sid)
        with process_lock(self.store.base/'schedules.lock'):
            s=self.load(sid)
            s['autonomous_recovery']=enabled
            self.save(s)
        return s

    def disable(self, sid):
        with process_lock(self.store.base/'schedules.lock'):
            s=self.load(sid)
            if s.get('status')=='removed':raise ValueError('Restore this removed schedule before pausing it')
            s.update(enabled=False,status='paused');self.save(s)
        if s.get('active_run') and self.store.checkpoint_path(s['active_run']).exists():
            from mission_supervisor import disarm
            disarm(self.root,s['active_run'])
        return s

    def remove(self, sid):
        """Reversibly remove a schedule from active lists; retain every run record."""
        with process_lock(self.store.base/'schedules.lock'):
            s=self.load(sid)
            if s.get('status')!='removed':
                s.update(enabled=False,status='removed',removed_at=time.time())
                self.save(s)
        if s.get('active_run') and self.store.checkpoint_path(s['active_run']).exists():
            from mission_supervisor import disarm
            disarm(self.root,s['active_run'])
        return self.load(sid)

    def restore(self, sid):
        """Restore a removed schedule paused; never restart it implicitly."""
        with process_lock(self.store.base/'schedules.lock'):
            s=self.load(sid)
            if s.get('status')!='removed':raise ValueError('This schedule is not in Removed schedules')
            s.update(enabled=False,status='paused')
            s.pop('removed_at',None)
            self.save(s)
        return s

    def _ensure_run(self, s):
        mid=s['active_run'];path=self.store.checkpoint_path(mid)
        if path.exists():
            m=self.store.load(mid)
            if m.get('schedule_id')!=s['id'] or m['mode']!=s['mode']:
                raise RuntimeError('Scheduled run identity mismatch; review required')
        else:
            # ID was checkpointed in the schedule BEFORE creating the mission.
            # Recovery reuses that ID and never duplicates an occurrence.
            m=self.store.create(s['objective'],s['mode'],s['max_steps'],mission_id=mid,schedule_id=s['id'])
        if not self.enabled(s) or (self.store.base/'supervisor.stop').exists():return
        if m.get('pending_action') or m['status'] not in ACTIVE or self.store.stopped(m):return
        from mission_supervisor import policy_path
        from remote_lifecycle import stop_epoch
        atomic_json(policy_path(self.store,mid),{'enabled':True,'mode':m['mode'],'armed_at':time.time(), 'remote_stop_epoch':stop_epoch(self.root),
                                              'schedule_id':s['id'],'schedule_epoch':s['epoch']})
        # Creating the checkpoint alone does not finish setup. Retain the
        # failure count until the run policy has actually been published.
        if s.get('setup_failures') or s.get('error') or s['status']!='running':
            s.update(setup_failures=0,status='running')
            s.pop('error',None)
            self.save(s)

    def tick(self, now=None):
        now=time.time() if now is None else float(now)
        from chat_priority import active as direct_chat_active
        if (self.store.base/'supervisor.stop').exists() or direct_chat_active(self.root):return
        with process_lock(self.store.base/'schedules.lock'):
            for summary in self.list(summaries=True):
                if not self.enabled(summary):continue
                s = summary
                try:
                    s = self.load(summary['id'])
                    if not self.enabled(s): continue
                    if s.get('active_run'):
                        # Policy publication can fail after mission creation.
                        # Honor its persisted backoff as well, but inspect Stop,
                        # pending effects and terminal states without delay.
                        if s['next_run_at']>now:
                            if not self.store.checkpoint_path(s['active_run']).exists():continue
                            if s.get('setup_failures'):
                                m=self.store.load(s['active_run'])
                                if m['status'] in ACTIVE and not m.get('pending_action') and not self.store.stopped(m):continue
                        self._ensure_run(s)
                        m=self.store.load(s['active_run'])
                        if m['status']=='needs_review' and s.get('autonomous_recovery'):
                            from mission_recovery import recover
                            try:
                                with self.store.lock(m['id']):
                                    m=self.store.load(m['id'])
                                    if m['status']=='needs_review':recover(self.store,m,m.get('error','Planning needs another strategy'))
                            except OSError:
                                continue  # A worker owns the checkpoint; inspect it on the next tick.
                            m=self.store.load(m['id'])
                        if m['status']=='complete' or (m['status']=='budget_exhausted' and s.get('autonomous_recovery') and not m.get('pending_action') and not self.store.stopped(m)):
                            s['runs_completed']+=int(m['status']=='complete')
                            outcome={'mission':m['id'],'finished_at':m['updated_at'],'status':m['status']}
                            if m['status']=='budget_exhausted':
                                outcome['error']='Occurrence budget used; continue unfinished work with a different strategy on the next heartbeat.'
                                outcome['last_failure']=m.get('recovery_history',[])[-1:]
                            s['history']=(s['history']+[outcome])[-128:]
                            s['active_run']=None
                            if not s['interval_seconds'] or (s['max_runs'] and s['runs_started']>=s['max_runs']):
                                s.update(enabled=False,status='complete')
                            else:
                                # Coalesce missed ticks; never replay a backlog or overlap work.
                                s.update(next_run_at=max(s['next_run_at']+s['interval_seconds'],now+s['interval_seconds']),status='scheduled')
                            self.save(s)
                        elif m.get('agent_pause'):
                            s.update(enabled=False,status='paused',error='Agent paused: '+str(m.get('error','No further progress possible')))
                            self.save(s)
                        elif m.get('pending_action') or m['status'] not in ACTIVE or self.store.stopped(m):
                            s.update(enabled=False,status='needs_review',error='Active run requires review/resume; no later run will start')
                            self.save(s)
                        continue
                    if s['next_run_at']>now:continue
                    require_space(self.root, 4*1024**2, for_outputs=True)
                    s['runs_started']+=1
                    s.update(active_run=uuid.uuid5(uuid.UUID(hex=s['id']),str(s['runs_started'])).hex,status='running')
                    self.save(s)
                    self._ensure_run(s)
                except (OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
                    # Retry only when the assigned run has no checkpoint, or
                    # has a valid active checkpoint with no uncertain action.
                    # A pending action, STOP, corrupt record, or identity
                    # mismatch must remain behind the explicit review gate.
                    if s.get('_summary'): continue
                    mid=s.get('active_run')
                    retry_preparation=not mid
                    try:
                        if mid:
                            mission=self.store.load(mid)
                            retry_preparation=(mission.get('schedule_id')==s['id'] and
                                               mission.get('mode')==s['mode'] and
                                               mission['status'] in ACTIVE and
                                               not mission.get('pending_action') and
                                               not self.store.stopped(mission))
                    except FileNotFoundError:
                        retry_preparation=True
                    except (OSError,ValueError,KeyError,TypeError,RuntimeError):
                        retry_preparation=False
                    if retry_preparation:
                        failures=min(1000000,int(s.get('setup_failures',0))+1)
                        delay=min(300,30*(2**min(failures-1,4)))
                        s.update(setup_failures=failures,status='scheduled',next_run_at=now+delay,
                                 error=f'Run setup failed before any mission action; retrying in {delay} seconds: {type(exc).__name__}: {exc}')
                    else:
                        s.update(enabled=False,status='needs_review',error=str(exc))
                    self.save(s)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=ROOT)
    sub=ap.add_subparsers(dest='command',required=True)
    p=sub.add_parser('create');p.add_argument('objective');p.add_argument('--mode',choices=('observe','full','vm'),default='observe')
    p.add_argument('--steps',type=int,default=12);p.add_argument('--interval',type=int,default=3600)
    p.add_argument('--first-at',type=float);p.add_argument('--max-runs',type=int,default=0)
    for name in ('enable','disable','remove','restore'):sub.add_parser(name).add_argument('id')
    sub.add_parser('list');ns=ap.parse_args();store=Schedules(ns.root)
    if ns.command=='create':r=store.create(ns.objective,ns.mode,ns.steps,ns.interval,ns.first_at,ns.max_runs,origin='user')
    elif ns.command=='enable':
        r=store.enable(ns.id)
        from mission_supervisor import ensure_running
        r={'schedule':r,'supervisor':ensure_running(ns.root)}
    elif ns.command=='disable':r=store.disable(ns.id)
    elif ns.command=='remove':r=store.remove(ns.id)
    elif ns.command=='restore':r=store.restore(ns.id)
    else:r=store.list()
    print(json.dumps(r,indent=2))


if __name__=='__main__':main()
