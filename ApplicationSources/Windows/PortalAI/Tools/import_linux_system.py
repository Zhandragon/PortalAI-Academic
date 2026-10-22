"""Package Linux FFmpeg/QEMU/Tk display libraries without installing host packages."""
import io
import json
import lzma
import os
from pathlib import Path,PurePosixPath
import posixpath
import re
import sys
import tarfile

sys.path.insert(0,str(Path(__file__).resolve().parent))
from import_linux_validation import ROOT,BASE,get,sha,ar_data
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json,require_space

WANTED=('ffmpeg','qemu-system-x86','qemu-system-data','seabios','libxft2','libxrender1',
        'libxext6','libgl1','libgomp1','xvfb','xauth','fonts-dejavu-core','libportaudio2','libopencl1')


def main():
    extras='--extras' in sys.argv
    science='--science' in sys.argv
    genomics='--genomics' in sys.argv
    shells='--genomics-tools' in sys.argv
    kicad='--kicad' in sys.argv
    kicad_resources='--kicad-resources' in sys.argv
    plan_only='--plan-only' in sys.argv
    if sum((extras,science,genomics,shells,kicad,kicad_resources))>1:raise ValueError('Select one Linux payload kind')
    destination=ROOT/('Runtime/LinuxSystem/kicad-resources' if kicad_resources else 'Runtime/LinuxSystem/kicad' if kicad else 'Runtime/LinuxSystem/genomics-tools' if shells else 'Runtime/LinuxSystem/genomics' if genomics else 'Runtime/LinuxSystem/science' if science else 'Runtime/LinuxSystem/extras' if extras else 'Runtime/LinuxSystem/rootfs')
    if destination.exists():raise RuntimeError('Linux payload exists; verify rather than overwrite')
    require_space(ROOT,3*1024**3)
    release=get(BASE+'dists/trixie/Release',2*1024**2).decode()
    entries=[r.split() for r in release.split('SHA256:\n',1)[1].splitlines() if len(r.split())==3]
    expected,size,relative=next(r for r in entries if r[2]=='main/binary-amd64/Packages.xz')
    compressed=get(BASE+'dists/trixie/'+relative,int(size))
    if len(compressed)!=int(size) or sha(compressed)!=expected:raise RuntimeError('Linux package index integrity failed')
    index=lzma.decompress(compressed);records={};providers={}
    for block in index.decode().split('\n\n'):
        row=dict(line.split(': ',1) for line in block.splitlines() if ': ' in line and not line.startswith(' '))
        if 'Package' not in row:continue
        records[row['Package']]=row
        for name in row.get('Provides','').split(','):
            providers.setdefault(name.strip().split(' ')[0],row['Package'])
    pending=list(('kicad-symbols','kicad-footprints','kicad-packages3d') if kicad_resources else ('kicad',) if kicad else ('bash','busybox-static') if shells else ('mafft',) if genomics else ('libxinerama1','libxcursor1') if science else ('sox','libsox-fmt-all','libglu1-mesa','libxmu6','libxi6','libegl1') if extras else WANTED);selected={}
    while pending:
        name=pending.pop()
        if name not in records:name=providers.get(name,name)
        if name in selected:continue
        if name not in records:raise RuntimeError('Missing required Linux package: '+name)
        row=records[name];selected[name]=row
        for field in ('Depends','Pre-Depends'):
            for requirement in row.get(field,'').split(','):
                if not requirement.strip():continue
                options=[re.split(r'[\s:(]',x.strip())[0] for x in requirement.split('|')]
                child=next((n for n in options if n in records),None) or next((providers[n] for n in options if n in providers),None)
                if child is None:raise RuntimeError('Cannot resolve package dependency: '+requirement)
                pending.append(child)
    total=sum(int(r['Size']) for r in selected.values())
    expanded=sum(int(r.get('Installed-Size',0))*1024 for r in selected.values())
    require_space(ROOT,max(total*5,total+expanded*2))
    if total>1200*1024**2:raise RuntimeError('Native Linux dependency closure exceeds reviewed 1.2 GiB download budget')
    if plan_only:
        print(json.dumps({'destination':str(destination),'packages':len(selected),'download_bytes':total,
            'installed_bytes_estimate':sum(int(r.get('Installed-Size',0))*1024 for r in selected.values()),
            'package_index_sha256':expected,'release_sha256':sha(release.encode()),
            'assets':[{'name':name,'version':row['Version'],'bytes':int(row['Size']),'sha256':row['SHA256'],'url':BASE+row['Filename']} for name,row in sorted(selected.items())]},indent=2))
        return
    cache=ROOT/'Cache/LinuxSystem';cache.mkdir(parents=True,exist_ok=True)
    print(json.dumps({'packages':len(selected),'download_bytes':total}),flush=True)
    links={};assets=[];files={}
    stage=destination.with_name(destination.name+'-stage')
    stage.mkdir(parents=True,exist_ok=True)
    for name,row in sorted(selected.items()):
        path=cache/Path(row['Filename']).name
        data=path.read_bytes() if path.exists() else get(BASE+row['Filename'],int(row['Size']))
        if len(data)!=int(row['Size']) or sha(data)!=row['SHA256']:raise RuntimeError('Linux package integrity failed: '+name)
        if not path.exists():path.write_bytes(data)
        assets.append({'name':name,'version':row['Version'],'bytes':len(data),'sha256':sha(data),'url':BASE+row['Filename']})
        with tarfile.open(fileobj=io.BytesIO(ar_data(data)),mode='r:*') as archive:
            for member in archive:
                relative=posixpath.normpath(member.name.removeprefix('./'))
                if relative.startswith('/') or '..' in PurePosixPath(relative).parts:raise ValueError('Unsafe Debian path')
                if member.isfile():
                    if member.size>300*1024**2:raise ValueError('Unexpectedly large native payload member')
                    file=stage/relative;file.parent.mkdir(parents=True,exist_ok=True)
                    blob=archive.extractfile(member).read();file.write_bytes(blob);files[relative]={'sha256':sha(blob),'mode':member.mode,'bytes':len(blob)}
                elif member.issym() or member.islnk():
                    target=member.linkname
                    links[relative]=posixpath.normpath(target.lstrip('/') if target.startswith('/') else posixpath.join(posixpath.dirname(relative),target))
        print(json.dumps({'verified':name,'version':row['Version']}),flush=True)
    def resolve(path,seen=()):
        if path in files:return path
        if path in seen or path not in links:raise ValueError('Unresolved native link: '+path)
        return resolve(links[path],(*seen,path))
    unresolved=[]
    for name,target in links.items():
        try:source=resolve(target)
        except ValueError:unresolved.append({'path':name,'target':target});continue
        path=stage/name;path.parent.mkdir(parents=True,exist_ok=True)
        blob=(stage/source).read_bytes();path.write_bytes(blob);files[name]={**files[source],'materialized_link':target}
    # Broken manpage/config alternatives do not affect execution. Required ELF
    # libraries are checked in the actual Linux guest before readiness is claimed.
    if kicad:
        # wxWidgets locates KiCad modules beside /proc/self/exe. Explicit ELF
        # loader execution therefore needs an identical loader beside .kiface.
        source='usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        name='usr/lib/kicad/ld-linux-x86-64.so.2'
        blob=(stage/source).read_bytes();(stage/name).write_bytes(blob)
        files[name]={**files[source],'portable_loader_copy':source}
    os.replace(stage,destination)
    receipt={'verified':True,'destination':destination.relative_to(ROOT).as_posix(),'assets':assets,'suite':'trixie','architecture':'amd64','release_sha256':sha(release.encode()),
             'package_index_sha256':expected,'files':[{'path':k,**v} for k,v in sorted(files.items())],
             'unresolved_optional_links':unresolved,'maintainer_scripts_executed':False}
    atomic_json(ROOT/('Maintenance/Imports/linux-system-kicad-resources.json' if kicad_resources else 'Maintenance/Imports/linux-system-kicad.json' if kicad else 'Maintenance/Imports/linux-system-genomics-tools.json' if shells else 'Maintenance/Imports/linux-system-genomics.json' if genomics else 'Maintenance/Imports/linux-system-science.json' if science else 'Maintenance/Imports/linux-system-extras.json' if extras else 'Maintenance/Imports/linux-system-payload.json'),receipt)
    print(json.dumps({'installed_files':len(files),'bytes':sum(v['bytes'] for v in files.values()),'unresolved_links':len(unresolved)}))

if __name__=='__main__':main()
