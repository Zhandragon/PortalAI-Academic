"""Build a local r76 Windows package from a verified r75 archive; never installs.

Only the launcher, tour, version and guide change in paid payloads. Model pins,
licence review and published suite download URLs are retained. --trial applies
the existing separate trial overlay and paid-install overwrite guard.
"""
import argparse, hashlib, importlib.util, json, shutil, sys, tempfile, zipfile
from pathlib import Path
VERSION='2026.11.11-Desktop-r76'
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,value):p.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def build(repo,previous,stage,bootstrap,trial=False):
    expected=Path(str(previous)+'.sha256').read_text().split()[0]
    assert sha(previous)==expected,'Previous archive checksum differs'
    stage.mkdir(parents=True,exist_ok=False);package=stage/'package';package.mkdir()
    with zipfile.ZipFile(previous) as z:
        for item in z.infolist():
            assert '/' not in item.filename and '\\' not in item.filename
            with z.open(item) as src,(package/item.filename).open('xb') as out:shutil.copyfileobj(src,out,1024**2)
    for row in json.loads((package/'PACKAGE_SHA256.json').read_text()):
        p=package/row['path'];assert p.stat().st_size==row['bytes'] and sha(p)==row['sha256']
    release=json.loads((package/'release.json').read_text());old=release['distribution_version'];edition=release['upgrade']['edition']
    assert not trial or edition=='Full'
    original_components=json.dumps(release['components'],sort_keys=True)
    assert sha(package/'payload.zip')==release['payload']['sha256']
    app=repo/'ApplicationSources/Windows/PortalAI'
    overlay={name:(app/name).read_bytes() for name in ('ControlCenter/PortableAI_GUI.py','ControlCenter/app_tour.py','ControlCenter/release_version.py','Documentation/Onboarding_r76.txt')}
    assert VERSION.encode() in overlay['ControlCenter/release_version.py']
    native=repo/'InstallerSources/Windows'
    if trial:
        trial_builder=module('onboarding_trial',repo/'TrialSources/build_overlay.py');overlay.update(trial_builder.sources('Windows'))
        native_copy=stage/'trial-installer-source';native_copy.mkdir()
        for p in native.iterdir():
            if p.suffix in ('.py','.cs'):shutil.copy2(p,native_copy/p.name)
        p=native_copy/'portable_update.py';p.write_text(trial_builder.guarded_updater(p.read_text()),encoding='utf-8')
        p=native_copy/'Installer.cs';text=p.read_text(encoding='utf-8')
        text=trial_builder.replace(text,'Text="PortalAI suite installer"','Text="PortalAI Full trial installer"')
        text=trial_builder.replace(text,'title.Text="PortalAI "+primaryEdition;','title.Text="PortalAI Full — 3-day trial";')
        p.write_text(text,encoding='utf-8');native=native_copy
        release['trial']={'duration_hours':72,'starts':'first-app-launch','retained_per_os_user':True,'purchase_url':'https://payhip.com/b/Kw54p'}
    rows=[];old_rows={r['member']:r for r in release['payload']['members']};replacement=stage/'payload-r76.zip'
    with zipfile.ZipFile(package/'payload.zip') as src,zipfile.ZipFile(replacement,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as dest:
        for name in sorted(set(src.namelist())|{'PortalAI/'+n for n in overlay}):
            if name.endswith('/'):continue
            relative=name.removeprefix('PortalAI/');data=overlay[relative] if relative in overlay else src.read(name)
            row=dict(old_rows.get(name,{'member':name,'dest':name.replace('PortalAI/','PortalAI Windows/',1)}))
            row.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest());rows.append(row);dest.writestr(name,data)
    replacement.replace(package/'payload.zip')
    release['payload'].update(bytes=(package/'payload.zip').stat().st_size,sha256=sha(package/'payload.zip'),members=rows)
    release.update(distribution_version=VERSION,release='PortalAI-'+VERSION+'-suite-'+edition+('-Trial' if trial else '')+'-Windows',supersedes_release=old)
    upgrade={**release['upgrade'],**json.loads((package/'upgrade.json').read_text())};upgrade['version']=VERSION
    upgrade['compatible_versions']=list(dict.fromkeys(upgrade.get('compatible_versions',[])+[old]));release['upgrade']=upgrade
    release['onboarding']={'guide':'PortalAI Windows/Documentation/Onboarding_r76.txt','optional_survey':True,'bundles':['Lightweight','Full'],'optional_tour':True,'new_dependencies':False}
    assert json.dumps(release['components'],sort_keys=True)==original_components
    sys.path.insert(0,str(repo/'InstallerSources/Windows'));import installer_core
    installer_core.plan(release,[]);installer_core.plan(release,[c['id'] for c in release['components']])
    dump(package/'release.json',release);dump(package/'upgrade.json',upgrade)
    plan=json.loads((package/'storage-plan.json').read_text());plan.update(release=release['release'],payload_bytes=sum(r['bytes'] for r in rows),payload_files=len(rows));dump(package/'storage-plan.json',plan)
    executable=next(package.glob('PortalAI*Install*.exe'));built=stage/'installer-r76.exe';module('onboarding_native',native/'build.py').build(bootstrap,built);built.replace(executable)
    start=package/'START_HERE.txt';start.write_text(start.read_text(encoding='utf-8').replace(old,VERSION)+'\n'+(app/'Documentation/Onboarding_r76.txt').read_text(encoding='utf-8')+('\nFREE FULL TRIAL: 72 hours from first application launch. Choose a new empty folder; this trial cannot replace a paid installation.\n' if trial else ''),encoding='utf-8')
    pins=[{'path':p.name,'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(package.iterdir()) if p.name!='PACKAGE_SHA256.json'];dump(package/'PACKAGE_SHA256.json',pins)
    output=stage/f'PortalAI-{edition}{"-Trial" if trial else ""}-Windows-Installer-{VERSION}.zip'
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(package.iterdir()):z.write(p,p.name)
    Path(str(output)+'.sha256').write_text(sha(output)+'  '+output.name+'\n')
    with zipfile.ZipFile(output) as z:
        for row in pins:
            assert z.getinfo(row['path']).file_size==row['bytes']
            with z.open(row['path']) as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
    with zipfile.ZipFile(package/'payload.zip') as z:
        for row in rows:
            data=z.read(row['member']);assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
    report={'version':VERSION,'edition':edition,'trial':trial,'published':False,'archive':str(output),'sha256':sha(output),'payload_files':len(rows),'changed_source_files':sorted(overlay),'component_pins_unchanged':True,'archive_and_payload_verified':True,'minimum_and_full_install_plans_passed':True,'recipient_install_tested':False}
    dump(stage/'validation.json',report);print(json.dumps(report),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('repo','previous','stage','bootstrap'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--trial',action='store_true');a=p.parse_args();build(a.repo,a.previous,a.stage,a.bootstrap,a.trial)
