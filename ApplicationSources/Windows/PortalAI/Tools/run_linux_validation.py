"""Boot bounded offline Linux tests with copied source/runtime data, no host mounts.

Separate validation guest: does not modify the secure mission guest, provision
OS features, enable networking, or extract any guest workspace onto the host.
"""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json,require_space,portable_path
from vm_runner import preflight,command_line,ProcessBudget
sys.path.insert(0,str(Path(__file__).resolve().parent))
from validation_artifacts import ValidationArtifacts,add_artifact_arguments,require_output_space


INIT=r'''#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
/usr/bin/busybox --install -s /usr/bin
chmod 755 /
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mkdir -p /sys/fs/cgroup /tmp /portable/Data /portable/Maintenance/Endurance /portable/Cache
mount -t tmpfs -o size=32m,nosuid,nodev tmpfs /portable/Data || poweroff -f
mount -t tmpfs -o size=64m,nosuid,nodev tmpfs /portable/Maintenance || poweroff -f
mount -t cgroup2 none /sys/fs/cgroup || poweroff -f
mkdir /sys/fs/cgroup/portalai-validation
echo $$ > /sys/fs/cgroup/portalai-validation/cgroup.procs
chown 1000:1000 /sys/fs/cgroup/portalai-validation /sys/fs/cgroup/portalai-validation/cgroup.procs /sys/fs/cgroup/portalai-validation/cgroup.subtree_control /sys/fs/cgroup/portalai-validation/cgroup.threads
chmod 1777 /tmp
chown -R 1000:1000 /portable/Data /portable/Maintenance /portable/Cache
export HOME=/portable/Data PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
export PORTALAI_CGROUP_ROOT=/sys/fs/cgroup/portalai-validation
export LD_LIBRARY_PATH=/portable/Runtime/LinuxPython/lib:/usr/lib/x86_64-linux-gnu
timeout -s KILL 65 su portal -s /bin/sh -c 'cd /portable && /portable/Runtime/LinuxPython/bin/python3 -B /portable/Tools/linux_guest_tests.py'
echo PORTAL_LINUX_EXIT=$?
sync
poweroff -f
'''


def write_entry(out,name,data,mode,ino):
    encoded=name.encode()+b'\0'
    fields=[ino,mode,0,0,1,0,len(data),0,0,0,0,len(encoded),0]
    header=b'070701'+b''.join(f'{value:08x}'.encode() for value in fields)+encoded
    out.write(header);out.write(b'\0'*(-len(header)%4));out.write(data);out.write(b'\0'*(-len(data)%4))


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    add_artifact_arguments(parser)
    options=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,options.artifacts_dir)
    plan=preflight(ROOT)
    require_output_space(ROOT,artifacts,400*1024**2,for_outputs=True)
    folder=artifacts.path(uuid.uuid4().hex);folder.mkdir(parents=True)
    initrd=folder/'initramfs'
    inputs={}
    pyroot=ROOT/'Runtime/LinuxPython'
    for file in pyroot.rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts and not any(p in ('test','tests','ensurepip','site-packages','include','share') for p in file.relative_to(pyroot).parts):
            inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'Agent').glob('*.py'):inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    inputs['portable/Agent/hardware_profiles.json']=ROOT/'Agent/hardware_profiles.json'
    for name in ('linux_guest_tests.py','mission_endurance.py'):inputs['portable/Tools/'+name]=ROOT/'Tools'/name
    for name in ('portalai_missions_linux.py','portalai-missions.sh'):
        inputs['portable/Launchers/'+name]=ROOT/'Launchers'/name
    inputs['portable/Validation/Tests/test_mission_accounts.py']=ROOT/'Maintenance/Tests/test_mission_accounts.py'
    account_receipt=json.loads((ROOT/'Maintenance/Imports/linux-accounts-lock.json').read_text(encoding='utf-8'))
    account_root=ROOT/'Runtime/AccountPython/linux-packages'
    for row in account_receipt['files']:
        file=portable_path(account_root,row['path'])
        with file.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=row['sha256']:raise RuntimeError('Linux account file hash changed: '+row['path'])
        inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    receipt=json.loads((ROOT/'Maintenance/Imports/linux-validation-libs.json').read_text())
    for row in receipt['files']:
        if row['path'].startswith('usr/share/doc/'):continue
        file=portable_path(ROOT/receipt['destination'],row['path'])
        with file.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=row['sha256']:raise RuntimeError('Linux test payload hash changed: '+row['path'])
        inputs[row['path']]=file
    loader=next(p for name,p in inputs.items() if name.endswith('/ld-linux-x86-64.so.2') and '/x86_64-linux-gnu/' in name)
    inputs['lib64/ld-linux-x86-64.so.2']=loader
    directories={str(p) for name in inputs for p in Path(name).parents if str(p)!='.'}
    with initrd.open('wb') as output:
        output.write((Path(plan['guest'])/'boot/initramfs-virt').read_bytes())
        with gzip.GzipFile(fileobj=output,mode='wb',mtime=0,compresslevel=1) as archive:
            ino=100000
            for name in sorted(directories,key=lambda n:(n.count('/'),n)):
                ino+=1;write_entry(archive,name.replace('\\','/'),b'',0o40755,ino)
            for name,file in sorted(inputs.items()):
                ino+=1;write_entry(archive,name,file.read_bytes(),0o100755 if file.suffix!='.py' else 0o100644,ino)
            for name,data,mode in [('init',INIT.encode(),0o100755),('etc/passwd',b'root:x:0:0:root:/:/bin/sh\nportal:x:1000:1000:Portal:/portable/Data:/bin/sh\n',0o100644),('etc/group',b'root:x:0:\nportal:x:1000:\n',0o100644),('TRAILER!!!',b'',0)]:
                ino+=1;write_entry(archive,name,data,mode,ino)
    args=command_line(plan,initrd);args[args.index('-m')+1]='768'
    report={'passed':False,'network':False,'host_mounts':[],'guest_memory_mib':768,'accelerator':plan['accelerator'],
            'physical_linux_test':False,'test_folder':str(folder)}
    process=job=None
    log=artifacts.path('linux-guest-validation.log')
    try:
        with log.open('wb') as output:
            process=subprocess.Popen(args,cwd=folder,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=ProcessBudget(process);process.wait(timeout=90)
        text=log.read_text(encoding='utf-8',errors='replace')
        line=next((line for line in text.splitlines() if line.startswith('PORTAL_LINUX_RESULT=')),None)
        if line:report.update(json.loads(line.split('=',1)[1]))
        report['exit_code']=process.returncode
        if not report['passed']:report['tail']=text[-2500:]
    finally:
        if job:job.close()
        if process and process.poll() is None:process.kill();process.wait(timeout=5)
        atomic_json(artifacts.path('linux-guest-validation.json'),report)
    print(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    # Use the same bundled loader/native payload as the recipient GUI. The
    # former smaller guest assumed host glibc and no longer represents the bundle.
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from run_linux_packaging import main as packaging_main
    sys.argv=[sys.argv[0],'--media','--cases','supervision',*sys.argv[1:]]
    raise SystemExit(packaging_main())
