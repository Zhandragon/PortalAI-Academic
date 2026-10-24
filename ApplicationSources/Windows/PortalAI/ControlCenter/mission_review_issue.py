"""Short, evidence-based review explanations. No model calls or state changes."""
SECTION = 'Most Recent Review Issue'
READ_ONLY = {'read_file', 'history', 'previous_run', 'recall', 'inbox'}


def compact(value, limit=210):
    text = str(value or '')[-12000:]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if any('Traceback (most recent call last)' in line for line in lines):
        text = lines[-1] if lines else ''
    text = ' '.join(''.join(c if c.isprintable() else ' ' for c in text).split())
    return text if len(text) <= limit else text[:limit-1].rstrip() + '…'


def needs_attention(mission=None, schedule=None):
    m, s = mission or {}, schedule or {}
    return bool(m.get('status') in ('needs_review', 'budget_exhausted') or m.get('agent_pause') or
                m.get('status') == 'paused' and m.get('pending_action') or s.get('status') == 'needs_review')


def explain(error, action=None, *, agent_pause=False, budget=False):
    """Translate known saved errors; unfamiliar reports remain attributed excerpts."""
    text = compact(error, 400); low = text.casefold(); action = action or {}
    kind = action.get('action')
    if kind and kind not in READ_ONLY:
        return ('The last action has no confirmed saved outcome. It may already have taken effect.',
                'Check Action history and the actual output. Choose “Reviewed: skip action” to leave it unrepeated, or “Reviewed: retry” only after checking that repeating it is safe.')
    if budget:
        return ('This run used all of its allowed actions.',
                'Create a new mission with a suitable budget and the unfinished objective; an exhausted run cannot be resumed.')
    if 'child missions need attention' in low or low.startswith('subtask paused:'):
        return ('A subtask is blocked, so its parent cannot continue.',
                'Find the subtask ID in Details, search for it in Missions, and review that subtask first.')
    if agent_pause:
        return ('Nice paused because it reported: ' + compact(error, 180),
                'Open “Add review instructions” and give a changed goal, missing information or a different strategy. Leave it paused if you want to stop.')
    if 'mission file reads are restricted to source/documentation' in low:
        return ('The requested file is outside read_file’s allowed source/documentation area, even in Full mode.',
                'Give an allowed file path, or instruct Nice to use an action permitted by this mission’s access mode. Then review the failed read and retry with the corrected plan.')
    if 'filenotfounderror' in low or 'no such file or directory' in low or 'cannot find the file' in low:
        return ('A required file or folder could not be found.',
                'Check the path in Details. Supply the correct existing path in “Add review instructions”, then review and retry.')
    if 'repeated identical actions' in low or 'repeated completed action' in low:
        return ('Nice kept choosing the same action without making progress.',
                'Open “Add review instructions” and specify a different next step or strategy, then submit the review.')
    if 'context' in low and any(word in low for word in ('budget', 'do not fit', 'exceeds', 'too large')):
        return ('The mission instructions and history do not fit the model’s available context.',
                'Shorten the review instructions, use a larger supported context, or create a smaller mission. Then resume when ready.')
    if 'not available in' in low and 'mode' in low or 'permissionerror' in low or 'access is denied' in low:
        return ('The attempted action was blocked by an access restriction.',
                'Check the mission’s saved access mode and the affected resource. Give a permitted next step; changing the new-mission dropdown does not change this mission.')
    if any(word in low for word in ('invalid json', 'valid json', 'action object', 'incomplete', 'no action', 'invalid action')):
        return ('The model did not produce a usable next action.',
                'Give one concrete next step in “Add review instructions”. If this repeats, review the model/context settings before resuming.')
    if any(word in low for word in ('out of memory', 'not enough memory', 'insufficient memory', 'free ram', 'commit headroom')):
        return ('The model or tool could not get enough memory.',
                'Free memory or choose a compatible smaller model/tool configuration, then resume when ready.')
    if 'connectionrefused' in low or 'connection refused' in low or 'timed out' in low:
        return ('A model or service could not be reached or did not respond in time.',
                'Check Runtime and the reported service in Details, then resume when it is available.')
    if 'unknown outcome' in low or kind:
        return ('The last action has no confirmed saved result.',
                'Inspect the pending action in Details and choose “Reviewed: skip action” or “Reviewed: retry” after checking its outcome.')
    return ('Reported problem: ' + compact(text) if text else 'The run requested review without recording a specific reason.',
            'Check Details and Action history, then use “Add review instructions” to tell Nice what to change before continuing.')


def summary(mission=None, activity=None, *, schedule=None, historical=False, unavailable=None):
    m, s, activity = mission or {}, schedule or {}, activity or {}
    current_schedule = s if not historical else {}
    error = m.get('error'); action = m.get('pending_action'); state = m.get('status')
    if state in ('queued', 'running', 'waiting') and action and not error and not needs_attention(m, current_schedule):
        return 'MOST RECENT REVIEW ISSUE\n\nNo review is currently requested. An action is pending or in progress; check Overview for its live status.'
    heading = 'Needs review' if state == 'needs_review' or state == 'paused' and action else 'Recorded issue'
    reviewed = False
    if unavailable:
        problem = 'The selected mission record could not be read.'
        next_step = 'Check the mission ID and the file error in Details. Restore or repair the record before continuing; no action has been retried.'
        heading = 'Record unavailable'
    elif current_schedule.get('status') == 'needs_review' and not needs_attention(m) and not action:
        if m and state in ('queued', 'running', 'waiting', 'complete', 'paused') and not error:
            problem = 'The schedule is still paused after its current run stopped or was reviewed.'
            next_step = 'In Missions, Resume this run if it is stopped; then return to Schedules and Enable when ready.'
        else:
            problem = 'The schedule could not prepare or continue its run. Reported: ' + compact(current_schedule.get('error'), 180)
            next_step = 'Check Details for the setup or file error. Correct it before enabling this schedule.'
        heading = 'Schedule needs attention'
    else:
        if not error and not action and not needs_attention(m):
            candidates = []
            for row in m.get('review_history', []):
                if isinstance(row, dict) and (row.get('previous_error') or row.get('pending_action')):
                    candidates.append((row.get('at', 0), row.get('previous_error'), row.get('pending_action'), True))
            for row in activity.get('events', []):
                if isinstance(row, dict) and row.get('phase') == 'needs_review':
                    candidates.append((row.get('at', 0), row.get('message'), None, False))
            if candidates:
                def order(row):
                    try:return float(row[0] or 0)
                    except (ValueError, TypeError):return 0
                _, error, action, reviewed = max(candidates, key=order)
                heading = 'Reviewed earlier' if reviewed else 'Earlier recorded issue'
            elif current_schedule.get('error'):
                error = current_schedule['error']; heading = 'Schedule issue recorded'
            else:
                return 'MOST RECENT REVIEW ISSUE\n\nNo review issue is recorded for ' + ('this selected run.' if m else 'this selection.') + '\nCheck Overview for its current status.'
        if state == 'paused' and m.get('agent_pause'):heading = 'Nice paused this mission'
        if state == 'budget_exhausted':heading = 'Action budget used'
        problem, next_step = explain(error, action, agent_pause=m.get('agent_pause', False), budget=state == 'budget_exhausted')
        if state in ('queued', 'running', 'waiting', 'complete') and not needs_attention(m):
            next_step = 'No review is currently requested for this run. Check Overview for its current status.'
            if error and not reviewed:heading = 'Earlier failure / no current review request'
        if state == 'budget_exhausted' and not action and current_schedule.get('autonomous_recovery'):
            next_step = 'This occurrence ended. Check the schedule’s run limit and enabled state; a remaining heartbeat may continue the unfinished work.'
        if not historical and s.get('active_run') == m.get('id') and needs_attention(m):
            next_step = 'In Missions: ' + next_step + (' The schedule is removed; Restore it before enabling.' if s.get('status')=='removed' else ' Afterwards, Resume if stopped and Enable the schedule.')
    rows = ['MOST RECENT REVIEW ISSUE', heading, '', 'Problem: ' + problem, '', 'What to do: ' + next_step]
    if action and action.get('action'):
        target = compact(action.get('path'), 110)
        rows += ['', 'Attempt: ' + compact(action['action'], 40) + (' — ' + target if target else '')]
    mid = m.get('id') or current_schedule.get('active_run')
    if mid:rows += ['', 'Mission ID: ' + compact(mid, 64)]
    if s:rows += ['Schedule ID: ' + compact(s.get('id'), 64)]
    if historical:rows += ['Showing the selected previous run, not the current schedule’s blocker.']
    return '\n'.join(rows)
