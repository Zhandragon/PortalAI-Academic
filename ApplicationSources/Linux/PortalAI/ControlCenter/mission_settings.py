"""Persistent mission controls, using the existing Control Center palette."""
from pathlib import Path
from datetime import datetime
import json
import queue
import sys
import threading
import tkinter as tk
from record_dates import RecordDates, describe as describe_dates, formatted as date_text
from record_controls import RecordSort, record_name, FoldPanel, record_columns
from rounded_text import RoundedText
from gold_controls import GoldSpinbox
from tkinter import ttk
from confirmation_dialog import ask_yes_no

def mission_details(mission=None, *, mode=None, catalogue=None, memory=None, supervision=None, unavailable=None):
    """Show the same readable field guide with and without saved mission data."""
    m = mission or {}
    def when(item):
        if item is None:return None
        try:return datetime.fromtimestamp(item).strftime('%Y-%m-%d %H:%M:%S (local time)')
        except (ValueError, TypeError, OverflowError, OSError):return 'Invalid saved time; review required.'
    def value(item):
        if item is None or item == '' or item == [] or item == {}: return 'Nothing found to report.'
        return json.dumps(item, indent=2, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
    dates = (catalogue or {}).get("dates") or describe_dates(m)
    fields = [
        ('Mission ID', m.get('id')), ('Name', record_name(m)), ('Objective', m.get('objective')),
        ('Created (local)', date_text(dates['created_at'], dates['created_fallback'])),
        ('Updated (local)', date_text(dates['updated_at'], dates['updated_fallback'])),
        ('Date information', dates['note']),
        ('Access permissions', (mode or {}).get('description')), ('Current status', m.get('status')),
        ('Actions used / allowed', f"{m.get('steps', 0)} / {m.get('max_steps', 0)}" if mission else None),
        ('Record source', (catalogue or {}).get('origin', {}).get('label')),
        ('Classification basis', (catalogue or {}).get('origin', {}).get('source')), ('Schedule ID', m.get('schedule_id')),
        ('Automatic continuation', ('Armed to continue' if supervision.get('enabled') else 'Not armed') if supervision is not None else None),
        ('Direct chat checkpoint', m.get('chat_checkpoint')),
        ('Next planned run', when(m.get('next_run_at'))), ('Subtasks being waited for', m.get('waiting_for_children')),
        ('Action awaiting execution or review', m.get('pending_action')),
        ('Latest action and result', m.get('history', [])[-1:]), ('Recent remembered context', memory),
        ('Last reported error', m.get('error')),
        ('Current review instructions', m.get('review_instructions')),
        ('Latest review', m.get('review_history', [])[-1:]),
    ]
    intro = ('Selected mission: current saved state. This view does not run actions.' if mission else
             'No mission selected. Select a row in Saved missions to see its details. Nothing found to report yet.')
    if unavailable: intro = 'Mission details unavailable: '+str(unavailable)
    return intro+'\n\n'+'\n'.join(label+': '+value(item) for label, item in fields)


def show_mission_settings(parent, root: Path, colors: dict, *, session=None, jobs=None, embedded=False, schedules=None, framed=True):
    root = Path(root).resolve()
    sys.path.insert(0, str(root / "Agent"))
    from account_permissions import require_admin
    require_admin(root, session)
    from profile_paths import enabled
    if enabled(root) and not callable(getattr(jobs, 'thread', None)):
        raise RuntimeError('Account missions require the tracked background-job shutdown gate.')
    from mission_runner import Missions, ACTIVE
    from mission_modes import MODES, profile, check_and_save
    from runtime_policy import require_space
    from mission_supervisor import arm, disarm, ensure_running, read_policy
    from mission_catalog import MissionCatalog, VIEWS, visible as row_visible
    from mission_search import matches
    from record_refresh import RecordRefresh, visible
    store = Missions(root)
    catalog = MissionCatalog(root, store=store)
    date_catalog = RecordDates(root, "missions", store=store)
    from internal_sheet import InternalSheet
    win = InternalSheet(parent, 'Missions', colors,embedded=embedded,framed=framed,fill_height=True)
    bg = colors.get("panel", colors.get("bg", "#17202A"))
    fg = colors.get("text", "#E5E5E5")
    accent = colors.get("accent", "#55C5BF")
    win.configure(bg=bg)
    frame = tk.Frame(win.content, bg=bg, padx=12, pady=5)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="Missions are one-shot tasks that run until completed.", bg=bg, fg=fg, anchor='w', wraplength=1100, justify="left").pack(fill='x', pady=(0, 4))
    creation = FoldPanel(frame,win.skin,'New mission')
    creation.pack(fill='x',pady=(0,3));create_body=creation.body
    win.creation_panel=creation
    win.skin.label(create_body, 'New mission objective', heading=True).pack(fill='x', anchor='w')
    objective = RoundedText(create_body,palette=win.skin.colors,scrollbars=True,horizontal=False, height=2 if embedded else 3, wrap="word", bg=bg, fg=fg, insertbackground=fg, relief="solid", bd=1)
    objective.pack(fill="x")
    objective_state = tk.StringVar(value='No objective entered. Describe the outcome, inputs and limits; choose access and a budget, then Create mission.')
    tk.Label(create_body, textvariable=objective_state, anchor='w', bg=bg, fg=accent, wraplength=780, justify='left').pack(fill='x', pady=(3, 0))
    def objective_changed(*_):
        if objective.edit_modified():
            objective_state.set('Draft only; nothing runs until you create and explicitly start the mission.' if objective.get('1.0', 'end').strip() else
                                'No objective entered. Describe the outcome, inputs and limits; choose access and a budget, then Create mission.')
            objective.edit_modified(False)
    objective.bind('<<Modified>>', objective_changed, add='+')
    from ui_extensions import ResponsiveFlow
    settings = ResponsiveFlow(create_body, bg=bg, hgap=6, vgap=5)
    settings.pack(fill="x", pady=3)
    mode_labels = {profile(key)["label"]: key for key in MODES}
    mode = tk.StringVar(value=profile("observe")["label"])
    steps = tk.StringVar(value="12")
    mode_choice=win.skin.combo(settings,mode,list(mode_labels));mode_choice.configure(width=23);settings.add(mode_choice)
    budget_frame=win.skin.frame(settings)
    tk.Label(budget_frame,text='Action budget',bg=bg,fg=fg).pack(side='left',padx=(0,6))
    budget=GoldSpinbox(budget_frame,from_=1,to=100,textvariable=steps,width=5,palette=win.skin.colors)
    budget.pack(side='left');win.skin.gold_controls.append(budget)
    settings.add(budget_frame)
    mode_description = tk.StringVar()
    def describe(*_):
        mode_description.set(profile(mode_labels[mode.get()])["description"] + " Applies to new missions.")
    mode.trace_add("write", describe)
    describe()
    tk.Label(create_body, textvariable=mode_description, bg=bg, fg=fg, anchor='w', justify="left", wraplength=1100).pack(fill='x', pady=(0, 3))
    from record_controls import RecordSearch, RecordClassification
    data_area=tk.Frame(frame,bg=bg);data_area.pack(fill='both',expand=True)
    table=tk.Frame(data_area,bg=bg)
    detail_host=tk.Frame(data_area,bg=bg)
    record_columns(data_area,table,detail_host)
    win.skin.label(table, 'Saved missions', heading=True).pack(fill='x', anchor='w', pady=(0, 2))
    search = RecordSearch(table, win.skin, lambda: refresh())
    search.pack(fill='x',pady=(0,3))
    filter_panel=FoldPanel(table,win.skin,'Filters & list actions');filter_panel.pack(fill='x')
    win.filters_panel=filter_panel
    filters = ResponsiveFlow(filter_panel.body, bg=bg, hgap=6, vgap=4)
    filters.pack(fill='x', pady=(0, 3))
    filters.add(tk.Label(filters,text='Show',bg=bg,fg=fg))
    view = tk.StringVar(value=VIEWS[0])
    picker = win.skin.combo(filters,view,VIEWS);picker.configure(width=23)
    filters.add(picker)
    count = tk.StringVar()

    list_note = tk.StringVar()
    tk.Label(table, textvariable=list_note, anchor='w', bg=bg, fg=fg, wraplength=480, justify='left').pack(fill='x', pady=(0, 2))
    win.skin.label(detail_host, 'Selected mission details', heading=True).pack(fill='x', anchor='w', pady=(0, 2))
    tree = ttk.Treeview(table, columns=("origin", "mode", "status", "steps", "objective", "name", "created", "updated", "id"), displaycolumns=("name", "status", "origin", "created", "updated", "mode", "steps", "objective", "id"), show="headings", height=4 if embedded else 8, selectmode="browse")
    for key, label, width in [("origin", "Category / source", 150), ("mode", "Access", 130), ("status", "Status", 150), ("steps", "Used / limit", 105), ("objective", "Description", 365), ("name", "Name", 240), ("created", "Created (local)", 175), ("updated", "Updated (local)", 175), ("id", "Mission ID", 290)]:
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=key == "objective")
    tree.pack(fill="both", expand=True)
    win.style_tree(tree)
    sorter = RecordSort(tree, lambda: refresh())
    win.record_sort = sorter
    from ui_extensions import ResponsiveGrid
    controls = ResponsiveGrid(frame,bg=bg,min_cell_width=145,max_columns=5,hgap=6,vgap=5)
    controls.pack(fill="x", pady=3)
    status = tk.StringVar(value="Select a mission to inspect its latest action and outcome.")
    options=FoldPanel(detail_host,win.skin,'Classification');options.pack(fill='x',pady=(0,3))
    win.options_panel=options
    classification = RecordClassification(options.body, win.skin, lambda: classify(), mission=True)
    classification.pack(fill='x', pady=(0, 3))
    from mission_monitor import RunViewer,controller_status,live_state,mission_enabled
    viewer=RunViewer(detail_host,win.skin,store,height=7 if embedded else 10,jobs=jobs)
    viewer.pack(fill='both',expand=True);detail=viewer.text;win.run_viewer=viewer
    review_host=FoldPanel(detail_host,win.skin,'Add review instructions')
    win.review_panel=review_host
    review_body=review_host.body
    win.skin.label(review_body,'Additional instructions for this mission',heading=True).pack(fill='x')
    tk.Label(review_body,text='Edit the current guidance; prior versions are kept. Applies to this run only. Stop and schedule Enable remain separate.',
             bg=bg,fg=fg,anchor='w',wraplength=620,justify='left').pack(fill='x')
    review_text=RoundedText(review_body,palette=win.skin.colors,scrollbars=True,horizontal=False,height=3,
                            wrap='word',bg=bg,fg=fg,insertbackground=fg,relief='solid',bd=1)
    review_text.pack(fill='x')
    review_choices={'Unresolved: save guidance only':None,'Reviewed: skip pending action':'skip','Reviewed: allow retry / replan':'retry'}
    review_resolution=tk.StringVar(value=next(iter(review_choices)))
    review_picker=win.skin.combo(review_body,review_resolution,list(review_choices));review_picker.pack(fill='x',pady=3)
    review_drafts={};review_current=[None];review_results=queue.Queue()
    def sync_review(m=None):
        mid=m['id'] if m else None
        if mid!=review_current[0]:
            previous=review_current[0]
            if previous in review_drafts:
                review_drafts[previous]['text']=review_text.get('1.0','end-1c')
                review_drafts[previous]['resolution']=review_resolution.get()
            review_current[0]=mid
            if m:
                draft=review_drafts.setdefault(mid,{'text':m.get('review_instructions',''),'version':m['updated_at'],'resolution':next(iter(review_choices))})
                review_text.delete('1.0','end');review_text.insert('1.0',draft['text']);review_resolution.set(draft['resolution'])
        available=bool(m and m['status'] in ('paused','needs_review') and not listed.get(mid,{}).get('deleted'))
        if available:
            review_host.pack(fill='x',pady=(5,0))
            review_picker.configure(state='readonly' if m.get('pending_action') else 'disabled')
        else:review_host.pack_forget()
    tk.Label(frame, textvariable=status, bg=bg, fg=accent, anchor="w", justify="left", wraplength=1100).pack(fill="x", pady=(2, 0))
    events = queue.Queue()
    busy = [False]
    listed = {}

    def display_detail(text):
        if detail.get('1.0', 'end-1c') == text:return
        position = detail.yview()[0]
        detail.configure(state='normal'); detail.delete('1.0', 'end'); detail.insert('1.0', text)
        detail.configure(state='disabled'); detail.yview_moveto(position)

    def selected():
        values = tree.selection()
        if not values:
            raise ValueError("Select a mission first")
        return values[0]

    def load_detail(request):
        mid, catalogue = request
        m=store.load(mid)
        from mission_memory import Memory
        try:memory=Memory(store,m).recall(limit=3)
        except Exception as exc:memory={'error':str(exc)}
        policy=read_policy(store,mid)
        return dict(m=m,catalogue=catalogue,enabled=mission_enabled(store,m),
                    details=mission_details(m,mode=profile(m['mode']),catalogue=catalogue,
                                            memory=memory,supervision=policy))

    def apply_detail(value):
        m=value['m']
        classification.show(m['id'],value['catalogue'].get('classification'))
        viewer.update_view(m,details=value['details'],enabled=value['enabled'])
        sync_review(m)

    def detail_failed(exc):
        classification.show();sync_review()
        viewer.reader.discard();viewer.context={};viewer.run_ids={}
        viewer._display((mission_details(unavailable=exc),True))

    detail_reader=RecordRefresh(win,load_detail,apply_detail,check=lambda:require_admin(root,session),
                                error=detail_failed,jobs=jobs)
    def show_detail(*_):
        values=tree.selection()
        if not values:
            detail_reader.discard()
            detail_failed(None)
            return
        mid=values[0]
        if viewer.identity!=mid:
            classification.show();sync_review()
            viewer.reader.discard()
            viewer._display(('Loading selected mission…',True))
        detail_reader.request((mid,dict(listed.get(mid,{}))))

    def load_rows(request):
        view_name,query=request
        all_rows=catalog.rows('All records')
        errors=list(catalog.errors)
        summaries={row['mission']['id']:row['mission'] for row in all_rows}
        if query.strip():
            rows=[row for row in all_rows if matches(query,row['mission']['id'],row['mission'].get('objective'),
                row['mission'].get('schedule_id'),row['mission'].get('parent'),row['mission'].get('status'),row['origin']['label'])]
        else:rows=[row for row in all_rows if row_visible(row,view_name)]
        from chat_priority import active as direct_chat_active
        chat_is_active=direct_chat_active(root)
        controller=controller_status(store)
        order={};items=[]
        for row in reversed(rows):
            m=row['mission']
            label='Deleted · '+m['status'] if row['deleted'] else 'paused for chat' if m.get('chat_paused') and m['status'] in ACTIVE and chat_is_active else m['status']
            if not row['deleted'] and m['status'] in ACTIVE:
                try:
                    from mission_activity import read as read_activity
                    armed=mission_enabled(store,m,summaries)
                    label=live_state(m,read_activity(store,m['id']) if armed else {},controller,enabled=armed)
                except (OSError,ValueError,KeyError,TypeError):label='Status unavailable; review details'
            dates=row['dates']=date_catalog.info(m)
            name=record_name(m)
            values=(row['origin']['label'],profile(m['mode'])['label'],label,f"{m['steps']}/{m['max_steps']}",m['objective'][:150],name[:150],
                    date_text(dates['created_at'],dates['created_fallback']),date_text(dates['updated_at'],dates['updated_fallback']),m['id'])
            order[m['id']]=dict(zip(('origin','mode','status','steps','objective','name','created','updated','id'),values))
            order[m['id']].update(name=name,objective=m['objective'],steps=(m['steps'],m['max_steps']),
                                  created=dates['created_at'],updated=dates['updated_at'])
            items.append((m['id'],values))
        return dict(rows=rows,items=items,order=order,errors=errors,query=query)

    def apply_rows(value):
        rows=value['rows'];query=value['query'];existing=set(tree.get_children())
        listed.clear();listed.update((row['mission']['id'],row) for row in rows)
        count.set(f'{len(rows)} '+('search matches (all records)' if query.strip() else 'records shown'))
        list_note.set(count.get()+'. Search IDs/keywords; click headings to sort.' if rows else 'No matches. Search an ID/keyword or change Filters.')
        for mid,values in value['items']:
            if mid in existing:
                if tuple(tree.item(mid,'values'))!=tuple(str(v) for v in values):tree.item(mid,values=values)
                existing.remove(mid)
            else:tree.insert('', 'end',iid=mid,values=values)
        for mid in existing:tree.delete(mid)
        sorter.apply(value['order'])
        if query.strip() and len(rows)==1 and not tree.selection():
            tree.selection_set(rows[0]['mission']['id']);tree.see(rows[0]['mission']['id'])
        if value['errors']:status.set('Some records need review; original files preserved: '+', '.join(x['mission'] for x in value['errors']))
        show_detail()

    def rows_failed(exc):
        listed.clear()
        for mid in tree.get_children():tree.delete(mid)
        detail_reader.discard();detail_failed(exc)
        status.set(str(exc))

    rows_reader=RecordRefresh(win,load_rows,apply_rows,check=lambda:require_admin(root,session),error=rows_failed,jobs=jobs)
    def refresh():
        rows_reader.request((view.get(),search.query.get()),invalidate=True)
    win.bind('<Map>',lambda event:refresh() if event.widget is win else None,add='+')

    def classify():
        try:
            require_admin(root, session)
            if busy[0]:raise ValueError('Wait for the current request to finish')
            mid=selected()
            catalog.classify(mid, classification.chosen())
            classification.current=None
            refresh()
            status.set('Classification saved for '+mid+'. Automatic uses the original recorded or inferred source.')
        except Exception as exc:status.set(str(exc))

    def background(task):
        if busy[0]:
            status.set("Wait for the current request to finish.")
            return
        busy[0] = True
        status.set("Working…")
        def run():
            try:
                require_admin(root, session)
                events.put((True, task()))
            except Exception as exc:
                events.put((False, f"{type(exc).__name__}: {exc}"))
        (jobs.thread if jobs is not None else threading.Thread)(target=run, daemon=True).start()

    def create():
        text, execution_mode = objective.get("1.0", "end").strip(), mode_labels[mode.get()]
        try:
            budget = int(steps.get())
        except ValueError:
            status.set("Action budget must be an integer from 1 to 100.")
            return
        def task():
            require_space(root, for_outputs=True)
            m = store.create(text, execution_mode, budget)
            message = "Created " + m["id"] + ". Select it and start the worker when ready."
            try: catalog.mark_origin(m['id'])
            except Exception as exc: message += ' Origin label could not be saved: ' + str(exc)
            return message
        background(task)

    def check_vm():
        def task():
            result = check_and_save(root, probe=True)
            if not result["vm"]["ready"]:
                raise RuntimeError(result["vm"]["error"])
            return "VM check passed: hardware-backed guest, unprivileged user, offline, no host mounts. Report: Maintenance/Reports/execution-modes.json"
        background(task)

    def start():
        try:
            require_admin(root, session)
            mission_id = selected()
            if listed.get(mission_id, {}).get('deleted'):
                raise ValueError('Restore this mission to the working list first; restoration does not start it')
            m = store.load(mission_id)
            if m["status"] not in ACTIVE:
                raise ValueError("Resume this mission first; completed/exhausted missions need a new action budget")
            if (store.folder(mission_id) / "STOP").exists():
                raise ValueError("Resume the stopped mission first")
            arm(root, mission_id)
            result=ensure_running(root)
            status.set('Mission armed. '+('Starting supervisor; follow Live activity.' if result.get('started') else
                       'Supervisor already active; follow Live activity.' if result.get('already_running') else result.get('reason','Supervisor startup is not confirmed.')))
        except Exception as exc:
            status.set(str(exc))

    def stop():
        try:
            require_admin(root, session)
            disarm(root, selected())
            status.set("Stop requested for this mission and its current subtasks. Interrupted actions require review.")
            refresh()
        except Exception as exc:
            status.set(str(exc))

    def resume(reviewed=None):
        try:
            mission_id = selected()
            if listed.get(mission_id, {}).get('deleted'):
                raise ValueError('Restore this mission to the working list before resuming')
        except ValueError as exc:
            status.set(str(exc))
            return
        def task():
            store.resume(mission_id, reviewed)
            return "Resumed. Use Run until finished on the root mission; paused subtasks must be resumed separately."
        background(task)

    def review_with_instructions():
        try:
            require_admin(root,session)
            mid=selected()
            if mid!=review_current[0] or listed.get(mid,{}).get('deleted'):
                raise ValueError('Select a stopped mission and inspect its details first')
            text=review_text.get('1.0','end-1c').strip()
            if not text:raise ValueError('Enter additional instructions before submitting the review')
            version=review_drafts[mid]['version'];resolution=review_choices[review_resolution.get()]
            current=store.load(mid)
            if current['updated_at']!=version:
                # Show fresh evidence, but do not apply the old decision to it.
                review_drafts[mid]['version']=current['updated_at']
                review_resolution.set(next(iter(review_choices)))
                show_detail()
                raise ValueError('The mission changed. Details refreshed; inspect the new outcome, choose its resolution and submit again. Your instructions are retained.')
        except Exception as exc:
            status.set(str(exc));return
        def task():
            result=store.review(mid,text,resolution,expected_updated_at=version)
            review_results.put((mid,result['updated_at'],text))
            if result.get('pending_action'):
                return 'Instructions saved. The pending action is still unresolved; inspect its outcome and choose skip or retry before continuing.'
            if result['status']=='paused':
                return 'Instructions saved. Stop remains in effect; use Resume when ready, then Enable the schedule or Run until finished on the root mission.'
            return ('Instructions saved for the next plan. Enable this schedule to continue this run; future runs keep their original objective.' if result.get('schedule_id') else
                    'Instructions saved for the next plan. An armed mission can continue; otherwise use Run until finished on its root.')
        background(task)

    review_button=win.skin.button(review_body,'Reviewed: additional instructions',review_with_instructions)
    review_button.pack(fill='x')

    def delete():
        try:
            deletion_session = require_admin(root, session)
            if busy[0]: raise ValueError('Wait for the current request to finish')
            mid = selected()
            mission = store.load(mid)
            if mission.get('parent'): raise ValueError('Select the top-level mission; its subtasks are kept together')
            if listed.get(mid, {}).get('deleted'): raise ValueError('This record is already deleted from the working list')
            if mission['status'] in ACTIVE or read_policy(store, mid).get('enabled'):
                raise ValueError('Stop this mission and wait for its worker to finish before deleting')
            if mission.get('schedule_id'):
                raise ValueError('Scheduled run records are retained with their schedule; they cannot be deleted here')
            if not ask_yes_no('Delete mission from working list?',
                    'Move this stopped mission and its subtasks into the Deleted view?\n\n'
                    + mission['objective'][:240] + '\n\n'
                    'All original checkpoints, history, memory and generated files remain on this account’s SSD workspace. '
                    'This does not free disk space. Restore makes the records visible again without starting them. '
                    'Active, armed or schedule-linked missions are refused.', parent=win, colors=win.skin.colors,
                    validate=lambda: require_admin(root, deletion_session)): return
        except Exception as exc:
            status.set(str(exc)); return
        def task():
            result = catalog.delete(mid)
            return f"Deleted {result['records_retained']} record(s) from the working list. Restore is available in Deleted; no files were erased."
        background(task)

    def restore():
        try:
            row = listed[selected()]
            mid = row.get('deleted_root')
            if not mid: raise ValueError('Select a deleted record first')
        except (KeyError, ValueError) as exc:
            status.set(str(exc)); return
        def task():
            catalog.restore(mid)
            return 'Restored to the working list. No mission was resumed or armed.'
        background(task)

    settings.add(win.skin.button(settings,'Create mission',create))
    from schedule_settings import show_schedule_settings
    if not embedded:settings.add(win.skin.button(settings,'Schedules…',lambda:show_schedule_settings(win,root,colors,session=session,jobs=jobs)))
    settings.add(win.skin.button(settings,'Check VM',check_vm))
    for label, command in [("Run until finished", start), ("Stop", stop), ("Resume", resume),
                           ("Reviewed: skip action", lambda: resume("skip")), ("Reviewed: retry", lambda: resume("retry"))]:
        controls.add(win.skin.button(controls,label,command))
    for title,command in (('Refresh',refresh),('Delete…',delete),('Restore',restore)):
        filters.add(win.skin.button(filters,title,command))
    def context_actions(mid):
        try:
            m=store.load(mid);deleted=bool(listed.get(mid,{}).get('deleted'))
            armed=bool(read_policy(store,mid).get('enabled'));stopped=store.stopped(m)
            pending=bool(m.get('pending_action'));available=not deleted and not busy[0]
            version=m.get('updated_at')
            def reviewed(resolution):
                if store.load(mid).get('updated_at')!=version:
                    status.set('Mission changed. Inspect its latest action before reviewing it.');refresh();return
                resume(resolution)
            return [
                dict(label='Run',command=start,enabled=available and m['status'] in ACTIVE and not stopped and not pending and not armed),
                dict(label='Stop',command=stop,enabled=not deleted and (armed or (m['status'] in ACTIVE and not stopped))),
                dict(label='Resume',command=resume,enabled=available and not pending and (stopped or m['status']=='needs_review')),
                None,
                dict(label='Review: retry',command=lambda:reviewed('retry'),enabled=available and pending),
                dict(label='Review: skip',command=lambda:reviewed('skip'),enabled=available and pending),
                None,
                dict(label='Delete…',command=delete,tone='danger',enabled=available and not m.get('parent') and not m.get('schedule_id') and m['status'] not in ACTIVE and not armed),
                dict(label='Restore',command=restore,enabled=deleted and not busy[0])]
        except (ValueError,OSError,KeyError,PermissionError):
            return [dict(label='Record unavailable — refresh the list',enabled=False)]
    from record_context_menu import RecordContextMenu
    win.record_context_menu=RecordContextMenu(win,tree,context_actions,title='Mission actions')
    picker.bind('<<ComboboxSelected>>', lambda _event: refresh())
    tree.bind("<<TreeviewSelect>>", show_detail)
    timer = [None]
    def tick():
        try:
            while True:
                mid,version,text=review_results.get_nowait()
                if mid in review_drafts:review_drafts[mid]['version']=version
        except queue.Empty:
            pass
        try:
            while True:
                ok, message = events.get_nowait()
                busy[0] = False
                status.set(message)
        except queue.Empty:
            pass
        try:
            if visible(win):rows_reader.request((view.get(),search.query.get()))
        except Exception as exc:
            status.set(str(exc))
        timer[0] = win.after(1500, tick)
    def close():
        if timer[0] is not None:
            win.after_cancel(timer[0])
            timer[0] = None
        win.destroy()
    win.on_close = close
    win.refresh_records=refresh
    win.mission_tree=tree
    win.record_search=search
    win.record_classification=classification
    win.mission_detail=detail
    win.review_instructions=review_text
    win.review_resolution=review_resolution
    win.review_submit=review_button
    win.review_status=status
    win.bind('<Destroy>', lambda event: win.after_cancel(timer[0]) if event.widget is win and timer[0] is not None else None, add='+')
    def resize_objective(event=None):
        viewport=max(1,int(event.height if event is not None else win.skin.canvas.winfo_height()))
        base=2 if embedded else 3
        rows=base+max(0,min(5,(viewport-850)//180))
        if int(objective.cget('height'))!=rows:objective.configure(height=rows)
    win.skin.canvas.bind('<Configure>',resize_objective,add='+')
    refresh()
    win.finish()
    timer[0] = win.after(1500, tick)
    return win
