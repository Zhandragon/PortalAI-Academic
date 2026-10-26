"""Version-aware public-file updates with readback, recovery, and account fences.

Plans never mutate the installation. Apply requires a normally closed installation.
No private formats, accounts, keys, preferences, or existing optional assets migrate.
"""
from __future__ import annotations
import argparse, ast, contextlib, hashlib, json, os, re, shutil, stat, sys, uuid
from pathlib import Path, PurePosixPath

class UpdateError(RuntimeError): pass

PROTECTED=('Private','Data','Outputs','User Folder','Cache','PortableCache','Logs','Backups','Benchmarks','Patch/Videos',
 'Maintenance/Reports','Maintenance/Archive','Maintenance/Endurance','Maintenance/Repair',
 'MusicUnderstanding/cache/demucs',
 'Agent/.runtime','HomeAssistant/state','HomeAssistant/Connections',
 'Generative/ComfyUI_windows_portable/ComfyUI/input',
 'Generative/ComfyUI_windows_portable/ComfyUI/output',
 'Generative/ComfyUI_windows_portable/ComfyUI/temp',
 'Generative/ComfyUI_windows_portable/ComfyUI/user',
 'OpenWebUI/data','OpenWebUI/.runtime','Music/ACE-Step-1.5/.cache',
 'Music/ACE-Step-1.5/gradio_outputs','Maintenance/Updates')
PREFERENCES={'Agent/config.json','Agent/hardware_profiles.json','Agent/instance-settings.json',
 'Agent/model_policy.json','Agent/media_policy.json'}
STAMP='ControlCenter/release_version.py'
BOOT='ControlCenter/control_center_bootstrap.py'
RECEIPT='Maintenance/Imports/distribution-version.json'
PENDING='Maintenance/Updates/PENDING.json'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def relative(value):
    if not isinstance(value,str) or not value or '\\' in value:raise UpdateError('Invalid path')
    parts=value.split('/')
    reserved={'CON','PRN','AUX','NUL'}|{p+str(i) for p in ('COM','LPT') for i in range(1,10)}
    if any(p in ('','.','..') or p.endswith((' ','.')) or p.split('.')[0].upper() in reserved
           or any(ord(c)<32 or c in ':*?"<>|' for c in p) for p in parts):raise UpdateError('Unsafe path: '+value)
    return parts

def path(root,name):
    root=Path(root).absolute();p=root.joinpath(*relative(name))
    for q in [*reversed(root.parents),root,*[root.joinpath(*relative(name)[:i]) for i in range(1,len(relative(name))+1)]]:
        if q.exists() or q.is_symlink():
            s=q.lstat()
            if stat.S_ISLNK(s.st_mode) or getattr(s,'st_file_attributes',0)&1024 or (stat.S_ISREG(s.st_mode) and s.st_nlink!=1):
                raise UpdateError('Linked update path refused: '+str(q))
    if not p.resolve().is_relative_to(root.resolve()):raise UpdateError('Path escapes root')
    return p

def public(name):
    relative(name);low=name.casefold()
    if any(low==p.casefold() or low.startswith(p.casefold()+'/') for p in PROTECTED):raise UpdateError('Protected path: '+name)
    if any(x.casefold() in ('.git','__pycache__','.runtime','connections','state') for x in name.split('/')):
        raise UpdateError('Live state or cache path: '+name)
    if name.endswith(('.log','.lock','.pyc')):raise UpdateError('Live state or cache file: '+name)
    return name

def read_json(p):
    def unique(pairs):
        out={}
        for k,v in pairs:
            if k in out:raise UpdateError('Duplicate JSON key')
            out[k]=v
        return out
    return json.loads(p.read_text(encoding='utf-8-sig'),object_pairs_hook=unique)

def atomic(p,data):
    p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_name(p.name+'.tmp-'+uuid.uuid4().hex)
    with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(temp,p)

def write_json(p,value):atomic(p,(json.dumps(value,indent=2)+'\n').encode())

def copy_atomic(source,p,expected,mode):
    p.parent.mkdir(parents=True,exist_ok=True);temp=p.with_name(p.name+'.tmp-'+uuid.uuid4().hex)
    with source.open('rb') as inp,temp.open('xb') as out:
        shutil.copyfileobj(inp,out,1024*1024);out.flush();os.fsync(out.fileno())
    if sha(temp)!=expected:raise UpdateError('Staged copy checksum failed')
    os.chmod(temp,mode);os.replace(temp,p)

def merge_executable_recovery(source,target):
    """Keep recovery pins for unselected assets while replacing updated pins."""
    name='Maintenance/ExecutableRecovery/manifest.json';new=path(source,name);old=path(target,name)
    if not new.exists():return
    merged={}
    for p in (old,new):
        if not p.exists():continue
        data=read_json(p)
        if data.get('version')!=1 or not isinstance(data.get('files'),list):raise UpdateError('Invalid executable recovery index')
        for row in data['files']:
            public(row['path'])
            if not re.fullmatch('[a-f0-9]{64}',row.get('sha256','')) or type(row.get('bytes')) is not int:raise UpdateError('Invalid executable recovery pin')
            merged[row['path']]=row
    write_json(new,{'version':1,'files':sorted(merged.values(),key=lambda r:r['path'])})

def version(root):
    p=path(root,STAMP)
    if p.exists():
        if p.stat().st_size>32768:raise UpdateError('Oversized release stamp')
        tree=ast.parse(p.read_text(encoding='utf-8-sig'))
        values=[ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='RELEASE_VERSION' for t in n.targets)]
        if len(values)!=1 or not isinstance(values[0],str):raise UpdateError('Invalid release stamp')
        return values[0]
    return None

def parsed(value):
    m=re.fullmatch(r'(\d{4})\.(\d{2})\.(\d{2})-(?:(\w+)-)?r(\d+)',value or '')
    if not m:return None
    return (tuple(map(int,m.group(1,2,3))),m.group(4) or 'upstream',int(m.group(5)))

def compatibility(root,manifest):
    old=version(root);new=manifest['version'];a,b=parsed(old),parsed(new)
    if not b:raise UpdateError('Unrecognized destination version')
    if old==new:return old,'repair'
    if a:
        if a[0]>b[0] or (a[1]==b[1] and a[2]>b[2]):raise UpdateError('Downgrade refused: '+old+' -> '+new)
        if a[0]==b[0] and a[1]!=b[1] and old not in manifest.get('compatible_versions',[]):
            raise UpdateError('Different release streams need a reviewed compatibility entry: '+old)
        if a[0]<(2026,10,10):raise UpdateError('This legacy release needs a reviewed account migration before updating')
        return old,'upgrade'
    # Pre-stamp releases are supported only by exact, released public fingerprints.
    for item in manifest.get('legacy_fingerprints',[]):
        if item.get('files') and all(path(root,n).is_file() and sha(path(root,n))==h for n,h in item['files'].items()):
            return item['version'],'legacy-upgrade'
    raise UpdateError('Unidentified legacy installation. A public-file compatibility review is required; no files changed.')

def validate_manifest(manifest):
    if manifest.get('schema')!=1 or manifest.get('kind')!='portalai-public-update':raise UpdateError('Unsupported update manifest')
    seen=set()
    for row in manifest['files']:
        name=public(row['path']);key=name.casefold()
        if key in seen:raise UpdateError('Duplicate destination')
        seen.add(key)
        if type(row.get('bytes')) is not int or row['bytes']<0 or not re.fullmatch('[a-f0-9]{64}',row.get('sha256','')):raise UpdateError('Missing file pin')
        if type(row.get('mode',420)) is not int or row.get('mode',420)&~0o777:raise UpdateError('Invalid mode')
    if any('/'.join(name.split('/')[:i]).casefold() in seen for name in seen for i in range(1,len(name.split('/')))):raise UpdateError('File/directory collision')
    if STAMP.casefold() not in seen:raise UpdateError('Release stamp missing')

def plan(source,target,manifest):
    path(source,'Agent');path(target,'Agent')
    source=Path(source).resolve();target=Path(target).resolve();validate_manifest(manifest)
    if source==target or source.is_relative_to(target) or target.is_relative_to(source):raise UpdateError('Staging must be outside the installation')
    if not path(target,'Agent/profile_workspace.py').is_file() or not path(target,BOOT).is_file():
        raise UpdateError('Choose an existing account-capable PortalAI application folder')
    if path(target,PENDING).exists():raise UpdateError('An interrupted update needs recovery first')
    old,action=compatibility(target,manifest)
    known=path(target,RECEIPT)
    if known.exists():
        receipt=read_json(known)
        if receipt.get('version') and receipt['version']!=old:raise UpdateError('Release stamp and installed receipt disagree')
        for key in ('edition','platform'):
            if receipt.get(key) and receipt[key]!=manifest.get(key):raise UpdateError('Edition/platform change refused: '+key)
    # Pre-receipt Academic installs have an explicit marker in their public manual.
    master=path(target,'PortableAI_Master_Instructions_v45.txt')
    academic=master.exists() and 'PORTALAI ACADEMIC INSTRUCTIONS' in master.read_text(encoding='utf-8-sig')[:10000]
    if academic!=(manifest.get('edition')=='Academic'):raise UpdateError('Edition change refused')
    rows=[];backup_bytes=0;install_bytes=0
    for item in manifest['files']:
        name=item['path'];s=path(source,name);t=path(target,name)
        if not s.is_file() or s.stat().st_size!=item['bytes'] or sha(s)!=item['sha256']:raise UpdateError('Payload checksum failed: '+name)
        if t.exists() and not t.is_file():raise UpdateError('Destination is not a file: '+name)
        current=sha(t) if t.exists() else None
        status='unchanged' if current==item['sha256'] else 'replace' if current else 'add'
        if t.exists() and (name in PREFERENCES or name.endswith(('.ini','.cfg'))):status='preserve-setting'
        if 'expected_before' in item and current not in item['expected_before'] and current!=item['sha256']:
            raise UpdateError('Source differs from reviewed baseline: '+name)
        if status=='replace':backup_bytes+=t.stat().st_size
        if status in ('replace','add'):install_bytes+=item['bytes']
        rows.append({**item,'before':current,'status':status,'before_mode':stat.S_IMODE(t.stat().st_mode) if t.exists() else None})
    stamp_row=next(r for r in rows if r['path']==STAMP)
    if version(source)!=manifest['version'] or stamp_row['status']=='preserve-setting':raise UpdateError('Payload version mismatch')
    return {'schema':1,'from_version':old,'to_version':manifest['version'],'action':action,'target':str(target),
            'source':str(source),'edition':manifest['edition'],'platform':manifest['platform'],'files':rows,
            'backup_bytes':backup_bytes,'install_bytes':install_bytes,'private_data_changed':False}

@contextlib.contextmanager
def closed_guard(target,source):
    # Import the verified new guard code, never execute an untrusted version stamp.
    saved=sys.path[:];sys.path[:0]=[str(source/'Agent'),str(source/'Tools')]
    try:
        import profile_shutdown,instance_runtime
        from mission_runner import process_lock
        with process_lock(target/'Private/profile-runtime.lock'),instance_runtime.locked(instance_runtime.host_directory()/(instance_runtime.instance_key(target)+'.lease'),timeout=1):
            marker=profile_shutdown._marker(target)
            if marker and marker['state']!='closed':raise UpdateError('Exit PortalAI normally and wait for verified sealing')
            users=path(target,'Private/Users')
            if marker is None and users.exists() and any(users.iterdir()):
                raise UpdateError('Account closure cannot be verified. Open PortalAI and exit normally before updating.')
            if not profile_shutdown.verify_stopped(target)['stopped']:raise UpdateError('Close PortalAI and its owned components before updating')
            if users.exists():
                for user in users.iterdir():
                    workspace=path(target,'Private/Users/'+user.name+'/Workspace')
                    if workspace.exists():
                        for base,dirs,files in os.walk(workspace,followlinks=False):
                            if files:raise UpdateError('An account workspace still has unsealed files; recover it in PortalAI first')
                            for d in dirs:path(target,(Path(base)/d).relative_to(target).as_posix())
            yield
    finally:sys.path[:]=saved

def restore(target,journal):
    if journal.get('target')!=str(target) or not re.fullmatch(r'Maintenance/Updates/[a-f0-9]{32}',journal.get('recovery','')):
        raise UpdateError('Invalid recovery journal')
    for row in journal['files']:
        public(row['path'])
        if not re.fullmatch('[a-f0-9]{64}',row.get('sha256','')) or (row.get('before') is not None and not re.fullmatch('[a-f0-9]{64}',row['before'])):
            raise UpdateError('Invalid recovery pin')
    recovery=path(target,journal['recovery']);rows=journal['files']
    # Validate every current identity before restoring any file.
    for row in rows:
        p=path(target,row['path']);current=sha(p) if p.exists() else None
        if current not in (row['before'],row['sha256']):raise UpdateError('Recovery conflict: '+row['path'])
        if row['before']:
            b=path(recovery,row['path'])
            if not b.is_file() or sha(b)!=row['before']:raise UpdateError('Recovery checksum failed: '+row['path'])
    for row in reversed(rows):
        p=path(target,row['path']);current=sha(p) if p.exists() else None
        if current==row['before']:continue
        if row['before']:
            copy_atomic(path(recovery,row['path']),p,row['before'],row['before_mode'])
            if sha(p)!=row['before']:raise UpdateError('Recovery readback failed')
        else:p.unlink()
    journal['state']='rolled-back';write_json(recovery/'journal.json',journal)
    path(target,PENDING).unlink()

def apply(source,target,manifest,stop=None,progress=None):
    path(source,'Agent');path(target,'Agent')
    source=Path(source).resolve();target=Path(target).resolve();progress=progress or (lambda *_:None)
    prepared=plan(source,target,manifest)
    changes=[r for r in prepared['files'] if r['status'] in ('replace','add')]
    if not changes:return {**prepared,'verified':True,'changed':0}
    if BOOT not in {r['path'] for r in manifest['files']} or b'PENDING.json' not in path(source,BOOT).read_bytes():
        raise UpdateError('Update payload lacks the interrupted-update startup guard')
    if shutil.disk_usage(target).free<prepared['backup_bytes']+prepared['install_bytes']+512*1024**2:raise UpdateError('Insufficient update and recovery space')
    with closed_guard(target,source):
        fresh=plan(source,target,manifest)
        if fresh!=prepared:raise UpdateError('Installation changed after planning')
        # Bootstrap is first, so an interrupted publication cannot start mixed code.
        changes.sort(key=lambda r:(r['path']!=BOOT,r['path']==STAMP,r['path']))
        token=uuid.uuid4().hex;recovery=path(target,'Maintenance/Updates/'+token)
        recovery.mkdir(parents=True,exist_ok=False)
        for row in changes:
            if row['before']:
                s=path(target,row['path']);b=path(recovery,row['path']);b.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(s,b)
                if sha(b)!=row['before']:raise UpdateError('Recovery backup failed')
        journal={**prepared,'files':changes,'recovery':'Maintenance/Updates/'+token,'state':'prepared'}
        write_json(recovery/'journal.json',journal);write_json(path(target,PENDING),journal)
        try:
            for i,row in enumerate(changes):
                if stop and stop.is_set():raise UpdateError('Update cancelled; original files restored')
                p=path(target,row['path']);s=path(source,row['path'])
                if (sha(p) if p.exists() else None)!=row['before']:raise UpdateError('Destination changed: '+row['path'])
                if sha(s)!=row['sha256']:raise UpdateError('Staged source changed')
                copy_atomic(s,p,row['sha256'],row.get('mode',0o644))
                if sha(p)!=row['sha256']:raise UpdateError('Update readback failed')
                progress('Updating public application files',i+1,len(changes))
            for row in changes:
                if sha(path(target,row['path']))!=row['sha256']:raise UpdateError('Final readback failed')
            journal['state']='complete';write_json(recovery/'journal.json',journal)
            path(target,PENDING).unlink()
        except BaseException:
            restore(target,journal);raise
    return {k:v for k,v in {**prepared,'verified':True,'changed':len(changes),'recovery':str(recovery)}.items() if k!='files'}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--target',type=Path,required=True)
    ap.add_argument('--manifest',type=Path,required=True)
    mode=ap.add_mutually_exclusive_group();mode.add_argument('--apply',action='store_true');mode.add_argument('--recover',action='store_true')
    args=ap.parse_args();manifest=read_json(args.manifest)
    if args.recover:
        path(args.target,'Agent');path(args.source,'Agent')
        validate_manifest(manifest)
        for r in manifest['files']:
            if sha(path(args.source,r['path']))!=r['sha256']:raise UpdateError('Recovery helper payload mismatch')
        with closed_guard(args.target.resolve(),args.source.resolve()):restore(args.target.resolve(),read_json(path(args.target,PENDING)))
        result={'recovered':True}
    elif args.apply:result=apply(args.source,args.target,manifest)
    else:
        result=plan(args.source,args.target,manifest)
        result={**{k:v for k,v in result.items() if k!='files'},'changes':[{k:r[k] for k in ('path','status')} for r in result['files'] if r['status']!='unchanged']}
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,UpdateError) as e:print('PortalAI update: '+str(e),file=sys.stderr);raise SystemExit(2)
