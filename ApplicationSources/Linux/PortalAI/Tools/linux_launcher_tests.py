"""Actual delegated Linux launcher in a gated owned worker, without account login."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path('/portable');sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]


def child():
    assert sys.stdin.readline().strip()=='go'
    from linux_job import current_group
    before=current_group()
    assert before.name.startswith('portalai-job-'),before
    spec=importlib.util.spec_from_file_location('guest_gui_launcher',ROOT/'Launchers/portalai_gui_linux.py')
    launcher=importlib.util.module_from_spec(spec);spec.loader.exec_module(launcher)
    calls=[]
    with patch.object(launcher.runpy,'run_path',side_effect=lambda *a,**kw:calls.append((a,kw))), \
         patch.object(launcher.os,'execve',side_effect=AssertionError('Existing delegated scope must be used')):
        launcher.main()
    assert len(calls)==1 and calls[0][0]==(str(ROOT/'ControlCenter/control_center_bootstrap.py'),),calls
    assert current_group()==before,'GUI launcher escaped its owned worker group'
    print('Actual Linux GUI launcher delegation/preflight/dispatch passed; nested worker ownership preserved',flush=True)


def main():
    from mission_supervisor import WorkerJob
    from platform_runtime import python_path
    from runtime_policy import portable_env
    proc=job=None
    try:
        proc=subprocess.Popen([str(python_path(ROOT)),'-B','-I',str(Path(__file__)),'child'],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=portable_env(ROOT))
        job=WorkerJob(proc);job.limit_memory(512*1024**2)
        out,err=proc.communicate('go\n',timeout=25)
        assert proc.returncode==0,(out,err)
        print(out,flush=True)
    finally:
        if job:job.close()
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=5)
    # The real dependency probe must select the exact native compatibility layer.
    from dependency_check import check,platform_checks
    row=next(row for row in platform_checks() if row[0]=='Linux media CPU import check')
    only_kornia=(row[0],row[1],row[2],('kornia_rs',))
    result=check(ROOT,only_kornia)
    assert result['status']=='PASS',result
    assert '/kornia_compat/' in result['detail'],result
    print('Linux dependency checker selected verified Kornia compatibility layer',flush=True)


if __name__=='__main__':child() if sys.argv[-1:] == ['child'] else main()
