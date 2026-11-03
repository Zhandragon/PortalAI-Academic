"""Experimental sparse projection edits; originals are never written.

Adaptation of Takehi et al.'s published weight-space repetition intervention:
https://rikiyat.github.io/blog/weight-space-programming/
https://github.com/RikiyaT/lm_understand-logs/tree/main/exp8_math

This module implements the algebra, not a claim that any direction is beneficial.
A direction must come from THIS model's matched activation captures. A LoRA
adapter represents an additive rank-one update without duplicating a GGUF.
GGUF inference is numerically distinct from the paper's BF16 tensor overwrite.
"""
import argparse,hashlib,json,os,sys
from pathlib import Path
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2]
sys.path[:0]=[str(LAB/'reader-packages'),str(ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages')]
import numpy as np
import gguf

def direction(productive,repetitive):
    """Paired mean contrast, unit norm; no labels or activations from holdout."""
    p=np.asarray(productive,dtype=np.float32);r=np.asarray(repetitive,dtype=np.float32)
    if p.shape!=r.shape or p.ndim!=2 or p.shape[0]<4:raise ValueError('Need at least four matched activation pairs')
    if not np.isfinite(p).all() or not np.isfinite(r).all():raise ValueError('Nonfinite activation')
    u=(r-p).mean(axis=0);norm=float(np.linalg.norm(u))
    if norm<1e-8:raise ValueError('No measurable paired activation contrast')
    return u/norm

def factors(weight,u,columns=64,dose=1.0,writer_contrast=None):
    """B@A = -dose*u*(mask*(u@W)); only selected MLP writer columns change."""
    w=np.asarray(weight,dtype=np.float32);u=np.asarray(u,dtype=np.float32)
    if w.ndim!=2 or u.shape!=(w.shape[0],):raise ValueError('Direction and projection shape mismatch')
    if not np.isfinite(w).all() or not np.isfinite(u).all():raise ValueError('Nonfinite weights/direction')
    if not .999<np.linalg.norm(u)<1.001:raise ValueError('Direction must have unit norm')
    if type(columns) is not int or not 1<=columns<=min(64,w.shape[1]):raise ValueError('At most 64 columns per site')
    if not 0<float(dose)<=6:raise ValueError('Dose must be positive and <= 6; evaluate a dose sweep')
    projection=u@w
    scores=np.abs(projection)
    if writer_contrast is not None:
        contrast=np.asarray(writer_contrast,dtype=np.float32)
        if contrast.shape!=scores.shape or not np.isfinite(contrast).all():raise ValueError('Invalid writer contrast')
        scores=scores*np.abs(contrast)
    selected=np.sort(np.argsort(scores,kind='stable')[-columns:])
    a=np.zeros((1,w.shape[1]),dtype=np.float32);a[0,selected]=projection[selected]
    b=(-float(dose)*u[:,None]).astype(np.float32)
    if float(np.linalg.norm(a))<1e-8:raise ValueError('No nonzero projection selected')
    return a,b,selected

def random_control(a,b,u,seed):
    """Orthogonal direction, identical selected columns and delta Frobenius norm."""
    rng=np.random.default_rng(seed);v=rng.normal(size=u.shape).astype(np.float32)
    v-=u*float(u@v);v/=np.linalg.norm(v)
    return a.copy(),v[:,None]*np.linalg.norm(b)

def save_adapter(path,arch,entries,metadata):
    path=Path(path)
    if path.exists():raise FileExistsError('Never overwrite an existing experiment artifact')
    writer=gguf.GGUFWriter(str(path),arch=arch)
    writer.add_type('adapter');writer.add_string('adapter.type','lora');writer.add_float32('adapter.lora.alpha',1.0)
    for name,a,b in entries:
        if not name.endswith('.ffn_down.weight'):raise ValueError('Only MLP down projections may be edited')
        writer.add_tensor(name+'.lora_a',np.ascontiguousarray(a))
        writer.add_tensor(name+'.lora_b',np.ascontiguousarray(b))
    writer.write_header_to_file();writer.write_kv_data_to_file();writer.write_tensors_to_file();writer.close()
    manifest={**metadata,'adapter_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'adapter_bytes':path.stat().st_size,'installed':False,'evaluation_status':'unvalidated candidate','original_weights_modified':False}
    path.with_suffix('.json').write_text(json.dumps(manifest,indent=2))
    return manifest

def build(a):
    if not a.output.resolve().is_relative_to(LAB.resolve()):raise ValueError('Candidate artifacts must remain in the portable experiment folder')
    if a.capture.stat().st_size>1024**2:raise ValueError('Capture manifest exceeds 1 MiB')
    spec=json.loads(a.capture.read_text())
    if spec.get('split')!='selection':raise ValueError('Direction fitting requires selection-only captures')
    if len(set(spec['case_ids']))<4:raise ValueError('At least four distinct matched cases required')
    if spec.get('model_sha256')!=a.model_sha256:raise ValueError('Capture provenance differs from selected model')
    model=a.model.resolve()
    if model.suffix!='.gguf' or not model.is_relative_to((ROOT/'LLM/models').resolve()):raise ValueError('Select an installed model under this root')
    with model.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
    if actual!=a.model_sha256:raise ValueError('Installed model hash mismatch')
    reader=gguf.GGUFReader(str(model),'r');tensors={t.name:t for t in reader.tensors}
    arch=reader.fields['general.architecture'].contents()
    if not 1<=len(spec['sites'])<=2:raise ValueError('Pilot limit: one or two causally investigated sites')
    entries=[];controls=[];sites=[]
    for site in spec['sites']:
        name=site['tensor'];tensor=tensors[name]
        if not name.endswith('.ffn_down.weight'):raise ValueError('Unsupported weight site')
        capture=(a.capture.parent/site['activations']).resolve()
        if not capture.is_relative_to(a.capture.parent.resolve()):raise ValueError('Capture must remain inside experiment')
        if capture.stat().st_size>64*1024**2:raise ValueError('Activation archive exceeds 64 MiB')
        with np.load(capture,allow_pickle=False) as arrays:
            u=direction(arrays['productive'],arrays['repetitive'])
            writer_contrast=arrays['writer_contrast'] if 'writer_contrast' in arrays else None
        w=gguf.quants.dequantize(tensor.data,tensor.tensor_type)
        fa,fb,cols=factors(w,u,a.columns,a.dose,writer_contrast)
        ca,cb=random_control(fa,fb,u,a.seed)
        relative=float(np.linalg.norm(fa)*np.linalg.norm(fb)/np.linalg.norm(w))
        if relative>.15:raise ValueError('Candidate exceeds 15% per-matrix perturbation ceiling')
        sites.append({'tensor':name,'shape':list(w.shape),'selected_columns':cols.tolist(),'relative_matrix_delta':relative,'direction_sha256':hashlib.sha256(u.tobytes()).hexdigest(),'activation_sha256':hashlib.sha256(capture.read_bytes()).hexdigest()})
        entries.append((name,fa,fb));controls.append((name,ca,cb));del w
    common={'method':'matched-activation sparse rank-one projection','base_model_sha256':actual,'base_model':model.name,'architecture':arch,'dose':a.dose,'sites':sites,'selection_case_ids':spec['case_ids'],'seed':a.seed,'requires':['baseline','dose sweep','site isolation','norm-matched orthogonal random control','held-out math/coding/tool-use/reasoning accuracy','latency and memory comparison']}
    print(json.dumps(save_adapter(a.output,arch,entries,common)))
    print(json.dumps(save_adapter(a.output.with_name(a.output.stem+'-control.gguf'),arch,controls,{**common,'control':True})))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--model-sha256',required=True);p.add_argument('--capture',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--dose',type=float,default=1);p.add_argument('--columns',type=int,default=64);p.add_argument('--seed',type=int,default=20261103)
    build(p.parse_args())
