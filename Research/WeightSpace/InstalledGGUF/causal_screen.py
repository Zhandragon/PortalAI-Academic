"""Natural-case forward diagnostics, site/dose isolation and random controls.

LoRA represents a causal delta without extra full model copies. It does not
establish serialized GGUF quality: any selected hypothesis is then directly
materialized and generated natively before it can qualify for confirmation.
"""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json,time
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2];ENGINE=ROOT/'Tools/WeightSpace'
sys.path[:0]=[str(LAB),str(ENGINE),str(ROOT/'Agent')]
import research_guard
research_guard.LAB=LAB
from native_forward import Forward,metadata,np
from experiment import Ledger,sha,space,atomic_json
from sparse_edit import save_adapter
from service_manager import acquire_gpu_lease,release_gpu_lease
from diagnosis import propose

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);args=parser.parse_args()
    spec=json.loads((LAB/'protocol.json').read_text())['models'][args.model]
    model=ROOT/'LLM/models'/spec['filename'];folder=LAB/'experiments'/args.model
    status=folder/'EXTENDED-STATUS.json'
    if status.is_file() and json.loads(status.read_text()).get('qualified') is False:
        if (folder/'002-localization/localization.json').exists():raise RuntimeError('Conflicting localization admission evidence')
        print(json.dumps({'model':args.model,'causal_screen_not_admitted':True,'reason':'Insufficient natural success/failure contrast; retain the original.'}),flush=True)
        return
    from extend_discovery import records as read_records
    records=read_records(folder)
    ledger=Ledger(folder/'ledger.sqlite');fingerprint=sha(model)
    lease=acquire_gpu_lease('weight-space-causal-'+args.model,timeout=3)
    try:
        localization=folder/'002-localization'
        if not localization.exists():
            localization.mkdir()
            request={'base_sha256':fingerprint,'source_pass':'001-natural-discovery','method':'native outcome contrast and all-layer replay'}
            ledger.begin('002-localization','discovery',request)
            try:
                result=propose(model,records,localization,progress=lambda row:print(json.dumps(row),flush=True));ledger.end('002-localization',result)
            except ValueError as exc:
                ledger.end('002-localization',{'not_admitted':str(exc)})
                atomic_json(folder/'CAUSAL-STATUS.json',{'qualified':False,'reason':str(exc),'production_model_changed':False});return
        recipes=sorted(localization.glob('candidate-site-*.json'))
        if not recipes:raise RuntimeError('No complete localization recipes; inspect earlier evidence')
        loc=json.loads((localization/'localization.json').read_text());ids=loc['good_ids']+loc['bad_ids']
        recordmap={r['id']:r for r in records}
        with (LAB/'practice.jsonl').open(encoding='utf-8') as stream:practice={r['id']:r for r in map(json.loads,stream) if r['id'] in ids}
        out=folder/'003-causal-screen';out.mkdir(exist_ok=False)
        adapters=[];rng=np.random.default_rng(2026110301)
        for path in recipes:
            recipe=json.loads(path.read_text());site=recipe['sites'][0];u=np.asarray(site['direction'],dtype=np.float32)
            width=next(r['shape'][1] for r in __import__('quantized_edit').inventory(model)['dense_mlp_sites'] if r['name']==site['tensor'])
            fa=np.zeros((1,width),dtype=np.float32);fa[0,site['columns']]=np.asarray(site['coefficients'],dtype=np.float32)
            fb=-u[:,None];random=rng.normal(size=len(u)).astype(np.float32);random-=u*float(u@random);random/=np.linalg.norm(random)
            for control,b in [(False,fb),(True,-random[:,None])]:
                dest=out/(path.stem+('-random' if control else '')+'.gguf')
                save_adapter(dest,spec['architecture'],[(site['tensor'],fa,b)],{'base_model_sha256':fingerprint,'control':control,'source_recipe':path.name})
                adapters.append({'path':dest,'control':control,'recipe':path,'tensor':site['tensor']})
        with Forward(model,context=34816,batch=128) as engine:
            texts=[]
            for identifier in ids:
                row=practice[identifier];saved=recordmap[identifier];solution=row.get('solution') or str(row['answer'])
                target='<think>\n'+solution+'\n</think>\n\\boxed{'+str(row['answer'])+'}<|im_end|>'
                prompt_tokens=engine.tokenize(saved['prompt']);tokens=engine.tokenize(saved['prompt']+target)
                if len(tokens)>32768:raise ValueError('Reference solution exceeds published teacher-forcing text cap')
                texts.append({'id':identifier,'tokens':tokens,'loss_from':len(prompt_tokens),'natural_correct':saved['grading']['correct'],'reference_type':'worked_solution' if row.get('solution') else 'answer_only'})
            total=sum(len(t['tokens']) for t in texts)
            if total>524288:raise ValueError('Teacher-forced pass exceeds published aggregate token cap')
            atomic_json(out/'cases.json',{'ids':ids,'tokens':total,'reference_types':{t['id']:t['reference_type'] for t in texts},'target':'Worked solution where available, otherwise answer only, with explicit thinking/final formatting. Diagnostic loss only, not answer accuracy or natural reasoning likelihood.','good_ids':loc['good_ids'],'bad_ids':loc['bad_ids']})
            def evaluate(identifier,adapter=None,dose=0):
                request={'base_sha256':fingerprint,'ids':ids,'reference_format':'boxed-v1','adapter_sha256':sha(adapter) if adapter else None,'dose':dose,'type':'teacher_forced','total_tokens':total}
                if not ledger.begin(identifier,'discovery',request):return json.loads((out/(identifier+'.json')).read_text())
                start=time.monotonic()
                try:
                    engine.adapter(adapter,dose) if adapter else engine.adapter()
                    values={t['id']:engine.evaluate(t['tokens'],loss_from=t['loss_from'],capture=False)['loss'] for t in texts}
                    result={'losses':values,'mean_reference_nll':float(np.mean(list(values.values()))),'seconds':time.monotonic()-start,'request':request}
                    atomic_json(out/(identifier+'.json'),result);ledger.end(identifier,{'mean_reference_nll':result['mean_reference_nll']})
                    print(json.dumps({'pass':identifier,'mean_reference_nll':result['mean_reference_nll'],'seconds':round(result['seconds'],2)}),flush=True)
                    return result
                except BaseException as exc:ledger.end(identifier,{'error':repr(exc)},False);raise
            base=evaluate('003-reference-baseline');results=[]
            zero=evaluate('004-zero-dose',adapters[0]['path'],0)
            if max(abs(zero['losses'][k]-base['losses'][k]) for k in ids)>.001:raise RuntimeError('Zero-dose adapter changes the baseline beyond tolerance')
            counter=5
            for adapter in adapters:
                for dose in ([1.,4.] if adapter['control'] else [.5,1.,2.,4.,6.]):
                    result=evaluate(f'{counter:03d}-'+adapter['path'].stem+'-dose-'+str(dose),adapter['path'],dose);counter+=1
                    delta={key:result['losses'][key]-base['losses'][key] for key in ids}
                    row={'recipe':adapter['recipe'].name,'control':adapter['control'],'tensor':adapter['tensor'],'dose':dose,'mean_delta':float(np.mean(list(delta.values()))),'good_delta':float(np.mean([delta[k] for k in loc['good_ids']])),'bad_delta':float(np.mean([delta[k] for k in loc['bad_ids']]))}
                    results.append(row)
            candidates=[r for r in results if not r['control'] and r['good_delta']<=.01]
            best=min(candidates,key=lambda r:r['mean_delta']) if candidates else None
            report={'baseline_reference_nll':base['mean_reference_nll'],'dose_results':results,'selected_for_generation':best,
                    'meaning':'Loss screen selects a hypothesis for native quantized generation; no task accuracy or intelligence improvement established.','production_model_changed':False}
            atomic_json(out/'summary.json',report)
            if best:
                recipe=json.loads((localization/best['recipe']).read_text());recipe['dose']=best['dose'];recipe['causal_screen_sha256']=sha(out/'summary.json')
                atomic_json(folder/'selected-recipe.json',recipe)
            print(json.dumps(report),flush=True)
    finally:release_gpu_lease(lease);ledger.close()

if __name__=='__main__':main()
