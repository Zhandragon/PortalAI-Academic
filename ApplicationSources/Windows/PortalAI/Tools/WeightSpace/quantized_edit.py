"""Sparse direct subtraction in GGUF, preserving untouched quantization blocks.

The model is selected by the user. Only dense MLP down projections are eligible.
No architecture-blind change to embeddings, output head, norms or full matrices.
All original bytes remain immutable; output is a new candidate and evidence file.
"""
import ctypes as C,hashlib,json,os,re,shutil,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE/'reader-packages'),str(ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages')]
os.environ.setdefault('OPENBLAS_NUM_THREADS','2')
import numpy as np
import gguf
from experiment import atomic_json,sha,space

SUPPORTED={0,1,8,10,11,12,13,14,30}

class Quantizer:
    def __init__(self):
        proof=json.loads((HERE/'native-abi.json').read_text())
        path=ROOT/'LLM/llamacpp/ggml-base.dll'
        if sha(path)!=proof['libraries']['ggml-base.dll']:raise RuntimeError('Native quantizer does not match the verified build')
        self.dll=C.CDLL(str(path))
        self.quantize=self.dll.ggml_quantize_chunk;self.quantize.restype=C.c_size_t
        self.quantize.argtypes=[C.c_int,C.c_void_p,C.c_void_p,C.c_int64,C.c_int64,C.c_int64,C.c_void_p]
        self.requires=self.dll.ggml_quantize_requires_imatrix;self.requires.restype=C.c_bool;self.requires.argtypes=[C.c_int]

    def blocks(self,values,kind):
        if int(kind) not in SUPPORTED or self.requires(int(kind)):raise ValueError('This quantization requires an unsupported importance matrix or encoder')
        block,encoded=gguf.GGML_QUANT_SIZES[kind]
        values=np.ascontiguousarray(values,dtype=np.float32).reshape(-1,block)
        if not np.isfinite(values).all():raise ValueError('Nonfinite edited values')
        result=np.empty((len(values),encoded),dtype=np.uint8)
        size=self.quantize(int(kind),values.ctypes.data,result.ctypes.data,0,len(values),block,None)
        if size!=result.nbytes:raise RuntimeError('Encoded tensor size changed')
        return result

def inventory(model):
    reader=gguf.GGUFReader(str(Path(model).resolve()),'r');arch=reader.fields['general.architecture'].contents()
    sites=[]
    for tensor in reader.tensors:
        if re.fullmatch(r'blk\.\d+\.ffn_down\.weight',tensor.name) and len(tensor.shape)==2:
            sites.append({'name':tensor.name,'shape':[int(x) for x in reversed(tensor.shape)],'quantization':tensor.tensor_type.name,'editable':int(tensor.tensor_type) in SUPPORTED})
    return {'architecture':arch,'dense_mlp_sites':sites,'compatible':bool(sites) and any(t['editable'] for t in sites),'notes':'Architecture support must also pass native forward and candidate controls. A compatible tensor layout is not evidence of improved behavior.'}

def checked_site(reader,site):
    name=site['tensor'];tensors={t.name:t for t in reader.tensors}
    if not re.fullmatch(r'blk\.\d+\.ffn_down\.weight',name) or name not in tensors:raise ValueError('Only existing dense MLP down projection weights may be edited')
    tensor=tensors[name]
    if len(tensor.shape)!=2 or int(tensor.tensor_type) not in SUPPORTED:raise ValueError('Unsupported tensor shape or quantization')
    width,rows=map(int,tensor.shape)
    if rows>65536 or width>131072:raise ValueError('Selected tensor exceeds the bounded editor shape')
    u=np.asarray(site['direction'],dtype=np.float32);columns=np.asarray(site['columns'])
    coefficients=np.asarray(site['coefficients'],dtype=np.float32)
    if u.shape!=(rows,) or not np.isfinite(u).all() or not .999<=float(np.linalg.norm(u))<=1.001:raise ValueError('Direction must be finite and unit length with one value per output row')
    if columns.ndim!=1 or columns.dtype.kind not in 'iu' or not 1<=len(columns)<=64 or len(set(columns.tolist()))!=len(columns) or np.any(columns<0) or np.any(columns>=width):raise ValueError('Select 1 to 64 unique in-range columns')
    if coefficients.shape!=columns.shape or not np.isfinite(coefficients).all():raise ValueError('Invalid selected-column coefficients')
    return tensor,u,columns.astype(np.int64),coefficients

def validate_recipe(reader,recipe,base_hash):
    if recipe.get('base_sha256')!=base_hash:raise ValueError('Recipe belongs to a different model; directions cannot be transferred between variants')
    if recipe.get('method')!='sparse-projection-subtraction-v1':raise ValueError('Unknown direct-edit recipe')
    dose=recipe.get('dose')
    if type(dose) not in (float,int) or not np.isfinite(dose) or not 0<=dose<=6:raise ValueError('Dose must be finite, between 0 and 6')
    sites=recipe.get('sites',[])
    if not 1<=len(sites)<=2 or len({s['tensor'] for s in sites})!=len(sites):raise ValueError('Choose one or two distinct, causally investigated sites')
    return [checked_site(reader,site) for site in sites]

def row_bytes(tensor):
    rows=int(tensor.shape[1]);return tensor.data.view(np.uint8).reshape(rows,-1)

def projection(model,tensor_name,direction,*,writer_contrast=None,columns=64):
    """Read one matrix in small row chunks; never dequantize the full model."""
    reader=gguf.GGUFReader(str(model),'r');tensor=next(t for t in reader.tensors if t.name==tensor_name)
    width,rows=map(int,tensor.shape);u=np.asarray(direction,dtype=np.float32)
    if u.shape!=(rows,) or not np.isfinite(u).all() or not .999<=np.linalg.norm(u)<=1.001:raise ValueError('Invalid contrast direction')
    values=row_bytes(tensor);p=np.zeros(width,dtype=np.float64);norm2=0.
    for offset in range(0,rows,64):
        w=gguf.quants.dequantize(values[offset:offset+64],tensor.tensor_type).reshape(-1,width)
        p+=u[offset:offset+len(w)].astype(np.float64)@w.astype(np.float64)
        norm2+=float(np.sum(w.astype(np.float64)**2))
    scores=np.abs(p)
    if writer_contrast is not None:
        contrast=np.asarray(writer_contrast,dtype=np.float64)
        if contrast.shape!=p.shape or not np.isfinite(contrast).all():raise ValueError('Invalid writer contrast')
        scores*=np.abs(contrast)
    if not 1<=columns<=64:raise ValueError('At most 64 columns per site')
    selected=np.sort(np.argsort(scores,kind='stable')[-columns:])
    return {'tensor':tensor_name,'direction':u.tolist(),'columns':selected.tolist(),'coefficients':p[selected].tolist(),'matrix_norm':float(np.sqrt(norm2))}

def materialize(model,recipe,output,*,progress=None):
    model=Path(model).resolve(strict=True);output=Path(output).absolute()
    if model.suffix.lower()!='.gguf' or output.suffix.lower()!='.gguf':raise ValueError('Select GGUF input and output files')
    if output.exists() or output.is_symlink() or output.resolve()==model:raise FileExistsError('Candidate output must be a new file')
    output.parent.mkdir(parents=True,exist_ok=True)
    if output.parent.resolve().is_relative_to((ROOT/'LLM/models').resolve()):raise ValueError('Candidates must be evaluated outside the live models folder')
    if any(p.is_symlink() for p in [output.parent,*output.parent.parents]):raise ValueError('Output path must not traverse a symlink')
    partial=output.with_name(output.name+'.partial');receipt=output.with_suffix('.edit.json')
    if partial.exists() or receipt.exists():raise FileExistsError('An earlier candidate artifact needs review; it will not be overwritten')
    space(output.parent,model.stat().st_size+64*1024**2)
    fingerprint=sha(model);reader=gguf.GGUFReader(str(model),'r');sites=validate_recipe(reader,recipe,fingerprint)
    encoder=Quantizer();report=[]
    with model.open('rb') as source,partial.open('xb') as dest:
        shutil.copyfileobj(source,dest,8*1024**2);dest.flush();os.fsync(dest.fileno())
    if sha(partial)!=fingerprint:raise RuntimeError('Candidate copy checksum mismatch; partial evidence retained')
    try:
        with partial.open('r+b',buffering=0) as target:
            for tensor,u,cols,coeff in sites:
                width,rows=map(int,tensor.shape);kind=tensor.tensor_type;block,encoded=gguf.GGML_QUANT_SIZES[kind]
                original=row_bytes(tensor);blocks=np.unique(cols//block);norm2=delta2=rounding2=actual_delta2=0.;changed=changed_values=0
                for start in range(0,rows,32):
                    raw=np.asarray(original[start:start+32]);n=len(raw)
                    weights=gguf.quants.dequantize(raw,kind).reshape(n,width)
                    norm2+=float(np.sum(weights.astype(np.float64)**2))
                    revised=weights.copy();revised[:,cols]-=float(recipe['dose'])*u[start:start+n,None]*coeff[None,:]
                    wanted=(revised-weights).astype(np.float64);delta2+=float(np.sum(wanted**2))
                    if np.any(wanted):
                        active=revised.reshape(n,-1,block)[:,blocks,:]
                        new=encoder.blocks(active,kind).reshape(n,len(blocks),encoded)
                        actual=gguf.quants.dequantize(new.reshape(n,-1),kind).reshape(n,len(blocks),block)
                        rounding2+=float(np.sum((actual.astype(np.float64)-active)**2))
                        actual_delta2+=float(np.sum((actual.astype(np.float64)-weights.reshape(n,-1,block)[:,blocks,:])**2))
                        changed_values+=int(np.count_nonzero(actual!=weights.reshape(n,-1,block)[:,blocks,:]))
                        packed=raw.copy().reshape(n,-1,encoded)
                        changed+=int(np.count_nonzero(packed[:,blocks,:]!=new));packed[:,blocks,:]=new
                        target.seek(tensor.data_offset+start*raw.shape[1]);target.write(packed.tobytes())
                    if progress:progress(tensor.name,start+n,rows)
                relative=float(np.sqrt(delta2/max(norm2,1e-30)))
                actual_relative=float(np.sqrt(actual_delta2/max(norm2,1e-30)))
                if max(relative,actual_relative)>.15:raise ValueError('Direct edit exceeded the 15% per-matrix norm ceiling')
                report.append({'tensor':tensor.name,'quantization':kind.name,'selected_columns':cols.tolist(),'changed_bytes':changed,'intended_scalar_positions':rows*len(cols),'actual_changed_dequantized_values':changed_values,'intended_relative_delta':relative,'actual_relative_delta':actual_relative,'quantization_error_norm':float(np.sqrt(rounding2)),'unchanged_blocks_copied_verbatim':True})
            target.flush();os.fsync(target.fileno())
        if sha(model)!=fingerprint:raise RuntimeError('Original changed during candidate construction')
        result={'format_version':1,'base_model':model.name,'base_sha256':fingerprint,'candidate_sha256':sha(partial),'candidate_bytes':partial.stat().st_size,
                'recipe_sha256':hashlib.sha256(json.dumps(recipe,sort_keys=True).encode()).hexdigest(),'sites':report,'model_scalar_values':sum(t.n_elements for t in reader.tensors),'production_model_changed':False,'validation':'unvalidated candidate','native_quantizer_sha256':sha(ROOT/'LLM/llamacpp/ggml-base.dll')}
        atomic_json(receipt,result);os.replace(partial,output);space(output.parent)
        return result
    except BaseException:
        # Keep an interrupted partial for explicit review, never load it as a model.
        raise
