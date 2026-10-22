"""Measure actual launcher pages with disposable accounts and synthetic status."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent','Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window
from test_settings_surfaces_tk import widgets


def inspect(built,app,destination):
    original=app.geometry();measurements=[]
    import tkinter as tk
    from tkinter import ttk
    from mission_runner import Missions
    from mission_schedule import Schedules
    from mission_catalog import MissionCatalog
    root=built['root']
    mission=Missions(root).create('Inspect the synthetic report and summarize any changes')
    MissionCatalog(root).mark_origin(mission['id'])
    schedule=Schedules(root).create('Review the synthetic report once an hour','observe',12,3600,None,3)
    def measure(name,canvas,targets):
        app.update()
        bottom=canvas.winfo_rooty()+canvas.winfo_height()
        rows=[{'name':name,'height':canvas.winfo_height(),'content_height':canvas.bbox('all')[3],
               'fits':canvas.yview()==(0.0,1.0),
               'all_targets_visible':all(w.winfo_ismapped() and w.winfo_rooty()+w.winfo_height()<=bottom for w in targets)}]
        measurements.extend(rows)
        capture_window(app,destination/(name+'.png'))
    for mode in ('light','dark'):
        if built['theme_mode']!=mode and mode=='light':built['toggle_theme']()
        if mode=='dark':built['toggle_theme']()
        for width,height in ((1260,820),(1080,720)):
            app.geometry(f'{width}x{height}+40+40');built['show_tab']('runtime');app.update()
            # Only fixture state: no listeners, models or worker services start.
            for key in built['services']:
                built['set_pair'](built['services'],key,'STOPPED','On-demand; starts automatically when needed')
            built['set_pair'](built['services'],'qwen','READY','Synthetic Qwen3.5-27B-Uncensored-Q4_K_M.gguf; :8080')
            for key in built['activities']:
                built['set_pair'](built['activities'],key,'OFFLINE','Starts automatically when a media task needs it')
            built['set_pair'](built['activities'],'ace','MONITORING UNAVAILABLE','/v1/stats did not respond')
            built['set_pair'](built['activities'],'agent','QWEN INFERENCE','Active inference for 1m 35s; deferred=0')
            built['set_pair'](built['activities'],'qwen','POSSIBLY STALLED','Busy 1m 35s; token counters unchanged for 90s')
            for key,box in built['runtime_model_boxes'].items():
                built['set_box_text'](box,'Synthetic model / component\nCPU or GPU route remains unchanged')
            built['relayout_service_cards'](force=True);app.update()
            measure(f'models-{mode}-{width}',built['tab_scroll_canvases']['runtime'],built['service_cards'])
            built['open_account_missions']();page=built['persistence_page']
            for key in ('missions','schedules'):
                page.select(key);app.update();sheet=page.pages[key]
                tree=sheet.mission_tree if key=='missions' else sheet.schedule_tree
                tree.selection_set(mission['id'] if key=='missions' else schedule['id']);tree.event_generate('<<TreeviewSelect>>');app.update()
                controls=[w for w in widgets(sheet) if isinstance(w,ttk.Button)]
                measure(f'{key}-{mode}-{width}',sheet.skin.canvas,[tree,*controls])
    app.geometry('600x720+40+40')
    for key in ('missions','schedules'):
        built['persistence_page'].select(key);app.update()
        sheet=built['persistence_page'].pages[key]
        sheet.skin.canvas.yview_moveto(1);app.update()
        capture_window(app,destination/(key+'-narrow-bottom.png'))
    built['toggle_theme']();app.geometry(original);app.update()
    (destination/'layout.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')
    if EXPECT_FIT:
        assert all(row['fits'] and row['all_targets_visible'] for row in measurements if row['name'].endswith('-1260')),measurements


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',required=True);parser.add_argument('--expect-fit',action='store_true')
    args=parser.parse_args();EXPECT_FIT=args.expect_fit
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),inspector=inspect)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(not report.get('passed'))
