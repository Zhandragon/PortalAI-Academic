"""Build complete download bundles without changing native installers or optional selections.

Usage: python tools/build_welcome_bundles.py --inputs VERIFIED_INPUTS.json --output OUTPUT --edition Full
Inputs must name clean published archives and their independently verified SHA-256 digests.
"""
from pathlib import Path, PurePosixPath
import argparse, hashlib, io, json, os, shutil, stat, tarfile, zipfile

VERSION='2026.11.25-bundle4'
PLATFORMS=('Windows','Mac','Linux')
BASELINE='4637cebf54e6f748f3fae8d54300a94834b1043220c417d1894b2c1d1f040bf9'
WINDOWS_EXTRACTION_ROOT_BUDGET=120

def mac_development_file(relative):
    """Exclude PyObjC's test suite/debug symbols, never its runtime extensions."""
    parts=PurePosixPath(relative).parts
    if len(parts)<4 or parts[:2]!=('PortalAI-Projection','Runtime'):
        return False
    if parts[2] not in ('MacPackages-arm64','MacPackages-x86_64'):
        return False
    return parts[3]=='PyObjCTest' or any(p.endswith('.dSYM') for p in parts[3:])

def windows_path_report(names):
    """Reserve 120 UTF-16 characters for the destination, including the ZIP stem.

    This covers a normal Downloads path and the default Extract All folder.
    Check classic file and directory limits without requiring long-path support.
    """
    longest=0
    for name in names:
        units=len(name.replace('/','\\').encode('utf-16-le'))//2
        full=WINDOWS_EXTRACTION_ROOT_BUDGET+1+units
        parent=name.rpartition('/')[0]
        parent_units=len(parent.replace('/','\\').encode('utf-16-le'))//2
        if full>=260 or (parent and WINDOWS_EXTRACTION_ROOT_BUDGET+1+parent_units>247):
            raise ValueError('Bundle path exceeds the Windows extraction budget: '+name)
        longest=max(longest,units)
    return dict(max_relative_path_characters=longest,
        extraction_root_budget=WINDOWS_EXTRACTION_ROOT_BUDGET,
        max_full_path_characters=WINDOWS_EXTRACTION_ROOT_BUDGET+1+longest)
def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def entries(p):
    if str(p).endswith('.zip'):
        with zipfile.ZipFile(p) as z:
            for m in z.infolist():
                if not m.is_dir():
                    yield m.filename,z.read(m),(m.external_attr>>16)&0o777 or 0o644
    else:
        with tarfile.open(p,'r:gz') as t:
            for m in t:
                if m.isfile():yield m.name,t.extractfile(m).read(),m.mode
                elif not m.isdir():raise ValueError('Unexpected archive link: '+m.name)
def write_file(root,name,data,mode=0o644):
    parts=PurePosixPath(name)
    if parts.is_absolute() or '..' in parts.parts or '\\' in name or ':' in name:raise ValueError('Unsafe archive member')
    p=root/str(parts);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    return str(parts),mode
def stage_utilities(inputs,dest,include_abliterator):
    modes={}
    ha=dict((name.removeprefix('HomeAssistant/'),(data,mode)) for name,data,mode in entries(inputs['HomeAssistant']['path']))
    patch={name:(data,mode) for name,data,mode in entries(inputs['HostUpdate']['path'])}
    # The companion update archive has a single root directory.
    patch={name.split('app/',1)[1]:(data,mode) for name,(data,mode) in patch.items() if '/app/' in name or name.startswith('app/')}
    assert set(patch)=={'portalai_target.py','native_handoff.py'},set(patch)
    for platform in PLATFORMS:
        prefix=f'Utilities/{platform}/'
        baseline_seen=False
        for name,data,mode in entries(inputs['Projection/'+platform]['path']):
            if 'Utilities/' not in name:continue
            relative=name.split('Utilities/',1)[1]
            if relative.startswith('PortalAI HA Setup/Setup Files/HomeAssistant/'):continue
            if platform=='Mac' and mac_development_file(relative):continue
            if relative.endswith('PortalAI-Projection/app/portalai_target.py'):
                assert hashlib.sha256(data).hexdigest()==BASELINE,'Unreviewed Projection baseline'
                baseline_seen=True
                data,mode=patch['portalai_target.py']
            rel,mode=write_file(dest,prefix+relative,data,mode);modes[rel]=mode
        assert baseline_seen
        data,mode=patch['native_handoff.py']
        rel,mode=write_file(dest,prefix+'PortalAI-Projection/app/native_handoff.py',data,mode);modes[rel]=mode
        for relative,(data,mode) in ha.items():
            rel,mode=write_file(dest,prefix+'PortalAI HA Setup/Setup Files/HomeAssistant/'+relative,data,mode);modes[rel]=mode
        readme=('Optional Projection and Home Assistant 0.5.13\n\n'
            'These companions are included for convenience. Main setup does not run them.\n'
            'Open the Projection launcher only if you want remote access, select your\n'
            'installed PortalAI folder, and create your own connection and pairing.\n'
            'The matching host update is already applied to this clean companion.\n'
            'Use the PortalAI HA Setup launcher only to configure an existing HA instance.\n'
            'Keep PortalAI-Projection and PortalAI HA Setup beside each other.\n'
            'Linux/macOS native acceptance remains unverified. See START_HERE.txt.\n')
        rel,mode=write_file(dest,prefix+'README.txt',readme.encode());modes[rel]=mode
    if include_abliterator:
        for name,data,mode in entries(inputs['Abliterator/Windows']['path']):
            rel,mode=write_file(dest,'FullOnly/Portable Abliterator Setup/'+name,data,mode);modes[rel]=mode
    return modes
def start_here(edition,platforms):
    return f"""PortalAI {edition} — complete download bundle — {VERSION}

INCLUDED
Windows application: r85 (2026-11-22), when selected.
Mac/Linux applications: experimental r75 (2026-11-09), when selected.
Projection: platform companion with matching Home Assistant 0.5.13 host update.
Home Assistant receiver/frontend: 0.5.13 + Recovery 0.1.0.
Platforms in this bundle: {', '.join(platforms)}.

1. Extract the ENTIRE ZIP to a new folder on a suitable drive.
   Windows: NTFS. Mac: APFS. Linux: ext4 with execution enabled.
   Keep Packages, Utilities and the setup scripts together.
2. Windows: open Start Setup.cmd.
   Mac: open Start Setup.command, or run bash prepare-setup.sh.
   Linux: run bash prepare-setup.sh.
   Setup verifies the included native installers, then asks before opening
   the installer for this OS. It does not start the companion utilities.
   Windows setup suggests this drive's root. Use Browse, Drive root or the
   editable installation root field to choose where PortalAI is installed.
3. Choose your destination and desired components in the native installer.
   Models and selected runtime dependencies still need internet and disk space.
   Existing users: exit PortalAI normally and choose Update existing (Windows)
   or use the native --upgrade workflow (Mac/Linux).

OPTIONAL UTILITIES
All utility files for the included platforms are in Utilities/<OS>.
Nothing here is selected, installed into your existing application, configured,
paired or activated automatically. Select only the optional components you want.
You can leave all companion folders unused.

Projection: open Utilities/<OS>/PortalAI-Projection/Start Projection.cmd
(Windows), Start Projection.command (Mac), or Start Projection.sh (Linux).
Choose the installed PortalAI application folder when creating the connection.
Home Assistant: use the neighboring PortalAI HA Setup launcher only when wanted.
Both folders must stay together. You do not need a separate Projection download.
Selecting Projection during setup places both folders in Utilities beside the
installed application. You can also copy the two folders there for a NEW install.
Do not overwrite existing Connections or state when updating.
{"Portable Abliterator: Windows only, included in Windows/Universal bundles at Utilities/Windows/Portable Abliterator Setup. Extracted setup is optional; run Portable-Abliterator-Install.exe only if wanted. Its selected runtime dependencies still download during installation." if edition=="Full" else "Academic: Portable Abliterator and Full-only model assets are excluded."}
Windows reset and Weight-Space Editor entry points remain in the native app
payload where supported; use them from the installed application's Utilities.

CURRENT RELEASE
Bundle 4 recreates the drive layout from a ZIP extracted anywhere on the drive.
Windows Start Setup defaults to the drive root. Edit Installation root directory,
Browse, or Drive root before installing. Mac/Linux ask for an installation root.
Applications go in PortalAI Windows, PortalAI Mac or PortalAI Linux under that
root. Selected companions go beside them in Utilities, never under Platforms.
Existing application/companion folders are preserved; use Update existing for an
installed application. An unrelated Utilities/Installers folder is allowed.

All components selects every available model group and optional native utility.
Express remains lightweight. Models stay optional and download during setup;
the ZIP does not contain their weights. Full includes the 27B variants and source
weights, ACE-Step 4B, Whisper Turbo, FLUX 9B FP8 and the Abliterator example model.
Academic keeps its standard-model boundary. Mac/Linux offer the complete eligible
model catalog; native runtime support still varies. FLUX requires the recipient's
own publisher access and Hugging Face read token; no credentials are bundled.
Successful setup removes completed temporary model/runtime downloads. Interrupted
downloads are retained for retry. Full Windows with all components is about 431
GiB installed and requires additional temporary download and recovery space.

Native archives remain byte-for-byte intact. Verified setup overlays add the
destination controls and model catalogs without changing the r85/r75 app payloads.
The Windows extraction-path fix is retained. Only Windows has extensive runtime
testing; physical Mac/Linux installations and live inference were not rerun here.

VERIFICATION
bundle.json records the native package versions, sizes and hashes.
SHA256SUMS covers the contents of this bundle; verify with shasum -a 256 -c
SHA256SUMS (Mac) or sha256sum -c SHA256SUMS (Linux).
PowerShell: Get-FileHash -Algorithm SHA256 <downloaded ZIP>.
Compare the whole-download digest with the release's SHA256SUMS file.
prepare-setup.ps1 -VerifyOnly / bash prepare-setup.sh --verify-only checks
the included native archives without starting an installation.
-ExtractOnly / --extract-only prepares the native installer without launching it.

Documentation: https://github.com/Zhandragon/{"PortalAI" if edition=="Full" else "PortalAI-Academic"}/blob/main/Documentation/CURRENT-DOWNLOADS.md
"""
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--edition',choices=['Full','Academic'],required=True)
    args=parser.parse_args()
    repo=Path(__file__).resolve().parents[1]
    inputs={item['key']:item for item in json.loads(args.inputs.read_text())}
    required=[args.edition+'/'+p for p in PLATFORMS]+['Projection/'+p for p in PLATFORMS]+['HomeAssistant','HostUpdate','WindowsSetup']
    if args.edition=='Full':required.append('Abliterator/Windows')
    inputs={key:inputs[key] for key in required}
    for item in inputs.values():
        assert sha(item['path'])==item['sha256'],'Input changed: '+item['key']
    stage=args.output/'staged-utilities'
    stage.mkdir(parents=True,exist_ok=True)
    modes=stage_utilities(inputs,stage,args.edition=='Full')
    from complete_model_catalog import prepare,encoded
    model_overlay,model_catalog=prepare(repo,inputs[args.edition+'/Windows']['path'],args.edition)
    common_setup={'Setup/Models/model-catalog.json':encoded(model_catalog),
        'Setup/Models/complete_models.py':(repo/'InstallerSources/Models/complete_models.py').read_bytes()}
    for name in ('installer_core.py','installer_storage.py','model_choices.py','suite_installer.py'):
        common_setup['Setup/Models/Engine/'+name]=(repo/'InstallerSources/Windows'/name).read_bytes()
    for name,data in model_overlay.items():
        if name.startswith('ModelData/'):common_setup['Setup/Models/'+name]=data
    native_setup={};suite_catalogs={}
    with zipfile.ZipFile(inputs[args.edition+'/Windows']['path']) as archive:
        suite_catalogs['Windows']=archive.read('suite-catalog.json')
    for platform in ('Mac','Linux'):
        script='install-macos.sh' if platform=='Mac' else 'install.sh'
        with tarfile.open(inputs[args.edition+'/'+platform]['path'],'r:gz') as archive:
            names=archive.getnames()
            script_name=next(n for n in names if n.endswith('/'+script))
            sums_name=next(n for n in names if n.endswith('/SHA256SUMS'))
            original=archive.extractfile(script_name).read().decode()
            sums=archive.extractfile(sums_name).read().decode()
            suite_catalogs[platform]=archive.extractfile(next(n for n in names if n.endswith('/suite-catalog.json'))).read()
        old='"$PYTHON" -B "$ROOT/Tools/choose_optional_models.py"' if platform=='Mac' else '"$PYTHON" -B "$STAGE/PortalAI/Tools/choose_optional_models.py"'
        new='"$PYTHON" -B "$SELF_DIR/model-setup/complete_models.py" --root "$ROOT"' if platform=='Mac' else '"$PYTHON" -B "$SCRIPT_DIR/model-setup/complete_models.py" --root "$STAGE/PortalAI"'
        assert original.count(old)==1,'Unreviewed native model-chooser entry point'
        updated=original.replace(old,new)
        native_app_name='PortalAI '+('Academic ' if args.edition=='Academic' else '')+platform
        default_old='DEST="${1:-'+('$SELF_DIR' if platform=='Mac' else '$SCRIPT_DIR')+'/'+native_app_name+'}"'
        source_var='$SELF_DIR' if platform=='Mac' else '$SCRIPT_DIR'
        default_new=("PORTALAI_DRIVE_ROOT=$(LC_ALL=C df -Pk \""+source_var+"\" | awk 'NR==2 {for(i=1;i<=5;i++)sub(/^[[:space:]]*[^[:space:]]+[[:space:]]+/,\"\");print}')\n"
            +'[ -n "$PORTALAI_DRIVE_ROOT" ] || { echo "Cannot determine installation drive root." >&2; exit 2; }\n'
            +'DEST="${1:-${PORTALAI_DRIVE_ROOT%/}/PortalAI '+platform+'}"')
        assert updated.count(default_old)==1,'Unreviewed native default destination'
        updated=updated.replace(default_old,default_new)
        suite_old='"${STAGE}/PortalAI/Tools/suite_installer.py"' if platform=='Linux' else '"${ROOT}/Tools/suite_installer.py"'
        suite_new='"$SCRIPT_DIR/model-setup/Engine/suite_installer.py"' if platform=='Linux' else '"$SELF_DIR/model-setup/Engine/suite_installer.py"'
        assert updated.count(suite_old)==1,'Unreviewed native suite entry point'
        updated=updated.replace(suite_old,suite_new).encode()
        old_line=hashlib.sha256(original.encode()).hexdigest()+'  '+script
        assert sums.count(old_line)==1,'Native script checksum differs'
        sums=sums.replace(old_line,hashlib.sha256(updated).hexdigest()+'  '+script)
        native_setup[platform]={script:updated,'SHA256SUMS':sums.encode()}
    local_suites={}
    for platform in PLATFORMS:
        projection=[];abliterator=[]
        for rel in sorted(modes):
            if rel.startswith('Utilities/'+platform+'/'):
                tail=rel.split('/',2)[2]
                if not tail.startswith(('PortalAI-Projection/','PortalAI HA Setup/')):continue
                row=dict(source_file=rel,file='SuiteAssets/projection/Utilities/'+tail,dest='Utilities/'+tail)
                source=stage/rel;projection.append(row)
            elif platform=='Windows' and rel.startswith('FullOnly/Portable Abliterator Setup/'):
                tail=rel.removeprefix('FullOnly/Portable Abliterator Setup/')
                row=dict(source_file='Utilities/Windows/Portable Abliterator Setup/'+tail,file='SuiteAssets/abliterator/'+tail,dest=tail)
                source=stage/rel;abliterator.append(row)
            else:continue
            row.update(bytes=source.stat().st_size,sha256=sha(source))
        local_assets=[dict(id='projection-'+platform.lower(),platform=platform,files=projection)]
        if abliterator:local_assets.append(dict(id='abliterator-windows',platform='Windows',files=abliterator,additional_download_bytes=3103192679))
        local_json=encoded(dict(schema=1,base_catalog_sha256=hashlib.sha256(suite_catalogs[platform]).hexdigest(),assets=local_assets))
        tsv=''.join(f"{r['source_file']}\t{r['file']}\t{r['bytes']}\t{r['sha256']}\n" for a in local_assets for r in a['files']).encode()
        local_suites[platform]={'suite-local.json':local_json,'suite-copy.tsv':tsv}
        if platform in native_setup:
            extra={name.removeprefix('Setup/Models/'):data for name,data in common_setup.items()}
            sums=native_setup[platform]['SHA256SUMS'].decode().rstrip('\n')+'\n'
            sums+=''.join(hashlib.sha256(data).hexdigest()+'  model-setup/'+name+'\n' for name,data in sorted(extra.items()))
            sums+=hashlib.sha256(local_json).hexdigest()+'  suite-local.json\n'
            sums+=''.join(r['sha256']+'  '+r['file']+'\n' for a in local_assets for r in a['files'])
            native_setup[platform]['SHA256SUMS']=sums.encode()
    outputs=[]
    for selection in ['Windows','Mac','Linux','Universal']:
        platforms=PLATFORMS if selection=='Universal' else (selection,)
        name=f'PortalAI-{args.edition}-{selection}-Bundle-{VERSION}.zip'
        target=args.output/name
        if target.exists():raise FileExistsError(target)
        assets=[]
        for platform in platforms:
            item=inputs[args.edition+'/'+platform]
            p=Path(item['path'])
            assets.append(dict(platform=platform,file=p.name,bytes=p.stat().st_size,sha256=item['sha256'],
                version='2026.11.22-Desktop-r85' if platform=='Windows' else '2026.11.09-Desktop-r75',
                url=item['asset']['browser_download_url']))
        win=inputs[args.edition+'/Windows']['path']
        with zipfile.ZipFile(win) as z:
            exe=next(n for n in z.namelist() if n.endswith('-Install.exe') and '/' not in n)
        manifest=dict(schema=1,version=VERSION,edition=args.edition,platforms=platforms,assets=assets,
            windows_installer=exe,utilities_optional=True,home_assistant='0.5.13',
            projection_host_update='0.5.13',abliterator_included=args.edition=='Full' and 'Windows' in platforms)
        setup_files=dict(common_setup)
        for platform in platforms:
            files={**(model_overlay if platform=='Windows' else native_setup[platform]),**local_suites[platform]}
            for name,data in files.items():setup_files['Setup/'+platform+'/'+name]=data
        manifest['model_catalog_version']=model_catalog['version']
        manifest['setup_files']=[dict(file=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest()) for name,data in sorted(setup_files.items())]
        if 'Windows' in platforms:
            setup=Path(inputs['WindowsSetup']['path'])
            manifest['windows_launcher']=dict(file='Setup/PortalAI-Setup.exe',bytes=setup.stat().st_size,sha256=inputs['WindowsSetup']['sha256'])
        hashes={}
        def put(z,rel,data,mode=0o644,compression=zipfile.ZIP_DEFLATED):
            zi=zipfile.ZipInfo(rel,(2026,11,25,0,0,0))
            zi.create_system=3;zi.external_attr=(stat.S_IFREG|mode)<<16;zi.compress_type=compression
            z.writestr(zi,data,compresslevel=5)
            hashes[rel]=hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(target,'x',allowZip64=True) as z:
            for name,data in sorted(setup_files.items()):put(z,name,data)
            put(z,'setup.tsv',''.join(f"{r['file']}\t{r['bytes']}\t{r['sha256']}\n" for r in manifest['setup_files']).encode())
            if 'Windows' in platforms:put(z,manifest['windows_launcher']['file'],setup.read_bytes())
            for platform,a in zip(platforms,assets):
                source=Path(inputs[args.edition+'/'+platform]['path'])
                rel='Packages/'+a['file']
                # Already-compressed archives stay byte-for-byte intact.
                z.write(source,rel,compress_type=zipfile.ZIP_STORED)
                hashes[rel]=a['sha256']
            for rel,mode in sorted(modes.items()):
                if rel.startswith('FullOnly/'):
                    if not manifest['abliterator_included']:continue
                    dest='Utilities/Windows/'+rel.removeprefix('FullOnly/')
                else:
                    if rel.split('/')[1] not in platforms:continue
                    dest=rel
                put(z,dest,(stage/rel).read_bytes(),mode)
            # WindowsPath sorts case-insensitively; use that explicit order on every build host.
            for source in sorted((repo/'InstallerSources/Bundle').iterdir(),key=lambda p:p.name.casefold()):
                if source.is_file():
                    put(z,source.name,source.read_bytes(),0o755 if source.suffix in ('.sh','.command') else 0o644)
            put(z,'bundle.json',(json.dumps(manifest,indent=2)+'\n').encode())
            put(z,'assets.tsv',''.join(f"{a['platform']}\t{a['file']}\t{a['bytes']}\t{a['sha256']}\t{a['url']}\n" for a in assets).encode())
            put(z,'START_HERE.txt',start_here(args.edition,platforms).encode())
            windows_path_report([*hashes,'BUNDLE-CONTENTS.json','SHA256SUMS'])
            put(z,'BUNDLE-CONTENTS.json',(json.dumps(dict(version=VERSION,files=hashes.copy()),indent=2)+'\n').encode())
            put(z,'SHA256SUMS',''.join(f'{value}  {key}\n' for key,value in sorted(hashes.items())).encode())
        assert target.stat().st_size<2_000_000_000,'Split-free GitHub bundle exceeds 2 GB'
        checksum=sha(target)
        name=target.name
        outputs.append(dict(edition=args.edition,platform=selection,name=name,path=str(target),bytes=target.stat().st_size,sha256=checksum,manifest=manifest))
        print(f'Built {name}: {target.stat().st_size:,} bytes',flush=True)
    (args.output/'bundle-build.json').write_text(json.dumps(outputs,indent=2)+'\n')
    print('Completed four bundles; native archives retained and complete optional catalogs added.',flush=True)
if __name__=='__main__':main()

