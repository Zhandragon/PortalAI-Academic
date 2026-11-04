"""Generate from actual serialized edits, with a quantized random-direction control."""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json,time,gc
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2];ENGINE=ROOT/'Tools/WeightSpace'
sys.path[:0]=[str(LAB),str(ENGINE),str(ROOT/'Agent')]
import research_guard
research_guard.LAB=LAB
from native_forward import Forward,metadata,render,item_seed,np
from quantized_edit import materialize
from research_grading import grade
from experiment import Ledger,atomic_json,sha,space,paired_summary
from service_manager import acquire_gpu_lease,release_gpu_lease

def verify_feasibility_resume(folder,model,cases):
    """Accept only the checksummed, reviewed norm rejection with a complete baseline."""
    out=folder/'004-generation-screen';saved=json.loads((out/'feasibility-resume.json').read_text())
    assert saved['model']==folder.name=='4-standard'
    assert saved['base_sha256']==sha(model)
    assert saved['selected_recipe_sha256']==sha(folder/'selected-recipe.json')
    assert saved['random_recipe_sha256']==sha(out/'random-recipe.json')
    assert saved['cases_sha256']==sha(out/'cases.json') and json.loads((out/'cases.json').read_text())==cases
    assert saved['baseline_request_sha256']==sha(out/'baseline/request.json')
    assert not (out/'summary.json').exists() and not (out/'candidate').exists() and not (out/'random').exists()
    original={}
    for name,expected in saved['baseline_records'].items():
        path=out/'baseline'/name
        assert path.name==hashlib.sha256(expected['id'].encode()).hexdigest()[:20]+'.json' and sha(path)==expected['sha256']
        value=json.loads(path.read_text());assert value['id']==expected['id'] and type(value['grading']['correct']) is bool
        original[value['id']]=value
    assert set(original)=={case['id'] for case in cases}
    rejected=out/saved['rejected_partial']['path']
    assert rejected.resolve().parent==(out/'rejected-candidate-dose4').resolve()
    assert sha(rejected)==saved['rejected_partial']['sha256']
    ledger=Ledger(folder/'ledger.sqlite')
    try:
        assert ledger.db.execute("SELECT status FROM runs WHERE id='gen-screen-baseline'").fetchone()==('complete',)
        assert not ledger.db.execute("SELECT id FROM runs WHERE id IN ('gen-screen-candidate','gen-screen-random')").fetchall()
    finally:ledger.close()
    return original

def broad_cases():
    frozen=LAB/'discovery-broad.json'
    if frozen.is_file():return json.loads(frozen.read_text(encoding='utf-8'))
    # These are discovery regressions, not the unopened final benchmarks.
    sys.path.insert(0,str(LAB.parent/'Weight-Space-20261103'))
    from benchmark import cases,TOOLS
    output=[]
    for row in cases('selection'):
        case={'id':'discovery-broad-'+row['id'],'prompt':row['prompt'],'domain':row['area']}
        if row['area']=='coding':case.update(kind='coding',checks=row['checks'])
        elif row['area']=='tool_use':case.update(kind='tool',tools=TOOLS,calls=[{'name':row['tool'],'arguments':row['args']}])
        elif isinstance(row['answer'],(int,float)):
            case.update(kind='math',prompt=row['prompt'].split('End with FINAL:')[0]+'Put your final answer in \\boxed{}.',answer=str(row['answer']))
        else:
            case.update(kind='exact',prompt=row['prompt'].split('Answer FINAL:')[0].split('End with FINAL:')[0]+' Return only the correct label, with no explanation: '+('IMPOSSIBLE or POSSIBLE.' if row['answer']=='IMPOSSIBLE' else 'A, B, or NEITHER.'),answer=row['answer'])
        output.append(case)
    for index,(prompt,answer) in enumerate([
       ('Return only JSON with keys name and count. Set name to PortalAI and count to the number of letters in NICE.',{'name':'PortalAI','count':4}),
       ('Return exactly three lines: Ready on line one, Set on line two, Go on line three. No punctuation.','Ready\nSet\nGo'),
       ('Sort the numbers 9, 2, 6, 2 ascending. Return only a JSON array.',[2,2,6,9]),
       ('Respond with exactly this sentence and nothing else: I will verify the result before declaring success.','I will verify the result before declaring success.')]):
        output.append({'id':'discovery-instruction-'+str(index),'kind':'exact' if isinstance(answer,str) else 'json','domain':'instruction','prompt':prompt,'answer':answer})
    return output

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True);parser.add_argument('--resume-feasibility',action='store_true');args=parser.parse_args()
    spec=json.loads((LAB/'protocol.json').read_text())['models'][args.model];folder=LAB/'experiments'/args.model
    model=ROOT/'LLM/models'/spec['filename'];chosen=folder/'selected-recipe.json'
    if not chosen.exists():print('No eligible recipe');return
    recipe=json.loads(chosen.read_text());fingerprint=sha(model)
    if recipe['base_sha256']!=fingerprint:raise ValueError('Selected recipe/base mismatch')
    loc=json.loads((folder/'002-localization/localization.json').read_text())
    ids=loc['bad_ids']+loc['good_ids'][:len(loc['bad_ids'])]
    with (LAB/'practice.jsonl').open(encoding='utf-8') as stream:practice={r['id']:r for r in map(json.loads,stream) if r['id'] in ids}
    cases=[{'id':identifier,'domain':'math','kind':'math','prompt':practice[identifier]['problem']+'\nPlease reason step by step, and put your final answer within \\boxed{}.', 'answer':practice[identifier]['answer']} for identifier in ids]+broad_cases()
    out=folder/'004-generation-screen';resumed_baseline=None
    if args.resume_feasibility:resumed_baseline=verify_feasibility_resume(folder,model,cases)
    else:out.mkdir(exist_ok=False);atomic_json(out/'cases.json',cases)
    from extend_discovery import records as read_records
    original_records={r['id']:r for r in read_records(folder)}
    ledger=Ledger(folder/'ledger.sqlite');lease=None;results={};timings={};receipts={}
    from edit_feasibility import random_control
    random_recipe=random_control(recipe)
    if args.resume_feasibility:assert json.loads((out/'random-recipe.json').read_text())==random_recipe
    else:atomic_json(out/'random-recipe.json',random_recipe)
    try:
        lease=acquire_gpu_lease('weight-space-generation-'+args.model,timeout=3)
        for arm,current_recipe in [('baseline',None),('candidate',recipe),('random',random_recipe)]:
            research_guard.require_gpu_unpaused();space(LAB)
            if arm=='baseline' and resumed_baseline is not None:
                results[arm]={k:v['grading']['correct'] for k,v in resumed_baseline.items()}
                timings[arm]={k:v['seconds'] for k,v in resumed_baseline.items()}
                print(json.dumps({'baseline_reused':len(results[arm]),'checkpoint_verified':True}),flush=True)
                continue
            arm_dir=out/arm;arm_dir.mkdir();path=model
            if current_recipe is not None:
                path=arm_dir/'candidate.gguf';cpu_id='cpu-materialize-'+arm+('-feasible' if args.resume_feasibility else '')
                ledger.begin(cpu_id,'cpu',{'recipe':current_recipe,'base_sha256':fingerprint})
                try:receipts[arm]=materialize(model,current_recipe,path);ledger.end(cpu_id,receipts[arm])
                except BaseException as exc:ledger.end(cpu_id,{'error':repr(exc)},False);raise
            pass_id='gen-screen-'+arm;request={'base_sha256':fingerprint,'model_sha256':sha(path),'case_sha256':sha(out/'cases.json'),'sampling':spec['sampling']}
            ledger.begin(pass_id,'discovery',request);atomic_json(arm_dir/'request.json',request)
            results[arm]={};timings[arm]={}
            try:
                meta=metadata(path)
                with Forward(path,context=34816,batch=256) as engine:
                    for case in cases:
                        research_guard.require_gpu_unpaused();space(LAB)
                        if arm=='baseline' and case['id'] in original_records:
                            saved=original_records[case['id']];value={k:v for k,v in saved.items() if k!='activations'}
                            value['reused_from']='001-natural-discovery (identical input and seed)'
                        else:
                            prompt=render(meta['template'],[{'role':'user','content':case['prompt']}],tools=case.get('tools'))
                            settings={k:v for k,v in spec['sampling'].items() if k!='thinking'}
                            value=engine.generate(prompt,seed=item_seed(case['id']),progress=lambda n,seconds:print(json.dumps({'arm':arm,'progress':case['id'],'tokens':n,'seconds':round(seconds,1)}),flush=True) if n%8192==0 else None,**settings)
                            value.pop('activations');value['grading']=grade(case,value['text']);value['id']=case['id']
                        value['domain']=case['domain'];atomic_json(arm_dir/(hashlib.sha256(case['id'].encode()).hexdigest()[:20]+'.json'),value)
                        results[arm][case['id']]=value['grading']['correct'];timings[arm][case['id']]=value['seconds']
                        print(json.dumps({'arm':arm,'id':case['id'],'correct':value['grading']['correct'],'tokens':value['tokens'],'seconds':round(value['seconds'],1)}),flush=True)
                ledger.end(pass_id,{'correct':sum(results[arm].values()),'total':len(cases),'model_sha256':request['model_sha256']})
            except BaseException as exc:ledger.end(pass_id,{'error':repr(exc)},False);raise
            if arm!='baseline':
                gc.collect()
                if arm=='candidate':
                    from edit_profiles import export_profile
                    profile=export_profile(ROOT,model,path,current_recipe,label=args.model+' discovery experiment')
                    atomic_json(arm_dir/'edit-profile.json',profile)
                # Delete only this fully evaluated, reproducible disposable copy.
                # The exact recipe, checksum, quantization receipt and all results remain.
                if path.parent.resolve()!=arm_dir.resolve() or path.name!='candidate.gguf' or sha(path)!=receipts[arm]['candidate_sha256']:raise RuntimeError('Disposable candidate identity changed; retain it')
                path.unlink();atomic_json(arm_dir/'candidate-retired.json',{'sha256':receipts[arm]['candidate_sha256'],'reason':'Completed disposable comparison; recipe can recreate these exact bytes.','original_modified':False})
        by_domain={}
        for domain in sorted({c['domain'] for c in cases}):
            keys=[c['id'] for c in cases if c['domain']==domain]
            by_domain[domain]=paired_summary({k:results['baseline'][k] for k in keys},{k:results['candidate'][k] for k in keys})
        paired=paired_summary(results['baseline'],results['candidate']);control=paired_summary(results['baseline'],results['random'])
        qualified=paired['gain']>0 and sum(results['candidate'].values())>sum(results['random'].values()) and all(row['gain']>=0 for row in by_domain.values())
        summary={'paired':paired,'random_control':control,'domains':by_domain,'eligible_for_independent_confirmation':qualified,
                 'feasibility_resume':args.resume_feasibility,'feasibility_decision_sha256':sha(out/'feasibility-decision.json') if args.resume_feasibility else None,
                 'latency_ratio':sum(timings['candidate'].values())/sum(timings['baseline'].values()),'model_receipts':receipts,
                 'status':'Promising discovery result; independent confirmation and separate final benchmarks still required.' if qualified else 'Tested hypothesis did not pass the discovery screen. No production replacement.',
                 'production_model_changed':False}
        atomic_json(out/'summary.json',summary);print(json.dumps(summary),flush=True)
    finally:
        if lease:release_gpu_lease(lease)
        ledger.close()

if __name__=='__main__':main()
