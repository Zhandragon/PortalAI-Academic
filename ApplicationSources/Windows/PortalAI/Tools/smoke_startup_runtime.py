"""Disposable native GUI checks for model observations and telemetry event delivery."""
import argparse,json,sys,time,threading
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','ControlCenter','Agent')]
from smoke_login_continuity import run
from smoke_effort_settings_sync import inspect as inspect_saved_choices
from smoke_account_panels import capture_window
from validation_artifacts import ValidationArtifacts

def inspect(built,app,destination):
    tour=getattr(app,'_portalai_app_tour',None)
    if tour is not None:
        if tour.timer:app.after_cancel(tour.timer);tour.timer=None
        tour.close()
    from runtime_policy import load_effective_policy
    from model_preferences import save
    control=built['native_chat_panel'].effort;root=built['root']
    if any(m['id']=='qwen27-q4' for m in load_effective_policy(root)['models']):
        inspect_saved_choices(built,app,destination)
    else:
        # Academic keeps its standard-only catalogue throughout the same fixture.
        with patch.object(control,'refresh_capabilities'):
            for model,level in [('qwen1.7-q8','fast'),('qwen4-q4','balanced'),('qwen27-standard-q4','deep')]:
                save(root,{'selection':model});control.sync_saved_choice()
                assert control.profile==level
            assert all(m.get('variant','standard')=='standard' for m in load_effective_policy(root)['models'])
    def pump():
        until=time.monotonic()+.7
        while time.monotonic()<until:app.update();time.sleep(.01)
    with patch.object(control,'refresh_capabilities'):
        save(root,{'selection':'auto'})
        control.sync_saved_choice()
        model=next(m for m in load_effective_policy(root)['models'] if m['id']=='qwen27-standard-q4')
        event={'ok':True,'ticket':built['startup_gate'].ticket(),'policy_edited_at':built['last_policy_edit'][0],
               'model':model,'detail':'Synthetic 27B startup receipt; no model loaded'}
        built['event_q'].put(('startup_result',event));pump()
        assert control.profile=='deep' and int(control.scale.get())==2
        assert load_effective_policy(root)['selection']=='auto'
        control.sync_saved_choice();assert control.profile=='deep'
        built['show_tab']('chat');app.update()
        assert control.widget.winfo_ismapped()
        capture_window(app,destination/'automatic-27b.png')
        save(root,{'selection':'qwen4-q4'})
        built['last_policy_edit'][0]=time.monotonic()
        built['event_q'].put(('startup_result',event));pump()
        assert control.profile=='balanced' and int(control.scale.get())==1
        assert load_effective_policy(root)['selection']=='qwen4-q4'
        built['startup_gate'].cancel()
        built['event_q'].put(('startup_result',event));pump()
        assert control.profile=='balanced'
    # Sample actual host counters; no inventory or service/model startup is invoked.
    from activity_monitor import Sampler,TelemetryMonitor
    stop=threading.Event();rows=[]
    def publish(sample):rows.append(sample);built['event_q'].put(('telemetry',sample))
    monitor=TelemetryMonitor(Sampler(),stop,publish)
    thread=threading.Thread(target=monitor.run,name='SyntheticTelemetry',daemon=True)
    started=time.monotonic();thread.start();app.geometry('1100x920+30+30');built['show_tab']('activity')
    try:
        while time.monotonic()-started<36:app.update();time.sleep(.02)
        capture_window(app,destination/'runtime-warmup.png')
    finally:stop.set();thread.join(6)
    assert not thread.is_alive()
    assert len(rows)>=15, len(rows)
    assert any(row['cpu'] is not None for row in rows)
    assert len(built['activity_charts'].samples)==len(rows)
    assert rows[-1]['at']-rows[0]['at']>=30
    summary={'real_host_samples':len(rows),'observed_seconds':rows[-1]['at']-rows[0]['at'],
             'first_ten_seconds':sum(r['at']-rows[0]['at']<10 for r in rows),
             'last_intervals':[round(b['at']-a['at'],2) for a,b in zip(rows[-5:],rows[-4:])],
             'cpu_available':any(r['cpu'] is not None for r in rows),'gpu_available':any(r.get('gpu') is not None for r in rows),
             'monitor_stopped':True,'automatic_receipt_ui_synced':True,'later_manual_choice_won':True,'stale_stop_receipt_ignored':True}
    (destination/'runtime-summary.json').write_text(json.dumps(summary,indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--runtime-root',type=Path,default=ROOT)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),inspector=inspect,runtime_root=args.runtime_root)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report));raise SystemExit(not report.get('passed'))
