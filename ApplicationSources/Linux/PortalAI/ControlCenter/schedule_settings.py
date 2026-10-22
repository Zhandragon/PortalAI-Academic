"""Schedule controls kept inside the existing persistent-missions interface."""
from datetime import datetime
import json
from pathlib import Path
import tkinter as tk
from rounded_text import RoundedText
from tkinter import ttk


def schedule_details(schedule=None, *, enabled=None, access=None, unavailable=None):
    s = schedule or {}
    def when(value):
        if value is None:return None
        try:return datetime.fromtimestamp(value).strftime('%Y-%m-%d %H:%M:%S (local time)')
        except (ValueError, TypeError, OSError):return 'Invalid saved time; review required.'
    fields = [
        ('Schedule ID', s.get('id')), ('Objective for each run', s.get('objective')),
        ('Access permissions', access), ('Saved status', s.get('status')),
        ('Enabled to start runs', ('Yes' if enabled else 'No; paused') if enabled is not None else None),
        ('Repeat interval', ('Once only' if s.get('interval_seconds') == 0 else f"Every {s.get('interval_seconds', 0)/60:g} minutes") if schedule else None),
        ('Next planned run', when(s.get('next_run_at'))), ('Actions allowed per run', s.get('max_steps')),
        ('Run limit', ('Until stopped' if s.get('max_runs') == 0 else s.get('max_runs')) if schedule else None),
        ('Runs completed / started', f"{s.get('runs_completed', 0)} / {s.get('runs_started', 0)}" if schedule else None),
        ('Active mission ID', s.get('active_run')), ('Recent run results', s.get('history')),
        ('Last reported error', s.get('error')),
    ]
    def value(item):
        if item is None or item == '' or item == [] or item == {}:return 'Nothing found to report.'
        return json.dumps(item, indent=2, ensure_ascii=False) if isinstance(item, (dict, list)) else str(item)
    intro = ('Selected schedule: saved timing, limits and run results. Paused schedules do not start runs.' if schedule else
             'No schedule selected. Select a row in Saved schedules to see its details. Nothing found to report yet.')
    if unavailable:intro = 'Schedule details unavailable: '+str(unavailable)
    return intro+'\n\n'+'\n'.join(label+': '+value(item) for label, item in fields)


def show_schedule_settings(parent, root, colors, *, session=None, embedded=False, framed=True):
    from account_permissions import require_admin
    require_admin(root, session)
    from mission_schedule import Schedules
    from mission_supervisor import ensure_running
    from mission_modes import MODES, profile
    store=Schedules(root)
    from internal_sheet import InternalSheet
    win=InternalSheet(parent, 'Mission schedules', colors,embedded=embedded,framed=framed)
    bg=colors.get('panel',colors.get('bg'));fg=colors.get('text')
    win.configure(bg=bg)
    frame=tk.Frame(win.content,bg=bg,padx=12,pady=5);frame.pack(fill='both',expand=True)
    def label(text):
        w=tk.Label(frame,text=text,bg=bg,fg=fg,anchor='w',justify='left',wraplength=1100);w.pack(fill='x',pady=(0,4));return w
    label('One run at a time, with shared scoped memory and a separate action budget. Missed runs do not pile up; errors need review. Stop/Exit pauses schedules.\nKeep PortalAI running, the SSD connected and the computer awake.')
    win.skin.label(frame, 'New schedule objective', heading=True).pack(fill='x', anchor='w')
    objective=RoundedText(frame,palette=win.skin.colors,scrollbars=True,horizontal=False,height=2 if embedded else 3,wrap='word',bg=bg,fg=fg,insertbackground=fg);objective.pack(fill='x')
    objective_state=tk.StringVar(value='No objective entered. Describe each run, choose timing and access, then Create paused schedule. Existing rows are not edited here.')
    tk.Label(frame,textvariable=objective_state,anchor='w',bg=bg,fg=fg,wraplength=1100,justify='left').pack(fill='x',pady=(2,3))
    def objective_changed(*_):
        if objective.edit_modified():
            objective_state.set('Draft only. Creating saves it paused; Enable is a separate action.' if objective.get('1.0','end').strip() else
                                'No objective entered. Describe each run, choose timing and access, then Create paused schedule. Existing rows are not edited here.')
            objective.edit_modified(False)
    objective.bind('<<Modified>>',objective_changed,add='+')
    form=tk.Frame(frame,bg=bg);form.pack(fill='x',pady=2)
    win.skin.compact=embedded
    mode=tk.StringVar(value=profile('observe')['label']);labels={profile(m)['label']:m for m in MODES}
    interval=tk.StringVar(value='60');steps=tk.StringVar(value='12');limit=tk.StringVar(value='0');first=tk.StringVar()
    from ui_extensions import ResponsiveGrid
    fields=ResponsiveGrid(form,bg=bg,min_cell_width=270,max_columns=3 if embedded else 1,hgap=10,vgap=4)
    fields.pack(fill='x')
    for title,var in (('Repeat interval: minutes (0 = once)',interval),('Actions per run (1–100)',steps),('Run limit (0 = until stopped)',limit),('First run: local YYYY-MM-DD HH:MM (blank = now)',first)):
        cell=win.skin.frame(fields);fields.add(cell)
        win.skin.label(cell,title).pack(fill='x',pady=(0,2))
        entry=win.skin.entry(cell,'');entry.configure(textvariable=var);entry.pack(fill='x')
    cell=win.skin.frame(fields);fields.add(cell)
    win.skin.label(cell,'Access mode').pack(fill='x',pady=(0,2))
    win.skin.combo(cell,mode,list(labels)).pack(fill='x')
    create_cell=win.skin.frame(fields);fields.add(create_cell)
    hint=tk.StringVar()
    def describe(*_):hint.set(profile(labels[mode.get()])['description'])
    mode.trace_add('write',describe);describe()
    tk.Label(frame,textvariable=hint,bg=bg,fg=fg,anchor='w',wraplength=1100,justify='left').pack(fill='x',pady=(0,3))
    data_area=tk.Frame(frame,bg=bg);data_area.pack(fill='both',expand=True)
    table=tk.Frame(data_area,bg=bg)
    detail_host=tk.Frame(data_area,bg=bg)
    from ui_extensions import adaptive_columns
    adaptive_columns(data_area,[table,detail_host],minimum=850 if embedded else 10000)
    win.skin.label(table,'Saved schedules',heading=True).pack(fill='x',anchor='w',pady=(0,2))
    list_note=tk.StringVar()
    tk.Label(table,textvariable=list_note,anchor='w',bg=bg,fg=fg,wraplength=480,justify='left').pack(fill='x',pady=(0,2))
    win.skin.label(detail_host,'Selected schedule details',heading=True).pack(fill='x',anchor='w',pady=(0,2))
    tree=ttk.Treeview(table,columns=('status','next','runs','objective'),show='headings',height=3 if embedded else 6,selectmode='browse')
    for key,title,width in [('status','State',110),('next','Next run (local)',140),('runs','Completed / started',120),('objective','Objective',400)]:
        tree.heading(key,text=title);tree.column(key,width=width,stretch=key=='objective')
    tree.pack(fill='both',expand=True)
    from ui_extensions import ResponsiveGrid
    controls=ResponsiveGrid(frame,bg=bg,min_cell_width=140,max_columns=3);controls.pack(fill='x',pady=4)
    status=tk.StringVar(value='Creating a schedule does not enable it. Select it and click Enable when ready.')
    tk.Label(frame,textvariable=status,bg=bg,fg=fg,anchor='w',wraplength=1100,justify='left').pack(fill='x')
    detail=RoundedText(detail_host,palette=win.skin.colors,scrollbars=True,horizontal=False,height=9,font=('Segoe UI',9),wrap='word',bg=bg,fg=fg,state='disabled');detail.pack(fill='both',expand=True)
    def display_detail(text):
        if detail.get('1.0','end-1c')==text:return
        position=detail.yview()[0]
        detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0',text);detail.configure(state='disabled')
        detail.yview_moveto(position)
    def selected():
        ids=tree.selection()
        if not ids:raise ValueError('Select a schedule first')
        return ids[0]
    def show(*_):
        try:
            s=store.load(selected())
            display_detail(schedule_details(s,enabled=store.enabled(s),access=profile(s['mode'])['description']))
        except (ValueError,OSError) as exc:
            display_detail(schedule_details(unavailable=exc if tree.selection() else None))
    def refresh():
        old=set(tree.get_children())
        rows=store.list()
        list_note.set('Select a row to inspect its timing, progress and run results.' if rows else
                      'Nothing found to report. Columns show state, next run, completed / started runs and objective.')
        for s in rows:
            state=s['status'] if store.enabled(s) or s.get('status') in ('complete','needs_review') else 'paused'
            at=datetime.fromtimestamp(s['next_run_at']).strftime('%Y-%m-%d %H:%M') if 'next_run_at' in s else 'Review file'
            values=(state,at,f"{s.get('runs_completed',0)} / {s.get('runs_started',0)}",s['objective'][:160])
            if s['id'] in old:tree.item(s['id'],values=values);old.remove(s['id'])
            else:tree.insert('','end',iid=s['id'],values=values)
        for sid in old:tree.delete(sid)
        show()
    def create():
        try:
            require_admin(root, session)
            at=datetime.strptime(first.get().strip(),'%Y-%m-%d %H:%M').astimezone().timestamp() if first.get().strip() else None
            s=store.create(objective.get('1.0','end').strip(),labels[mode.get()],int(steps.get()),int(interval.get())*60,at,int(limit.get()))
            refresh();tree.selection_set(s['id']);show();status.set('Created paused. Enable explicitly to start this schedule.')
        except Exception as exc:status.set(str(exc))
    def toggle(enable):
        try:
            require_admin(root, session)
            if enable:
                store.enable(selected());result=ensure_running(Path(root));status.set('Schedule enabled. '+str(result.get('reason','Supervisor running.')))
            else:store.disable(selected());status.set('Schedule paused; any interrupted action requires review in Persistent missions.')
            refresh();show()
        except Exception as exc:status.set(str(exc))
    win.skin.button(create_cell,'Create paused schedule',create).pack(side='bottom',fill='x')
    for text,cmd in [('Enable',lambda:toggle(True)),('Pause',lambda:toggle(False)),('Refresh',refresh)]:
        controls.add(win.skin.button(controls,text,cmd))
    tree.bind('<<TreeviewSelect>>',show)
    timer=[None]
    def tick():
        try:refresh()
        except Exception as exc:status.set(str(exc))
        timer[0]=win.after(2000,tick)
    def close():
        if timer[0]:win.after_cancel(timer[0])
        win.destroy()
    win.on_close=close
    win.refresh_records=refresh
    win.schedule_tree=tree
    win.bind('<Destroy>',lambda event:win.after_cancel(timer[0]) if event.widget is win and timer[0] else None,add='+')
    win.style_tree(tree);win.finish();refresh();timer[0]=win.after(2000,tick)
    return win
