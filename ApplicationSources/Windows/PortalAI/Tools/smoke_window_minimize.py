"""Actual Windows launcher, disposable account, no production services."""
import argparse,ctypes,json,sys,time
from ctypes import wintypes
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Agent','ControlCenter')]
from smoke_login_continuity import run

def inspect(built,app,destination):
    u=ctypes.WinDLL('user32',use_last_error=True)
    u.IsIconic.argtypes=[wintypes.HWND];u.IsIconic.restype=wintypes.BOOL
    def spin():
        until=time.monotonic()+.15
        while time.monotonic()<until:app.update();time.sleep(.01)
    assert built['native_chat_panel'].drop_target.enabled
    records=[]
    for _ in range(8):
        built['chrome_buttons']['minimize'].invoke();spin()
        records.append(bool(u.IsIconic(built['_custom_hwnd']())))
        built['restore_from_tray']();spin()
    assert all(records),records
    # The shared login fixture suppresses the tray until our explicit test.
    tray=built['tray'];tray.show=type(tray).show.__get__(tray,type(tray))
    assert tray.show(),'Explorer refused the disposable tray icon'
    for _ in range(3):
        built['minimize_to_tray']();spin();assert app.state()=='withdrawn'
        built['restore_from_tray']();spin();assert app.state()=='normal'
    (destination/'window-cycles.json').write_text(json.dumps({'passed':True,'taskbar_cycles':8,'tray_cycles':3,'drop_hook_active':True}),encoding='utf-8')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();out=Path(args.artifacts_dir)
    report=run(out,inspector=inspect)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(not report.get('passed'))
