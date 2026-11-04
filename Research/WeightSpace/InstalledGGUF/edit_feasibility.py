"""CPU admission of the already-scored site/dose grid, without model copies.

Rank only by existing discovery loss, then enforce the unchanged editor's 15%
matrix-norm bound for both the exact quantized edit and its random control.
No generated candidate answers or held-out outcomes inform this admission.
"""
import json,sys
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2]
sys.path[:0]=[str(ROOT/'Tools/WeightSpace')]
from quantized_edit import Quantizer,gguf,np,row_bytes,validate_recipe
from experiment import sha,atomic_json

def random_control(recipe):
    result=json.loads(json.dumps(recipe));rng=np.random.default_rng(2026110301)
    for site in result['sites']:
        u=np.asarray(site['direction'],dtype=np.float32);v=rng.normal(size=len(u)).astype(np.float32)
        v-=u*float(v@u);v/=np.linalg.norm(v);site['direction']=v.tolist()
    result['control']='orthogonal norm-matched direction'
    return result

def probe(model,recipe,fingerprint):
    reader=gguf.GGUFReader(str(model),'r');sites=validate_recipe(reader,recipe,fingerprint)
    encoder=Quantizer();results=[]
    for tensor,u,cols,coeff in sites:
        width,rows=map(int,tensor.shape);kind=tensor.tensor_type;block,encoded=gguf.GGML_QUANT_SIZES[kind]
        original=row_bytes(tensor);blocks=np.unique(cols//block);norm2=delta2=actual_delta2=0.
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
                actual_delta2+=float(np.sum((actual.astype(np.float64)-weights.reshape(n,-1,block)[:,blocks,:])**2))
        intended=float(np.sqrt(delta2/max(norm2,1e-30)));actual=float(np.sqrt(actual_delta2/max(norm2,1e-30)))
        results.append({'tensor':tensor.name,'dose':recipe['dose'],'intended_relative_delta':intended,'actual_relative_delta':actual,'within_bound':max(intended,actual)<=.15})
    return {'admitted':all(r['within_bound'] for r in results),'sites':results,'matrix_norm_ceiling':.15,'GPU_loaded':False,'model_copy_created':False}

def choose(model,localization,results,out,ledger,*,prefix='cpu-feasibility'):
    fingerprint=sha(model);attempts=[]
    candidates=sorted((r for r in results if not r['control'] and r['good_delta']<=.01),key=lambda r:r['mean_delta'])
    for index,row in enumerate(candidates):
        recipe=json.loads((localization/row['recipe']).read_text());recipe['dose']=row['dose']
        identifier=prefix+'-'+str(index)
        request={'recipe':recipe,'base_sha256':fingerprint,'norm_ceiling':.15,'includes_norm_matched_control':True}
        assert ledger.begin(identifier,'cpu',request),'Feasibility evidence already exists; reconcile explicitly'
        try:
            edited=probe(model,recipe,fingerprint);control=probe(model,random_control(recipe),fingerprint)
            evidence={'rank':index,'discovery_loss_result':row,'candidate':edited,'random_control':control,'admitted':edited['admitted'] and control['admitted']}
            atomic_json(out/(identifier+'.json'),evidence);ledger.end(identifier,evidence)
        except BaseException as exc:ledger.end(identifier,{'error':repr(exc)},False);raise
        attempts.append(evidence)
        if evidence['admitted']:
            assert sha(model)==fingerprint,'Original changed during feasibility checks'
            return row,attempts
    assert sha(model)==fingerprint,'Original changed during feasibility checks'
    return None,attempts
