"""Small backbone-conditioned ProteinMPNN jobs; portable CPU is an explicit backend."""
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from Scientific.biology import integer,number,sequence,AA

REVISION='8907e6671bfbfc92303b5f79c4b5e6ce47cdef57'


def validate_request(p):
    if not isinstance(p,dict) or not isinstance(p.get('pdb'),str) or not p['pdb'].strip():
        raise ValueError('protein.design requires input.pdb: a local/attached text PDB file path. Use science {"operation":"protein.design","input":{"pdb":"file.pdb","chain":"A"}}. Do not replace pdb with structure/file; see biology.help.')
    chain=p.get('chain')
    if not isinstance(chain,str) or len(chain)!=1 or not chain.isalnum():
        raise ValueError('protein.design requires input.chain: one alphanumeric PDB chain ID. Use protein.inspect to list chains.')
    unknown=set(p)-{'pdb','chain','count','temperature','seed','fixed_positions','device','export','output_dir'}
    if unknown:
        raise ValueError('Unsupported protein.design arguments: '+', '.join(sorted(unknown))+'. This is fixed-backbone sequence design, not PAM/binding/function optimization; see biology.help.')


def verify_assets(root,windows=False):
    receipt=json.loads((root/'Maintenance/Imports/protein-mpnn.json').read_text(encoding='utf-8'))
    if receipt.get('verified') is not True or receipt.get('revision')!=REVISION:raise RuntimeError('ProteinMPNN receipt does not match the pinned release')
    from profile_paths import _contained
    selected=[r for r in receipt['files'] if '/vendor/' in r['path'] or windows]
    needed={'Runtime/ProteinDesign/vendor/protein_mpnn_utils.py','Runtime/ProteinDesign/vendor/vanilla_model_weights/v_48_020.pt'}
    if not needed.issubset({r['path'] for r in selected}):raise RuntimeError('Incomplete ProteinMPNN receipt')
    for row in selected:
        if not row['path'].startswith('Runtime/ProteinDesign/'):raise RuntimeError('Invalid protein asset path')
        path=_contained(root,root/row['path'])
        if path.stat().st_size!=row['bytes']:raise RuntimeError('Protein asset size changed')
        with path.open('rb') as handle:digest=hashlib.file_digest(handle,'sha256').hexdigest()
        if digest!=row['sha256']:raise RuntimeError('Protein asset hash changed: '+row['path'])


def backbone(text,chain):
    from Bio.PDB import PDBParser
    from Bio.SeqUtils import seq1
    if not isinstance(chain,str) or len(chain)!=1 or not chain.isalnum():raise ValueError('Specify one alphanumeric PDB chain')
    structure=PDBParser(QUIET=True,PERMISSIVE=False).get_structure('design',io.StringIO(text))
    models=list(structure)
    if len(models)!=1 or chain not in models[0]:raise ValueError('Require one model and the requested chain')
    residues=[r for r in models[0][chain] if r.id[0]==' ']
    if not 8<=len(residues)<=256:raise ValueError(f'CPU design supports 8..256 residues in one chain; selected chain has {len(residues)}. Use protein.inspect for full structures or protein.structure_variants for explicit sequence edits. Do not silently crop the structure.')
    positions=[];coords={atom+'_chain_A':[] for atom in ('N','CA','C','O')};previous=None
    for r in residues:
        if r.id[2]!=' ' or (previous is not None and r.id[1]!=previous+1):raise ValueError('Insertion codes or numbering gaps require an explicitly repaired backbone')
        previous=r.id[1];positions.append(r.id[1])
        for atom in ('N','CA','C','O'):
            if atom not in r or r[atom].is_disordered():raise ValueError('Backbone atoms must be complete and have one conformer')
            xyz=[float(v) for v in r[atom].coord]
            if any(not math.isfinite(v) or abs(v)>1e5 for v in xyz):raise ValueError('Invalid backbone coordinates')
            coords[atom+'_chain_A'].append(xyz)
    native=sequence(''.join(seq1(r.resname,undef_code='X') for r in residues),AA,256)
    return {'name':'design','num_of_chains':1,'seq':native,'seq_chain_A':native,'coords_chain_A':coords},positions


def design(p,context):
    from media_paths import media_reference
    from profile_paths import private_path,_contained
    from runtime_policy import memory_info,require_space,portable_env
    from platform_runtime import python_path
    from mission_supervisor import WorkerJob
    if p.get('device','cpu')!='cpu':raise ValueError('ProteinMPNN currently has an explicit CPU backend; GPU acceleration is not enabled or silently substituted')
    root=context.root;context.check()
    validate_request(p)
    if memory_info()[1]<3*1024**3:raise RuntimeError('ProteinMPNN needs 3 GiB free RAM; use a smaller chat model or stop other work')
    require_space(root,32*1024**2,for_outputs=True)
    path=media_reference(root,p['pdb'])
    with path.open('rb') as handle:data=handle.read(2*1024**2+1)
    if len(data)>2*1024**2:raise ValueError('PDB input exceeds 2 MiB. protein.design supports one complete 8..256-residue chain; use protein.inspect for full-structure analysis. Do not silently truncate the file.')
    context.check();protein,positions=backbone(data.decode('ascii'),p['chain'])
    count=integer(p.get('count',1),'count',1,8);temperature=number(p.get('temperature',.1),'temperature',.05,1)
    seed=integer(p.get('seed',1),'seed',1,2147483647)
    fixed=p.get('fixed_positions',[])
    if not isinstance(fixed,list) or len(fixed)>=len(positions):raise ValueError('Keep at least one residue designable')
    fixed=[integer(i,'fixed position',1,len(positions)) for i in fixed]
    if len(set(fixed))!=len(fixed):raise ValueError('Duplicate fixed position')
    request_data={'protein':protein,'count':count,'temperature':temperature,'seed':seed,'fixed_positions':fixed}
    staging=private_path(root,'Cache/tmp',context=context.identity)/('protein_'+uuid.uuid4().hex)
    _contained(root,staging);context.check();staging.mkdir(parents=True)
    identities={};proc=job=None
    def write(name,data):
        context.check();path=_contained(root,staging/name)
        with path.open('xb') as handle:
            stat=os.fstat(handle.fileno());identities[name]=(stat.st_dev,stat.st_ino);handle.write(data);handle.flush();os.fsync(handle.fileno())
        return path
    try:
        request=write('input.json',json.dumps(request_data,allow_nan=False).encode())
        gate=staging/'gate'
        cmd=[str(python_path(root)),'-B','-I',str(root/'Scientific/protein_design_worker.py'),str(request)]
        launch=write('launch.json',json.dumps({'command':cmd,'gate':str(gate)}).encode())
        log=write('log.txt',b'');env=portable_env(root)
        env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
        context.check()
        with log.open('ab') as out:
            proc=subprocess.Popen([str(python_path(root)),'-B','-I',str(root/'Agent/sdcpp_worker.py'),str(launch)],
                cwd=root,env=env,stdin=subprocess.DEVNULL,stdout=out,stderr=out,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=WorkerJob(proc);job.limit_memory(2*1024**3);context.check();write('gate',b'')
            while proc.poll() is None:
                context.check();job.check()
                if memory_info()[1]<768*1024**2:raise RuntimeError('Protein design stopped at the free-RAM reserve')
                if log.stat().st_size>1024**2:raise RuntimeError('Protein worker log limit exceeded')
                time.sleep(.1)
        context.check()
        raw=log.read_text(encoding='utf-8',errors='replace')
        if proc.returncode:raise RuntimeError('Protein worker failed: '+raw[-1500:])
        line=next((s for s in raw.splitlines() if s.startswith('PORTAL_PROTEIN=')),None)
        if not line:raise RuntimeError('Protein worker returned no result')
        result=json.loads(line.split('=',1)[1])
        if len(result['sequences'])!=count:raise RuntimeError('Incomplete protein design result')
        for row in result['sequences']:
            candidate=sequence(row['sequence'],AA,256)
            if len(candidate)!=len(positions) or any(candidate[i-1]!=protein['seq'][i-1] for i in fixed):raise RuntimeError('Protein worker violated fixed residues or sequence length')
        context.check()
        return {**result,'compute':'cpu','pdb_sha256':hashlib.sha256(data).hexdigest(),'chain':p['chain'],
            'input_sequence':protein['seq'],'pdb_residue_numbers':positions,'fixed_positions':fixed,'seed':seed,'temperature':temperature,
            'limitations':['Single-chain fixed-backbone inverse folding, not de novo backbone generation or structure prediction.',
                'Other chains, ligands, cofactors and binding interfaces are not modeled.',
                'Model sequence likelihood is not stability, function, expression or experimental validation.']}
    finally:
        if job:job.close()
        if proc and proc.poll() is None:proc.kill();proc.wait(timeout=10)
        for name,identity in identities.items():
            file=_contained(root,staging/name)
            if file.exists():
                stat=file.lstat()
                if (stat.st_dev,stat.st_ino)!=identity:raise RuntimeError('Protein cleanup refused a replaced file')
                file.unlink()
        if staging.exists():staging.rmdir()
