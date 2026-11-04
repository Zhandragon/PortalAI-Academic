"""Natural outcome localization for an editor to investigate, not auto-promotion.

Contrast captures are a hypothesis. A recipe still needs site isolation, dose
controls, a norm-matched random control and independent confirmation.
"""
import json,re
from pathlib import Path
from native_forward import Forward,metadata,np
from quantized_edit import projection
from experiment import atomic_json,sha,space

def contrast(good,bad):
    good=np.asarray(good,dtype=np.float64);bad=np.asarray(bad,dtype=np.float64)
    if good.ndim!=2 or bad.ndim!=2 or good.shape[1]!=bad.shape[1] or min(len(good),len(bad))<4:raise ValueError('Localization needs at least four natural successes and four natural failures')
    delta=bad.mean(0)-good.mean(0);norm=float(np.linalg.norm(delta))
    if not np.isfinite(delta).all() or norm<1e-8:raise ValueError('No measurable activation contrast')
    u=(delta/norm).astype(np.float32)
    variance=float(np.mean(np.var(good,axis=0,ddof=1)/len(good)+np.var(bad,axis=0,ddof=1)/len(bad)))
    return u,float(norm/np.sqrt(max(variance*len(u),1e-20))),delta

def propose(model,records,work,*,progress=None):
    model=Path(model);work=Path(work);meta=metadata(model)
    good=[r for r in records if r['grading']['correct'] and r['finish']=='stop']
    bad=[r for r in records if not r['grading']['correct']]
    # Stable choice, not selection on contrast size after trying many subsets.
    good=sorted(good,key=lambda r:r['id'])[:8];bad=sorted(bad,key=lambda r:r['id'])[:8]
    if min(len(good),len(bad))<4:raise ValueError('Fewer than four natural successes or failures: collect more discovery cases before proposing a direction.')
    layers=int(meta['layers']);names=[name for layer in range(layers) for name in (f'l_out-{layer}',f'ffn_swiglu-{layer}')]
    total=sum(r['prompt_tokens']+min(8192,r['tokens']) for r in good+bad)
    if total>524288:raise ValueError('Teacher-forced pass token budget exceeded')
    captures={}
    with Forward(model,context=34816,batch=128,capture_names=names) as engine:
        for row in good+bad:
            space(work);capture=engine.capture_replay(row['prompt'],row['token_ids'])
            captures[row['id']]=capture
            if progress:progress({'captured':row['id'],'correct':row['grading']['correct']})
    scores=[]
    for layer in range(layers):
        key=f'answer/l_out-{layer}';writer=f'answer/ffn_swiglu-{layer}'
        u,score,_=contrast([captures[r['id']][key] for r in good],[captures[r['id']][key] for r in bad])
        wdelta=np.mean([captures[r['id']][writer] for r in bad],axis=0)-np.mean([captures[r['id']][writer] for r in good],axis=0)
        scores.append({'layer':layer,'contrast_signal_to_noise':score,'direction':u,'writer_contrast':wdelta})
    ranked=sorted(scores,key=lambda r:r['contrast_signal_to_noise'],reverse=True)
    # Expose all site measurements. Initial candidates remain hypotheses.
    evidence={'base_sha256':sha(model),'good_ids':[r['id'] for r in good],'bad_ids':[r['id'] for r in bad],
              'teacher_forced_tokens':total,'sites':[{'layer':r['layer'],'contrast_signal_to_noise':r['contrast_signal_to_noise']} for r in ranked],
              'limits':'Unpaired natural outcome contrast may reflect problem difficulty or topic. Causal controls are required; no intelligence or deployment conclusion follows from this ranking.'}
    atomic_json(work/'localization.json',evidence)
    arrays={}
    for label,rows in [('good',good),('bad',bad)]:
        for name in names:arrays[label+'/'+name]=np.stack([captures[r['id']]['answer/'+name] for r in rows])
    np.savez(work/'activation-means.npz',**arrays)
    recipes=[]
    for rank,row in enumerate(ranked[:3]):
        site=projection(model,f"blk.{row['layer']}.ffn_down.weight",row['direction'],writer_contrast=row['writer_contrast'])
        recipe={'method':'sparse-projection-subtraction-v1','base_sha256':evidence['base_sha256'],'dose':1.,'sites':[site],
                'evidence_sha256':sha(work/'localization.json'),'status':'Unvalidated hypothesis; requires causal tests and unseen confirmation.'}
        path=work/f'candidate-site-{rank+1}.json';atomic_json(path,recipe);recipes.append(path.name)
    return {'recipes':recipes,'evidence':'localization.json','production_model_changed':False}
