"""Test projection in the existing bounded offline VM; no host mounts/accounts."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import gzip,hashlib,json,subprocess,sys,time,uuid

MODULE=Path(__file__).resolve().parents[1];ROOT=default_target()
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent'),str(MODULE/'Tools')]
from run_linux_validation import write_entry
from vm_runner import preflight,command_line,ProcessBudget
from validation_artifacts import ValidationArtifacts,require_output_space
from runtime_policy import memory_info
from package_linux_runtime import needed

INIT=r'''#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
/usr/bin/busybox --install -s /usr/bin
chmod 755 /
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
ip link set lo up
mkdir -p /tmp /dev/shm /sys/fs/cgroup
mount -t tmpfs -o size=128m tmpfs /tmp
mount -t tmpfs -o size=64m tmpfs /dev/shm
chmod 1777 /tmp /dev/shm
mount -t cgroup2 none /sys/fs/cgroup
echo +memory > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/portalai-validation
echo +memory > /sys/fs/cgroup/portalai-validation/cgroup.subtree_control
mkdir /sys/fs/cgroup/portalai-validation/controller
echo $$ > /sys/fs/cgroup/portalai-validation/controller/cgroup.procs
chown -R 1000:1000 /sys/fs/cgroup/portalai-validation
mkdir -p /tmp/.X11-unix /usr/share/X11 /PortalAI/Data /PortalAI/Cache /PortalAI/Agent/.runtime /PortalAI-Projection/Tests/Validation /PortalAI-Projection/state/input /PortalAI-Projection/Connections
chmod 1777 /tmp/.X11-unix
chown -R 1000:1000 /PortalAI /PortalAI-Projection
ln -s /PortalAI/Runtime/LinuxSystem/rootfs/usr/share/X11/xkb /usr/share/X11/xkb
cat > /usr/bin/xkbcomp <<'EOF'
#!/bin/sh
N=/PortalAI/Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu
exec "$N/ld-linux-x86-64.so.2" --library-path "$N" /PortalAI/Runtime/LinuxSystem/rootfs/usr/bin/xkbcomp "$@"
EOF
chmod 755 /usr/bin/xkbcomp
export HOME=/PortalAI-Projection/state PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PORTALAI_CGROUP_ROOT=/sys/fs/cgroup/portalai-validation
export XDG_CACHE_HOME=/PortalAI-Projection/state/cache TMPDIR=/tmp
timeout -s KILL 210 su portal -s /bin/sh -c 'cd /PortalAI-Projection && /PortalAI-Projection/Runtime/LinuxPython/run-python -B -I /PortalAI-Projection/Tests/linux_guest.py'
echo PROJECTION_GUEST_EXIT=$?
sync
poweroff -f
'''

def main():
    artifacts=ValidationArtifacts(ROOT,ROOT/'Maintenance/Validation/ProjectionLinux')
    if memory_info()[1]<5*1024**3:raise RuntimeError('Need 5 GiB free RAM for bounded 2-GiB Linux guest')
    require_output_space(ROOT,artifacts,700*1024**2,for_outputs=True)
    plan=preflight(ROOT);folder=artifacts.path('guest_'+uuid.uuid4().hex);folder.mkdir()
    inputs={}
    receipt=json.loads((MODULE/'Runtime/linux-receipt.json').read_text())
    for row in receipt['files']:
        path=MODULE/row['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Runtime integrity mismatch')
        inputs['PortalAI-Projection/'+row['path']]=path
        if row['path'].startswith('Runtime/LinuxPython/'):
            inputs['PortalAI/'+row['path']]=path
    for path in (MODULE/'app').glob('*.py'):inputs['PortalAI-Projection/app/'+path.name]=path
    for path in (MODULE/'Tests').glob('*.py'):inputs['PortalAI-Projection/Tests/'+path.name]=path
    for path in (MODULE/'HomeAssistant/custom_components/portalai_projection').glob('*.py'):inputs['PortalAI-Projection/HomeAssistant/custom_components/portalai_projection/'+path.name]=path
    for path in (ROOT/'Agent').glob('*.py'):inputs['PortalAI/Agent/'+path.name]=path
    for rel in ('Agent/config.json','Agent/hardware_profiles.json','ControlCenter/remote_desktop_input.py','HomeAssistant/setup_pairing.py','Runtime/LinuxPython/run-python'):
        inputs['PortalAI/'+rel]=ROOT/rel
    for rel in ('Runtime/LinuxPython/run-python','Runtime/cacert.pem','Runtime/LinuxFonts/fonts.conf','Start Projection.sh'):
        inputs['PortalAI-Projection/'+rel]=MODULE/rel
    native={}
    for name in ('linux-system-payload.json','linux-system-extras.json','linux-system-science.json'):
        data=json.loads((ROOT/'Maintenance/Imports'/name).read_text())
        for row in data['files']:
            rel=row['path'];path=ROOT/data['destination']/rel
            if Path(rel).parent.as_posix() in ('usr/lib/x86_64-linux-gnu','usr/lib'):native.setdefault(path.name,(path,row['sha256']))
            if name=='linux-system-payload.json' and (rel in ('usr/bin/Xvfb','usr/bin/xkbcomp') or rel.startswith(('usr/share/X11/xkb/','usr/share/fonts/X11/misc/'))):
                if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Fixture runtime mismatch')
                inputs['PortalAI/Runtime/LinuxSystem/rootfs/'+rel]=path
    queue=['ld-linux-x86-64.so.2','libnss_files.so.2','libnss_dns.so.2']
    for path in list(inputs.values()):
        if path.name in ('Xvfb','xkbcomp'):queue.extend(needed(path))
    for row in receipt['files']:
        if row['path'].startswith('Runtime/LinuxNative/') and Path(row['path']).name in native:queue.append(Path(row['path']).name)
    seen=set()
    while queue:
        name=queue.pop()
        if name in seen:continue
        seen.add(name);path,digest=native[name]
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise RuntimeError('Native integrity mismatch')
        inputs['PortalAI/Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/'+name]=path;queue.extend(needed(path))
    directories={p.as_posix() for name in inputs for p in Path(name).parents if str(p)!='.'}
    initrd=folder/'initramfs'
    with initrd.open('wb') as output:
        output.write((Path(plan['guest'])/'boot/initramfs-virt').read_bytes())
        with gzip.GzipFile(fileobj=output,mode='wb',mtime=0,compresslevel=1) as archive:
            ino=100000
            for name in sorted(directories,key=lambda n:(n.count('/'),n)):
                ino+=1;write_entry(archive,name,b'',0o40755,ino)
            for name,path in sorted(inputs.items()):
                ino+=1;write_entry(archive,name,path.read_bytes(),0o100755 if path.suffix!='.py' else 0o100644,ino)
            for name,data,mode in [('init',INIT.encode(),0o100755),('etc/passwd',b'root:x:0:0:root:/:/bin/sh\nportal:x:1000:1000:Portal:/PortalAI-Projection/state:/bin/sh\n',0o100644),('etc/group',b'root:x:0:\nportal:x:1000:\n',0o100644),('TRAILER!!!',b'',0)]:
                ino+=1;write_entry(archive,name,data,mode,ino)
    args=command_line(plan,initrd);args[args.index('-m')+1]='2048';log=folder/'guest.log';process=job=None
    result={'passed':False,'network':False,'host_mounts':[],'guest_memory_mib':2048,'host_cap_gib':3,'physical_linux':False}
    try:
        with log.open('wb') as output:
            process=subprocess.Popen(args,cwd=folder,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=ProcessBudget(process,3*1024**3);process.wait(timeout=240)
        text=log.read_text(errors='replace')
        line=next((x for x in text.splitlines() if x.startswith('PROJECTION_LINUX_RESULT=')),None)
        if line:result.update(json.loads(line.split('=',1)[1]))
        else:result['tail']=text[-6500:]
    finally:
        if job:job.close()
        if process and process.poll() is None:process.kill();process.wait(5)
        result['log']=str(log);artifacts.path('result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));return 0 if result['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
