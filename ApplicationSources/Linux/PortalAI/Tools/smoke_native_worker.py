"""Exercise the shared media worker and cancellation without model/GPU loading."""
import json
from pathlib import Path
import sys
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
import sdcpp_bridge as sd
from smoke_profile import SmokeProfile


def main():
    profile=SmokeProfile(ROOT)
    checks=[]
    for kind,folder in [('image','Images'),('video','Videos'),('sfx','SFX'),('music','Music')]:
        def command(part):
            return [sys.executable,'-B','-c',
                    'import pathlib,sys;pathlib.Path(sys.argv[1]).write_bytes(b"PORTAL_WORKER_TEST")',str(part)]
        def validate(part):
            if part.read_bytes()!=b'PORTAL_WORKER_TEST':raise AssertionError('Worker output differs')
        result=sd.run_generation({'backend':'test','engine':'test'},command,validate,kind=kind,timeout=10)
        output=Path(result['files'][0])
        if output.parent!=profile.outputs(folder):raise AssertionError('Wrong output directory')
        output.unlink()  # Exact file created by this test, after verifying content.
        checks.append({'name':kind+' worker output staged and validated','passed':True})
    ready=threading.Event();finished=threading.Event();observed=[]
    def cancel():
        deadline=time.monotonic()+8
        while time.monotonic()<deadline and not finished.is_set():
            active=sd.media_runtime(ROOT)/'sdcpp-active.json'
            if active.exists():
                try:state=json.loads(active.read_text())
                except (OSError,ValueError):continue
                if state.get('backend')=='test' and state.get('kind')=='music':
                    observed.append(state['token']);sd.cancel(ROOT);ready.set();return
            time.sleep(.025)
    thread=threading.Thread(target=cancel);thread.start()
    try:
        try:
            sd.run_generation({'backend':'test','engine':'test'},
                lambda part:[sys.executable,'-B','-c','import time;time.sleep(20)'],
                lambda part:(_ for _ in ()).throw(AssertionError('Cancelled output must not validate')),
                kind='music',timeout=10)
        except RuntimeError as exc:
            if 'stopped' not in str(exc):raise
        else:raise AssertionError('Cancellation did not stop worker')
    finally:finished.set();thread.join(timeout=9)
    if not ready.is_set() or not observed:raise AssertionError('Cancellation did not observe its job')
    if list(profile.outputs('Music').glob('acestep_'+observed[0][:12]+'*')):raise AssertionError('Cancelled output published')
    checks.append({'name':'music cancellation publishes no output','passed':True})
    report={'passed':True,'model_or_gpu_inference':False,'checks':checks}
    profile.save('native-worker-smoke.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
