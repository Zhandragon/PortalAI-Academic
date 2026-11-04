"""Read-only routing of explicitly selected, prepared weight-edit profiles.

Original model assets and variant choices remain authoritative. No hashing of
multi-gigabyte files, model loading or filesystem mutation occurs in GUI previews.
"""
import json,os,re,stat,zipfile
from pathlib import Path

ID=re.compile(r'[0-9a-f]{24}')
MAX_PATCH=1024**3

def home(root):return Path(root)/'LLM/WeightEdits'

def safe_path(root,path):
    root=Path(root).resolve();path=Path(path).absolute()
    if not path.resolve().is_relative_to(root):raise ValueError('Weight-profile path escapes its portable directory')
    for part in [path,*path.parents]:
        if part.exists() or part.is_symlink():
            info=part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Weight-profile path traverses a reparse point')
        if part==root:break
    return path

def identity(path):
    s=Path(path).stat()
    return {'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'ctime_ns':s.st_ctime_ns,'file_id':s.st_ino}

def read_manifest(path):
    path=Path(path)
    if path.stat().st_size>MAX_PATCH:raise ValueError('Edit-profile archive exceeds 1 GiB')
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or set(names)!={'manifest.json','delta.bin','recipe.json','receipt.json'}:raise ValueError('Unexpected edit-profile members')
        if z.getinfo('manifest.json').file_size>4*1024**2 or sum(i.file_size for i in z.infolist())>MAX_PATCH+16*1024**2:raise ValueError('Edit-profile expansion exceeds limits')
        m=json.loads(z.read('manifest.json'));delta_size=z.getinfo('delta.bin').file_size
    if not isinstance(m,dict) or m.get('format')!='portalai-weight-edit-v1' or not isinstance(m.get('id'),str) or not ID.fullmatch(m['id']):raise ValueError('Invalid edit-profile manifest')
    if not isinstance(m.get('label'),str) or not 1<=len(m['label'])<=96:raise ValueError('Invalid edit-profile label')
    if not isinstance(m.get('base_name'),str) or Path(m['base_name']).name!=m['base_name'] or not m['base_name'].lower().endswith('.gguf'):raise ValueError('Invalid base model filename')
    for key in ('base_sha256','candidate_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}',m.get(key,'')):raise ValueError('Invalid edit-profile checksum')
    if type(m.get('model_bytes')) is not int or m['model_bytes']<1:raise ValueError('Invalid model size')
    segments=m.get('segments');end=0
    if not isinstance(segments,list) or not 1<=len(segments)<=8192:raise ValueError('Invalid edit-profile segments')
    for row in segments:
        if not isinstance(row,dict):raise ValueError('Invalid edit-profile segment')
        offset,length=row.get('offset'),row.get('bytes')
        if type(offset) is not int or type(length) is not int or offset<end or not 1<=length<=65536 or offset+length>m['model_bytes']:raise ValueError('Invalid or overlapping edit-profile segment')
        for key in ('before_sha256','after_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}',row.get(key,'')):raise ValueError('Invalid segment checksum')
        end=offset+length
    if delta_size!=sum(12+2*row['bytes'] for row in segments):raise ValueError('Exact delta length does not match its manifest')
    return m

def catalog(root):
    folder=home(root)/'Profiles'
    if not folder.exists():return []
    safe_path(home(root),folder);rows=[]
    # Small sidecars keep Settings independent of potentially large archives.
    for card in sorted(folder.glob('*.profile.json'))[:64]:
        try:
            safe_path(home(root),card)
            if card.stat().st_size>4096:continue
            m=json.loads(card.read_text())
            if not isinstance(m,dict):continue
            identifier=m.get('id','')
            if not isinstance(identifier,str) or not ID.fullmatch(identifier):continue
            path=safe_path(home(root),folder/(identifier+'.wsedit'))
            if card.name!=identifier+'.profile.json' or not path.is_file():continue
            if not isinstance(m.get('label'),str) or not 1<=len(m['label'])<=96:continue
            rows.append({'id':m['id'],'label':m['label'],'base_name':m['base_name'],'base_sha256':m['base_sha256'],
                         'candidate_sha256':m['candidate_sha256'],'patch_bytes':path.stat().st_size,
                         'status':'experimental','automatic_retry_eligible':False,
                         'prepared':(home(root)/'Prepared'/m['id']/'ready.json').is_file()})
        except (OSError,ValueError,KeyError,zipfile.BadZipFile):continue
    return rows

def resolve_model(root,model,policy):
    selected=policy.get('weight_edit_profile','original')
    if selected=='original':return model
    if not isinstance(selected,str) or not ID.fullmatch(selected):raise ValueError('Unknown weight-edit profile')
    folder=home(root);archive=safe_path(folder,folder/'Profiles'/(selected+'.wsedit'))
    m=read_manifest(archive)
    if m['id']!=selected:raise ValueError('Edit-profile identifier does not match its archive')
    base=Path(model['absolute_path'])
    if base.name!=m['base_name']:
        return {**model,'weight_edit_note':'Selected edit does not match this model/variant; using original weights.'}
    cache=safe_path(folder,folder/'Prepared'/selected);ready=cache/'ready.json';candidate=cache/'candidate.gguf'
    safe_path(folder,ready);safe_path(folder,candidate)
    try:
        if ready.stat().st_size>16384:raise ValueError('Oversized prepared-profile certificate')
        proof=json.loads(ready.read_text())
    except FileNotFoundError as exc:raise RuntimeError('Prepare the selected weight-edit profile in Utilities, or select Original weights in Settings.') from exc
    if (proof.get('profile_id')!=selected or proof.get('candidate_sha256')!=m['candidate_sha256'] or
            proof.get('base_sha256')!=m['base_sha256'] or proof.get('base_identity')!=identity(base) or
            proof.get('candidate_identity')!=identity(candidate) or proof.get('archive_identity')!=identity(archive)):
        raise RuntimeError('Prepared weight-edit profile changed. Re-prepare it or choose Original weights.')
    # The preparation worker verified complete hashes. A preview checks file
    # identity and timestamps only; this cache is not a hostile-tampering proof.
    return {**model,'absolute_path':str(candidate),'path':candidate.relative_to(Path(root)).as_posix(),
            'label':model.get('label',model.get('id',base.stem))+' · '+m['label'],
            'weight_edit_profile':selected,'weight_edit_label':m['label'],'weight_edit_status':'experimental',
            'original_absolute_path':str(base),'base_model_sha256':m['base_sha256'],'candidate_sha256':m['candidate_sha256']}
