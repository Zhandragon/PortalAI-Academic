"""Opt-in repair of missing public runtime files from verified installation backups.

Checksums establish installation identity, not a malware verdict. This module
never changes antivirus settings, reads quarantine payloads or starts a runtime.
"""
from pathlib import Path, PurePosixPath
import hashlib,json,os,re,shutil,stat,tempfile,zipfile
import xml.etree.ElementTree as ET

FOLDER='Maintenance/ExecutableRecovery'
MAX_FILE=1024**3
MAX_MANIFEST=8*1024**2
PUBLIC={'Runtime','Runtimes','LLM','Image','ImageNative','Voice','Tools','Science','Scientific','ComfyUI','MMAudio','MuseTalk','ACE-Step','Music','MusicUnderstanding','Generative','Video','SpeechToText'}

def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def checked(root,relative):
    root=Path(root).resolve()
    if not isinstance(relative,str) or '\\' in relative or ':' in relative:
        raise ValueError('Invalid relative recovery path')
    parts=PurePosixPath(relative).parts
    if not parts or relative!=PurePosixPath(relative).as_posix() or any(p in ('.','..') for p in parts) or relative.startswith('/'):
        raise ValueError('Invalid relative recovery path')
    if any(p.endswith(('.', ' ')) or re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',p) for p in parts):
        raise ValueError('Invalid Windows recovery path')
    path=root
    for part in parts:
        path=path/part
        if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):
            raise ValueError('Recovery does not follow symbolic links or junctions')
    if not path.resolve().is_relative_to(root):raise ValueError('Recovery path escapes installation')
    return path

def eligible(relative):
    p=PurePosixPath(relative)
    if relative in ('PortalAI.exe','Repair PortalAI.exe'):return True
    if not p.parts or p.parts[0] not in PUBLIC:return False
    if any(s.casefold() in ('cache','data','private','downloads','executableRecovery'.casefold()) for s in p.parts):return False
    if p.suffix.casefold()=='.exe':return True
    if relative.startswith(('LLM/backends/','ImageNative/backends/','Runtime/BootstrapPython/')):
        if p.suffix.casefold() in ('.dll','.dylib') or '.so' in p.name:return True
    return (p.name in ('llama-server','sd-cli','sd-server','ffmpeg','ffprobe','sox','piper','qemu-system-x86_64') or
            (relative.startswith(('Runtime/LinuxPython/bin/','Runtime/MacPython/bin/')) and p.name.startswith('python')))

def _rows(root):
    p=checked(root,FOLDER+'/manifest.json')
    if not p.exists():return []
    if p.stat().st_size>MAX_MANIFEST:raise ValueError('Recovery manifest exceeds limit')
    data=json.loads(p.read_bytes())
    if data.get('version')!=1 or not isinstance(data.get('files'),list) or len(data['files'])>20000:
        raise ValueError('Unsupported recovery manifest')
    seen=set()
    for r in data['files']:
        name=r['path'];checked(root,name)
        if not eligible(name) or name.casefold() in seen:raise ValueError('Invalid or duplicate recovery target')
        seen.add(name.casefold())
        if not re.fullmatch('[a-f0-9]{64}',r['sha256']) or type(r['bytes']) is not int or not 0<r['bytes']<=MAX_FILE:
            raise ValueError('Invalid recovery fingerprint')
        if type(r.get('mode',0o755)) is not int:raise ValueError('Invalid recovery mode')
    return data['files']

def _archive(root,row):return checked(root,FOLDER+'/'+row['sha256']+'.zip')

def _verify_archive(root,row):
    p=_archive(root,row)
    if p.stat().st_size>row['bytes']+1024**2:raise ValueError('Recovery archive exceeds limit')
    with zipfile.ZipFile(p) as z:
        names=z.infolist()
        if len(names)!=1 or names[0].filename!='file' or names[0].file_size!=row['bytes']:
            raise ValueError('Recovery archive inventory mismatch')
        with z.open('file') as f:
            h=hashlib.sha256();total=0
            while chunk:=f.read(1024**2):
                total+=len(chunk)
                if total>row['bytes']:raise ValueError('Recovery archive exceeds expected size')
                h.update(chunk)
        if total!=row['bytes'] or h.hexdigest()!=row['sha256']:raise ValueError('Recovery backup checksum mismatch')

def register(root,files,source,check_cancel=lambda:None):
    """Installer-only: input fingerprints must come from the verified install plan.

    Never called by the automatic scanner or repair UI. Existing installation
    upgrades must supply previously published pins, not hashes of arbitrary files.
    """
    root=Path(root).resolve();folder=checked(root,FOLDER);folder.mkdir(parents=True,exist_ok=True)
    rows={r['path']:r for r in _rows(root)};added=0
    for item in files:
        name=item['path']
        if not eligible(name):continue
        check_cancel();path=checked(root,name)
        if not path.is_file():continue
        if path.stat().st_size!=item['bytes'] or not 0<item['bytes']<=MAX_FILE or digest(path)!=item['sha256']:
            raise ValueError('Cannot back up a file that differs from its installation pin: '+name)
        row=dict(path=name,bytes=item['bytes'],sha256=item['sha256'],mode=stat.S_IMODE(path.stat().st_mode)&0o777,source=str(source)[:1000])
        target=_archive(root,row)
        if target.exists():_verify_archive(root,row)
        else:
            # Standard ZIP backups; never an alternate executable or automatic AV exception.
            fd,tmp=tempfile.mkstemp(prefix='backup-',suffix='.tmp',dir=folder);os.close(fd)
            try:
                with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=1) as z:z.write(path,'file')
                check_cancel();os.replace(tmp,target);_verify_archive(root,row)
            finally:Path(tmp).unlink(missing_ok=True)
        rows[name]=row;added+=1
    manifest=checked(root,FOLDER+'/manifest.json')
    fd,tmp=tempfile.mkstemp(prefix='manifest-',suffix='.tmp',dir=folder)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(dict(version=1,files=sorted(rows.values(),key=lambda r:r['path'])),f,indent=2);f.flush();os.fsync(f.fileno())
        check_cancel();os.replace(tmp,manifest)
    finally:Path(tmp).unlink(missing_ok=True)
    return dict(registered=added,total=len(rows))

def avast_evidence(root,missing,index=None):
    """Read only matching Avast metadata, never quarantine contents."""
    if index is None:
        if os.name!='nt':return {}
        index=Path(os.environ.get('PROGRAMDATA','C:/ProgramData'))/'Avast Software/Avast/chest/index.xml'
    index=Path(index)
    try:
        if not index.is_file() or index.stat().st_size>4*1024**2:return {}
        xml=index.read_bytes()
        if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():return {}
        tree=ET.fromstring(xml)
        targets={os.path.normcase(str(checked(root,r['path']))):r['path'] for r in missing}
        evidence={}
        for entry in tree.iter('ChestEntry'):
            folder=entry.findtext('OrigFolder');name=entry.findtext('OrigFileName')
            if folder and name:
                key=os.path.normcase(str(Path(folder)/name))
                if key in targets:evidence[targets[key]]='Avast quarantine record: '+str(entry.findtext('Virus') or 'detection recorded')[:160]
        return evidence
    except (OSError,ValueError,ET.ParseError):return {}

def inspect(root,verify_backups=False):
    rows=_rows(root);missing=[]
    for row in rows:
        path=checked(root,row['path'])
        if path.exists():continue
        item=dict(row);item['backup_available']=_archive(root,row).is_file()
        if verify_backups and item['backup_available']:
            try:_verify_archive(root,row);item['backup_verified']=True
            except (OSError,ValueError,zipfile.BadZipFile) as exc:item.update(backup_available=False,error=str(exc))
        missing.append(item)
    evidence=avast_evidence(root,missing)
    for row in missing:row['evidence']=evidence.get(row['path'],'File missing. Antivirus interference is possible, but is not confirmed.')
    return dict(registered=len(rows),missing=missing)

def restore(root,paths,check_cancel=lambda:None):
    """Explicit Proceed only. Recheck manifest, backup and destination on each file.

    Existing files are never overwritten. No execution, model restart or mission
    arming occurs; Stop/logout can cancel before any further file publication.
    """
    rows={r['path']:r for r in _rows(root)};restored=[];errors=[]
    for name in dict.fromkeys(paths):
        check_cancel()
        try:
            row=rows[name];path=checked(root,name)
            if path.exists():raise ValueError('Target already exists; it was left unchanged')
            _verify_archive(root,row);check_cancel()
            path.parent.mkdir(parents=True,exist_ok=True);checked(root,name)
            # Publish only a complete verified file; interrupted repair cannot
            # leave a partial executable in its live location.
            fd,temporary=tempfile.mkstemp(prefix='portalai-repair-',suffix='.tmp',dir=path.parent)
            try:
                with os.fdopen(fd,'wb') as target,zipfile.ZipFile(_archive(root,row)) as z,z.open('file') as source:
                    h=hashlib.sha256();total=0
                    while chunk:=source.read(1024**2):
                        check_cancel();total+=len(chunk)
                        if total>row['bytes']:raise ValueError('Recovery file exceeds limit')
                        target.write(chunk);h.update(chunk)
                    if total!=row['bytes'] or h.hexdigest()!=row['sha256']:raise ValueError('Recovery readback mismatch')
                    target.flush();os.fsync(target.fileno())
                os.chmod(temporary,row.get('mode',0o755)&0o777);check_cancel();checked(root,name)
                if os.name=='nt':os.rename(temporary,path)  # Windows refuses an existing target.
                else:os.link(temporary,path)  # POSIX rename would overwrite; link is exclusive.
            finally:Path(temporary).unlink(missing_ok=True)
            if digest(path)!=row['sha256']:raise ValueError('Restored file was changed or removed; review antivirus alert')
            restored.append(name)
        except (OSError,ValueError,KeyError,zipfile.BadZipFile) as exc:errors.append(dict(path=name,error=str(exc)))
    return dict(restored=restored,errors=errors)

def seed_native_install(root):
    """Fresh native installer, after verified archive extraction/native compilation."""
    root=Path(root).resolve()
    if (root/'Private').exists():raise ValueError('Fresh-install seeding refuses an account installation')
    rows=[]
    for directory in ['LLM/backends','Runtime/LinuxPython/bin','Runtime/MacPython/bin']:
        base=checked(root,directory)
        if not base.exists():continue
        for p in base.rglob('*'):
            if p.is_symlink() or not p.is_file():continue
            rel=p.relative_to(root).as_posix()
            if eligible(rel):rows.append(dict(path=rel,bytes=p.stat().st_size,sha256=digest(p)))
    return register(root,rows,'Fresh native installation: verified archives and native build output')
