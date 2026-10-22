"""Disposable real-window selection, async reads and retained-memory editing."""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Tools', 'ControlCenter', 'Agent')]
from validation_artifacts import ValidationArtifacts
from writer_jobs import WriterJobs
THREAD = WriterJobs.thread
from smoke_login_continuity import run
from smoke_account_panels import capture_window


def inspect(built, app, destination):
    panel = built['native_chat_panel']; root = built['root']
    if root == ROOT or not root.is_relative_to(destination): raise ValueError('Disposable profile required')
    panel._thread = lambda **kwargs: THREAD(panel._writer_jobs, **kwargs)
    panel._schedule_model_probe = lambda **kwargs: None
    panel._schedule_memory_maintenance_original = panel._schedule_memory_maintenance
    panel._schedule_memory_maintenance = lambda *args, **kwargs: None
    sessions = []
    for n in range(4):
        session = panel.store.new_session()
        session.update(title=f'Synthetic history {n}', messages=[{'role': 'user', 'content': f'Unique needle {n}'}])
        panel.store.save_session(session); sessions.append(session)
    panel.load_session(sessions[-1]['id'], synchronous=True)
    built['show_tab']('chat'); app.geometry('972x820+30+30'); panel.refresh_sessions_labels_only(); app.update()
    box = panel.session_list
    box.selection_clear(0, 'end'); box.selection_set(0); box.selection_anchor(0); box.activate(0); box.focus_force()
    box.event_generate('<Shift-Down>'); app.update()
    assert box.curselection() == (0, 1), box.curselection()
    x,y,w,h = box.bbox(3)
    box.event_generate('<Control-Button-1>', x=x+4, y=y+h//2)
    box.event_generate('<Control-ButtonRelease-1>', x=x+4, y=y+h//2); app.update()
    assert box.curselection() == (0, 1, 3), box.curselection()
    selected = panel._selected_history_ids()
    panel.toggle_current_chat_memory(); app.update()
    assert all(not panel.memory.chat_included(sid) for sid in selected)
    assert set(panel._selected_history_ids()) == set(selected)
    panel.toggle_current_chat_memory(); app.update()
    assert all(panel.memory.chat_included(sid) for sid in selected)
    x,y,w,h = box.bbox(0); _,y2,_,h2 = box.bbox(2)
    box.event_generate('<Button-1>', x=x+4, y=y+h//2)
    box.event_generate('<B1-Motion>', x=x+4, y=y2+h2//2)
    box.event_generate('<ButtonRelease-1>', x=x+4, y=y2+h2//2); app.update()
    assert box.curselection() == (0, 1, 2), box.curselection()
    # The window must keep receiving callbacks during a deliberately slow disk read.
    beats = []
    active = [True]
    def beat():
        beats.append(time.monotonic())
        if active[0]: app.after(10, beat)
    beat()
    original = panel.store.load_session
    def slow(sid): time.sleep(.35); return original(sid)
    with patch.object(panel.store, 'load_session', side_effect=slow):
        panel.load_session(sessions[0]['id'])
        deadline = time.monotonic()+4
        while getattr(panel, '_session_load_request', None) and time.monotonic()<deadline:
            app.update(); time.sleep(.005)
    active[0] = False
    assert panel.session['id'] == sessions[0]['id']
    assert len(beats) >= 8, len(beats)
    for session in sessions:
        panel.memory._chat_state(session['id']).update(title=session['title'], capsule='Keep the first line. Remove this fragment. Keep the last line.', cursor=1)
    panel.memory.data['facts'] = {'fixture.preference': {'kind':'preference','observations': [
        {'session_id': sessions[0]['id'], 'value':'Keep blue; remove red; keep green.', 'importance':4}]}}
    panel.memory.save()
    panel.open_memory_panel(); app.update()
    editor = panel._memory_items_editor
    assert editor.search.get() == ''
    assert panel._memory_tabs.selected == 'retained'
    editor.list.selection_set(0); editor.select()
    start = editor.selected['text'].index('remove red; ')
    editor.detail.tag_add('sel', f'1.0+{start}c', f'1.0+{start+12}c')
    editor.delete(fragment=True)
    assert panel.memory.data['facts']['fixture.preference']['observations'][0]['value'] == 'Keep blue; keep green.'
    assert len(panel.memory.blocked_items()) == 1
    editor.toggle_blocked(); editor.list.selection_set(0); editor.select(); editor.delete()
    assert panel.memory.blocked_items() == []
    editor.toggle_blocked()
    # Explicit rebuild uses the existing inference interface with deterministic
    # fixture responses; this is lifecycle/UI evidence, not live model evidence.
    panel._schedule_memory_maintenance = panel._schedule_memory_maintenance_original
    panel.memory.set_chat_included(sessions[-1]['id'], False)
    panel._cached_model_online = True  # The inference interface below is a fixture.
    with patch.object(panel.memory, '_complete', return_value=json.dumps({'capsule':'Fresh synthetic capsule','upserts':[]})) as inference:
        panel._rebuild_included_memory()
        deadline=time.monotonic()+8
        while getattr(panel, '_memory_rebuild_pending', None) and time.monotonic()<deadline:
            app.update(); time.sleep(.01)
        assert panel._memory_rebuild_pending is None, 'Rebuild did not finish'
        assert inference.call_count == 3, inference.call_count
    assert panel.memory._chat_state(sessions[-1]['id'])['capsule'] != 'Fresh synthetic capsule'
    editor.list.selection_set(0); editor.select()
    for theme in ('light','dark'):
        if theme == 'dark': built['toggle_theme'](); app.update()
        for width in (972,720):
            app.geometry(f'{width}x820+30+30'); app.update()
            assert editor.delete_button.winfo_ismapped()
            capture_window(app,destination/f'memory-{theme}-{width}.png')
    built['toggle_theme'](); panel._close_sheet(); app.update()
    panel._memory_paused_by_stop=True
    (destination/'checks.json').write_text(json.dumps({'shift_arrow':True,'ctrl_click':True,'drag':True,
        'selection_preserved':True,'heartbeat_callbacks_during_read':len(beats),'fragment_delete':True,
        'blocked_item_release':True,'included_only_rebuild':True},indent=2),encoding='utf-8')


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args(); artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try: report=run(artifacts.path(),inspector=inspect)
    except Exception as exc: report={'passed':False,'error':str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(not report.get('passed'))
