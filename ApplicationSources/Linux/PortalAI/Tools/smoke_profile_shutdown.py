"""Real Windows process-handle shutdown, using disposable synthetic accounts.

Never calls shutdown for the installed PortalAI root or changes its account state.
The temporary worker has a kill-on-close job for fixture cleanup on failure.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))


def run():
    if os.name!='nt':
        raise RuntimeError('Use the offline profiles guest case for Linux validation')
    import local_accounts,service_manager
    from mission_supervisor import WorkerJob
    from profile_shutdown import stop_owned,verify_stopped,_snapshot,_select
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    base=ROOT/'Cache/ProfileShutdownTests';base.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='fixture-',dir=base) as folder:
        root=Path(folder).resolve();worker=foreign=job=store=None
        try:
            with patch.object(local_accounts,'_KDF_N',1024):
                store=local_accounts.LocalAccounts(root)
                session=store.bootstrap('SyntheticShutdownOwner','synthetic process smoke passphrase')
                marker={'user_id':session.user_id,'epoch':'f'*32,'state':'closing','controller_pid':os.getpid()}
                active=root/'Private/active-session.json';active.write_text(json.dumps(marker))
                mission=root/'Data/Missions/fixture';mission.mkdir(parents=True)
                policy=mission/'run-policy.json';policy.write_text('{"enabled":true,"armed_at":42}')
                schedule=mission/'schedule.json';schedule.write_text('{"enabled":true,"epoch":"original"}')
                before=(policy.read_bytes(),schedule.read_bytes())
                script=root/'Agent/probe.ps1';script.parent.mkdir()
                gate=root/'gate';ready=root/'ready.json'
                script.write_text('''param([string]$Gate,[string]$Ready)
$ErrorActionPreference='Stop'
while (-not (Test-Path -LiteralPath $Gate)) {Start-Sleep -Milliseconds 20}
$child=Start-Process -FilePath (Join-Path $PSHOME 'powershell.exe') -WindowStyle Hidden -PassThru -ArgumentList @('-NoProfile','-NonInteractive','-Command','Start-Sleep -Seconds 60')
@{child=$child.Id}|ConvertTo-Json -Compress|Set-Content -LiteralPath $Ready -Encoding UTF8
Start-Sleep -Seconds 60
''',encoding='utf-8')
                env=dict(os.environ);env.pop('PORTALAI_ACCOUNT_UNLOCK',None)
                worker=subprocess.Popen([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                    '-File',str(script),'-Gate',str(gate),'-Ready',str(ready)],env=env,
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                job=WorkerJob(worker);gate.touch()
                deadline=time.monotonic()+15
                while not ready.exists():
                    if worker.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError('Synthetic owned worker did not reach its ready gate')
                    time.sleep(.05)
                child=int(json.loads(ready.read_text(encoding='utf-8-sig'))['child'])
                foreign=subprocess.Popen([str(powershell),'-NoProfile','-NonInteractive','-Command','Start-Sleep -Seconds 60'],
                    env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                initial=_select(root,_snapshot())
                assert worker.pid in initial and child in initial and foreign.pid not in initial
                with patch.object(service_manager,'root_dir',return_value=root):
                    receipt=stop_owned(root,session,marker)
                assert receipt['stopped'] and receipt['model_fenced'],receipt
                assert worker.pid in receipt['stopped_pids'] and child in receipt['stopped_pids'],receipt
                assert worker.wait(timeout=5)!=0 and child not in _snapshot()
                assert foreign.poll() is None,'Unrelated same-name process was stopped'
                assert (policy.read_bytes(),schedule.read_bytes())==before
                assert json.loads(active.read_text())==marker
                assert verify_stopped(root)['stopped']
                return {'passed':True,'checks':['exact owned PowerShell -File attribution','proved external child ancestry',
                    'native handle creation/image identity and termination','unrelated same-name process preserved',
                    'armed mission/schedule bytes unchanged','closing marker unchanged','two final empty snapshots'],
                    'scope':'temporary synthetic Windows account/process fixture only; no installed-root shutdown or model inference'}
        finally:
            if job:job.close()
            for process in (worker,foreign):
                if process and process.poll() is None:process.kill()
                if process:process.wait(timeout=8)
            if store:store.logout()


def main():
    try:result=run()
    except Exception as exc:result={'passed':False,'error':type(exc).__name__+': '+str(exc)}
    path=ROOT/'Maintenance/Reports'/('profile-windows-shutdown-'+uuid.uuid4().hex+'.json')
    with path.open('x',encoding='utf-8') as output:json.dump(result,output,indent=2)
    print(json.dumps({**result,'report':str(path)}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
