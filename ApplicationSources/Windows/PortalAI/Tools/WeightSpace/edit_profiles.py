"""Compact exact GGUF deltas and bounded prepared copies; originals stay immutable."""
import hashlib,json,os,shutil,struct,sys,zipfile
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(HERE)]
from experiment import atomic_json,sha,space
from weight_edit_profiles import home,safe_path,identity,read_manifest,ID,MAX_PATCH
BLOCK=65536

def digest(data):return hashlib.sha256(data).hexdigest()

def export_profile(root,model,candidate,recipe,*,label,progress=None):
    from quantized_edit import gguf,validate_recipe
    root=Path(root).resolve();model=Path(model).resolve(strict=True);candidate=Path(candidate).resolve(strict=True)
    label=str(label).strip()
    if not 1<=len(label)<=96:raise ValueError('Choose a profile label of 1 to 96 characters')
    receipt=json.loads(candidate.with_suffix('.edit.json').read_text())
    if candidate==model or candidate.stat().st_size!=model.stat().st_size:raise ValueError('Expected a separate same-sized candidate')
    if receipt.get('candidate_bytes')!=model.stat().st_size:raise ValueError('Candidate receipt size mismatch')
    reader=gguf.GGUFReader(str(model),'r');sites=validate_recipe(reader,recipe,receipt['base_sha256'])
    ranges=sorted((int(t.data_offset),int(t.data_offset+t.data.nbytes)) for t,*_ in sites)
    identifier=digest((receipt['base_sha256']+receipt['candidate_sha256']).encode())[:24]
    folder=safe_path(home(root),home(root)/'Profiles');folder.mkdir(parents=True,exist_ok=True)
    target=folder/(identifier+'.wsedit');partial=target.with_suffix('.wsedit.partial')
    if target.exists() or partial.exists():raise FileExistsError('This profile already exists or an interrupted export needs review')
    space(folder,MAX_PATCH+16*1024**2);before_identity=identity(model);segments=[];hbase=hashlib.sha256();hedit=hashlib.sha256()
    with zipfile.ZipFile(partial,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        with model.open('rb') as source,candidate.open('rb') as edited,z.open('delta.bin','w') as delta:
            offset=0
            while before:=source.read(BLOCK):
                after=edited.read(len(before));hbase.update(before);hedit.update(after)
                if len(after)!=len(before):raise RuntimeError('Candidate changed size during export')
                if before!=after:
                    # A profile may change only the recipe's measured MLP sites.
                    intervals=[(max(0,a-offset),min(len(before),b-offset)) for a,b in ranges if a<offset+len(before) and b>offset]
                    cursor=0
                    for a,b in intervals:
                        if before[cursor:a]!=after[cursor:a]:raise ValueError('Candidate changed bytes outside its permitted tensors')
                        cursor=b
                    if before[cursor:]!=after[cursor:]:raise ValueError('Candidate changed bytes outside its permitted tensors')
                    segments.append({'offset':offset,'bytes':len(before),'before_sha256':digest(before),'after_sha256':digest(after)})
                    if len(segments)>8192:raise ValueError('Exact delta exceeds the bounded profile size')
                    delta.write(struct.pack('<QI',offset,len(before)));delta.write(before);delta.write(after)
                offset+=len(before)
                if progress and offset%(256*1024**2)==0:progress(offset,model.stat().st_size)
            if edited.read(1):raise RuntimeError('Candidate changed size during export')
        if not segments:raise ValueError('Candidate contains no weight change')
        if hbase.hexdigest()!=receipt['base_sha256'] or hedit.hexdigest()!=receipt['candidate_sha256']:raise ValueError('Model/candidate checksum no longer matches the edit evidence')
        if identity(model)!=before_identity:raise RuntimeError('Original changed during profile export')
        manifest={'format':'portalai-weight-edit-v1','id':identifier,'label':label,'base_name':model.name,
                  'base_sha256':hbase.hexdigest(),'candidate_sha256':hedit.hexdigest(),'model_bytes':offset,
                  'segments':segments,'validation':'experimental','automatic_retry_eligible':False,
                  'quantization':'Exact before/after bytes from the evaluated GGUF; not a low-rank approximation.'}
        for name,value in [('manifest.json',manifest),('recipe.json',recipe),('receipt.json',receipt)]:z.writestr(name,json.dumps(value,sort_keys=True))
    if partial.stat().st_size>MAX_PATCH:raise ValueError('Compressed edit profile exceeds 1 GiB')
    with partial.open('r+b') as stream:stream.flush();os.fsync(stream.fileno())
    if read_manifest(partial)!=manifest:raise RuntimeError('Profile readback mismatch')
    os.replace(partial,target)
    card={k:manifest[k] for k in ('id','label','base_name','base_sha256','candidate_sha256','model_bytes')}
    card.update(patch_bytes=target.stat().st_size,validation='experimental',automatic_retry_eligible=False)
    atomic_json(folder/(identifier+'.profile.json'),card)
    return {**card,'profile_archive':str(target),'original_modified':False}

def clear_prepared(root,identifier,*,in_use=()):
    """Caller holds the portable GPU lease/lifecycle mutex; delete only known cache files."""
    if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('Invalid profile identifier')
    folder=safe_path(home(root),home(root)/'Prepared'/identifier)
    if not folder.exists():return False
    expected={'candidate.gguf','ready.json'}
    if {p.name for p in folder.iterdir()}!=expected:raise RuntimeError('Interrupted or unfamiliar cache files need review; nothing removed')
    candidate=safe_path(home(root),folder/'candidate.gguf');ready=safe_path(home(root),folder/'ready.json')
    if candidate.resolve() in {Path(p).resolve() for p in in_use}:raise RuntimeError('This prepared model is loaded; switch to Original weights and finish unloading it first')
    if ready.stat().st_size>16384:raise ValueError('Oversized prepared-profile certificate')
    proof=json.loads(ready.read_text())
    if proof.get('profile_id')!=identifier or proof.get('candidate_identity')!=identity(candidate):raise RuntimeError('Prepared file identity changed; nothing removed')
    # Every final target was resolved and checked above. Never delete originals,
    # arbitrary contents, directories recursively, or the compact profile itself.
    candidate.unlink();ready.unlink();folder.rmdir()
    return True

def prepare_profile(root,model,identifier,*,in_use=(),progress=None):
    """Create an exact loadable candidate, retaining at most two prepared copies."""
    root=Path(root).resolve();model=Path(model).resolve(strict=True)
    if not isinstance(identifier,str) or not ID.fullmatch(identifier):raise ValueError('Invalid profile identifier')
    archive=safe_path(home(root),home(root)/'Profiles'/(identifier+'.wsedit'));manifest=read_manifest(archive)
    if manifest['id']!=identifier or model.name!=manifest['base_name'] or model.stat().st_size!=manifest['model_bytes']:raise ValueError('Profile does not match this original model')
    prepared=safe_path(home(root),home(root)/'Prepared');prepared.mkdir(parents=True,exist_ok=True)
    folder=safe_path(home(root),prepared/identifier);candidate=folder/'candidate.gguf';partial=folder/'candidate.gguf.partial';ready=folder/'ready.json'
    if ready.exists():
        from weight_edit_profiles import resolve_model
        result=resolve_model(root,{'absolute_path':str(model)},{'weight_edit_profile':identifier})
        return {'prepared':True,'cached':True,'candidate':result['absolute_path'],'profile_id':identifier,'original_modified':False}
    if folder.exists() and any(folder.iterdir()):raise RuntimeError('Interrupted preparation needs review; it will not be silently overwritten')
    other=sorted([p for p in prepared.iterdir() if p.is_dir() and p.name!=identifier],key=lambda p:p.stat().st_mtime)
    # Verify the new copy before evicting a previously useful one. Admission
    # includes this temporary third copy, so even staging preserves the floor.
    space(prepared,model.stat().st_size+64*1024**2);folder.mkdir(exist_ok=True)
    base_identity=identity(model);archive_identity=identity(archive);h=hashlib.sha256()
    with model.open('rb') as source,partial.open('xb') as output:
        while chunk:=source.read(8*1024**2):h.update(chunk);output.write(chunk)
        output.flush();os.fsync(output.fileno())
    if h.hexdigest()!=manifest['base_sha256'] or identity(model)!=base_identity:raise RuntimeError('Original does not match the profile; incomplete copy retained')
    with zipfile.ZipFile(archive) as z,z.open('delta.bin') as delta,partial.open('r+b',buffering=0) as output:
        for index,row in enumerate(manifest['segments']):
            header=delta.read(12)
            if len(header)!=12 or struct.unpack('<QI',header)!=(row['offset'],row['bytes']):raise ValueError('Malformed exact delta')
            before=delta.read(row['bytes']);after=delta.read(row['bytes'])
            if digest(before)!=row['before_sha256'] or digest(after)!=row['after_sha256']:raise ValueError('Delta segment checksum mismatch')
            output.seek(row['offset'])
            if output.read(row['bytes'])!=before:raise ValueError('Candidate copy does not match expected original bytes')
            output.seek(row['offset']);output.write(after)
            if progress and index%128==0:progress(index,len(manifest['segments']))
        if delta.read(1):raise ValueError('Unexpected data after exact delta')
        output.flush();os.fsync(output.fileno())
    if sha(partial)!=manifest['candidate_sha256']:raise RuntimeError('Prepared candidate failed complete checksum verification')
    if identity(archive)!=archive_identity or identity(model)!=base_identity:raise RuntimeError('Profile or original changed during preparation')
    while len(other)>=2:
        unused=next((p for p in other if (p/'candidate.gguf').resolve() not in {Path(v).resolve() for v in in_use}),None)
        if unused is None:raise RuntimeError('Prepared cache is busy; originals and active models were left untouched')
        clear_prepared(root,unused.name,in_use=in_use);other.remove(unused)
    os.replace(partial,candidate)
    proof={'profile_id':identifier,'base_sha256':manifest['base_sha256'],'candidate_sha256':manifest['candidate_sha256'],
           'base_identity':base_identity,'archive_identity':archive_identity,'candidate_identity':identity(candidate)}
    atomic_json(ready,proof)
    return {'prepared':True,'cached':False,'candidate':str(candidate),'profile_id':identifier,'original_modified':False}
