"""Sequential post-crash regressions using a temporary small model when chat is stopped.

Never changes hardware/model settings. Existing chat is adopted as-is; a model
started only for this test is stopped afterward and saved launch metadata restored.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
import service_manager as service
from runtime_policy import atomic_json,build_plan,load_policy,portable_env
from chat_model_switch import _argv,_guard,_owned_listener,_spawn,PreparationCancelled


def exact_listener(identity,command,pid=None):
    rows=identity.get('listeners',[])
    return bool(len(rows)==1 and rows[0].get('portable_qwen') and
        (pid is None or rows[0]['pid']==pid) and _argv(rows[0].get('command_line',''))==command)


def start_temporary(plan,guard):
    """Own an exact process and observe Stop throughout its startup wait."""
    process=lease=None
    try:
        while lease is None:
            guard()
            try:lease=service.acquire_gpu_lease('crash-smoke-start',timeout=.3)
            except TimeoutError:continue
        with service._qwen_lifecycle_mutex():
            guard()
            if _owned_listener()['open']:raise RuntimeError('Chat started before temporary test startup')
            process=_spawn(ROOT,plan['command'])
        deadline=time.monotonic()+300
        while time.monotonic()<deadline:
            guard()
            if process.poll() is not None:raise RuntimeError('Temporary test model exited before readiness')
            with service._qwen_lifecycle_mutex():
                guard()
                identity=_owned_listener()
                if identity['open'] and service._qwen_health_ready():
                    if not exact_listener(identity,plan['command'],process.pid):
                        raise RuntimeError('A different model answered temporary startup')
                    line=subprocess.list2cmdline(plan['command']) if os.name=='nt' else shlex.join(plan['command'])
                    service._remember_qwen_launch(line,plan['command'][0])
                    atomic_json(ROOT/'Agent/.runtime/hardware_launch_plan.json',plan)
                    return identity
            time.sleep(.25)
        raise TimeoutError('Temporary test model readiness timed out')
    except BaseException:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        raise
    finally:
        if lease is not None:service.release_gpu_lease(lease)


def cleanup_temporary(command,expected,guard,saved,report):
    with service._qwen_lifecycle_mutex():
        try:guard()
        except PreparationCancelled as exc:
            report['cleanup_skipped']=str(exc);report['passed']=False;return
        current=_owned_listener()
        expected_rows=(expected or {}).get('listeners',[])
        pid=expected_rows[0].get('pid') if len(expected_rows)==1 else None
        if current['open']:
            if pid is None or not exact_listener(current,command,pid):
                report['cleanup_skipped']='A different model now owns the listener';report['passed']=False;return
            service._stop_qwen_listener();report['temporary_model_stopped']=True
        guard()
        if not service.port_open(8080):
            for path,data in saved.items():
                if data is None:path.unlink(missing_ok=True)
                else:path.write_bytes(data)
            report['launch_metadata_restored']=True
        else:
            report['cleanup_skipped']='Listener remained active after temporary model stop';report['passed']=False


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remaining',action='store_true',help='Run native chat handoff and VM checks only')
    parser.add_argument('--report',default='crash-lifecycle.json')
    args=parser.parse_args(argv)
    if Path(args.report).name!=args.report:raise ValueError('Report must be a filename')
    report_path=ROOT/'Maintenance/Reports'/args.report
    started_at=time.time()
    guard=lambda:_guard(ROOT,started_at)
    guard()
    initial=_owned_listener()
    if initial['open'] and not initial['portable_qwen']:raise RuntimeError('Chat port belongs to another application')
    paths=[ROOT/'Agent/.runtime'/name for name in ('qwen_launch_command.txt','qwen_launch_executable.txt','hardware_launch_plan.json')]
    saved={path:path.read_bytes() if path.exists() else None for path in paths}
    launched=False;command=None;expected=None
    report={'passed':False,'initial_chat_running':initial['portable_qwen'],'checks':[],'started_at':started_at}
    try:
        if not initial['portable_qwen']:
            policy={**load_policy(ROOT),'selection':'qwen4-q4','backend':'cuda','context_tokens':8192}
            plan=build_plan(ROOT,policy=policy);command=plan['command']
            guard()
            launched=True
            expected=start_temporary(plan,guard)
            report['temporary_model']=plan['model']['id']+'/'+plan['backend']['backend']
        checks=[('smoke_chat_effort.py',650,[]),('smoke_handoff_recovery.py',420,[]),
                ('smoke_voice_handoff.py',650,[]),('smoke_native_image.py',300,['--engine','sdcpp-vulkan']),
                ('smoke_native_image_cancel.py',300,[]),
                ('smoke_chat_handoff.py',500,['--case','native-image','--effort','fast','--report','effort-native-chat-handoff.json']),
                ('smoke_vm.py',450,[]),('smoke_execution_modes.py',120,[])]
        if args.remaining:checks=checks[-3:]
        for filename,timeout,arguments in checks:
            guard()
            path=ROOT/'Maintenance/Reports'/('crash-'+Path(filename).stem+'.log')
            child_env=portable_env(ROOT);child_env['PORTALAI_SMOKE_STARTED_AT']=str(started_at)
            with path.open('wb') as output:
                result=subprocess.run([sys.executable,'-B','-I',str(ROOT/'Tools'/filename),*arguments],cwd=ROOT,env=child_env,
                    stdout=output,stderr=subprocess.STDOUT,timeout=timeout,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            row={'test':filename,'passed':result.returncode==0,'log':str(path)};report['checks'].append(row)
            guard()
            if launched:
                with service._qwen_lifecycle_mutex():
                    guard()
                    current=_owned_listener()
                    if exact_listener(current,command):expected=current
            atomic_json(report_path,report)
            print(json.dumps(row),flush=True)
            if result.returncode:raise RuntimeError('Sequential regression failed: '+filename)
        report['passed']=True
    finally:
        try:
            if launched:cleanup_temporary(command,expected,guard,saved,report)
        except BaseException:
            report['passed']=False;raise
        finally:
            report['finished_at']=time.time()
        atomic_json(report_path,report)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
