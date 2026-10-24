"""Opt-in schedule replanning; never retry an uncertain external effect."""
import time
from copy import deepcopy

READ_ONLY = {'read_file', 'history', 'previous_run', 'recall', 'inbox'}


def previous_run_history(store,mission,start=1,count=1):
    from mission_schedule import Schedules
    from mission_context import history_page
    current=mission;seen=set()
    while current.get('parent'):
        if current['id'] in seen:raise ValueError('Mission parent cycle')
        seen.add(current['id']);current=store.load(current['parent'])
    if not current.get('schedule_id'):raise ValueError('This mission has no previous scheduled run')
    schedule=Schedules(store.root).load(current['schedule_id'])
    if schedule.get('active_run')!=current['id'] or schedule['mode']!=mission['mode']:
        raise ValueError('Current scheduled run identity mismatch')
    if not schedule.get('history'):raise ValueError('This schedule has no previous finished run')
    prior=store.load(schedule['history'][-1]['mission'])
    if prior.get('schedule_id')!=schedule['id'] or prior['mode']!=mission['mode'] or prior.get('parent'):
        raise ValueError('Previous scheduled run identity mismatch')
    return history_page(prior,start,count)


def schedule_for(store, mission):
    from mission_schedule import Schedules
    current=mission;seen=set()
    while current.get('parent'):
        if current['id'] in seen:raise ValueError('Mission parent cycle')
        seen.add(current['id']);current=store.load(current['parent'])
    sid=current.get('schedule_id')
    if not sid:return None
    schedules=Schedules(store.root);schedule=schedules.load(sid)
    if schedule.get('active_run')!=current['id'] or schedule['mode']!=mission['mode']:
        return None
    if (schedule.get('autonomous_recovery') is not True or not schedules.enabled(schedule)
            or store.stopped(mission) or (store.base/'supervisor.stop').exists()):
        return None
    return schedule


def recover(store, mission, error):
    """Caller holds the mission lock. Record failure separately from successes."""
    if not schedule_for(store,mission):return False
    if mission.get('agent_pause') or mission.get('waiting_for_children'):return False
    pending=mission.get('pending_action')
    if pending and pending.get('action') not in READ_ONLY:return False
    if mission['steps']>=mission['max_steps']:
        mission['status']='budget_exhausted';store.save(mission);return True
    original=mission
    mission=deepcopy(mission)
    count=mission.get('recovery_attempts',0)+1
    record={'at':time.time(),'action':pending,'error':str(error)[:3000],
            'outcome':'failed read-only action; no result obtained' if pending else 'planning failed; no action executed',
            'decision':'Replan using a different strategy; this is not a successful action or user review.'}
    # One failed decision consumes a unit of this occurrence's existing budget.
    mission.setdefault('recovery_history',[]).append(record)
    mission.update(steps=mission['steps']+1,pending_action=None,recovery_attempts=count,
                   planning_failures=0,error=str(error),status='waiting',
                   next_run_at=time.time()+min(300,15*2**min(count-1,5)))
    if mission['steps']>=mission['max_steps']:mission['status']='budget_exhausted'
    # Recheck the saved setting, Stop and epoch immediately before publication.
    if not schedule_for(store,mission):return False
    store.save(mission)
    original.clear();original.update(mission)
    return True
