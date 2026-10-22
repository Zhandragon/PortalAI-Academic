"""Bounded actual Linux GUI/native packaging check in the offline WHPX guest."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parent))
from run_linux_validation import ROOT,write_entry
sys.path.insert(0,str(ROOT/'Agent'))
from vm_runner import preflight,command_line,ProcessBudget
from runtime_policy import require_space,atomic_json,memory_info
from validation_artifacts import ValidationArtifacts,add_artifact_arguments,media_iso,require_output_space

INIT=r'''#!/bin/sh
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
/usr/bin/busybox --install -s /usr/bin
chmod 755 /
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
ip link set lo up
mkdir -p /sys/fs/cgroup /tmp /portable/Data /portable/Maintenance /portable/Cache /portable/Outputs /portable/Agent/.runtime
mount -t tmpfs -o size=128m tmpfs /tmp
mkdir -p /dev/shm
mount -t tmpfs -o size=64m tmpfs /dev/shm
chmod 1777 /dev/shm
for path in Data Maintenance Cache Outputs Agent/.runtime; do mount -t tmpfs -o size=64m tmpfs /portable/$path; chown 1000:1000 /portable/$path; done
mount -t cgroup2 none /sys/fs/cgroup
echo +memory > /sys/fs/cgroup/cgroup.subtree_control
mkdir /sys/fs/cgroup/portalai-validation
echo +memory > /sys/fs/cgroup/portalai-validation/cgroup.subtree_control
mkdir /sys/fs/cgroup/portalai-validation/controller
echo $$ > /sys/fs/cgroup/portalai-validation/controller/cgroup.procs
chown -R 1000:1000 /sys/fs/cgroup/portalai-validation
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp /tmp/.X11-unix
mkdir -p /usr/share/X11
ln -s /portable/Runtime/LinuxSystem/rootfs/usr/share/X11/xkb /usr/share/X11/xkb
cat > /usr/bin/xkbcomp <<'EOF'
#!/bin/sh
N=/portable/Runtime/LinuxSystem/rootfs/usr/lib
exec "$N/x86_64-linux-gnu/ld-linux-x86-64.so.2" --library-path "$N/x86_64-linux-gnu:$N" /portable/Runtime/LinuxSystem/rootfs/usr/bin/xkbcomp "$@"
EOF
chmod 755 /usr/bin/xkbcomp
export HOME=/portable/Data PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PORTALAI_CGROUP_ROOT=/sys/fs/cgroup/portalai-validation
timeout -s KILL 110 su portal -s /bin/sh -c 'cd /portable && /portable/Runtime/LinuxPython/run-python -B /portable/Tools/linux_packaging_tests.py'
echo PORTAL_PACKAGING_EXIT=$?
sync
poweroff -f
'''


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media',action='store_true',help='Run media/science cases in the bounded offline Linux guest')
    parser.add_argument('--cases',default='',help='Comma-separated media case names (requires --media)')
    parser.add_argument('--kicad-resources-iso',help='Existing read-only KiCad resource ISO; defaults to kicad-resources.iso in the artifacts directory')
    add_artifact_arguments(parser,media=True)
    options=parser.parse_args()
    media=options.media;cases=options.cases
    if cases and not media:parser.error('--cases requires --media')
    if cases:
        import linux_media_tests
        if any(name not in linux_media_tests.CASES for name in cases.split(',')):raise ValueError('Unknown Linux test case')
    artifacts=ValidationArtifacts(ROOT,options.artifacts_dir)
    disk=media_iso(ROOT,artifacts,options.media_iso) if media else None
    resources=None
    if media and (options.kicad_resources_iso or artifacts.path('kicad-resources.iso').is_file()):
        resources=media_iso(ROOT,artifacts,options.kicad_resources_iso or str(artifacts.path('kicad-resources.iso')))
    # The expanded native GUI/science payload no longer fits a 3 GiB initramfs.
    # Keep both suites inside the same admitted 6 GiB guest / 8 GiB host job.
    if memory_info()[1]<14*1024**3:raise RuntimeError('Insufficient free RAM for bounded Linux validation')
    plan=preflight(ROOT);require_output_space(ROOT,artifacts,2*1024**3,for_outputs=True)
    folder=artifacts.path('packaging_'+uuid.uuid4().hex);folder.mkdir(parents=True)
    inputs={}
    for directory in ('Runtime/LinuxPython','Runtime/LinuxPackages/gui','Runtime/Certificates','ControlCenter','Agent','Launchers'):
        base=ROOT/directory
        for file in base.rglob('*'):
            if not file.is_file() or '__pycache__' in file.parts or '.runtime' in file.parts:continue
            if directory=='Runtime/LinuxPython' and any(p in ('tests','test','site-packages','include','share','ensurepip') for p in file.relative_to(base).parts):continue
            if directory in ('Agent','Launchers') and file.suffix not in ('.py','.json','.sh'):continue
            if file.suffix.lower() in ('.log','.zip','.exe','.pyd','.dll'):continue
            inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for directory in ('Runtime/FFmpeg/linux-x64','Runtime/QEMU/linux-x64','Runtime/KiCad/linux-x64','Runtime/StableDiffusion/linux-cpu','Runtime/StableDiffusion/linux-vulkan'):
        for file in (ROOT/directory).rglob('*'):
            if file.is_file():inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    receipt=json.loads((ROOT/'Maintenance/Imports/linux-system-payload.json').read_text())
    base=ROOT/receipt['destination']
    for row in receipt['files']:
        name=row['path']
        if name.startswith(('usr/share/doc/','usr/share/man/','usr/share/locale/')):continue
        if '/dri/' in name or 'libLLVM' in name:continue
        file=base/name
        with file.open('rb') as f:actual=hashlib.file_digest(f,'sha256').hexdigest()
        if actual!=row['sha256']:raise RuntimeError('Native Linux asset checksum differs: '+name)
        inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    extra_receipt=json.loads((ROOT/'Maintenance/Imports/linux-system-extras.json').read_text())
    for row in extra_receipt['files']:
        relative=row['path']
        if (base/relative).exists() or relative.startswith(('usr/share/doc/','usr/share/man/','usr/share/locale/')):continue
        file=ROOT/extra_receipt['destination']/relative
        if hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Linux extra integrity mismatch')
        inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    science_receipt=json.loads((ROOT/'Maintenance/Imports/linux-system-science.json').read_text())
    for row in science_receipt['files']:
        relative=row['path']
        if (base/relative).exists() or relative.startswith(('usr/share/doc/','usr/share/man/')):continue
        file=ROOT/science_receipt['destination']/relative
        if hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Linux science library integrity mismatch')
        inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'Runtime/SoX/linux-x64').rglob('*'):
        if file.is_file():inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for kind in ('genomics','genomics-tools'):
        receipt=json.loads((ROOT/f'Maintenance/Imports/linux-system-{kind}.json').read_text())
        for row in receipt['files']:
            relative=row['path']
            if relative.startswith(('usr/share/doc/','usr/share/man/','usr/share/locale/')):continue
            file=ROOT/receipt['destination']/relative
            if hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('Linux genomics integrity mismatch')
            inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'Runtime/MAFFT/linux-x64').rglob('*'):
        if file.is_file():inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for kind in ('comfyextras','kornia_compat'):
        receipt=json.loads((ROOT/f'Maintenance/Imports/linux-{kind}-lock.json').read_text())
        for row in receipt['files']:
            file=ROOT/'Runtime/LinuxPackages'/kind/row['path']
            if hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError(kind+' integrity mismatch')
            inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'Scientific').glob('*.py'):inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    if 'biology' in cases.split(','):
        # Only pinned public source/weights; never include user PDBs or outputs.
        protein_receipt=json.loads((ROOT/'Maintenance/Imports/protein-mpnn.json').read_text())
        if not protein_receipt.get('verified') or protein_receipt.get('revision')!='8907e6671bfbfc92303b5f79c4b5e6ce47cdef57':
            raise RuntimeError('Unverified ProteinMPNN fixture assets')
        for row in protein_receipt['files']:
            if not row['path'].startswith('Runtime/ProteinDesign/vendor/'):continue
            file=ROOT/row['path']
            if not file.resolve().is_relative_to(ROOT/'Runtime/ProteinDesign/vendor') or file.stat().st_size!=row['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:
                raise RuntimeError('ProteinMPNN validation fixture differs')
            inputs['portable/'+row['path']]=file
    inputs['portable/MusicUnderstanding/runtime_driver.py']=ROOT/'MusicUnderstanding/runtime_driver.py'
    kicad_receipt=json.loads((ROOT/'Maintenance/Imports/linux-system-kicad.json').read_text())
    kicad_loader='usr/lib/kicad/ld-linux-x86-64.so.2'
    row=next(row for row in kicad_receipt['files'] if row['path']==kicad_loader)
    file=ROOT/kicad_receipt['destination']/kicad_loader
    if hashlib.sha256(file.read_bytes()).hexdigest()!=row['sha256']:raise RuntimeError('KiCad loader integrity mismatch')
    inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'Tools').glob('*.py'):inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'Maintenance/Tests').glob('*.py'):inputs['portable/Validation/Tests/'+file.name]=file
    for file in (ROOT/'Runtime/AccountPython/linux-packages').rglob('*'):
        if file.is_file() and '__pycache__' not in file.parts:inputs['portable/'+file.relative_to(ROOT).as_posix()]=file
    for file in ROOT.glob('PortableAI_Master_Instructions*'):inputs['portable/'+file.name]=file
    for file in (ROOT/'Maintenance/Imports').glob('*.json'):inputs['portable/Validation/Imports/'+file.name]=file
    for name in ('PortalAI.sh',):inputs['portable/'+name]=ROOT/name
    loader=base/'usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
    inputs['lib64/ld-linux-x86-64.so.2']=loader
    # The standalone interpreter has a portable RPATH; include libpython where its loader expects it.
    dirs={str(p).replace('\\','/') for name in inputs for p in Path(name).parents if str(p)!='.'}
    initrd=folder/'initramfs'
    init=INIT
    if cases:init=init.replace('export HOME=',f'export PORTALAI_LINUX_TEST_CASES={cases}\nexport HOME=')
    if media:
        setup=r'''
modprobe virtio_blk
modprobe isofs
mkdir -p /portable/.validationDisk
mount -t iso9660 -o ro /dev/vda /portable/.validationDisk || poweroff -f
for rel in Runtime/LinuxPackages/media Runtime/LinuxPackages/science Runtime/LinuxPackages/extras Runtime/LinuxPackages/musicunderstanding Runtime/LinuxTorch Video Services Music Generative Voice SpeechToText; do
  mkdir -p "/portable/$(dirname "$rel")"
  ln -s "/portable/.validationDisk/$rel" "/portable/$rel"
done
# Keep the small relocated loader in the initramfs so a previously verified
# large ISO can stay immutable. KiCad's module siblings point into that ISO.
kp=/portable/Runtime/LinuxSystem/kicad
ks=/portable/.validationDisk/Runtime/LinuxSystem/kicad
for rel in bin share; do ln -s "$ks/usr/$rel" "$kp/usr/$rel"; done
for file in "$ks/usr/lib"/*; do
  name=$(basename "$file")
  if [ "$name" != kicad ]; then ln -s "$file" "$kp/usr/lib/$name"; fi
done
for file in "$ks/usr/lib/kicad"/*.kiface; do ln -s "$file" "$kp/usr/lib/kicad/$(basename "$file")"; done
mkdir -p /portable/MusicUnderstanding/cache/demucs
for rel in models MOSS-Music cache/huggingface; do
  ln -s "/portable/.validationDisk/MusicUnderstanding/$rel" "/portable/MusicUnderstanding/$rel"
done
chown 1000:1000 /portable/MusicUnderstanding/cache/demucs
mkdir -p /portable/LLM
mount -o bind /portable/.validationDisk/LLM /portable/LLM
ln -s /portable/Validation/Imports /portable/Maintenance/Imports
mkdir -p /portable/PortableCache
mount -t tmpfs -o size=64m tmpfs /portable/PortableCache
chown 1000:1000 /portable/PortableCache
# Validation filesystem only: the production SSD reserve policy stays intact.
/portable/Runtime/LinuxPython/run-python -B -I -c 'import json; from pathlib import Path; p=Path("/portable/Agent/hardware_profiles.json"); policy=json.loads(p.read_text()); policy["storage"].update(minimum_free_gib=0,minimum_free_fraction=0,output_reserve_gib=0); p.write_text(json.dumps(policy))'
'''
        init=init.replace('timeout -s KILL 110',setup+'\ntimeout -s KILL 850').replace('Tools/linux_packaging_tests.py','Tools/linux_media_tests.py')
        if resources:
            resource_setup='''
mkdir -p /portable/.kicadResources
mount -t iso9660 -o ro /dev/vdb /portable/.kicadResources || poweroff -f
ln -s /portable/.kicadResources/Runtime/LinuxSystem/kicad-resources /portable/Runtime/LinuxSystem/kicad-resources
'''
            init=init.replace('mkdir -p /portable/PortableCache',resource_setup+'\nmkdir -p /portable/PortableCache')
    with initrd.open('wb') as out:
        out.write((Path(plan['guest'])/'boot/initramfs-virt').read_bytes())
        with gzip.GzipFile(fileobj=out,mode='wb',mtime=0,compresslevel=1) as archive:
            ino=100000
            for name in sorted(dirs,key=lambda n:(n.count('/'),n)):
                ino+=1;write_entry(archive,name,b'',0o40755,ino)
            for name,file in sorted(inputs.items()):
                ino+=1;write_entry(archive,name,file.read_bytes(),0o100755,ino)
            for name,data,mode in [('init',init.encode(),0o100755),('etc/passwd',b'root:x:0:0:root:/:/bin/sh\nportal:x:1000:1000:Portal:/portable/Data:/bin/sh\n',0o100644),('etc/group',b'root:x:0:\nportal:x:1000:\n',0o100644),('TRAILER!!!',b'',0)]:
                ino+=1;write_entry(archive,name,data,mode,ino)
    args=command_line(plan,initrd);args[args.index('-m')+1]='6144'
    if media:args+=['-cpu','Nehalem','-drive','file='+str(disk)+',format=raw,if=virtio,readonly=on']
    if resources:args+=['-drive','file='+str(resources)+',format=raw,if=virtio,readonly=on']
    report_name='linux-media-guest' if media else 'linux-packaging-guest'
    log=artifacts.path(report_name+'.log');report={'passed':False,'scope':'offline Linux guest GUI/native payload; no physical GPU or nested KVM'}
    proc=job=None
    try:
        with log.open('wb') as out:
            proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=ProcessBudget(proc,memory_bytes=8*1024**3);proc.wait(timeout=900 if media else 150)
        text=log.read_text(errors='replace')
        line=next((s for s in text.splitlines() if s.startswith('PORTAL_PACKAGING_RESULT=')),None)
        if line:report.update(json.loads(line.split('=',1)[1]))
        if not report['passed']:report['tail']=text[-3500:]
    finally:
        if job:job.close()
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=5)
        atomic_json(artifacts.path(report_name+'.json'),report)
    print(json.dumps(report));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
