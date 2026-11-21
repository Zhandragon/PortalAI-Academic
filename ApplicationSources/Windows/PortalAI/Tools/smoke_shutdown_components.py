"""Live Stop helper acceptance against disposable, proved-owned worker trees."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

SOURCE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(SOURCE/p) for p in ('Agent','ControlCenter','Tools')]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',type=Path,required=True)
    args=parser.parse_args()
    from validation_artifacts import ValidationArtifacts
    artifacts=ValidationArtifacts(SOURCE,args.artifacts_dir)
    root=artifacts.path('isolated-root');root.mkdir(exist_ok=True)
    for part in ('Agent','ControlCenter','Tools','Launchers'):
        for src in (SOURCE/part).rglob('*.py'):
            target=root/src.relative_to(SOURCE);target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    shutil.copyfile(SOURCE/'Agent/hardware_profiles.json',root/'Agent/hardware_profiles.json')
    worker=root/'Tools/new_unlisted_worker.py'
    worker.write_text('import json,subprocess,sys,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,"-c","import time;time.sleep(180)"],creationflags=subprocess.CREATE_NO_WINDOW)\nPath(sys.argv[1]).write_text(json.dumps({"child":p.pid}))\ntime.sleep(180)\n')
    flags=subprocess.CREATE_NO_WINDOW
    foreign=subprocess.Popen([sys.executable,'-c','import time;time.sleep(180)'],creationflags=flags)
    parent=subprocess.Popen([sys.executable,str(worker),str(root/'worker.json')],creationflags=flags)
    child=None
    try:
        until=time.monotonic()+8
        while not (root/'worker.json').exists():
            if time.monotonic()>until:raise TimeoutError('Worker did not become ready')
            time.sleep(.05)
        import importlib.util
        spec=importlib.util.spec_from_file_location('stop_fixture',SOURCE/'Launchers/Stop_PortableAI.py')
        stop=importlib.util.module_from_spec(spec);spec.loader.exec_module(stop)
        child_id=json.loads((root/'worker.json').read_text())['child']
        child=next(p for p in stop.cim_processes() if p['ProcessId']==child_id)
        completed=subprocess.run([sys.executable,str(root/'Launchers/Stop_PortableAI.py'),'--root',str(root),'--include-opengui'],capture_output=True,text=True,timeout=100,creationflags=flags)
        artifacts.path('stop.stdout').write_text(completed.stdout);artifacts.path('stop.stderr').write_text(completed.stderr)
        assert completed.returncode==0,completed.stdout+completed.stderr
        parent.wait(10)
        assert not any(p['ProcessId']==child_id and p['StartTicks']==child['StartTicks'] for p in stop.cim_processes())
        assert foreign.poll() is None,'Unrelated host process was stopped'
        report={'passed':True,'unlisted_owned_script_stopped':True,'external_descendant_stopped':True,'foreign_process_preserved':True,'synthetic':True}
        artifacts.path('result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
    finally:
        if parent.poll() is None:parent.kill();parent.wait(10)
        if child:
            stop.kill(child['ProcessId'],root,child)
        if foreign.poll() is None:foreign.kill();foreign.wait(10)


if __name__=='__main__':main()
