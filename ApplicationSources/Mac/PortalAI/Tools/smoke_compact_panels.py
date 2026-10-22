"""Render the real launcher with disposable accounts and suppressed compute jobs."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Maintenance/Tests','ControlCenter','Agent')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window
from test_settings_surfaces_tk import button,widgets


def inspect(built,app,destination):
    metrics={};initial=app.geometry()
    for key in ('settings','maintenance','activity','installed','persistence','help','chat'):
        built['show_tab'](key);app.update()
        if key=='installed':
            for index,(state,detail) in enumerate(built['installed_rows'].values()):
                state.configure(text='INSTALLED');detail.configure(text=f'Synthetic installed component {index}. Bundled assets and capability details for layout checks.')
            view=built['packages_view'];view.apply_palette(view.skin.colors);view.queue_layout();app.update()
            metrics['packages']={'height':view.skin.canvas.winfo_height(),'content_height':view.skin.canvas.bbox('all')[3]}
        capture_window(app,destination/(key+'-default.png'))
        if key in ('settings','maintenance'):
            canvas=built['tab_scroll_canvases'][key];bounds=canvas.bbox('all')
            metrics[key]={'height':canvas.winfo_height(),'content_height':bounds[3] if bounds else 0}
        if key=='settings':
            for check,save in built['settings_page'].section_buttons.values():
                assert check.winfo_rootx()<save.winfo_rootx()
                assert save.winfo_rooty()+save.winfo_height()<app.winfo_rooty()+app.winfo_height()
        if key=='maintenance':
            panels=[built['diag_panel'],built['maintenance_panel'],built['storage_page'].skin.borders[0].widget]
            metrics['maintenance']['borders']=[(p.winfo_rootx(),p.winfo_width()) for p in panels]
            assert max(p.winfo_rootx() for p in panels)-min(p.winfo_rootx() for p in panels)<=2
        if key=='activity':
            assert not built['process_box'].border.simple
            assert all(not border.simple for border in built['activity_charts'].borders)
        if key=='persistence':
            page=built['persistence_page'];mission=page.pages['missions']
            metrics['missions']={'height':mission.skin.canvas.winfo_height(),'content_height':mission.skin.canvas.bbox('all')[3]}
            page.select('schedules');app.update();capture_window(app,destination/'schedules-default.png')
            schedule=page.pages['schedules'];metrics['schedules']={'height':schedule.skin.canvas.winfo_height(),'content_height':schedule.skin.canvas.bbox('all')[3]}
        if key=='help':assert built['documentation_panel'].listbox.yview()[0]==0
        if key=='chat':
            chat=built['native_chat_panel']
            for name in ('Chat Preferences','Memory','Instructions','Edit last'):
                assert button(chat.host,name).cget('fg')==chat.COL['muted'],name
            assert chat.history_btn.cget('fg')==chat.COL['muted']
    built['show_tab']('installed');view=built['packages_view'];view.select('weights');app.update()
    capture_window(app,destination/'weights-default.png')
    built['toggle_theme']();app.update()
    for key in ('settings','maintenance','persistence'):
        built['show_tab'](key);app.update();capture_window(app,destination/(key+'-dark.png'))
    built['toggle_theme']();app.update()
    app.geometry('720x820+40+40');app.update()
    for key in ('settings','maintenance','installed','persistence'):
        if key=='installed':view.select('packages')
        built['show_tab'](key);app.update();capture_window(app,destination/(key+'-narrow.png'))
    app.geometry(initial);app.update()
    (destination/'layout.json').write_text(json.dumps(metrics,indent=2),encoding='utf-8')
    assert all(value['content_height']<=value['height']+3 for value in metrics.values()),metrics


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True);args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),'light',inspector=inspect)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('compact-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(0 if report.get('passed') else 1)
