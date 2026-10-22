"""Settings tabs and slider endpoints in a disposable, sealed launcher account."""
import argparse
import json
from pathlib import Path
import sys
from tkinter import font

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent','Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window


def inspect(built,app,destination):
    original=app.geometry();app.geometry('1260x820+40+40')
    measurements=[]
    persistence=built['persistence_page'];settings=built['settings_page']
    for mode in ('light','dark'):
        if mode=='dark':built['toggle_theme']()
        built['open_account_missions']();persistence.select('missions');app.update()
        reference=font.Font(app,font=persistence.buttons['missions'].cget('font')).actual()
        for button in persistence.buttons.values():
            assert button.winfo_rootx()>persistence.winfo_rootx()
            assert button.winfo_rooty()>persistence.winfo_rooty()
            assert button.winfo_rootx()+button.winfo_width()<persistence.winfo_rootx()+persistence.winfo_width()
        assert persistence.skin.borders[0].widget is persistence
        built['show_tab']('settings')
        for key in ('chat','media'):
            settings.tabs.select(key);app.update()
            assert all(font.Font(app,font=b.cget('font')).actual()==reference for b in settings.tabs.buttons.values())
            measurements.append({'case':f'settings-{mode}-{key}','tab_font':reference,
                                 'fits':settings.skin.canvas.yview()==(0.0,1.0)})
            capture_window(app,destination/f'settings-{mode}-{key}.png')
        built['show_tab']('chat');app.update()
        control=built['native_chat_panel'].effort;scale=control.scale
        # Exercise the real slider without saving model preferences or probing
        # hardware. The disposable UI gets the same three text labels.
        callback=scale.callback
        try:
            scale.callback=lambda value:control.label.configure(text=('Fast','Balanced','Deep')[int(float(value))])
            scale.set(0);app.update();x,y=scale.coords(0);endx,endy=scale.coords(2)
            assert x==scale.winfo_width()-endx,(x,endx,scale.winfo_width())
            assert endx>=scale.winfo_width()-10,(endx,scale.winfo_width())
            scale.event_generate('<ButtonPress-1>',x=x,y=y)
            scale.event_generate('<B1-Motion>',x=endx,y=endy)
            scale.event_generate('<ButtonRelease-1>',x=endx,y=endy);app.update()
            assert scale.get()==2 and control.label.cget('text')=='Deep'
            measurements.append({'case':f'effort-{mode}','value':scale.get(),'width':scale.winfo_width(),
                                 'thumb_center':scale.coords(),'right_edge_gap':scale.winfo_width()-endx-10})
            capture_window(app,destination/f'effort-{mode}.png')
        finally:scale.callback=callback
    app.geometry(original);built['toggle_theme']();app.update()
    (destination/'layout.json').write_text(json.dumps(measurements,indent=2),encoding='utf-8')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),inspector=inspect)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(not report.get('passed'))
