"""Rebuild the Windows r55 suite from a verified r54 archive and reviewed source.

Only tracked/new ApplicationSources/Windows files and the explicit public
Runtime/Knowledge layer are read. No live accounts, configuration or outputs are
imported. Existing dependencies and edition policy remain those of the receiving archive.
The pinned CC0 English male voice is appended to the existing Piper component.
Run with --repo, --previous, --knowledge and a new --stage on the build host.
"""
import argparse,hashlib,json,shutil,stat,subprocess,sys,zipfile
from pathlib import Path

VERSION='2026.10.31-Desktop-r55'

def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def write_json(path,data):path.write_bytes((json.dumps(data,indent=2,ensure_ascii=True)+'\n').encode())

def build(repo,previous,knowledge,stage):
    expected=Path(str(previous)+'.sha256').read_text().split()[0].lower()
    assert digest(previous)==expected,'Previous suite checksum differs'
    stage.mkdir(parents=True,exist_ok=False)
    package=stage/'package';package.mkdir()
    with zipfile.ZipFile(previous) as archive:
        for info in archive.infolist():
            assert '/' not in info.filename and '\\' not in info.filename,info.filename
            with archive.open(info) as src,(package/info.filename).open('xb') as dest:shutil.copyfileobj(src,dest,1024**2)
    for row in json.loads((package/'PACKAGE_SHA256.json').read_text()):
        p=package/row['path'];assert p.stat().st_size==row['bytes'] and digest(p)==row['sha256'],str(p)
    release=json.loads((package/'release.json').read_text())
    old=release['distribution_version'];edition='Academic' if release['edition']=='Academic' else 'Full'
    old_components=json.dumps(release['components'],sort_keys=True)
    assert digest(package/'payload.zip')==release['payload']['sha256']
    sources=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard','--','ApplicationSources/Windows'],cwd=repo).decode().split('\0')
    overlay={name.removeprefix('ApplicationSources/Windows/'):(repo/name) for name in filter(None,sources)}
    assert all('/Private/' not in n and '/Data/' not in n and not n.endswith('/AGENTS.md') for n in overlay)
    assert VERSION in overlay['PortalAI/ControlCenter/release_version.py'].read_text()
    if edition=='Academic':
        assert 'pieces.append(instruction_suffix(self.root))' in overlay['PortalAI/ControlCenter/native_chat.py'].read_text(encoding='utf-8')
        assert "TOPICS['academic']" in overlay['PortalAI/ControlCenter/help_catalog.py'].read_text(encoding='utf-8')
    for path in sorted(knowledge.rglob('*')):
        if '__pycache__' in path.parts or path.suffix=='.pyc':continue
        assert not path.is_symlink() and not (path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT),str(path)
        if path.is_file():overlay['PortalAI/Runtime/Knowledge/'+path.relative_to(knowledge).as_posix()]=path
    rows=[];old_rows={r['member']:r for r in release['payload']['members']};changed=[];added=[]
    newpayload=stage/'payload-r55.zip'
    with zipfile.ZipFile(package/'payload.zip') as src,zipfile.ZipFile(newpayload,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as dest:
        assert len(src.namelist())==len(set(src.namelist()))
        for name in sorted(set(src.namelist())|set(overlay)):
            if name.endswith('/'):continue
            if name in overlay:data=overlay[name].read_bytes()
            else:data=src.read(name)
            sha=hashlib.sha256(data).hexdigest()
            if name in old_rows:
                row=dict(old_rows[name]);
                if sha!=row['sha256']:changed.append(name)
            else:
                added.append(name)
                row={'member':name,'dest':name.replace('PortalAI/','PortalAI Windows/',1) if name.startswith('PortalAI/') else name}
            row.update(bytes=len(data),sha256=sha);rows.append(row)
            info=src.getinfo(name) if name in src.namelist() else zipfile.ZipInfo(name,(2026,10,30,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            dest.writestr(info,data)
    # Replace only the newly extracted build-stage payload; original archive is immutable.
    newpayload.replace(package/'payload.zip')
    release['payload'].update(bytes=(package/'payload.zip').stat().st_size,sha256=digest(package/'payload.zip'),members=rows)
    release['distribution_version']=VERSION
    release['release']=f'PortalAI-{VERSION}-suite-{edition}-Windows'
    release['supersedes_release']=old
    release['suite']['parent_archive_sha256']=expected
    release['voice_memory']={'guide':'PortalAI Windows/Documentation/Voice_Memory_r55.md','bounded_admission_retry':True,'unchanged_memory_reserves':True,'automatic_and_manual_voice_models':True,'independent_tts_override':True}
    release['portable_tasks']={'guide':'PortalAI Windows/Documentation/Portable_Tasks_r55.md','bounded_file_inspection':True,'streaming_text_pages':True,'extra_dependencies':False}
    release['history_delete']={'guide':'PortalAI Windows/Documentation/History_Delete_r54.md','selected_batch_preview':True}
    release['listener_ownership']={'guide':'PortalAI Windows/Documentation/Listener_Ownership_r53.md','native_windows_tcp_owner_table':True,'port_alone_grants_ownership':False}
    assert json.dumps(release['components'],sort_keys=True)==old_components
    voice_lock=json.loads((repo/'ApplicationSources/Windows/PortalAI/Agent/voice_assets.json').read_text())
    male_assets=[a for a in voice_lock['assets'] if a['id'].startswith('piper-nice-voice-')]
    assert len(male_assets)==3
    component=next(c for c in release['components'] if c['id']=='piper-voice')
    original_artifacts=list(component['artifacts'])
    for a in male_assets:
        component['artifacts'].append({'id':a['id'],'url':a['url'],'bytes':a['size'],'sha256':a['sha256'],
            'format':'file','members':[{'member':'','dest':'PortalAI Windows/'+a['dest'],'bytes':a['size'],'sha256':a['sha256']}]})
    assert component['artifacts'][:-3]==original_artifacts
    release['voice_memory']['nice_voice']={'primary':'qwen3-tts-custom','speaker':'Ryan','instructions_source':'Agent/nice_voice.py','fallback':'en_US-joe-medium','fallback_pitch_semitones':2,'fallback_license':'CC0','asset_pins':male_assets}

    # Run the unchanged install engine planner: all optional components, receipts,
    # destination overlap checks and dependency closure must still be valid.
    sys.path.insert(0,str(repo/'InstallerSources/Windows'))
    import installer_core
    chosen,artifacts,files,need=installer_core.plan(release,[c['id'] for c in release['components']])
    installer_core.plan(release,[])
    write_json(package/'release.json',release)
    upgrade=json.loads((package/'upgrade.json').read_text());upgrade['version']=VERSION
    if old not in upgrade['compatible_versions']:upgrade['compatible_versions'].append(old)
    write_json(package/'upgrade.json',upgrade)
    plan=json.loads((package/'storage-plan.json').read_text());plan.update(release=release['release'],payload_bytes=sum(r['bytes'] for r in rows),payload_files=len(rows))
    write_json(package/'storage-plan.json',plan)
    catalog=json.loads((package/'suite-catalog.json').read_text(encoding='utf-8'))
    catalog['catalog_version']=VERSION
    for row in catalog['assets']:
        if row.get('kind')=='installer' and row.get('platform')=='Windows':
            row['file']=row['file'].replace(old,VERSION)
            row['tag']='v'+VERSION
            row['url']=f"https://github.com/{row['repository']}/releases/download/v{VERSION}/{row['file']}"
            # Resolve final hashes from the matching sidecar or GitHub digest;
            # an archive cannot embed its own final checksum.
            row['resolve_release']=True
    write_json(package/'suite-catalog.json',catalog)
    start=package/'START_HERE.txt';start.write_bytes((start.read_text(encoding='utf-8').replace(old,VERSION)+'\nWindows r55: hands-free voice memory handoff and audio-reactive PortalAI visualizer. See Documentation/Voice_Memory_r55.md.\n').encode())
    pins=[{'path':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(package.iterdir()) if p.name!='PACKAGE_SHA256.json']
    write_json(package/'PACKAGE_SHA256.json',pins)
    output=stage/f'PortalAI-{edition}-Windows-Installer-{VERSION}-suite.zip'
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in sorted(package.iterdir()):archive.write(p,p.name)
    Path(str(output)+'.sha256').write_bytes((digest(output)+'  '+output.name+'\n').encode())
    # Read every published byte back, including every application member.
    with zipfile.ZipFile(output) as archive:
        for row in pins:
            data=archive.read(row['path']);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
    with zipfile.ZipFile(package/'payload.zip') as archive:
        for row in rows:
            data=archive.read(row['member']);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
    report={'version':VERSION,'edition':edition,'archive':output.name,'bytes':output.stat().st_size,'sha256':digest(output),
      'previous_sha256':expected,'changed_members':changed,'added_members':added,'payload_members':len(rows),
      'existing_dependency_pins_unchanged':True,'added_nice_voice_assets':male_assets,'all_components_plan':True,'minimum_components_plan':True,
      'all_archive_and_payload_hashes_verified':True,'full_recipient_install':False,
      'storage':{'installed_bytes':sum(r['bytes'] for r in files),'download_bytes':sum({a['sha256']:a['bytes'] for a in artifacts}.values()),'required_bytes':need,'files':len(files)},
      'package_files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(package.iterdir())]}
    write_json(stage/'validation.json',report)
    print(json.dumps({k:report[k] for k in ('version','edition','archive','bytes','sha256','payload_members','all_components_plan')}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();
    for name in ('repo','previous','knowledge','stage'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();build(a.repo.resolve(),a.previous.resolve(),a.knowledge.resolve(),a.stage.resolve())
