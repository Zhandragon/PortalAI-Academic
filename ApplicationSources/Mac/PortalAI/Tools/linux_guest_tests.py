"""Executed only inside the offline Linux validation guest."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from linux_job import LinuxJob,preflight,destroy,prepare_delegation
from platform_runtime import python_path
PY=str(python_path(ROOT))


def wait_for(predicate,seconds=8):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        if predicate():return
        time.sleep(.025)
    raise TimeoutError('Linux ownership test timed out')


def alive(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[0]!='Z'
    except FileNotFoundError:return False


def child(folder):
    gate=folder/'gate'
    wait_for(gate.exists)
    detached=subprocess.Popen([PY,'-c','import time;time.sleep(60)'],start_new_session=True)
    (folder/'child-pids.json').write_text(json.dumps([os.getpid(),detached.pid]))
    time.sleep(60)


def controller(folder):
    process=subprocess.Popen([PY,str(__file__),'child',str(folder)])
    job=LinuxJob(process)
    (folder/'group').write_text(str(job.group))
    (folder/'gate').touch()
    try:process.wait()
    finally:job.close()


def nested_controller(folder):
    """A chat/mission worker which starts a separately owned media worker."""
    wait_for((folder/'outer.gate').exists)
    inner=folder/'inner';inner.mkdir()
    process=subprocess.Popen([PY,str(__file__),'child',str(inner)])
    job=LinuxJob(process)
    try:
        # This exercises the same cgroup memory.max write used by media and VM.
        (job.group/'memory.max').write_text(str(512*1024**2))
        (folder/'nested.json').write_text(json.dumps({'group':str(job.group),'guardian':job.guardian.pid,
            'guardian_cgroup':Path(f'/proc/{job.guardian.pid}/cgroup').read_text()}))
        (inner/'gate').touch()
        process.wait()
    finally:job.close()


def nested_owner(folder):
    """Outer controller killed abruptly by the test, without normal close()."""
    process=subprocess.Popen([PY,str(__file__),'nested-controller',str(folder)])
    job=LinuxJob(process)
    (folder/'outer-group').write_text(str(job.group))
    (folder/'outer-pid').write_text(str(process.pid))
    (folder/'outer.gate').touch()
    try:process.wait()
    finally:job.close()


def nested_check(folder,crash=False):
    owner=outer=job=None
    try:
        if crash:
            owner=subprocess.Popen([PY,str(__file__),'nested-owner',str(folder)])
        else:
            outer=subprocess.Popen([PY,str(__file__),'nested-controller',str(folder)])
            job=LinuxJob(outer)
            (folder/'outer-group').write_text(str(job.group))
            (folder/'outer-pid').write_text(str(outer.pid))
            (folder/'outer.gate').touch()
        wait_for((folder/'inner/child-pids.json').exists)
        nested=json.loads((folder/'nested.json').read_text())
        assert nested['guardian_cgroup'].strip().endswith('/portalai-guardians'),nested
        pids=json.loads((folder/'inner/child-pids.json').read_text())
        pids+=[int((folder/'outer-pid').read_text()),nested['guardian']]
        if crash:owner.kill();owner.wait(timeout=8)
        else:job.close();outer.wait(timeout=8)
        wait_for(lambda:not any(alive(pid) for pid in pids))
        wait_for(lambda:not Path(nested['group']).exists())
    finally:
        if job:job.close()
        for process in (owner,outer):
            if process and process.poll() is None:process.kill();process.wait(timeout=8)
        # Recovery for a failed assertion is confined to this fixture's groups.
        for marker,key in ((folder/'nested.json','group'),(folder/'outer-group',None)):
            if marker.exists():
                group=Path(json.loads(marker.read_text())[key] if key else marker.read_text())
                if group.exists():destroy(group)


def fresh_scope(folder):
    """Exercise the real headless launcher in a previously unprepared scope."""
    wait_for((folder/'fresh.gate').exists)
    import runpy
    sys.argv=['portalai_missions_linux.py','supervisor','run','--seconds','0']
    runpy.run_path(str(ROOT/'Launchers/portalai_missions_linux.py'),run_name='__main__')
    base=Path(os.environ['PORTALAI_CGROUP_ROOT'])
    assert 'memory' in (base/'cgroup.subtree_control').read_text().split()
    probe=base/'portalai-memory-probe';probe.mkdir()
    try:
        (probe/'memory.max').write_text(str(512*1024**2))
        assert int((probe/'memory.max').read_text())==512*1024**2
    finally:probe.rmdir()
    (folder/'fresh.passed').touch()


def headless_preparation_check(base,folder):
    fresh=base/('portalai-headless-test-'+uuid.uuid4().hex);fresh.mkdir()
    process=None
    try:
        assert 'memory' not in (fresh/'cgroup.subtree_control').read_text().split()
        process=subprocess.Popen([PY,str(__file__),'fresh-scope',str(folder)],
                                 env={**os.environ,'PORTALAI_CGROUP_ROOT':str(fresh)})
        (fresh/'cgroup.procs').write_text(str(process.pid))
        (folder/'fresh.gate').touch()
        process.wait(timeout=15)
        assert process.returncode==0 and (folder/'fresh.passed').exists()
    finally:
        if process and process.poll() is None:process.kill();process.wait(timeout=8)
        # Only this fixture's freshly created hierarchy is removed.
        for name in ('portalai-memory-probe','portalai-controller'):
            child_group=fresh/name
            if child_group.exists():child_group.rmdir()
        fresh.rmdir()


def main():
    if len(sys.argv)==7 and sys.argv[1]=='worker' and sys.argv[3]=='run':
        import mission_endurance
        return mission_endurance.worker(Path(sys.argv[2]),sys.argv[4],int(sys.argv[6]))
    if len(sys.argv)==3:
        return {'child':child,'controller':controller,'nested-controller':nested_controller,
                'nested-owner':nested_owner,'fresh-scope':fresh_scope}[sys.argv[1]](Path(sys.argv[2]))
    checks=[]
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        print(json.dumps(checks[-1]),flush=True)
        if not value:raise AssertionError(name)
    print(json.dumps({'python':sys.version,'platform':sys.platform,'uid':os.getuid(),'preflight':preflight()}),flush=True)
    import sqlite3,ssl,tkinter
    db=sqlite3.connect(':memory:');db.execute('create virtual table notes using fts5(text)');db.close()
    check('Bundled Linux Python, SQLite FTS5, SSL and Tcl imports',tkinter.Tcl().eval('expr 2+3')=='5')
    cp=subprocess.run([PY,'-B','-I',str(ROOT/'Launchers/portalai_missions_linux.py'),'preflight'],
                      capture_output=True,text=True,timeout=10,check=True)
    check('Linux mission launcher accepts a delegated scope',json.loads(cp.stdout)['ready'])
    base=prepare_delegation()
    check('Delegated memory controller prepared for media and VM limits',
          'memory' in (base/'cgroup.subtree_control').read_text().split())
    with tempfile.TemporaryDirectory(dir=ROOT/'Data') as tmp:
        headless_preparation_check(base,Path(tmp))
    check('Headless launcher enables working memory limits in a fresh delegated scope',True)
    with tempfile.TemporaryDirectory(dir=ROOT/'Data') as tmp:
        folder=Path(tmp)
        process=subprocess.Popen([PY,str(__file__),'child',str(folder)])
        job=LinuxJob(process)
        try:
            (folder/'gate').touch();wait_for((folder/'child-pids.json').exists)
            pids=json.loads((folder/'child-pids.json').read_text())
            job.close();process.wait(timeout=8)
            wait_for(lambda:not any(alive(p) for p in pids))
            check('Cancellation kills owned worker and detached descendant',True)
        finally:
            job.close()
            if process.poll() is None:process.kill();process.wait()
    with tempfile.TemporaryDirectory(dir=ROOT/'Data') as tmp:
        folder=Path(tmp);parent=subprocess.Popen([PY,str(__file__),'controller',str(folder)])
        try:
            wait_for((folder/'child-pids.json').exists)
            pids=json.loads((folder/'child-pids.json').read_text())
            parent.kill();parent.wait(timeout=8)
            wait_for(lambda:not any(alive(p) for p in pids))
            check('Controller death kills detached descendants through EOF guardian',True)
        finally:
            if parent.poll() is None:parent.kill();parent.wait()
            if (folder/'group').exists():
                group=Path((folder/'group').read_text())
                if group.exists():destroy(group)
    with tempfile.TemporaryDirectory(dir=ROOT/'Data') as tmp:
        folder=Path(tmp);process=subprocess.Popen([PY,str(__file__),'child',str(folder)])
        job=LinuxJob(process)
        try:
            (folder/'gate').touch();wait_for((folder/'child-pids.json').exists)
            pids=json.loads((folder/'child-pids.json').read_text())
            job.close(completed=True)
            check('Explicit completed release preserves confirmed background effects',all(alive(p) for p in pids))
        finally:
            if job.group.exists():destroy(job.group)
            process.wait(timeout=8)
    for crash in (False,True):
        with tempfile.TemporaryDirectory(dir=ROOT/'Data') as tmp:
            nested_check(Path(tmp),crash)
        check('Outer controller death kills nested media and detached descendants' if crash else
              'Outer cancellation kills nested media and detached descendants',True)
    # Exercise actual Linux supervisor, schedules, memory and simulated accounts.
    import mission_endurance
    from runtime_policy import atomic_json
    from mission_schedule import Schedules
    from mission_supervisor import Supervisor
    with tempfile.TemporaryDirectory(dir=ROOT/'Maintenance') as tmp:
        root=Path(tmp)
        # Deliberately small RAM-filesystem test policy, only inside this guest.
        # The real portable SSD policy is never edited or relaxed.
        atomic_json(root/'Agent/hardware_profiles.json',{'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}})
        atomic_json(root/'case.json',{'version':2,'accounts':'mock only'})
        atomic_json(root/'Data/Accounts/profiles.json',{'simulation':{'backend':'mock','enabled':True,'permissions':['wallet_send']}})
        atomic_json(root/'Data/Accounts/Simulated/simulation.json',{'inbox':[],'outbox':[],'balance_wei':'100000','transactions':[]})
        schedules=Schedules(root);schedule=schedules.create('Linux mock-account ownership test','full',6,0)
        schedules.enable(schedule['id'])
        Supervisor(root,worker_command=[PY,str(__file__),'worker',str(root)],model_ready=lambda:True).run(seconds=14)
        result=mission_endurance.audit(root)
        check('Linux scheduled mission completes with memory and journaled mock transfer',result['completed']==1)
    # Real Linux crypto extension loading, encrypted vault round trip/tamper
    # rejection and EVM signing. RPC is mocked and this VM has no network device.
    import unittest
    tempfile.tempdir=str(ROOT/'Data')
    sys.path.insert(0,str(ROOT/'Validation/Tests'))
    suite=unittest.defaultTestLoader.loadTestsFromName('test_mission_accounts')
    account_result=unittest.TextTestRunner(verbosity=1).run(suite)
    check('Linux account encryption/signing and effect-journal regressions',account_result.wasSuccessful())
    print('PORTAL_LINUX_RESULT='+json.dumps({'passed':all(c['passed'] for c in checks),'checks':checks,
          'scope':'Offline WHPX Linux guest, not a physical Linux desktop/GPU test'}),flush=True)


if __name__=='__main__':main()
