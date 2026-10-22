"""Read-only schedule presentation filters; never an execution policy."""
ORIGIN_VIEWS=('All origins','User created','Diagnostic','Legacy / unclassified')
STATE_VIEWS=('Active and paused','Removed schedules','All schedules')


def origin(schedule):
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


def select(rows,state='Active and paused',source='All origins'):
    if state not in STATE_VIEWS or source not in ORIGIN_VIEWS:raise ValueError('Unknown schedule filter')
    kind={'User created':'user','Diagnostic':'diagnostic','Legacy / unclassified':'legacy'}.get(source)
    return [row for row in rows
            if (state=='All schedules' or (row.get('status')=='removed')==(state=='Removed schedules'))
            and (kind is None or origin(row)['kind']==kind)]
