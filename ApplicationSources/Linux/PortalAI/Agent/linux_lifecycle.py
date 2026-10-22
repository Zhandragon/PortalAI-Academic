"""Native Linux GUI lifecycle, with owned listeners and durable Stop generation."""
from instance_runtime import port as _instance_port, url as _instance_url
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import build_plan,atomic_json
from linux_process import launch,identity,owned,stop


def start_all(root=ROOT, requested_at=None):
    import service_manager as service
    state={'success':False,'stage':'starting','started_at':time.time() if requested_at is None else requested_at}
    path=root/'Agent/.runtime/native_startup_state.json'
    try:
        from chat_model_switch import prepare_startup, _guard
        result=prepare_startup(root,requested_at=state['started_at'])
        _guard(root,state['started_at'])
        from mission_supervisor import ensure_running
        missions=ensure_running(root)
        _guard(root,state['started_at'])
        state.update(success=True,stage='ready',qwen={'port':_instance_port('qwen'),'profile':result['model']['id'],
                     'model':result['model'],'already_running':not result['changed']},missions=missions)
    except Exception as exc:state.update(error=str(exc),stage='failed')
    atomic_json(path,state)
    return state


def stop_all(root=ROOT):
    import service_manager as service
    from mission_supervisor import pause_all
    from sdcpp_bridge import cancel
    pause_all(root);cancel(root)
    with service._qwen_lifecycle_mutex():
        service._write_qwen_generation({'token':'stopped-'+uuid.uuid4().hex,'reason':'explicit-stop','stopped_at':time.time()})
        if service._listener_identity()['portable_qwen']:service._stop_qwen_listener()
    stopped=[]
    for name in ('comfyui','preview'):
        path=root/'Agent/.runtime'/f'linux-{name}.json'
        if not path.exists():continue
        row=json.loads(path.read_text())
        try:stop(row,root);stopped.append(name)
        except (FileNotFoundError,ProcessLookupError):pass
        path.unlink(missing_ok=True)
    return {'success':True,'stopped':stopped,'missions':'disarmed','model_restore':'cancelled'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['start','stop']);p.add_argument('--root',type=Path,default=ROOT)
    p.add_argument('--requested-at',type=float)
    p.add_argument('--include-opengui',action='store_true');p.add_argument('--quiet',action='store_true');a=p.parse_args()
    if a.root.resolve()!=ROOT:raise SystemExit('Root override is not supported')
    result=start_all(requested_at=a.requested_at) if a.action=='start' else stop_all()
    print(json.dumps(result));raise SystemExit(0 if result['success'] else 1)
