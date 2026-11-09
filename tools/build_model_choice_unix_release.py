"""Apply reviewed r74 follow-up sources to pinned native Unix suites.

Preserves native dependencies, archive modes, platform/edition policy and all
upgrade history. No recipient execution or new runtime acceptance is implied.
"""
import argparse, ast, copy, hashlib, io, json, math, shutil, subprocess, tarfile
from pathlib import Path

VERSION='2026.11.09-Desktop-r75'

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def encoded(value):return (json.dumps(value,indent=2,ensure_ascii=True)+'\n').encode()

def build(repo,previous,stage,platform):
    expected=Path(str(previous)+'.sha256').read_text().split()[0].lower()
    assert digest(previous)==expected
    stage.mkdir(parents=True,exist_ok=False)
    package=stage/'package';package.mkdir()
    outer_info={}
    with tarfile.open(previous,'r:gz') as src:
        names=src.getnames();assert len(names)==len(set(names))
        prefix=names[0].split('/')[0]
        for item in src:
            assert item.isfile() and item.name.startswith(prefix+'/')
            name=item.name[len(prefix)+1:]
            assert name and not Path(name).is_absolute() and '..' not in Path(name).parts
            p=package/name;p.parent.mkdir(parents=True,exist_ok=True)
            with src.extractfile(item) as a,p.open('xb') as b:shutil.copyfileobj(a,b,1024**2)
            outer_info[name]=item
    for line in (package/'SHA256SUMS').read_text().splitlines():
        if line.strip():
            sha,name=line.split(maxsplit=1);assert digest(package/name.strip())==sha
    manifest=json.loads((package/'manifest.json').read_text())
    original_contract=json.loads((package/'upgrade.json').read_text())
    old=manifest['distribution_version'];edition=original_contract['edition']
    assert platform==original_contract['platform'] and edition in ('Full','Academic')
    component_key='artifacts' if platform=='Mac' else 'components'
    prior_components=copy.deepcopy(manifest[component_key])
    assert digest(package/'payload.tar.gz')==manifest[component_key]['payload.tar.gz']['sha256']
    base=repo/'ApplicationSources'/platform/'PortalAI'
    source_prefix=f'ApplicationSources/{platform}/PortalAI/'
    tracked=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard','--',source_prefix],cwd=repo).decode().split('\0')
    # Include the existing source-only workspace integration and its imports,
    # rather than putting its newer Chat module over an incomplete r51 payload.
    # Native binaries remain exactly as supplied by the pinned OS archive.
    source_suffixes={'.py','.json','.md','.txt','.js','.css','.html','.sh','.command','.pem','.svg','.csv','.tsv','.c','.h','.cpp','.toml','.yaml','.yml','.in','.ps1','.cmd','.bat'}
    overlay={}
    for name in filter(None,tracked):
        p=repo/name;rel=name.removeprefix(source_prefix)
        assert p.is_file() and '/Private/' not in name and '/Data/' not in name and p.name!='AGENTS.md'
        if p.suffix.lower() not in source_suffixes:continue
        data=p.read_bytes()
        if p.suffix=='.py':ast.parse(data,filename=name)
        overlay['PortalAI/'+rel]=data
    assert VERSION.encode() in overlay['PortalAI/ControlCenter/release_version.py']
    rewritten=stage/'payload-new.tar.gz';inventory=[];before={};updated=[]
    with tarfile.open(package/'payload.tar.gz','r:gz') as src,tarfile.open(rewritten,'w:gz',compresslevel=6) as dst:
        seen=set()
        for item in src:
            assert item.name not in seen;seen.add(item.name)
            assert not item.name.startswith('/') and '..' not in Path(item.name).parts
            if item.isfile():
                with src.extractfile(item) as stream:data=stream.read()
                oldsha=hashlib.sha256(data).hexdigest();before[item.name]={'sha256':oldsha,'bytes':len(data)}
                if item.name in overlay:
                    data=overlay.pop(item.name)
                    if hashlib.sha256(data).hexdigest()!=oldsha:updated.append(item.name)
                info=copy.copy(item);info.size=len(data)
                dst.addfile(info,io.BytesIO(data))
                inventory.append({'path':item.name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'mode':item.mode})
            else:dst.addfile(item)
        for name,data in overlay.items():
            assert name.startswith('PortalAI/') and Path(name).suffix.lower() in source_suffixes
            item=tarfile.TarInfo(name);item.size=len(data);item.mode=0o644
            dst.addfile(item,io.BytesIO(data));updated.append(name)
            inventory.append({'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'mode':item.mode})
    rewritten.replace(package/'payload.tar.gz')
    after={r['path']:r for r in inventory}
    for name,row in before.items():
        if name not in updated:assert after[name]['sha256']==row['sha256']
    manifest['distribution_version']=VERSION
    manifest['supersedes_release']=manifest['release']
    manifest['release']=f'PortalAI-{VERSION}-suite-{edition}-{platform}'
    manifest[component_key]['payload.tar.gz']={'bytes':(package/'payload.tar.gz').stat().st_size,'sha256':digest(package/'payload.tar.gz')}
    assert {k:v for k,v in prior_components.items() if k!='payload.tar.gz'}=={k:v for k,v in manifest[component_key].items() if k!='payload.tar.gz'}
    if platform=='Mac':
        manifest['application'].update(files=len(inventory),payload_bytes=sum(r['bytes'] for r in inventory),payload_sha256=digest(package/'payload.tar.gz'))
    contract=json.loads((package/'upgrade.json').read_text())
    contract['version']=VERSION
    contract['compatible_versions']=list(dict.fromkeys(contract.get('compatible_versions',[])+[old]))
    manifest['upgrade']=contract
    manifest['followup_queue']={'guide':'Documentation/Followup_Queue_r74.md','current_chat_only':True,'maximum_pending':32,'new_dependencies':False}
    manifest['science_examples']={'guide':'Documentation/Science_Examples_r73.md','native_recipient_acceptance':False,'new_dependencies':False,'matching_workspace_sources_included':True,'updated_members':updated}
    (package/'upgrade.json').write_bytes(encoded(contract))
    (package/'manifest.json').write_bytes(encoded(manifest))
    plan=json.loads((package/'storage-plan.json').read_text());plan['release']=manifest['release']
    payload_bytes=sum(r['bytes'] for r in inventory);oldbytes=sum(r['bytes'] for r in before.values());delta=payload_bytes-oldbytes;added=len(after)-len(before)
    for row in plan['architectures'].values():
        row['payload_bytes']=payload_bytes;row['payload_files']=len(inventory)
        row['base_kib']+=max(0,math.ceil(delta/1024))+max(0,added)*64
        row['recovery_backup_allowance_bytes']=row.get('recovery_backup_allowance_bytes',0)+max(0,delta)
    (package/'storage-plan.json').write_bytes(encoded(plan))
    catalog=json.loads((package/'suite-catalog.json').read_text());catalog['catalog_version']=VERSION
    for row in catalog['assets']:
        if row.get('kind')=='installer':
            oldtag=row['tag'];row['file']=row['file'].replace(oldtag.removeprefix('v'),VERSION)
            row['tag']='v'+VERSION;row['url']=f"https://github.com/{row['repository']}/releases/download/v{VERSION}/{row['file']}";row['resolve_release']=True
    (package/'suite-catalog.json').write_bytes(encoded(catalog))
    script='install-macos.sh' if platform=='Mac' else 'install.sh'
    (package/script).write_bytes((repo/'InstallerSources'/platform/script).read_bytes())
    manifest['model_download_choices']={'guide':'Documentation/Optional_Models_r75.txt','explicit_opt_in':True,'custom_chat_architecture':'qwen3','weights_separately_licensed':True}
    (package/'manifest.json').write_bytes(encoded(manifest))
    readme=package/'README.txt'
    readme.write_bytes((readme.read_text(encoding='utf-8').replace(old,VERSION)+'\nFollow-up sending r74: see Documentation/Followup_Queue_r74.md. The r73 science repairs and existing platform runtime limitations remain.\n').encode())
    files=sorted(p for p in package.rglob('*') if p.is_file() and p.name!='SHA256SUMS')
    (package/'SHA256SUMS').write_text(''.join(digest(p)+'  '+p.relative_to(package).as_posix()+'\n' for p in files),encoding='utf-8',newline='\n')
    output=stage/f'PortalAI-{edition}-{platform}-Installer-{VERSION}-suite.tar.gz'
    with tarfile.open(output,'w:gz',compresslevel=6) as dst:
        for p in sorted(package.rglob('*')):
            if not p.is_file():continue
            name=p.relative_to(package).as_posix();item=copy.copy(outer_info[name]);item.name=output.name.removesuffix('.tar.gz')+'/'+name;item.size=p.stat().st_size
            item.pax_headers = {k:v for k,v in item.pax_headers.items() if k not in ('path','size')}
            with p.open('rb') as f:dst.addfile(item,f)
    Path(str(output)+'.sha256').write_text(digest(output)+'  '+output.name+'\n',encoding='utf-8')
    with tarfile.open(package/'payload.tar.gz','r:gz') as verify:
        for item in verify:
            if item.isfile():
                r=after[item.name]
                with verify.extractfile(item) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==r['sha256']
                assert item.size==r['bytes'] and item.mode==r['mode']
    with tarfile.open(output,'r:gz') as verify:
        for item in verify:
            with verify.extractfile(item) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest(package/item.name.split('/',1)[1])
    report={'version':VERSION,'edition':edition,'platform':platform,'archive':str(output),'sha256':digest(output),'bytes':output.stat().st_size,'previous_sha256':expected,'changed_members':updated,'payload_members':len(inventory),'dependency_pins_unchanged':True,'unmodified_payload_members_verified':True,'native_recipient_execution':False}
    (stage/'validation.json').write_bytes(encoded(report));(stage/'payload-inventory.json').write_bytes(encoded(inventory));print(json.dumps(report),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('repo','previous','stage'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--platform',choices=['Linux','Mac'],required=True)
    a=p.parse_args();build(a.repo,a.previous,a.stage,a.platform)
