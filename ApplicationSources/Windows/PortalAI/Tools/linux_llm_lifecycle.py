"""Bounded 1.7B CPU lifecycle regression, exclusively inside the offline Linux guest."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))


def handoff_worker(folder):
    """Replicate a native-chat tool that is cancelled through its owning cgroup."""
    from runtime_policy import atomic_json
    from service_manager import qwen_gpu_handoff_begin
    deadline=time.monotonic()+10
    while not (folder/'start.gate').exists():
        if time.monotonic()>deadline:raise TimeoutError('LLM test worker was not assigned to its cgroup')
        time.sleep(.02)
    state=qwen_gpu_handoff_begin('linux-guest-nested-cancel')
    atomic_json(folder/'handoff.json',state)
    time.sleep(60)


def main():
    if not sys.platform.startswith('linux') or ROOT!=Path('/portable'):
        raise RuntimeError('This fixture only runs in the offline /portable Linux validation guest')
    if len(sys.argv)==3 and sys.argv[1]=='--handoff-worker':
        return handoff_worker(Path(sys.argv[2]))
    import service_manager as service
    from linux_process import launch,identity,is_llama,owned,stop
    from platform_runtime import python_path,linux_elf_command
    from runtime_policy import atomic_json,portable_env
    from linux_job import delegated_root,MOUNT
    base=delegated_root()
    if service.port_open(8080):raise RuntimeError('Guest LLM test port is already occupied')
    model=ROOT/'LLM/models/Qwen3-1.7B-Q8_0.gguf'
    executable=ROOT/'LLM/backends/linux-cpu/llama-server'
    if not model.is_file() or not executable.is_file():raise RuntimeError('Guest small CPU model/backend is missing')
    command=[str(executable),'-m',str(model),'-ngl','0','--device','none',
             '-c','2048','--parallel','1','--threads','2','--threads-batch','2',
             '--batch-size','64','--ubatch-size','64','--jinja','--host','127.0.0.1','--port','8080']
    expected,_=linux_elf_command(ROOT,command)
    controller_group=Path('/proc/self/cgroup').read_text()
    states=[];watchdogs=[];started=time.monotonic();deadline=started+185
    report={'passed':False,'model':model.name,'backend':'cpu','threads':2,'context_tokens':2048}

    def remaining(maximum,twice=False):
        budget=deadline-time.monotonic()-12
        if budget<=1:raise TimeoutError('Linux LLM fixture exhausted its bounded time')
        return min(maximum,budget/2 if twice else budget)

    def wait_ready(maximum=45):
        until=time.monotonic()+remaining(maximum)
        while time.monotonic()<until:
            if service._qwen_health_ready(timeout=1):
                observed=service._listener_identity()
                if not observed['portable_qwen'] or len(observed['listeners'])!=1:
                    raise AssertionError('Readiness did not come from exactly one owned model: '+str(observed))
                row=identity(observed['listeners'][0]['pid'])
                assert is_llama(row,ROOT),row
                assert row['argv']==expected,(row['argv'],expected)
                membership=Path(f"/proc/{row['pid']}/cgroup").read_text()
                relative=next(x[3:] for x in membership.splitlines() if x.startswith('0::'))
                group=(MOUNT/relative.lstrip('/')).resolve()
                assert membership==controller_group or group==base/'portalai-guardians',membership
                return row
            time.sleep(.2)
        raise TimeoutError('Linux small model did not become healthy in time')

    def record_state(state):
        states.append(state)
        assert state.get('active'),state
        assert shlex.split(state['command_line'])==expected,state['command_line']
        pid=state.get('watchdog_pid')
        if pid:
            try:watchdogs.append(identity(pid))
            except (OSError,ValueError):pass  # A successful watchdog may already have exited.

    def owned_models():
        result=[]
        for item in Path('/proc').iterdir():
            if not item.name.isdecimal():continue
            try:
                row=identity(int(item.name))
                if row['argv']==expected and is_llama(row,ROOT):result.append(row)
            except (OSError,ValueError):continue
        return result

    def nested_handoff(explicit_stop=False):
        from mission_supervisor import WorkerJob
        cache=ROOT/'Cache/LLMLifecycle';cache.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cache) as temporary:
            folder=Path(temporary);process=job=None
            try:
                with (folder/'worker.log').open('wb') as log:
                    process=subprocess.Popen([str(python_path(ROOT)),'-B','-I',str(Path(__file__).resolve()),
                        '--handoff-worker',str(folder)],cwd=ROOT,env=portable_env(ROOT),
                        stdin=subprocess.DEVNULL,stdout=log,stderr=log)
                    job=WorkerJob(process);job.limit_memory(512*1024**2)
                    (folder/'start.gate').touch();path=folder/'handoff.json'
                    until=time.monotonic()+remaining(20)
                    while not path.exists() and time.monotonic()<until:
                        if process.poll() is not None:raise RuntimeError((folder/'worker.log').read_text())
                        time.sleep(.05)
                    assert path.exists(),'Nested handoff did not finish'
                    state=json.loads(path.read_text());record_state(state)
                    guardian=Path(f"/proc/{state['watchdog_pid']}/cgroup").read_text()
                    assert guardian.strip().endswith('/portalai-guardians'),guardian
                    assert not service.port_open(8080),'Nested worker did not release the model'
                    if explicit_stop:
                        with service._qwen_lifecycle_mutex():
                            service._write_qwen_generation({'token':'explicit-guest-stop-'+uuid.uuid4().hex,
                                'reason':'explicit-stop','stopped_at':time.time()})
                    job.close();process.wait(timeout=8)
                marker=Path(state['marker_path']);until=time.monotonic()+remaining(45)
                while not marker.exists() and time.monotonic()<until:time.sleep(.1)
                assert marker.exists(),'Recovery watchdog did not survive outer cgroup cancellation'
                if explicit_stop:
                    assert marker.read_text()=='stale-generation',marker.read_text()
                    time.sleep(2)
                    assert not service.port_open(8080) and not owned_models(),'Explicit Stop resurrected Qwen'
                else:
                    assert marker.read_text()=='watchdog-restored',marker.read_text()
                    wait_ready(5)
            finally:
                if job:job.close()
                if process:
                    if process.poll() is None:process.kill()
                    process.wait(timeout=8)

    try:
        initial_pid=launch(command,ROOT,name='qwen')
        first=wait_ready()
        assert first['pid']==initial_pid
        assert Path(f"/proc/{first['pid']}/cgroup").read_text()==controller_group
        assert os.getsid(first['pid'])==first['pid'],'Detached launch did not create its own session'
        report['owned_detached_launch']=True
        payload={'messages':[{'role':'user','content':'Reply with one word: ready.'}],
                 'max_tokens':4,'temperature':0,'stream':False,
                 'chat_template_kwargs':{'enable_thinking':False}}
        request=urllib.request.Request('http://127.0.0.1:8080/v1/chat/completions',
            data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(request,timeout=remaining(30)) as response:
            assert response.status==200
            reply=json.load(response)
        content=reply['choices'][0]['message'].get('content','')
        assert isinstance(content,str) and content.strip(),reply
        report['short_inference']={'text':content[:80],'completion_tokens':reply.get('usage',{}).get('completion_tokens')}

        state=service.qwen_gpu_handoff_begin('linux-guest-small-cpu')
        record_state(state)
        assert first['pid'] in state['killed_pids'],state
        assert not service._listener_identity()['open'],'Model was not unloaded for the tool interval'
        result=service.qwen_gpu_handoff_end(state,timeout=remaining(35,twice=True))
        assert result.get('restored') and result.get('ready'),result
        restored=wait_ready(5)
        assert restored['pid']!=first['pid']
        assert Path(state['marker_path']).read_text()=='restored'
        report['normal_handoff']={'healthy':True,'exact_command':True,'pid_changed':True}

        code=("import os,json,sys;sys.path.insert(0,'/portable/Agent');"
              "from service_manager import qwen_gpu_handoff_begin;"
              "print(json.dumps(qwen_gpu_handoff_begin('linux-guest-owner-crash')),flush=True);os._exit(23)")
        crashed=subprocess.run([str(python_path(ROOT)),'-B','-I','-c',code],cwd=ROOT,
            env=portable_env(ROOT),capture_output=True,text=True,timeout=remaining(20))
        assert crashed.returncode==23,(crashed.returncode,crashed.stderr)
        state=json.loads(crashed.stdout.strip().splitlines()[-1]);record_state(state)
        assert restored['pid'] in state['killed_pids'],state
        marker=Path(state['marker_path']);until=time.monotonic()+remaining(60)
        while not marker.exists() and time.monotonic()<until:time.sleep(.25)
        assert marker.exists(),'Watchdog did not complete after the handoff owner exited'
        assert marker.read_text()=='watchdog-restored',marker.read_text()
        recovered=wait_ready(5)
        assert recovered['pid']!=restored['pid']
        assert service._read_qwen_generation() is None
        report['watchdog_recovery']={'healthy_at_marker':True,'exact_command':True,'owner_exit':23}
        nested_handoff()
        report['outer_cgroup_cancellation']={'watchdog_survived':True,'restored_healthy':True,'exact_command':True}
        nested_handoff(explicit_stop=True)
        report['explicit_stop']={'stale_generation':True,'model_remained_stopped':True}
        report['passed']=True
    except BaseException as exc:
        report['error']=f'{type(exc).__name__}: {exc}'
        for name in ('linux-qwen.log','linux-worker.log','qwen_handoff.log'):
            file=ROOT/'Agent/.runtime'/name
            if file.exists():
                with file.open('rb') as log:
                    log.seek(max(0,file.stat().st_size-1500))
                    print(name+': '+log.read().decode(errors='replace'),file=sys.stderr)
        raise
    finally:
        # Invalidate restoration before stopping our watchdogs and exact-command
        # models. No mission Stop, host process-name killing, or port-only kill.
        service._write_qwen_generation({'token':'guest-stopped-'+uuid.uuid4().hex,
            'reason':'explicit-stop','stopped_at':time.time()})
        for state in states:
            marker=Path(state['marker_path'])
            if not marker.exists():marker.write_text('guest-fixture-stopped')
        cleanup_errors=[]
        for row in watchdogs:
            try:
                if owned(row,ROOT):stop(row,ROOT)
            except (FileNotFoundError,ProcessLookupError):pass
            except Exception as exc:cleanup_errors.append('watchdog: '+str(exc))
        for row in owned_models():
            try:stop(row,ROOT)
            except (FileNotFoundError,ProcessLookupError):pass
            except Exception as exc:cleanup_errors.append('model: '+str(exc))
        report['cleanup']={'owned_models_remaining':len(owned_models()),'errors':cleanup_errors}
        report['elapsed_seconds']=round(time.monotonic()-started,2)
        if cleanup_errors or report['cleanup']['owned_models_remaining']:report['passed']=False
        atomic_json(ROOT/'Maintenance/Reports/linux-small-llm-lifecycle.json',report)
        print('PORTAL_LINUX_LLM='+json.dumps(report),flush=True)
    assert report['passed'],report


if __name__=='__main__':main()
