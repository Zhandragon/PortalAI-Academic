"""Derive Windows/Universal r80 online kits from verified published kits.

The Windows overlay reconstructs the exact bundled r80 payload from the public
Academic r80 archive. Unix specs/overlays and all licence notices are retained.
No installed app is launched or inspected.
"""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import zipfile
import build_payhip_full as builder

VERSION = '2026.11.21-Desktop-r80'
prepare = builder.prepare

def encoded(value):
    return (json.dumps(value, indent=2)+'\n').encode()

def windows_spec(releases, kind, previous):
    base = releases/'Academic/package'
    full = releases/kind/'package'
    base_archive = next((releases/'Academic').glob('*.zip'))
    full_archive = next((releases/kind).glob('*.zip'))
    base_rows = {r['path']: r for r in prepare.payload_inventory(base/'payload.zip', 'Windows')}
    inventory = prepare.payload_inventory(full/'payload.zip', 'Windows')
    full_rows = {r['path']: r for r in inventory}
    changed = [n for n,r in full_rows.items() if base_rows.get(n) != r]
    assert not any(n.lower().endswith(('.dll','.exe','.pyd','.so','.dylib','.zip','.gz','.whl','.onnx')) for n in changed)
    data = {}
    with zipfile.ZipFile(full/'payload.zip') as archive:
        for name in changed:
            data['payload/'+name] = archive.read(name)
    for path in full.iterdir():
        if path.name == 'payload.zip': continue
        if not (base/path.name).exists() or builder.prepare.digest(path) != builder.prepare.digest(base/path.name):
            data['outer/'+path.name] = path.read_bytes()
    blob = io.BytesIO()
    with zipfile.ZipFile(blob, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name,content in sorted(data.items()): archive.writestr(name,content)
    content = blob.getvalue()
    spec = copy.deepcopy(previous)
    spec.update(application_version=VERSION, output_folder=f'PortalAI-Full-{kind}-Windows-{VERSION}',
                base={**builder.pin(base_archive), 'file': base_archive.name, 'root': '', 'url': f'https://github.com/Zhandragon/PortalAI-Academic/releases/download/v{VERSION}/{base_archive.name}'},
                base_outer=[builder.pin(p) for p in sorted(base.iterdir()) if p.is_file()],
                overlay={'file': previous['overlay']['file'], 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()},
                outer_overlay=[builder.data_pin(n[6:],b) for n,b in sorted(data.items()) if n.startswith('outer/')],
                payload_overlay=[builder.data_pin(n[8:],b) for n,b in sorted(data.items()) if n.startswith('payload/')],
                outer_remove=sorted(set(p.name for p in base.iterdir())-set(p.name for p in full.iterdir())),
                payload_remove=sorted(set(base_rows)-set(full_rows)),full_payload_inventory=inventory,
                full_baseline_sha256=prepare.digest(full_archive),
                source_patch={'id':'computer-use-stop-resize-r80','release':VERSION,'files':[r['path'] for r in json.loads((builder.REPO/'tools/media-shutdown-update-Windows.json').read_text())['files']]})
    spec['base'].pop('path',None)
    return spec,content

def build(releases, baseline, output, kind):
    revision='2026.11.21-'+('Trial-online7' if kind=='Trial' else 'PayHip-online10')
    output.mkdir(parents=True,exist_ok=False)
    report=[]
    for profile in ('Windows','Universal'):
        matches=list(baseline.glob(f'PortalAI-Full-{ "Trial-" if kind=="Trial" else ""}{profile}-*.zip'))
        if kind=='Full':matches=[p for p in matches if '-Trial-' not in p.name]
        assert len(matches)==1
        with zipfile.ZipFile(matches[0]) as archive:
            files={n:archive.read(n) for n in archive.namelist() if not n.endswith('/')}
        for row in json.loads(files['KIT-SHA256.json']):
            prepare.check_bytes(files[row['path']],row)
        manifest=json.loads(files['payhip-manifest.json'])
        old_revision=manifest['packaging_revision']
        spec,overlay=windows_spec(releases,kind,manifest['platforms']['Windows'])
        spec['packaging_revision']=revision
        manifest['platforms']['Windows']=spec
        manifest['packaging_revision']=revision
        files['payhip-manifest.json']=encoded(manifest)
        files[spec['overlay']['file']]=overlay
        readme=files['START_HERE.txt'].decode('utf-8').replace(old_revision,revision)
        readme+='\nWINDOWS r80 UPDATE\nThe Windows installer and application now match '+VERSION+'.\nReference-guided media planning, staged edits, stronger owned-script Stop\nand tested desktop/browser workflows are included with r79 voice improvements. Unix packages retain r75.\nUse this new extracted kit for Windows/Universal setup; older kits are archived.\n'
        files['START_HERE.txt']=readme.encode('utf-8')
        folder=output/f'PortalAI-Full-{ "Trial-" if kind=="Trial" else ""}{profile}-{revision}'
        folder.mkdir()
        for name,data in files.items():
            if name in ('KIT-SHA256.json','BOOTSTRAP-SHA256SUMS') or name.endswith('.exe'):continue
            p=prepare.target(folder,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
        paths=sorted(p for p in folder.rglob('*') if p.is_file())
        prepare.write_json(folder/'KIT-SHA256.json',[builder.pin(p,p.relative_to(folder).as_posix()) for p in paths])
        (folder/'BOOTSTRAP-SHA256SUMS').write_text(''.join(prepare.digest(p)+'  '+p.relative_to(folder).as_posix()+'\n' for p in paths)+prepare.digest(folder/'KIT-SHA256.json')+'  KIT-SHA256.json\n',encoding='utf-8')
        builder.compile_bootstrap(folder,'all' if profile=='Universal' else 'Windows',output)
        prepare.HERE=folder;prepare.verify_kit()
        destination=output/(folder.name+'.zip')
        with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for p in sorted(folder.rglob('*')):
                if not p.is_file():continue
                entry=zipfile.ZipInfo.from_file(p,p.relative_to(folder).as_posix());entry.create_system=3
                entry.external_attr=(0o100755 if p.suffix in ('.sh','.command') else 0o100644)<<16
                entry.compress_type=zipfile.ZIP_DEFLATED;archive.writestr(entry,p.read_bytes())
        report.append(builder.pin(destination))
    universal=folder
    source=output/f'PortalAI-Full-{ "Trial-" if kind=="Trial" else ""}{revision}-source.zip'
    with zipfile.ZipFile(source,'x',zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        archive.writestr('SOURCE-README.txt',f'PortalAI {kind} r80 online kit corresponding source.\nShared Windows sources: https://github.com/Zhandragon/PortalAI-Academic/tree/v{VERSION}\nShared Mac/Linux sources: https://github.com/Zhandragon/PortalAI-Academic/tree/v2026.11.09-Desktop-r75\nFull/Trial differences are included under editions. GPLv3 and component notices remain in force.\n')
        archive.write(builder.REPO/'LICENSE','LICENSE')
        for name in ('InstallerSources/Payhip','InstallerSources/Windows','TrialSources','tools'):
            for p in sorted((builder.REPO/name).iterdir()):
                if p.is_file() and p.suffix in ('.py','.cs','.txt','.md','.json','.sh','.ps1'):
                    archive.write(p,p.relative_to(builder.REPO).as_posix())
        archive.write(universal/'payhip-manifest.json','payhip-manifest.json')
        for p in sorted((universal/'editions').glob('*.zip')):
            with zipfile.ZipFile(p) as overlay:
                for name in overlay.namelist():
                    if not name.lower().endswith('.exe'):archive.writestr('editions/'+p.stem+'/'+name,overlay.read(name))
    guide=output/f'PortalAI-START-HERE-{revision}.txt';guide.write_bytes((universal/'START_HERE.txt').read_bytes())
    deliverables=sorted(p for p in output.iterdir() if p.is_file() and p.suffix in ('.zip','.txt'))
    (output/f'SHA256SUMS-{revision}.txt').write_text(''.join(prepare.digest(p)+'  '+p.name+'\n' for p in deliverables))
    prepare.write_json(output/'build-report.json',dict(packaging_revision=revision,kind=kind,kits=report,windows_version=VERSION,unix_payloads_unchanged=True))
    print(json.dumps(report),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('releases','baseline','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--kind',choices=['Full','Trial'],required=True)
    a=parser.parse_args();build(a.releases,a.baseline,a.output,a.kind)
