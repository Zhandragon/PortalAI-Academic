"""Build public HA receiver and verify source-only recovery snapshots on the SSD."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import ast
import hashlib
import json
import os
import sys
import time
import zipfile

MODULE=Path(__file__).resolve().parents[1]
PORTAL=default_target()
sys.path.insert(0,str(PORTAL/'Tools'))
from snapshot_owned import required_master_paths


def sha(data):return hashlib.sha256(data).hexdigest()


def snapshot(root,files,folder):
    folder.mkdir(parents=True,exist_ok=False);rows=[]
    archive=folder/'source.zip'
    with archive.open('xb') as handle:
        with zipfile.ZipFile(handle,'w',zipfile.ZIP_DEFLATED) as output:
            for name in sorted(set(files)):
                path=root/name
                if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):raise ValueError('Invalid source path: '+name)
                data=path.read_bytes()
                if len(data)>16*1024**2:raise ValueError('Oversized source')
                output.writestr(name,data);rows.append({'path':name,'bytes':len(data),'sha256':sha(data)})
        handle.flush();os.fsync(handle.fileno())
    manifest={'scope':'Source/code/docs/config only. No user profiles, connections, device keys, screen frames or runtime binaries. Not an SSD backup.',
              'files':rows,'archive_sha256':sha(archive.read_bytes())}
    with (folder/'manifest.json').open('x',encoding='utf-8') as handle:
        json.dump(manifest,handle,indent=2);handle.flush();os.fsync(handle.fileno())
    with zipfile.ZipFile(archive) as source:
        assert source.testzip() is None
        for row in rows:
            data=source.read(row['path']);assert len(data)==row['bytes'] and sha(data)==row['sha256']
    return {'path':str(archive),'files':len(rows),'sha256':manifest['archive_sha256']}


def main():
    paths=[]
    for directory in ('app','HomeAssistant','Tests','Tools'):
        paths.extend(p for p in (MODULE/directory).rglob('*.py') if 'Validation' not in p.parts)
    for path in paths:ast.parse(path.read_text(encoding='utf-8-sig'),filename=str(path))
    receipt=json.loads((MODULE/'Runtime/receipt.json').read_text())
    linux=json.loads((MODULE/'Runtime/linux-receipt.json').read_text())
    receipt['files'].extend(linux['files'])
    for row in receipt['files']:
        data=(MODULE/row['path']).read_bytes()
        if len(data)!=row['bytes'] or sha(data)!=row['sha256']:raise RuntimeError('Runtime receipt mismatch: '+row['path'])
    home=MODULE/'HomeAssistant';archive=home/'portalai-projection-receiver-0.3.0.zip'
    source=[p for p in home.rglob('*') if p.is_file() and p.suffix in ('.py','.json','.yaml','.js','.txt') and '__pycache__' not in p.parts]
    manifest={}
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as output:
        for path in sorted(source):
            name=path.relative_to(home).as_posix();data=path.read_bytes();output.writestr(name,data);manifest[name]=sha(data)
        output.writestr('SHA256SUMS.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(archive) as check:
        assert check.testzip() is None
        for name,digest in manifest.items():assert sha(check.read(name))==digest
    package_hash=sha(archive.read_bytes())
    (home/'portalai-projection-receiver-0.3.0.sha256').write_text(package_hash+'  '+archive.name+'\n',encoding='ascii')
    stamp=time.strftime('%Y%m%d_%H%M%S')
    previous=json.loads((PORTAL/'Maintenance/Patches/HomeAssistant_final_20261012_150948/manifest.json').read_text())
    root_files={row['path'] for row in previous['files']}
    root_files.update(required_master_paths(PORTAL))
    root_files.update(('AGENTS.md','Agent/config.json','Documentation/Home_Assistant_Projection_20261012.txt','HomeAssistant/ha/RETIRED.txt'))
    root_snapshot=snapshot(PORTAL,root_files,PORTAL/'Maintenance/Patches'/('Projection_final_'+stamp))
    module_files={'README.txt','VALIDATION.txt','Start Projection.cmd','Start Projection.sh','Runtime/receipt.json','Runtime/linux-receipt.json','Runtime/LinuxPython/run-python','Runtime/LinuxFonts/fonts.conf'}
    for directory in ('app','HomeAssistant','Tests','Tools'):
        for path in (MODULE/directory).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.json','.yaml','.js','.txt','.sha256','.sh') and not any(x in path.parts for x in ('Validation','__pycache__')):
                module_files.add(path.relative_to(MODULE).as_posix())
    module_snapshot=snapshot(MODULE,module_files,MODULE/'Recovery'/('Source_'+stamp))
    report={'receiver':str(archive),'receiver_sha256':package_hash,'receiver_files':len(manifest),'owned_python_parsed':len(paths),
            'runtime_files_verified':len(receipt['files']),'runtime_bytes':sum(row['bytes'] for row in receipt['files']),
            'root_source_snapshot':root_snapshot,'module_source_snapshot':module_snapshot}
    (MODULE/'RELEASE.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
