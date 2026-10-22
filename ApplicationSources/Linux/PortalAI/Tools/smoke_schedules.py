"""Real model: two scheduled runs, scoped memory and a controller restart."""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_runner import Missions, ACTIVE
from mission_schedule import Schedules
from mission_supervisor import running, read_policy
from mission_memory import Memory
from runtime_policy import portable_env, atomic_json
from service_manager import _wait_qwen_ready


def main():
    missions=Missions(ROOT);schedules=Schedules(ROOT)
    if running(ROOT) or schedules.any_enabled() or any(read_policy(missions,m['id']).get('enabled') and m['status'] in ACTIVE for m in missions.list()):
        raise RuntimeError('Other armed work is present; do not interrupt it for this test')
    _wait_qwen_ready(300)
    marker=uuid.uuid4().hex[:10]
    objective=(f'Bounded schedule regression test {marker}. Use recall(query="schedule_probe") first. '
               f'If no saved schedule_probe entry exists, remember(key="schedule_probe",text="FIRST_PASS_{marker}") then complete. '
               f'If its text is FIRST_PASS_{marker}, remember(key="schedule_probe",text="SECOND_PASS_{marker}") then complete. '
               'Do not run shell commands, diagnostics, waits or subtasks. Save the exact text, without extra words. Each occurrence ends with complete.')
    s=schedules.create(objective,max_steps=5,interval_seconds=60,max_runs=2)
    schedules.enable(s['id'])
    report={'schedule':s['id'],'real_model':True,'checks':[],'started_at':time.time()}
    path=ROOT/'Maintenance/Reports/schedule-live.json'
    p=None;stream=None;restarted=False
    def launch():
        return subprocess.Popen([sys.executable,'-B',str(ROOT/'Agent/mission_supervisor.py'),'--root',str(ROOT),'run'],
                                cwd=ROOT,env=portable_env(ROOT),stdout=stream,stderr=stream,
                                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        with (ROOT/'Maintenance/Reports/schedule-live.log').open('wb') as stream:
            p=launch();deadline=time.monotonic()+360
            while time.monotonic()<deadline:
                current=schedules.load(s['id'])
                if current['status']=='needs_review':raise RuntimeError(json.dumps(current))
                if current['runs_completed']==1 and not restarted:
                    # Our own controller is between runs, so there is no pending effect.
                    p.kill();p.wait(timeout=10)
                    p=launch();restarted=True
                    report['checks'].append({'name':'Controller restarted between occurrences','passed':True})
                    atomic_json(path,report)
                if current['status']=='complete':break
                if p.poll() is not None:raise RuntimeError('Supervisor exited before the schedule completed')
                time.sleep(1)
            else:raise TimeoutError('Two-run schedule did not finish within its test deadline')
            p.wait(timeout=15)
        runs=[m for m in missions.list() if m.get('schedule_id')==s['id']]
        runs.sort(key=lambda m:m['created_at'])
        memory=Memory(missions,runs[-1]).recall('schedule_probe')
        remembered=[a['action'].get('text') for m in runs for a in m['history'] if a['action'].get('action')=='remember']
        report.update(runs=[{'id':m['id'],'status':m['status'],'steps':m['steps']} for m in runs],memory=memory,
                      remembered=remembered,finished_at=time.time())
        report['checks'].append({'name':'Exactly two complete runs without duplicated remembered effects',
                                 'passed':len(runs)==2 and all(m['status']=='complete' for m in runs) and remembered==['FIRST_PASS_'+marker,'SECOND_PASS_'+marker]})
        report['checks'].append({'name':'Second run recalled and updated first-run durable memory',
                                 'passed':bool(memory) and memory[0]['text']=='SECOND_PASS_'+marker and memory[0]['provenance']['mission']==runs[-1]['id']})
        report['passed']=restarted and all(c['passed'] for c in report['checks'])
        atomic_json(path,report);print(json.dumps(report),flush=True)
        return 0 if report['passed'] else 1
    except Exception as exc:
        report.update(passed=False,error=str(exc));atomic_json(path,report);raise
    finally:
        # Only this test schedule is disarmed; unrelated work is never stopped.
        if schedules.load(s['id'])['status']!='complete':schedules.disable(s['id'])
        if p is not None and p.poll() is None:
            p.terminate();p.wait(timeout=15)


if __name__=='__main__':raise SystemExit(main())
