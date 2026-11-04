"""Freeze once, then test 1,152 unique unseen practice questions without retuning."""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json,gc,time
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2];ENGINE=ROOT/'Tools/WeightSpace'
sys.path[:0]=[str(LAB),str(ENGINE),str(ROOT/'Agent')]
import research_guard
research_guard.LAB=LAB
from native_forward import Forward,metadata,render,item_seed
from quantized_edit import materialize
from evaluation import grade
from experiment import Ledger,atomic_json,sha,space,paired_summary
from service_manager import acquire_gpu_lease,release_gpu_lease

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);a=p.parse_args()
    folder=LAB/'experiments'/a.model;screen=folder/'004-generation-screen/summary.json'
    summary=json.loads(screen.read_text())
    if not summary['eligible_for_independent_confirmation']:
        print(json.dumps({'model':a.model,'confirmation_not_admitted':True}));return
    protocol=json.loads((LAB/'protocol.json').read_text());spec=protocol['models'][a.model]
    model=ROOT/'LLM/models'/spec['filename'];recipe_path=folder/'selected-recipe.json';recipe=json.loads(recipe_path.read_text())
    original_sha=sha(model);assert recipe['base_sha256']==original_sha
    out=folder/'005-independent-confirmation';out.mkdir(exist_ok=False)
    # Freeze identities before opening the confirmation questions/answers.
    frozen={'model':a.model,'base_sha256':original_sha,'recipe_sha256':sha(recipe_path),'recipe':recipe,
            'discovery_summary_sha256':sha(screen),'split_sha256':sha(LAB/'splits.json'),'sampling':spec['sampling'],
            'independent_question_count':1152,'retuning_after_confirmation':False,'frozen_at_unix':time.time()}
    atomic_json(out/'frozen.json',frozen)
    ids=json.loads((LAB/'splits.json').read_text())['confirmation_ids'];assert len(ids)==len(set(ids))==1152
    with (LAB/'practice.jsonl').open(encoding='utf-8') as stream:rows={r['id']:r for r in map(json.loads,stream) if r['id'] in ids}
    assert len(rows)==1152
    normalize=lambda text:' '.join(text.casefold().split())
    assert len({normalize(row['problem']) for row in rows.values()})==1152
    from extend_discovery import records
    seen=records(folder);seen_ids={r['id'] for r in seen};assert not seen_ids&set(ids)
    with (LAB/'practice.jsonl').open(encoding='utf-8') as stream:seen_text={normalize(r['problem']) for r in map(json.loads,stream) if r['id'] in seen_ids}
    assert not seen_text & {normalize(r['problem']) for r in rows.values()}
    ledger=Ledger(folder/'ledger.sqlite');lease=None;candidate=out/'candidate.gguf';results={};times={};cutoffs={}
    try:
        space(LAB,model.stat().st_size);lease=acquire_gpu_lease('weight-space-confirmation-'+a.model,timeout=3)
        ledger.begin('confirmation-materialize','cpu',frozen)
        try:receipt=materialize(model,recipe,candidate);ledger.end('confirmation-materialize',receipt)
        except BaseException as exc:ledger.end('confirmation-materialize',{'error':repr(exc)},False);raise
        expected=summary['model_receipts']['candidate']['candidate_sha256'];assert receipt['candidate_sha256']==expected,'Frozen candidate bytes differ'
        frozen['candidate_sha256']=expected;atomic_json(out/'candidate-identity.json',frozen)
        for arm,path in [('baseline',model),('candidate',candidate)]:
            arm_dir=out/arm;arm_dir.mkdir();results[arm]={};times[arm]=0.;cutoffs[arm]=0
            meta=metadata(path)
            with Forward(path,context=34816,batch=256) as engine:
                for batch_start in range(0,len(ids),256):
                    batch_ids=ids[batch_start:batch_start+256];identifier=f'confirmation-{arm}-{batch_start//256:02d}'
                    request={'ids':batch_ids,'base_sha256':original_sha,'candidate_sha256':expected,'sampling':spec['sampling'],'frozen_sha256':sha(out/'candidate-identity.json')}
                    ledger.begin(identifier,'confirmation',request)
                    try:
                        for key in batch_ids:
                            research_guard.require_gpu_unpaused();space(LAB)
                            row=rows[key];prompt=render(meta['template'],[{'role':'user','content':row['problem']+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}])
                            settings={k:v for k,v in spec['sampling'].items() if k!='thinking'}
                            value=engine.generate(prompt,seed=item_seed(key),**settings);value.pop('activations')
                            value.update(id=key,source=row['source'],grading=grade({'kind':'math','answer':row['answer']},value['text']))
                            atomic_json(arm_dir/(hashlib.sha256(key.encode()).hexdigest()[:20]+'.json'),value)
                            results[arm][key]=value['grading']['correct'];times[arm]+=value['seconds'];cutoffs[arm]+=value['finish']=='length'
                            print(json.dumps({'model':a.model,'phase':'confirmation','arm':arm,'completed':len(results[arm]),'total':1152}),flush=True)
                        ledger.end(identifier,{'cases':len(batch_ids),'correct':sum(results[arm][k] for k in batch_ids)})
                    except BaseException as exc:ledger.end(identifier,{'error':repr(exc)},False);raise
        paired=paired_summary(results['baseline'],results['candidate']);eligible=paired['lower_95']>0
        report={'paired':paired,'eligible_for_separate_final_benchmarks':eligible,'latency_ratio':times['candidate']/times['baseline'],'cutoffs':cutoffs,
                'frozen_candidate_sha256':expected,'base_unchanged':sha(model)==original_sha,'production_model_changed':False,
                'status':'Independent practice confirmation passed; separate final broad benchmarks still required.' if eligible else 'Independent evidence did not establish improvement. Retain the original; this holdout is consumed and cannot be used to tune a new claim.'}
        atomic_json(out/'summary.json',report)
        gc.collect()
        if candidate.parent.resolve()!=out.resolve() or sha(candidate)!=expected:raise RuntimeError('Disposable candidate identity changed; retain it')
        candidate.unlink();atomic_json(out/'candidate-retired.json',{'sha256':expected,'reason':'Comparison complete; frozen recipe recreates exact bytes.','original_modified':False})
        print(json.dumps(report),flush=True)
    finally:
        if lease:release_gpu_lease(lease)
        ledger.close()

if __name__=='__main__':main()
