"""Copy a minimal Linux runtime from existing checksum-pinned SSD receipts."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import hashlib
import json
import shutil
import struct

MODULE=Path(__file__).resolve().parents[1]
ROOT=default_target()

def needed(path):
    data=path.read_bytes()
    if not data.startswith(b'\x7fELF'):return []
    if data[4:6]!=b'\x02\x01':raise ValueError('Expected little-endian ELF64')
    offset=struct.unpack_from('<Q',data,40)[0];size,count=struct.unpack_from('<HH',data,58)
    sections=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)]
    result=[]
    for section in sections:
        if section[1]!=6:continue
        strings=sections[section[6]];table=data[strings[4]:strings[4]+strings[5]]
        for pos in range(section[4],section[4]+section[5],16):
            tag,value=struct.unpack_from('<qQ',data,pos)
            if tag==1:result.append(table[value:table.index(b'\0',value)].decode())
    return result

def main():
    files={};native={};provenance=[]
    def receipt(name):
        path=ROOT/'Maintenance/Imports'/name;data=json.loads(path.read_text())
        provenance.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        return data
    python=receipt('linux-python.json')
    for row in python['installed_files']:
        rel=Path(row['path'])
        if any(part in ('test','tests','include','share','ensurepip','site-packages','__pycache__') for part in rel.parts):continue
        if rel.parts[0]=='bin' and not rel.name.startswith('python3'):continue
        files['Runtime/LinuxPython/'+rel.as_posix()]=(ROOT/python['dest']/rel,row['sha256'])
    accounts=receipt('linux-accounts-lock.json')
    for row in accounts['files']:
        rel=row['path']
        if rel.startswith(('cryptography/','cffi/','pycparser/','_cffi_backend','cryptography-','cffi-','pycparser-')) and '__pycache__' not in rel:
            files['Runtime/LinuxPackages/'+rel]=(ROOT/'Runtime/AccountPython/linux-packages'/rel,row['sha256'])
    for name in ('linux-system-payload.json','linux-system-extras.json','linux-system-science.json','linux-system-kicad.json'):
        data=receipt(name)
        for row in data['files']:
            rel=Path(row['path'])
            if rel.parent.as_posix() in ('usr/lib/x86_64-linux-gnu','usr/lib'):
                native.setdefault(rel.name,(ROOT/data['destination']/rel,row['sha256']))
            if name=='linux-system-payload.json' and rel.as_posix().endswith(('/DejaVuSans.ttf','/DejaVuSans-Bold.ttf')):
                files['Runtime/LinuxFonts/'+rel.name]=(ROOT/data['destination']/rel,row['sha256'])
    python_libs={Path(name).name for name in files if name.startswith('Runtime/LinuxPython/lib/') and Path(name).parent.as_posix()=='Runtime/LinuxPython/lib'}
    queue=['ld-linux-x86-64.so.2','libX11.so.6','libXcomposite.so.1','libnss_files.so.2','libnss_dns.so.2']
    for file,digest in list(files.values()):queue.extend(needed(file))
    seen=set()
    while queue:
        name=queue.pop()
        if name.startswith('$ORIGIN/') and Path(name).name in python_libs:continue
        if name in seen or name in python_libs:continue
        seen.add(name)
        if name not in native:raise RuntimeError('Missing pinned native dependency '+name)
        source,digest=native[name];files['Runtime/LinuxNative/'+name]=(source,digest);queue.extend(needed(source))
    report=[]
    import sys
    sys.path.insert(0,str(ROOT/'Agent'))
    from runtime_policy import require_space
    require_space(ROOT,sum(source.stat().st_size for name,(source,_) in files.items() if not (MODULE/name).exists()),for_outputs=True)
    for name,(source,expected) in sorted(files.items()):
        data=source.read_bytes();actual=hashlib.sha256(data).hexdigest()
        if actual!=expected:raise RuntimeError('Source integrity mismatch: '+str(source))
        dest=MODULE/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists() and hashlib.sha256(dest.read_bytes()).hexdigest()!=actual:raise RuntimeError('Existing destination differs: '+name)
        if not dest.exists():
            with dest.open('xb') as output:output.write(data)
        if hashlib.sha256(dest.read_bytes()).hexdigest()!=actual:raise RuntimeError('Copied runtime integrity mismatch')
        report.append({'path':name,'bytes':len(data),'sha256':actual,'source':source.relative_to(ROOT).as_posix()})
    result={'platform':'Linux x86_64; bundled glibc loader, Python 3.12.15, Tk, cryptography; X11/XWayland required',
        'source_receipts':provenance,'files':report}
    (MODULE/'Runtime/linux-receipt.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(report),'bytes':sum(r['bytes'] for r in report),'native_libraries':len(seen)}))

if __name__=='__main__':main()
