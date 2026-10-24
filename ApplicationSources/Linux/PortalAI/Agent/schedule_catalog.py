"""Read-only schedule presentation filters; never an execution policy."""
from mission_search import matches
ORIGIN_VIEWS=('All origins','User created','Diagnostic','Legacy / unclassified')
STATE_VIEWS=('Active and paused','Removed schedules','All schedules')


def origin(schedule):
    manual=schedule.get('classification',{})
    labels={'user':'User created','diagnostic':'Diagnostic','legacy':'Unclassified'}
    if isinstance(manual,dict) and manual.get('kind') in labels:
        return {**manual,'label':labels[manual['kind']],'source':'Manually classified','confirmed':True,'manual':True}
    explicit=schedule.get('origin')
    if isinstance(explicit,dict) and explicit.get('kind') in ('user','diagnostic'):
        return {'kind':explicit['kind'],'label':'User created' if explicit['kind']=='user' else 'Diagnostic',
                'source':'Recorded at creation','confirmed':True}
    from mission_catalog import LEGACY_TEST_PREFIXES
    if any(str(schedule.get('objective','')).startswith(prefix) for prefix in LEGACY_TEST_PREFIXES):
        return {'kind':'diagnostic','label':'Legacy diagnostic','confirmed':False,
                'source':'Known self-test wording; original origin was not recorded'}
    return {'kind':'legacy','label':'Legacy / unclassified','confirmed':False,
            'source':'No recorded origin. Older user-created schedules may also appear here.'}


def select(rows,state='Active and paused',source='All origins',query=''):
    if state not in STATE_VIEWS or source not in ORIGIN_VIEWS:raise ValueError('Unknown schedule filter')
    if query.strip():
        return [row for row in rows if matches(query,row.get('id'),row.get('objective'),row.get('active_run'),
                row.get('source_mission'),row.get('status'),origin(row)['label'])]
    kind={'User created':'user','Diagnostic':'diagnostic','Legacy / unclassified':'legacy'}.get(source)
    return [row for row in rows
            if (state=='All schedules' or (row.get('status')=='removed')==(state=='Removed schedules'))
            and (kind is None or origin(row)['kind']==kind)]
