"""Persistent mission controls, using the existing Control Center palette."""
from pathlib import Path
from datetime import datetime
import json
import queue
import sys
import threading
import tkinter as tk
from rounded_text import RoundedText
from gold_controls import GoldSpinbox
from tkinter import ttk, messagebox

def mission_details(mission=None, *, mode=None, catalogue=None, memory=None, supervision=None, unavailable=None):
    """Show the same readable field guide with and without saved mission data."""
    m = mission or {}
    def when(item):
        if item is None:return None
        try:return datetime.fromtimestamp(item).strftime('%Y-%m-%d %H:%M:%S (local time)')
        except (ValueError, TypeError, OSError):return 'Invalid saved time; review required.'
    def value(item):
        if item is None or item == '' or item == [] or item == {}: return 'Nothing found to report.'
        return json.dumps(item, indent=2, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
    fields = [
        ('Mission ID', m.get('id')), ('Objective', m.get('objective')),
        ('Access permissions', (mode or {}).get('description')), ('Current status', m.get('status')),
        ('Actions used / allowed', f"{m.get('steps', 0)} / {m.get('max_steps', 0)}" if mission else None),
        ('Record source', (catalogue or {}).get('origin', {}).get('label')), ('Schedule ID', m.get('schedule_id')),
        ('Automatic continuation', ('Armed to continue' if supervision.get('enabled') else 'Not armed') if supervision is not None else None),
        ('Direct chat checkpoint', m.get('chat_checkpoint')),
        ('Next planned run', when(m.get('next_run_at'))), ('Subtasks being waited for', m.get('waiting_for_children')),
        ('Action awaiting execution or review', m.get('pending_action')),
        ('Latest action and result', m.get('history', [])[-1:]), ('Recent remembered context', memory),
        ('Last reported error', m.get('error')),
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
    from mission_catalog import MissionCatalog, VIEWS
    store = Missions(root)
    catalog = MissionCatalog(root, store=store)
    from internal_sheet import InternalSheet
    win = InternalSheet(parent, 'Missions and access', colors,embedded=embedded,framed=framed,fill_height=True)
    bg = colors.get("panel", colors.get("bg", "#17202A"))
    fg = colors.get("text", "#E5E5E5")
    accent = colors.get("accent", "#55C5BF")
    win.configure(bg=bg)
    frame = tk.Frame(win.content, bg=bg, padx=12, pady=5)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="Armed missions can resume after sign-in. Stop pauses them; runtime services are separate. Delete hides stopped records; Restore keeps files and history.", bg=bg, fg=fg, anchor='w', wraplength=1100, justify="left").pack(fill='x', pady=(0, 4))
    win.skin.label(frame, 'New mission objective', heading=True).pack(fill='x', anchor='w')
    objective = RoundedText(frame,palette=win.skin.colors,scrollbars=True,horizontal=False, height=2 if embedded else 3, wrap="word", bg=bg, fg=fg, insertbackground=fg, relief="solid", bd=1)
    objective.pack(fill="x")
    objective_state = tk.StringVar(value='No objective entered. Describe the outcome, inputs and limits; choose access and a budget, then Create mission.')
    tk.Label(frame, textvariable=objective_state, anchor='w', bg=bg, fg=accent, wraplength=780, justify='left').pack(fill='x', pady=(3, 0))
    def objective_changed(*_):
        if objective.edit_modified():
            objective_state.set('Draft only; nothing runs until you create and explicitly start the mission.' if objective.get('1.0', 'end').strip() else
                                'No objective entered. Describe the outcome, inputs and limits; choose access and a budget, then Create mission.')
            objective.edit_modified(False)
    objective.bind('<<Modified>>', objective_changed, add='+')
    from ui_extensions import ResponsiveFlow
    settings = ResponsiveFlow(frame, bg=bg, hgap=6, vgap=5)
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
    tk.Label(frame, textvariable=mode_description, bg=bg, fg=fg, anchor='w', justify="left", wraplength=1100).pack(fill='x', pady=(0, 3))
    filters = ResponsiveFlow(frame, bg=bg, hgap=6, vgap=4)
    filters.pack(fill='x', pady=(0, 3))
    filters.add(tk.Label(filters,text='Show',bg=bg,fg=fg))
    view = tk.StringVar(value=VIEWS[0])
    picker = win.skin.combo(filters,view,VIEWS);picker.configure(width=23)
    filters.add(picker)
    count = tk.StringVar()
    filters.add(tk.Label(filters, textvariable=count, bg=bg, fg=fg))
    tk.Label(frame, text='Legacy test? is a wording hint, not proven origin. Unclassified records stay visible.',
             bg=bg, fg=fg, anchor='w', wraplength=1100, justify='left').pack(fill='x', pady=(0, 2))
    data_area=tk.Frame(frame,bg=bg);data_area.pack(fill='both',expand=True)
    table=tk.Frame(data_area,bg=bg)
    detail_host=tk.Frame(data_area,bg=bg)
    from ui_extensions import adaptive_columns
    adaptive_columns(data_area,[table,detail_host],minimum=850 if embedded else 1350,stretch=True)
    win.skin.label(table, 'Saved missions', heading=True).pack(fill='x', anchor='w', pady=(0, 2))
    list_note = tk.StringVar()
    tk.Label(table, textvariable=list_note, anchor='w', bg=bg, fg=fg, wraplength=480, justify='left').pack(fill='x', pady=(0, 2))
    win.skin.label(detail_host, 'Selected mission details', heading=True).pack(fill='x', anchor='w', pady=(0, 2))
    tree = ttk.Treeview(table, columns=("origin", "mode", "status", "steps", "objective"), show="headings", height=4 if embedded else 8, selectmode="browse")
    for key, label, width in [("origin", "Record source", 112), ("mode", "Access", 130), ("status", "Status", 100), ("steps", "Used / limit", 85), ("objective", "Mission objective", 365)]:
        tree.heading(key, text=label)
        tree.column(key, width=width, stretch=key == "objective")
    tree.pack(fill="both", expand=True)
    win.style_tree(tree)
    from ui_extensions import ResponsiveGrid
    controls = ResponsiveGrid(frame,bg=bg,min_cell_width=145,max_columns=5,hgap=6,vgap=5)
    controls.pack(fill="x", pady=3)
    status = tk.StringVar(value="Select a mission to inspect its latest action and outcome.")
    detail = RoundedText(detail_host,palette=win.skin.colors,scrollbars=True,horizontal=False, height=9 if embedded else 12, font=("Segoe UI",9), wrap="word", bg=bg, fg=fg, relief="flat", state="disabled")
    detail.pack(fill="both", expand=True)
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

    def show_detail(*_):
        try:
            m = store.load(selected())
        except (ValueError, OSError) as exc:
            display_detail(mission_details(unavailable=exc if tree.selection() else None))
            return
        from mission_memory import Memory
        try:memory=Memory(store,m).recall(limit=3)
        except Exception as exc:memory={'error':str(exc)}
        display_detail(mission_details(m, mode=profile(m['mode']), catalogue=listed.get(m['id']),
                                       memory=memory, supervision=read_policy(store, m['id'])))

    def refresh():
        require_admin(root, session)
        existing = set(tree.get_children())
        rows = catalog.rows(view.get())
        listed.clear()
        listed.update((row['mission']['id'], row) for row in rows)
        count.set(f'{len(rows)} records shown')
        list_note.set('Select a row for its full objective, permissions and results.' if rows else
                      'Nothing found to report. Columns below show source, access, status, actions used / limit and objective.')
        from chat_priority import active as direct_chat_active
        chat_is_active=direct_chat_active(root)
        for row in reversed(rows):
            m = row['mission']
            label = 'Deleted · ' + m['status'] if row['deleted'] else 'paused for chat' if m.get('chat_paused') and m['status'] in ACTIVE and chat_is_active else m['status']
            values = (row['origin']['label'], profile(m["mode"])["label"], label, f"{m['steps']}/{m['max_steps']}", m["objective"][:150])
            if m["id"] in existing:
                tree.item(m["id"], values=values)
                existing.remove(m["id"])
            else:
                tree.insert("", "end", iid=m["id"], values=values)
        for key in existing:
            tree.delete(key)
        if catalog.errors:
            status.set('Some records need review; original files preserved: '+', '.join(x['mission'] for x in catalog.errors))
        show_detail()

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
            ensure_running(root)
            status.set("Armed until completion/action budget. Scheduled waits survive restart; the supervisor waits if chat is unavailable.")
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

    def delete():
        try:
            require_admin(root, session)
            if busy[0]: raise ValueError('Wait for the current request to finish')
            mid = selected()
            mission = store.load(mid)
            if mission.get('parent'): raise ValueError('Select the top-level mission; its subtasks are kept together')
            if listed.get(mid, {}).get('deleted'): raise ValueError('This record is already deleted from the working list')
            if mission['status'] in ACTIVE or read_policy(store, mid).get('enabled'):
                raise ValueError('Stop this mission and wait for its worker to finish before deleting')
            if mission.get('schedule_id'):
                raise ValueError('Scheduled run records are retained with their schedule; they cannot be deleted here')
            if not messagebox.askyesno('Delete mission from working list?',
                    'Move this stopped mission and its subtasks into the Deleted view?\n\n'
                    + mission['objective'][:240] + '\n\n'
                    'All original checkpoints, history, memory and generated files remain on this account’s SSD workspace. '
                    'This does not free disk space. Restore makes the records visible again without starting them. '
                    'Active, armed or schedule-linked missions are refused.', parent=win): return
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
    if not embedded:settings.add(win.skin.button(settings,'Schedules…',lambda:show_schedule_settings(win,root,colors,session=session)))
    settings.add(win.skin.button(settings,'Check VM',check_vm))
    for label, command in [("Run until finished", start), ("Stop", stop), ("Resume", resume),
                           ("Reviewed: skip action", lambda: resume("skip")), ("Reviewed: retry", lambda: resume("retry"))]:
        controls.add(win.skin.button(controls,label,command))
    for title,command in (('Refresh',refresh),('Delete…',delete),('Restore',restore)):
        filters.add(win.skin.button(filters,title,command))
    picker.bind('<<ComboboxSelected>>', lambda _event: refresh())
    tree.bind("<<TreeviewSelect>>", show_detail)
    timer = [None]
    def tick():
        try:
            while True:
                ok, message = events.get_nowait()
                busy[0] = False
                status.set(message)
        except queue.Empty:
            pass
        try:
            refresh()
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
    win.mission_detail=detail
    win.bind('<Destroy>', lambda event: win.after_cancel(timer[0]) if event.widget is win and timer[0] is not None else None, add='+')
    refresh()
    win.finish()
    timer[0] = win.after(1500, tick)
    return win
