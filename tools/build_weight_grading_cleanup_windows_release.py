"""Rebuild the Windows r67 suite from a verified r66 archive and reviewed source.

Only tracked/new ApplicationSources/Windows files and the explicit public
Runtime/Knowledge layer are read. No live accounts, configuration or outputs are
imported. Existing dependencies and edition policy remain those of the receiving archive.
All pre-existing runtime/model component pins remain unchanged. Adds the previously omitted optional NVIDIA runtime component from its separately reviewed manifest. Small reader/grader code is part of the application payload.
Run with --repo, --previous, --knowledge and a new --stage on the build host.
"""
import argparse,hashlib,json,shutil,stat,subprocess,sys,zipfile
from pathlib import Path

VERSION='2026.11.04-Desktop-r67'

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
        preferences=overlay['PortalAI/Agent/model_preferences.py'].read_text(encoding='utf-8')
        assert 'return enforce_policy(result)' in preferences and 'baseline = enforce_policy(baseline)' in preferences
        assert "return 'standard'" in preferences
        settings=overlay['PortalAI/ControlCenter/settings_page.py'].read_text(encoding='utf-8')
        assert 'from academic_policy import bind_help' in settings and 'Academic always uses standard vision companions' in settings
    for path in sorted(knowledge.rglob('*')):
        if '__pycache__' in path.parts or path.suffix=='.pyc':continue
        assert not path.is_symlink() and not (path.stat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT),str(path)
        if path.is_file():overlay['PortalAI/Runtime/Knowledge/'+path.relative_to(knowledge).as_posix()]=path
    rows=[];old_rows={r['member']:r for r in release['payload']['members']};changed=[];added=[]
    newpayload=stage/'payload-r67.zip'
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
            info=src.getinfo(name) if name in src.namelist() else zipfile.ZipInfo(name,(2026,11,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED
            dest.writestr(info,data)
    # Replace only the newly extracted build-stage payload; original archive is immutable.
    newpayload.replace(package/'payload.zip')
    release['payload'].update(bytes=(package/'payload.zip').stat().st_size,sha256=digest(package/'payload.zip'),members=rows)
    release['weight_space_editor']={'guide':'PortalAI Windows/Documentation/Weight_Space_Editor_r64.txt','minimum_free_gib':80,'production_models_changed':False,'native_backend':'Windows NVIDIA','input_format':'GGUF'}
    release['weight_edit_profiles']={'guide':'PortalAI Windows/Documentation/Weight_Edit_Profiles_r65.txt','prepared_copy_limit':2,'minimum_free_gib':80,'originals_preserved':True,'automatic_retry':False}
    release['distribution_version']=VERSION
    release['release']=f'PortalAI-{VERSION}-suite-{edition}-Windows'
    release['supersedes_release']=old
    prior_contract=release['upgrade']
    sidecar_contract=json.loads((package/'upgrade.json').read_text())
    assert prior_contract['edition']==sidecar_contract['edition']==edition
    assert prior_contract['platform']==sidecar_contract['platform']=='Windows'
    upgrade_contract={**prior_contract,**sidecar_contract,'version':VERSION}
    upgrade_contract['compatible_versions']=list(dict.fromkeys(prior_contract.get('compatible_versions',[])+sidecar_contract.get('compatible_versions',[])+[old]))
    legacy={json.dumps(row,sort_keys=True):row for row in prior_contract.get('legacy_fingerprints',[])+sidecar_contract.get('legacy_fingerprints',[])}
    upgrade_contract['legacy_fingerprints']=list(legacy.values())
    release['upgrade']=upgrade_contract
    release['suite']['parent_archive_sha256']=expected
    release['capability_intelligence']={'guide':'PortalAI Windows/Documentation/Capability_Intelligence_20261101.txt','features':6,'minimum_free_gib':80,'new_dependencies':False}
    release['portable_intelligence']={'guide':'PortalAI Windows/Documentation/Portable_Intelligence_r59.md','minimum_free_gib':80,'streamed_qwen_audio':True,'speaker_echo_cancellation':True,'new_model_weights':False,'new_runtime':False}
    release['portable_capabilities']={'guide':'PortalAI Windows/Documentation/Portable_Capabilities_r58.md','new_model_weights':False,'new_runtime':False,'bundled_browser_renderers':True}
    release['voice_onset']={'lead_ms':500,'tail_ms':350,'qwen_pitch_semitones':-.5,'same_stream':True,'pitch_output_samples_preserved':True,'new_dependencies':False}
    release['context_admission']={'guide':'PortalAI Windows/Documentation/Context_Admission_r56.md',
        'progressive_tool_loading':True,'max_loaded_optional_tools':4,'exact_parameter_schemas':True,
        'new_dependencies':False,'fresh_server_context_per_request':True,'unchanged_safety_reserves':True}
    assert json.dumps(release['components'],sort_keys=True)==old_components
    native_component=json.loads((repo/'InstallerSources/Windows/weight_space_cuda_component.json').read_text())
    assert native_component['id']=='windows-cuda-inference'
    assert not any(c['id']==native_component['id'] for c in release['components'])
    release['components'].append(native_component)
    assert json.dumps(release['components'][:-1],sort_keys=True)==old_components
    release['weight_space_editor']['installer_component']=native_component['id']
    release['weight_space_editor']['runtime_guide']='PortalAI Windows/Documentation/Weight_Space_Runtime_r67.txt'
    package_names={r['dest'].replace('\\','/') for c in release['components'] for a in c.get('artifacts',[]) for r in a['members']}
    for name in ('numpy','jinja2','sympy'):
        assert 'PortalAI Windows/Voice/Qwen3-TTS/.venv/Lib/site-packages/'+name+'/__init__.py' in package_names,name

    # Run the unchanged install engine planner: all optional components, receipts,
    # destination overlap checks and dependency closure must still be valid.
    sys.path.insert(0,str(repo/'InstallerSources/Windows'))
    import installer_core
    chosen,artifacts,files,need=installer_core.plan(release,[c['id'] for c in release['components']])
    installer_core.plan(release,[])
    write_json(package/'release.json',release)
    upgrade=dict(release['upgrade'])
    if old not in upgrade['compatible_versions']:upgrade['compatible_versions'].append(old)
    write_json(package/'upgrade.json',upgrade)
    plan=json.loads((package/'storage-plan.json').read_text());plan.update(release=release['release'],payload_bytes=sum(r['bytes'] for r in rows),payload_files=len(rows))
    c=native_component
    plan['components'].append({'id':c['id'],'label':c['label'],'required':False,'depends_on':c['depends_on'],
        'installed_bytes':sum(r['bytes'] for a in c['artifacts'] for r in a['members']),
        'files':sum(len(a['members']) for a in c['artifacts']),
        'downloads':[{'sha256':a['sha256'],'bytes':a['bytes']} for a in c['artifacts']]})
    assert {r['id'] for r in plan['components']}=={r['id'] for r in release['components']}
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
    start=package/'START_HERE.txt';start.write_bytes((start.read_text(encoding='utf-8').replace(old,VERSION)+'\nWindows r67: a worker cleanup failure halts evaluation instead of being scored as a wrong model answer. See Documentation/Weight_Grading_r67.txt.\n').encode())
    pins=[{'path':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(package.iterdir()) if p.name!='PACKAGE_SHA256.json']
    write_json(package/'PACKAGE_SHA256.json',pins)
    output=stage/f'PortalAI-{edition}-Windows-Installer-{VERSION}-suite.zip'
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
        for p in sorted(package.iterdir()):archive.write(p,p.name)
    Path(str(output)+'.sha256').write_bytes((digest(output)+'  '+output.name+'\n').encode())
    # Read every published byte back, including every application member.
    with zipfile.ZipFile(output) as archive:
        for row in pins:
            assert archive.getinfo(row['path']).file_size==row['bytes']
            with archive.open(row['path']) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
    with zipfile.ZipFile(package/'payload.zip') as archive:
        for row in rows:
            data=archive.read(row['member']);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
    report={'version':VERSION,'edition':edition,'archive':output.name,'bytes':output.stat().st_size,'sha256':digest(output),
      'previous_sha256':expected,'changed_members':changed,'added_members':added,'payload_members':len(rows),
      'existing_dependency_pins_unchanged':True,'new_dependencies':False,'new_runtime':False,'added_installer_component':'windows-cuda-inference','native_runtime_already_installed_on_D_E':True,'new_model_weights':False,'added_original_helper':'Tools/WeightSpace','all_components_plan':True,'minimum_components_plan':True,
      'all_archive_and_payload_hashes_verified':True,'native_storage_preflight_includes_component':True,'full_recipient_install':False,
      'storage':{'installed_bytes':sum(r['bytes'] for r in files),'download_bytes':sum({a['sha256']:a['bytes'] for a in artifacts}.values()),'required_bytes':need,'files':len(files)},
      'package_files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in sorted(package.iterdir())]}
    write_json(stage/'validation.json',report)
    print(json.dumps({k:report[k] for k in ('version','edition','archive','bytes','sha256','payload_members','all_components_plan')}),flush=True)
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();
    for name in ('repo','previous','knowledge','stage'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();build(a.repo.resolve(),a.previous.resolve(),a.knowledge.resolve(),a.stage.resolve())
