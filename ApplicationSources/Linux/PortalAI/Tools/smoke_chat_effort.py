"""Sequential live Fast/Deep/Fast switching; restores the initial owned model."""
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
import service_manager as service
from chat_model_switch import prepare_chat,_argv,_guard,_owned_listener,_require_idle,PreparationCancelled
from runtime_policy import atomic_json


def restore_baseline(original, expected, saved, started_at, report):
    """Restore only this test's idle listener, and never undo a subsequent Stop."""
    lease=None
    try:
        _guard(ROOT,started_at)
        lease=service.acquire_gpu_lease('effort-smoke-return',timeout=3)
        with service._qwen_lifecycle_mutex():
            _guard(ROOT,started_at)
            current=_owned_listener()
            if not current['open']:
                report['baseline_restoration_skipped']='No model is running; no unsolicited restart was attempted'
                return
            if current.get('listeners')!=expected.get('listeners'):
                report['baseline_restoration_skipped']='Listener identity changed outside the recorded test step'
                return
            same=all(_argv(row['command_line'])==_argv(original) for row in current['listeners'])
            if not same:_require_idle()
        if not same:
            def before_handoff():
                _guard(ROOT,started_at)
                if _owned_listener().get('listeners')!=expected.get('listeners'):
                    raise RuntimeError('Listener changed before test cleanup; it was left untouched')
                _require_idle()
            state=service.qwen_gpu_handoff_begin('effort-smoke-return',start_guard=before_handoff)
            if not state.get('active'):
                raise RuntimeError('Baseline restoration could not capture the test listener')
            with service._qwen_lifecycle_mutex():
                _guard(ROOT,started_at,state=state)
                state['command_line']=original
                atomic_json(Path(state['state_path']),state)
                service._remember_qwen_launch(original,_argv(original)[0])
            result=service.qwen_gpu_handoff_end(state)
            if not result.get('ready'):
                raise RuntimeError('Baseline restoration did not return a healthy model')
        with service._qwen_lifecycle_mutex():
            _guard(ROOT,started_at)
            current=_owned_listener()
            if not current['open'] or not all(_argv(row['command_line'])==_argv(original) for row in current['listeners']):
                raise RuntimeError('Baseline identity changed before metadata restoration')
            if not service._qwen_health_ready():
                raise RuntimeError('Baseline is not healthy after restoration')
            for path,data in saved.items():
                if data is None:path.unlink(missing_ok=True)
                else:path.write_bytes(data)
            report['baseline_restored']=True
    except PreparationCancelled:
        report['baseline_restoration_skipped']='Explicit Stop or a newer lifecycle cancelled test cleanup'
    except Exception as exc:
        report['baseline_restoration_error']=str(exc)
    finally:
        service.release_gpu_lease(lease)


def main():
    started_at=float(os.environ.get('PORTALAI_SMOKE_STARTED_AT') or time.time())
    _guard(ROOT,started_at)
    initial=service._listener_identity()
    rows=initial.get('listeners',[])
    if not rows or any(not r.get('portable_qwen') for r in rows):
        raise RuntimeError('Start an owned idle model before this test')
    original=rows[0]['command_line']
    expected=initial
    paths=[ROOT/'Agent/.runtime'/name for name in ('qwen_launch_command.txt','qwen_launch_executable.txt','hardware_launch_plan.json')]
    saved={path:path.read_bytes() if path.exists() else None for path in paths}
    report={'passed':False,'checks':[],'scope':'Actual NVIDIA host model switches and bounded inference; no physical AMD proof'}
    try:
        for profile in ('fast','fast','deep','fast'):
            _guard(ROOT,started_at)
            started=time.monotonic()
            plan=prepare_chat(ROOT,profile,requested_at=started_at)
            _guard(ROOT,started_at)
            expected=_owned_listener()
            payload={'messages':[{'role':'user','content':'Reply OK.'}],'max_tokens':2,
                     'chat_template_kwargs':{'enable_thinking':False},'temperature':0,'stream':False}
            request=urllib.request.Request('http://127.0.0.1:8080/v1/chat/completions',
                data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            _guard(ROOT,started_at)
            with urllib.request.urlopen(request,timeout=90) as response:
                answer=json.loads(response.read(100000))
            if not answer.get('choices'):raise RuntimeError('No inference result after model switch')
            report['checks'].append({'profile':profile,'model':plan['model']['id'],'changed':plan['changed'],
                'completion_options':plan['completion_options'],'seconds':round(time.monotonic()-started,2),
                'response':answer['choices'][0]['message']})
            atomic_json(ROOT/'Maintenance/Reports/chat-effort-live.json',report)
            print(json.dumps(report['checks'][-1]),flush=True)
        assert report['checks'][1]['changed'] is False
        assert report['checks'][2]['model'].startswith('qwen27-')
        assert report['checks'][2]['completion_options']['chat_template_kwargs']['enable_thinking'] is True
        report['passed']=True
    finally:
        restore_baseline(original,expected,saved,started_at,report)
        if not report.get('baseline_restored'):report['passed']=False
        atomic_json(ROOT/'Maintenance/Reports/chat-effort-live.json',report)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
