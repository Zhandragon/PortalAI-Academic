"""Schedule controls kept inside the existing persistent-missions interface."""
from datetime import datetime
import json
import time
from pathlib import Path
import tkinter as tk
from record_dates import RecordDates, describe as describe_dates, formatted as date_text
from record_controls import RecordSort, record_name, FoldPanel, record_columns
from rounded_text import RoundedText
from tkinter import ttk
from confirmation_dialog import ask_yes_no
from schedule_catalog import ORIGIN_VIEWS, STATE_VIEWS, origin as schedule_origin, select as select_schedules


def schedule_details(schedule=None, *, enabled=None, access=None, active_mission=None, unavailable=None, dates=None):
    s = schedule or {}
    def when(value):
        if value is None:return None
        try:return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S (local time)')
        except (ValueError, TypeError, OverflowError, OSError):return 'Invalid saved time; review required.'
    dates = dates or describe_dates(s)
    fields = [
        ('Schedule ID', s.get('id')), ('Name', record_name(s)), ('Objective for each run', s.get('objective')),
        ('Created (local)', date_text(dates['created_at'], dates['created_fallback'])),
        ('Updated (local)', date_text(dates['updated_at'], dates['updated_fallback'])),
        ('Date information', dates['note']),
        ('Source mission template', s.get('source_mission')),
        ('Record source', schedule_origin(s) if schedule else None),
        ('Autonomous recovery', 'On: replan ordinary failures; uncertain effects still require review' if s.get('autonomous_recovery') else 'Off: stop for review'),
        ('Access permissions', access), ('Saved status', s.get('status')),
        ('Enabled to start runs', ('Yes' if enabled else 'No; paused') if enabled is not None else None),
        ('Repeat interval', ('Once only' if s.get('interval_seconds') == 0 else f"Every {s.get('interval_seconds', 0)/60:g} minutes") if schedule else None),
        ('Next planned run', when(s.get('next_run_at'))), ('Actions allowed per run', s.get('max_steps')),
        ('Run limit', ('Until stopped' if s.get('max_runs') == 0 else s.get('max_runs')) if schedule else None),
        ('Runs completed / started', f"{s.get('runs_completed', 0)} / {s.get('runs_started', 0)}" if schedule else None),
        ('Active mission ID', s.get('active_run')),
        ('Active mission state', active_mission.get('status') if active_mission else None),
        ('Active mission actions used / allowed', f"{active_mission.get('steps', 0)} / {active_mission.get('max_steps', 0)}" if active_mission else None),
        ('Active mission pending action type', (active_mission.get('pending_action') or {}).get('action') if active_mission else None),
        ('Active mission error', active_mission.get('error') if active_mission else None),
        ('Recent run results', s.get('history')), ('Safe setup retries', s.get('setup_failures')),
        ('Last reported error', s.get('error')),
    ]
    def value(item):
        if item is None or item == '' or item == [] or item == {}:return 'Nothing found to report.'
        return json.dumps(item, indent=2, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
    intro = ('Selected schedule: saved timing, limits and run results. Paused schedules do not start runs.' if schedule else
             'No schedule selected. Select a row in Saved schedules to see its details. Nothing found to report yet.')
    if unavailable:intro = 'Schedule details unavailable: '+str(unavailable)
    return intro+'\n\n'+'\n'.join(label+': '+value(item) for label, item in fields)


def show_schedule_settings(parent, root, colors, *, session=None, jobs=None, embedded=False, framed=True):
    from account_permissions import require_admin
    require_admin(root, session)
    from profile_paths import enabled
    if enabled(root) and not callable(getattr(jobs,'thread',None)):
        raise RuntimeError('Account schedules require the tracked background-job shutdown gate.')
    from record_refresh import RecordRefresh, visible
    from mission_schedule import Schedules
    from mission_supervisor import ensure_running
    from mission_modes import MODES, profile
    from mission_catalog import MissionCatalog
    store=Schedules(root)
    catalog=MissionCatalog(root,store=store.store)
    date_catalog=RecordDates(root,"schedules",store=store.store)
    listed_dates={}
    from internal_sheet import InternalSheet
    win=InternalSheet(parent, 'Mission schedules', colors,embedded=embedded,framed=framed,fill_height=True)
    bg=colors.get('panel',colors.get('bg'));fg=colors.get('text')
    win.configure(bg=bg)
    frame=tk.Frame(win.content,bg=bg,padx=12,pady=3 if embedded else 5);frame.pack(fill='both',expand=True)
    def label(text):
        w=tk.Label(frame,text=text,bg=bg,fg=fg,anchor='w',justify='left',wraplength=1100);w.pack(fill='x',pady=(0,4));return w
    label('Schedules are missions that run on a heartbeat periodically for the length of runs selected or indefinitely. Schedules start paused and create one mission at a time. Missed runs do not pile up. Keep PortalAI open, the SSD connected and the computer awake. Stop/Exit pauses schedules.')
    creation=FoldPanel(frame,win.skin,'New schedule');creation.pack(fill='x',pady=(0,3))
    create_body=creation.body;win.creation_panel=creation
    win.skin.label(create_body, 'New schedule objective', heading=True).pack(fill='x', anchor='w')
    objective=RoundedText(create_body,palette=win.skin.colors,scrollbars=True,horizontal=False,height=2 if embedded else 3,wrap='word',bg=bg,fg=fg,insertbackground=fg);objective.pack(fill='x')
    objective_state=tk.StringVar(value='No objective entered. Describe each run, choose timing and access, then Create paused schedule. Existing rows are not edited here.')
    tk.Label(create_body,textvariable=objective_state,anchor='w',bg=bg,fg=fg,wraplength=1100,justify='left').pack(fill='x',pady=(2,3))
    def objective_changed(*_):
        if objective.edit_modified():
            objective_state.set('Draft only. Creating saves it paused; Enable is a separate action.' if objective.get('1.0','end').strip() else
                                'No objective entered. Describe each run, choose timing and access, then Create paused schedule. Existing rows are not edited here.')
            objective.edit_modified(False)
    objective.bind('<<Modified>>',objective_changed,add='+')
    form=tk.Frame(create_body,bg=bg);form.pack(fill='x',pady=2)
    win.skin.compact=embedded
    mode=tk.StringVar(value=profile('observe')['label']);labels={profile(m)['label']:m for m in MODES}
    interval=tk.StringVar(value='60');steps=tk.StringVar(value='12');limit=tk.StringVar(value='0');first=tk.StringVar()
    from ui_extensions import ResponsiveFlow
    fields=ResponsiveFlow(form,bg=bg,hgap=14,vgap=5)
    fields.pack(fill='x')
    for title,var in (('Every (minutes; 0 = once)',interval),('Actions/run (1–100)',steps),('Runs (0 = unlimited)',limit),('First run: YYYY-MM-DD HH:MM',first)):
        cell=win.skin.frame(fields);fields.add(cell)
        caption=win.skin.label(cell,title,width=0);caption.unbind('<Configure>');caption.pack(anchor='w',pady=(0,2))
        entry=win.skin.entry(cell,'');entry.configure(textvariable=var,width=23 if var is first else 9);entry.pack(anchor='w')
    cell=win.skin.frame(fields);fields.add(cell)
    win.skin.label(cell,'Access mode').pack(fill='x',pady=(0,2))
    access=win.skin.combo(cell,mode,list(labels));access.configure(width=24);access.pack(anchor='w')
    source_cell=win.skin.frame(fields);fields.add(source_cell)
    win.skin.label(source_cell,'Copy from an existing mission (optional)').pack(fill='x',pady=(0,2))
    source_row=win.skin.frame(source_cell);source_row.pack(fill='x')
    source_value=tk.StringVar(value='Choose a mission…')
    source_combo=win.skin.combo(source_row,source_value,['Choose a mission…']);source_combo.configure(width=25);source_combo.pack(side='left')
    source_ids={}
    templates_loaded=[False]
    source_mission=[None]
    def load_templates(_request):
        options={}
        for row in catalog.rows('User & unclassified'):
            mission=row['mission']
            if mission.get('parent') or mission.get('schedule_id') or row['origin']['kind'] not in {'user','unknown'}:continue
            title=' '.join(mission['objective'].split())[:76]
            options[f"{row['origin']['label']} · {title} · {mission['id'][:8]}"]=mission['id']
        return options
    def apply_templates(options):
        templates_loaded[0]=True
        source_ids.clear();source_ids.update(options)
        choices=['Choose a mission…',*options];source_combo.configure(values=choices)
        if source_value.get() not in choices:source_value.set(choices[0])
    template_reader=RecordRefresh(win,load_templates,apply_templates,check=lambda:require_admin(root,session),
        error=lambda exc:source_combo.configure(values=['Templates unavailable; refresh']),jobs=jobs)
    def refresh_templates():template_reader.request('templates',invalidate=True)
    def use_template():
        try:
            mid=source_ids[source_value.get()]
            mission=store.store.load(mid)
            objective.delete('1.0','end');objective.insert('1.0',mission['objective'])
            mode.set(profile(mission['mode'])['label'])
            steps.set(str(mission['max_steps']))
            source_mission[0]=mid
            status.set('Copied the selected mission into this schedule draft. The original remains unchanged; the schedule starts paused.')
        except Exception as exc:status.set('Select an available user or unclassified mission first: '+str(exc))
    win.skin.button(source_row,'Use mission',use_template).pack(side='right',padx=(5,0))
    tk.Label(source_cell,text='Copies the objective, access and budget.',bg=bg,fg=fg,anchor='w',wraplength=420,justify='left').pack(fill='x',pady=(3,0))
    hint=tk.StringVar()
    def describe(*_):hint.set(profile(labels[mode.get()])['description'])
    mode.trace_add('write',describe);describe()
    tk.Label(create_body,textvariable=hint,bg=bg,fg=fg,anchor='w',wraplength=1100,justify='left').pack(fill='x',pady=(0,3))
    from record_controls import RecordSearch, RecordClassification
    data_area=tk.Frame(frame,bg=bg);data_area.pack(fill='both',expand=True)
    table=tk.Frame(data_area,bg=bg)
    detail_host=tk.Frame(data_area,bg=bg)
    record_columns(data_area,table,detail_host)
    # Give the saved list and details the extra height when the main GUI grows.
    # The base layout remains unchanged while the available space is tight.
    win.skin.label(table,'Saved schedules',heading=True).pack(fill='x',anchor='w',pady=(0,2))
    search=RecordSearch(table,win.skin,lambda:refresh())
    search.pack(fill='x',pady=(0,3))
    list_note=tk.StringVar()
    tk.Label(table,textvariable=list_note,anchor='w',bg=bg,fg=fg,wraplength=480,justify='left').pack(fill='x',pady=(0,2))
    schedule_view=tk.StringVar(value='Active and paused')
    from ui_extensions import ResponsiveGrid
    filter_panel=FoldPanel(table,win.skin,'Filters');filter_panel.pack(fill='x')
    win.filters_panel=filter_panel
    filters=ResponsiveGrid(filter_panel.body,bg=bg,min_cell_width=220,max_columns=2)
    filters.pack(fill='x',pady=(0,4))
    view_row=tk.Frame(filters,bg=bg);filters.add(view_row)
    tk.Label(view_row,text='Show',bg=bg,fg=fg,anchor='w').pack(side='left',padx=(0,4))
    view_combo=win.skin.combo(view_row,schedule_view,STATE_VIEWS)
    view_combo.configure(width=19)
    view_combo.pack(side='left',fill='x',expand=True)
    origin_view=tk.StringVar(value='All origins')
    origin_row=tk.Frame(filters,bg=bg);filters.add(origin_row)
    tk.Label(origin_row,text='Source',bg=bg,fg=fg,anchor='w').pack(side='left',padx=(0,4))
    origin_combo=win.skin.combo(origin_row,origin_view,ORIGIN_VIEWS);origin_combo.configure(width=22);origin_combo.pack(side='left',fill='x',expand=True)
    win.skin.label(detail_host,'Selected schedule details',heading=True).pack(fill='x',anchor='w',pady=(0,2))
    tree=ttk.Treeview(table,columns=('origin','status','next','runs','objective','name','created','updated','mode','limit','id'),displaycolumns=('name','status','origin','created','updated','next','runs','mode','limit','objective','id'),show='headings',height=2 if embedded else 6,selectmode='browse')
    for key,title,width in [('origin','Category / source',150),('status','Status',150),('next','Next run (local)',175),('runs','Completed / started',160),('objective','Description',400),('name','Name',240),('created','Created (local)',175),('updated','Updated (local)',175),('mode','Access',130),('limit','Run limit (0 = unlimited)',190),('id','Schedule ID',290)]:
        tree.heading(key,text=title);tree.column(key,width=width,stretch=key=='objective')
    tree.pack(fill='both',expand=True)
    sorter=RecordSort(tree,lambda:refresh())
    win.record_sort=sorter
    from ui_extensions import ResponsiveGrid
    controls=ResponsiveGrid(frame,bg=bg,min_cell_width=170,max_columns=4);controls.pack(fill='x',pady=0 if embedded else 4)
    status=tk.StringVar(value='Creating a schedule does not enable it. Select it and click Enable when ready.')
    tk.Label(frame,textvariable=status,bg=bg,fg=fg,anchor='w',wraplength=1100,justify='left').pack(fill='x')
    from mission_monitor import RunViewer,controller_status,live_state
    from ui_extensions import ResponsiveFlow
    options=FoldPanel(detail_host,win.skin,'Classification & recovery');options.pack(fill='x',pady=(0,3))
    win.options_panel=options
    classification=RecordClassification(options.body,win.skin,lambda:classify())
    classification.picker.configure(width=16);classification.pack(anchor='w',pady=(0,3))
    autonomous=tk.BooleanVar(value=False)
    recovery_toggle=win.skin.check(options.body,'Autonomous recovery',autonomous)
    recovery_toggle.unbind('<Configure>');recovery_toggle.configure(wraplength=0,command=lambda:set_recovery(),state='disabled')
    recovery_toggle.pack_configure(anchor='w',fill='none')
    recovery_note=tk.StringVar(value='Select a schedule to set its recovery policy.')
    tk.Label(options.body,textvariable=recovery_note,bg=bg,fg=fg,anchor='w',justify='left',wraplength=520).pack(fill='x')
    viewer=RunViewer(detail_host,win.skin,store.store,height=3 if embedded else 7,jobs=jobs);viewer.pack(fill='both',expand=True)
    detail=viewer.text;win.run_viewer=viewer
    def display_detail(text):
        if detail.get('1.0','end-1c')==text:return
        position=detail.yview()[0]
        detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0',text);detail.configure(state='disabled')
        detail.yview_moveto(position)
    def selected():
        ids=tree.selection()
        if not ids:raise ValueError('Select a schedule first')
        return ids[0]
    toggle_button=[None]
    def update_toggle(enabled=False,available=False):
        button=toggle_button[0]
        if button is not None:button.configure(text='Disable' if enabled else 'Enable',state='normal' if available else 'disabled')

    def load_detail(request):
        sid,dates=request
        s=store.load(sid);armed=store.enabled(s);active=None
        available=s.get('status') not in ('removed','complete')
        if s.get('active_run'):
            try:active=store.store.load(s['active_run'])
            except (ValueError,OSError,KeyError,TypeError) as exc:active={'error':str(exc)}
        needs_review=bool(active and (not active.get('id') or active.get('status') not in {'queued','running','waiting','complete'} or
                                     active.get('pending_action') or store.store.stopped(active)))
        if available and not armed and s.get('active_run'):available=bool(active and not needs_review)
        return dict(s=s,active=active,enabled=armed,available=available,needs_review=needs_review,
            details=schedule_details(s,enabled=armed,access=profile(s['mode'])['description'],active_mission=active,dates=dates))

    def apply_detail(value):
        s=value['s'];active=value['active']
        autonomous.set(s.get('autonomous_recovery',False));recovery_toggle.configure(state='normal')
        recovery_note.set('Failed planning/reads replan; Stop and uncertain external effects still require review.' if autonomous.get() else
                          'Off: failures stop for review. Toggle applies to this schedule and does not enable it.')
        manual=s.get('classification',{})
        classification.show(s['id'],manual.get('kind') if isinstance(manual,dict) else None)
        update_toggle(value['enabled'],value['available'])
        if active and active.get('id') and value['needs_review']:
            recovery_note.set('Review/resume mission '+active['id']+' in Missions before enabling this schedule.')
        viewer.update_view(active if active and active.get('id') else None,schedule=s,enabled=value['enabled'],details=value['details'])

    def detail_failed(exc):
        classification.show();recovery_toggle.configure(state='disabled');autonomous.set(False)
        recovery_note.set('Select a schedule to set its recovery policy.');update_toggle()
        viewer.reader.discard();viewer.context={};viewer.run_ids={}
        viewer._display((schedule_details(unavailable=exc),True))

    detail_reader=RecordRefresh(win,load_detail,apply_detail,check=lambda:require_admin(root,session),error=detail_failed,jobs=jobs)
    def show(*_):
        selection=tree.selection()
        if not selection:
            detail_reader.discard();detail_failed(None)
            return
        sid=selection[0]
        if viewer.identity!=sid:
            classification.show();recovery_toggle.configure(state='disabled')
            update_toggle();viewer.reader.discard();viewer._display(('Loading selected schedule…',True))
        detail_reader.request((sid,listed_dates.get(sid)))

    def load_rows(request):
        state_filter,origin_filter,query=request
        rows=select_schedules(store.list(summaries=True),state_filter,origin_filter,query)
        controller=controller_status(store.store)
        order={};dates_by_id={};items=[]
        from chat_priority import active as direct_chat_active
        chat_is_active=direct_chat_active(root)
        for s in rows:
            armed=store.enabled(s)
            state='removed' if s.get('status')=='removed' else s['status'] if armed or s.get('status') in ('complete','needs_review') else 'paused'
            if armed:
                if chat_is_active:state='paused for chat'
                elif s.get('active_run'):
                    try:
                        from mission_activity import read as read_activity
                        mission=store.store.load(s['active_run'])
                        state=live_state(mission,read_activity(store.store,mission['id']),controller,enabled=True)
                    except (ValueError,OSError,KeyError,TypeError):state='Run needs review'
                elif s.get('next_run_at',0)<=time.time() and not controller.get('alive'):state='Enabled; controller stopped'
            try:at=datetime.fromtimestamp(s['next_run_at']).strftime('%Y-%m-%d %H:%M:%S') if 'next_run_at' in s else 'Review file'
            except (ValueError,TypeError,OverflowError,OSError):at='Review saved date'
            dates=dates_by_id[s['id']]=date_catalog.info(s);name=record_name(s)
            values=(schedule_origin(s)['label'],state,at,f"{s.get('runs_completed',0)} / {s.get('runs_started',0)}",s['objective'][:160],name[:150],
                    date_text(dates['created_at'],dates['created_fallback']),date_text(dates['updated_at'],dates['updated_fallback']),
                    profile(s['mode'])['label'] if s.get('mode') else 'Unknown',s.get('max_runs','Unknown'),s['id'])
            order[s['id']]=dict(zip(('origin','status','next','runs','objective','name','created','updated','mode','limit','id'),values))
            order[s['id']].update(name=name,objective=s['objective'],runs=(s.get('runs_completed',0),s.get('runs_started',0)),
                                   created=dates['created_at'],updated=dates['updated_at'],next=s.get('next_run_at'),limit=s.get('max_runs'))
            items.append((s['id'],values))
        return dict(rows=rows,items=items,order=order,dates=dates_by_id,query=query)

    pending_selection=[None]
    def apply_rows(value):
        rows=value['rows'];query=value['query'];old=set(tree.get_children())
        list_note.set(f'{len(rows)} matches across all schedules. Clear restores filters.' if query.strip() else
                      'Search IDs/keywords; click a heading to sort.' if rows else 'No schedules match these filters.')
        listed_dates.clear();listed_dates.update(value['dates'])
        for sid,values in value['items']:
            if sid in old:
                if tuple(tree.item(sid,'values'))!=tuple(str(v) for v in values):tree.item(sid,values=values)
                old.remove(sid)
            else:tree.insert('','end',iid=sid,values=values)
        for sid in old:tree.delete(sid)
        sorter.apply(value['order'])
        if pending_selection[0] and tree.exists(pending_selection[0]):
            tree.selection_set(pending_selection[0]);tree.see(pending_selection[0]);pending_selection[0]=None
        elif query.strip() and len(rows)==1 and not tree.selection():
            tree.selection_set(rows[0]['id']);tree.see(rows[0]['id'])
        show()

    def rows_failed(exc):
        listed_dates.clear()
        for sid in tree.get_children():tree.delete(sid)
        detail_reader.discard();detail_failed(exc);status.set(str(exc))
    rows_reader=RecordRefresh(win,load_rows,apply_rows,check=lambda:require_admin(root,session),error=rows_failed,jobs=jobs)
    def refresh():
        rows_reader.request((schedule_view.get(),origin_view.get(),search.query.get()),invalidate=True)
        if not templates_loaded[0] and not template_reader.running:refresh_templates()
    def mapped(event):
        if event.widget is win:
            refresh();refresh_templates()
    win.bind('<Map>',mapped,add='+')

    def classify():
        try:
            require_admin(root,session)
            sid=selected()
            store.classify(sid,classification.chosen())
            classification.current=None
            refresh();refresh_templates()
            status.set('Classification saved for '+sid+'. Linked runs without their own classification inherit a manual schedule label.')
        except Exception as exc:status.set(str(exc))
    def set_recovery():
        try:
            require_admin(root,session)
            store.set_autonomous_recovery(selected(),autonomous.get())
            status.set('Recovery policy saved. Review/resume any existing stopped run, then Enable when ready.')
            show()
        except Exception as exc:
            status.set(str(exc));show()
    def create():
        try:
            require_admin(root, session)
            at=datetime.strptime(first.get().strip(),'%Y-%m-%d %H:%M').astimezone().timestamp() if first.get().strip() else None
            s=store.create(objective.get('1.0','end').strip(),labels[mode.get()],int(steps.get()),int(interval.get())*60,at,int(limit.get()),source_mission[0],origin='user')
            search.query.set('')
            schedule_view.set('Active and paused');origin_view.set('User created')
            pending_selection[0]=s['id'];refresh();status.set('Created paused. Enable explicitly to start this schedule.')
        except Exception as exc:status.set(str(exc))
    def toggle(enable=None):
        try:
            require_admin(root, session)
            if enable is None:enable=not store.enabled(store.load(selected()))
            if enable:
                store.enable(selected());result=ensure_running(Path(root))
                status.set('Schedule enabled. '+('Starting supervisor; follow Live activity.' if result.get('started') else
                           'Supervisor already active; follow Live activity.' if result.get('already_running') else result.get('reason','Supervisor startup is not confirmed.')))
            else:store.disable(selected());status.set('Schedule paused; any interrupted action requires review in Persistent missions.')
            refresh();show()
        except Exception as exc:status.set(str(exc))
    def remove():
        try:
            deletion_session=require_admin(root, session)
            sid=selected();s=store.load(sid)
            if s.get('status')=='removed':raise ValueError('This schedule is already removed')
            prompt=('Remove this schedule from the active list? It will be paused; its history and generated mission records stay on the SSD. '
                    'Any in-progress mission will be stopped. An interrupted external action may still need review. Restore never starts it automatically.\n\n'
                    +s['objective'][:240])
            if not ask_yes_no('Remove schedule?',prompt,parent=win,colors=win.skin.colors,
                    validate=lambda:require_admin(root,deletion_session),
                    yes_label='Yes — remove schedule',no_label='No — keep schedule'):return
            store.remove(sid)
            status.set('Schedule removed and paused. Its records remain under Removed schedules; Restore does not resume it.')
            refresh()
        except Exception as exc:status.set(str(exc))
    def restore():
        try:
            require_admin(root, session)
            store.restore(selected())
            status.set('Schedule restored paused. Select Enable to resume; handle any active mission still needing review first.')
            schedule_view.set('Active and paused')
            refresh()
        except Exception as exc:status.set(str(exc))
    win.skin.button(create_body,'Create paused schedule',create).pack(anchor='w',pady=(3,0))
    toggle_button[0]=win.skin.button(controls,'Enable',toggle);controls.add(toggle_button[0]);win.schedule_toggle=toggle_button[0]
    for text,cmd in [('Remove…',remove),('Restore',restore),('Refresh',refresh)]:
        controls.add(win.skin.button(controls,text,cmd))
    def context_actions(sid):
        try:
            s=store.load(sid);enabled=store.enabled(s);removed=s.get('status')=='removed'
            active=store.store.load(s['active_run']) if s.get('active_run') else None
            pending=bool(active and active.get('pending_action'))
            stopped=bool(active and store.store.stopped(active))
            needs_review=bool(active and (active['status'] not in {'queued','running','waiting','complete'} or pending or stopped))
            available=not removed and s.get('status')!='complete'
            version=active.get('updated_at') if active else None
            def resume_run(reviewed=None):
                try:
                    require_admin(root,session)
                    current=store.load(sid)
                    if store.enabled(current):raise ValueError('Stop this schedule before reviewing its active run')
                    if not active or current.get('active_run')!=active['id']:raise ValueError('The active run changed; inspect it before resuming')
                    if store.store.load(active['id']).get('updated_at')!=version:raise ValueError('The mission changed; inspect its latest action before reviewing')
                    store.store.resume(active['id'],reviewed)
                    status.set('Mission resumed. Choose Run / enable schedule when ready; its timing and run limits are preserved.')
                    refresh();show()
                except Exception as exc:status.set(str(exc))
            return [
                dict(label='Run / enable schedule',command=lambda:toggle(True),enabled=available and not enabled and not needs_review),
                dict(label='Stop / pause schedule',command=lambda:toggle(False),enabled=available and (enabled or bool(active and not stopped))),
                dict(label='Resume active mission',command=resume_run,enabled=available and not enabled and needs_review and not pending),
                None,
                dict(label='Review: retry',command=lambda:resume_run('retry'),enabled=available and not enabled and pending),
                dict(label='Review: skip',command=lambda:resume_run('skip'),enabled=available and not enabled and pending),
                None,
                dict(label='Delete…',command=remove,tone='danger',enabled=not removed),
                dict(label='Restore',command=restore,enabled=removed)]
        except (ValueError,OSError,KeyError,PermissionError):
            return [dict(label='Record unavailable — refresh the list',enabled=False)]
    from record_context_menu import RecordContextMenu
    win.record_context_menu=RecordContextMenu(win,tree,context_actions,title='Schedule actions')
    tree.bind('<<TreeviewSelect>>',show)
    view_combo.bind('<<ComboboxSelected>>',lambda _event:refresh())
    origin_combo.bind('<<ComboboxSelected>>',lambda _event:refresh())
    win.schedule_origin_filter=origin_view;win.schedule_state_filter=schedule_view
    timer=[None]
    def tick():
        try:
            if visible(win):rows_reader.request((schedule_view.get(),origin_view.get(),search.query.get()))
        except Exception as exc:status.set(str(exc))
        timer[0]=win.after(2000,tick)
    def close():
        if timer[0]:win.after_cancel(timer[0])
        win.destroy()
    win.on_close=close
    win.refresh_records=refresh
    win.schedule_tree=tree
    win.record_search=search
    win.record_classification=classification
    win.autonomous_recovery=autonomous
    win.recovery_toggle=recovery_toggle
    win.recovery_note=recovery_note
    win.bind('<Destroy>',lambda event:win.after_cancel(timer[0]) if event.widget is win and timer[0] else None,add='+')
    def resize_objective(event=None):
        viewport=max(1,int(event.height if event is not None else win.skin.canvas.winfo_height()))
        base=2 if embedded else 3
        rows=base+max(0,min(5,(viewport-850)//180))
        if int(objective.cget('height'))!=rows:objective.configure(height=rows)
    win.skin.canvas.bind('<Configure>',resize_objective,add='+')
    win.style_tree(tree);win.finish();refresh_templates();refresh();timer[0]=win.after(2000,tick)
    return win
