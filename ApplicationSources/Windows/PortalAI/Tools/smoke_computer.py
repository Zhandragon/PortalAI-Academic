"""Native Windows computer controller on its own disposable window only."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools')]
from validation_artifacts import ValidationArtifacts
from platform_runtime import python_path
from desktop_control import Desktop


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-root',type=Path,default=ROOT);p.add_argument('--artifacts-dir',required=True);p.add_argument('--wait-for-focus',action='store_true');args=p.parse_args()
    if os.name!='nt':raise RuntimeError('This acceptance requires Windows')
    root=args.runtime_root.resolve();artifacts=ValidationArtifacts(root,args.artifacts_dir);base=artifacts.path('desktop-fixture');base.mkdir()
    # Dependencies come from the active SSD; state is a new synthetic root.
    from knowledge_embeddings import packages
    packages(root)
    ctrl=Desktop(base,None);worker=subprocess.Popen([str(python_path(root)),'-B','-I',str(ROOT/'Maintenance/Tests/workspace_desktop_fixture.py'),str(base)],creationflags=subprocess.CREATE_NO_WINDOW)
    checks=[]
    try:
        deadline=time.monotonic()+15
        while not (base/'desktop-window.json').exists():
            if worker.poll() is not None:raise RuntimeError('Synthetic desktop exited')
            if time.monotonic()>deadline:raise TimeoutError('Synthetic window did not appear')
            time.sleep(.05)
        row=json.loads((base/'desktop-window.json').read_text());hwnd=row['window'];check=lambda:None
        try:ctrl.call('screenshot',{'window':hwnd},check)
        except PermissionError:checks.append('Window blocked before explicit grant')
        else:raise AssertionError('Ungrantable window was captured')
        assert any(r['window']==hwnd and r['pid']==worker.pid for r in ctrl.windows())
        ctrl.grant(hwnd)
        if args.wait_for_focus:
            print('Waiting for the authorized synthetic window to receive foreground focus',flush=True)
            deadline=time.monotonic()+60
            while ctrl.api()[0].GetForegroundWindow()!=hwnd:
                if time.monotonic()>deadline:raise TimeoutError('Foreground test window was not activated')
                time.sleep(.05)
        print(json.dumps({'fixture_window':hwnd,'foreground':ctrl.api()[0].GetForegroundWindow(),'fixture_pid':worker.pid}),flush=True)
        shot=ctrl.call('screenshot',{'window':hwnd},check);assert ctrl.image_message(shot['observation'])
        checks.append('Owned window discovery, process identity grant and actual PNG screenshot')
        def act(action,**kwargs):
            nonlocal shot
            token=shot['observation'];shot=ctrl.call(action,{'window':hwnd,'observation':token,**kwargs},check);return token
        old=act('click',x=row['entry'][0],y=row['entry'][1]);act('type',text='Portable computer control verified')
        try:ctrl.call('click',{'window':hwnd,'observation':old,'x':2,'y':2},check)
        except ValueError:checks.append('Consumed observation token refused')
        else:raise AssertionError('Stale action replayed')
        act('keypress',keys=['CTRL','A']);act('type',text='Portable verification 42');act('click',x=row['button'][0],y=row['button'][1])
        deadline=time.monotonic()+3
        while not (base/'desktop-result.json').exists() and time.monotonic()<deadline:time.sleep(.05)
        assert json.loads((base/'desktop-result.json').read_text())['text']=='Portable verification 42'
        checks.append('Real click, Unicode input, keyboard shortcut and button effect verified independently')
        before=ctrl.observation['rect'];act('window',operation='maximize');assert ctrl.observation['rect']!=before;act('window',operation='restore')
        checks.append('Real window maximize/restore followed by fresh screenshot')
        ctrl.revoke()
        try:ctrl.call('type',{'window':hwnd,'observation':shot['observation'],'text':'must not type'},check)
        except PermissionError:checks.append('Revocation blocks further input')
        else:raise AssertionError('Revoked input executed')
        result={'passed':True,'synthetic_only':True,'model_selected_actions':False,'checks':checks}
        artifacts.path('computer-smoke.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    finally:
        ctrl.revoke()
        if worker.poll() is None:worker.terminate()
        worker.wait(timeout=10)


if __name__=='__main__':main()
