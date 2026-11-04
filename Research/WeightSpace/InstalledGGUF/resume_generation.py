"""Resume only missing inference cases after an explicitly reviewed GPU pause.

Complete arms and case files are immutable. An unfinished inference restarts
from its original per-item seed; benchmark tool calls are never executed.
This script never removes GPU-PAUSED.json and cannot resume while it exists.
"""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json,sqlite3,time,gc
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2]
sys.path[:0]=[str(LAB),str(ROOT/'Tools/WeightSpace'),str(ROOT/'Agent')]
from experiment import Ledger,atomic_json,sha,space,paired_summary
import research_guard
research_guard.LAB=LAB

def inspect(model_name):
    checkpoint=ROOT/'Maintenance/Validation/Weight-Profiles-r65/GPU-PAUSE-CHECKPOINT.json'
    state=json.loads(checkpoint.read_text());saved=state['models'][model_name]
    folder=LAB/'experiments'/model_name;out=folder/'004-generation-screen'
    if (out/'summary.json').exists():raise RuntimeError('This screen is already complete; do not replay it')
    for name in ('selected-recipe.json','004-generation-screen/cases.json'):
        assert sha(folder/name)==saved[name]['sha256'],'Frozen recipe/cases changed'
    cases=json.loads((out/'cases.json').read_text());ids={row['id'] for row in cases};assert len(ids)==len(cases)
    arms={}
    for arm in ('baseline','candidate','random'):
        arms[arm]={};expected=saved['generation_arms'][arm]['records']
        for row in expected:
            path=out/arm/row['file'];assert path.name==hashlib.sha256(row['id'].encode()).hexdigest()[:20]+'.json'
            assert sha(path)==row['sha256'],'Saved case changed: '+row['id']
            value=json.loads(path.read_text());assert value['id']==row['id'] and value['id'] in ids and type(value['grading']['correct']) is bool
            arms[arm][value['id']]=value
        actual=set()
        for path in (out/arm).glob('*.json'):
            value=json.loads(path.read_text())
            if 'id' in value and 'grading' in value:actual.add(value['id'])
        assert actual==set(arms[arm]),'Uncheckpointed case files require review'
    assert set(arms['baseline'])==set(arms['candidate'])==ids
    assert set(arms['random'])<ids
    request=json.loads((out/'random/request.json').read_text())
    assert request['case_sha256']==sha(out/'cases.json')
    spec=json.loads((LAB/'protocol.json').read_text())['models'][model_name]
    assert request['sampling']==spec['sampling']
    candidate=out/'random/candidate.gguf';receipt=json.loads(candidate.with_suffix('.edit.json').read_text())
    assert sha(candidate)==request['model_sha256']==receipt['candidate_sha256']==saved['generation_arms']['random']['retained_candidate']['sha256']
    model=ROOT/'LLM/models'/spec['filename'];assert sha(model)==request['base_sha256']==receipt['base_sha256']
    with sqlite3.connect(folder/'ledger.sqlite') as db:
        for arm in ('baseline','candidate'):
            assert db.execute('SELECT status FROM runs WHERE id=?',('gen-screen-'+arm,)).fetchone()==('complete',)
        rows=db.execute("SELECT id,status,evidence FROM runs WHERE id='gen-screen-random' OR id LIKE 'gen-screen-random-resume-%'").fetchall()
    assert rows and all(row[1]=='interrupted' and 'ResearchPaused' in (row[2] or '') for row in rows),'Only explicit pause interruptions are eligible'
    return {'checkpoint':checkpoint,'folder':folder,'out':out,'cases':cases,'arms':arms,'request':request,'spec':spec,'model':model,'candidate':candidate,'resume_number':len(rows)}

def resume(model_name,info):
    research_guard.require_gpu_unpaused();space(LAB)
    from service_manager import acquire_gpu_lease,release_gpu_lease
    from native_forward import Forward,metadata,render,item_seed
    from evaluation import grade
    out=info['out'];arms=info['arms'];pending=[case for case in info['cases'] if case['id'] not in arms['random']]
    ledger=Ledger(info['folder']/'ledger.sqlite');lease=None;identifier='gen-screen-random-resume-'+str(info['resume_number'])
    request={'original_request':info['request'],'checkpoint_sha256':sha(info['checkpoint']),'completed_ids':sorted(arms['random']),
             'pending_ids':[row['id'] for row in pending],'unfinished_case_restarts_from_original_seed':True}
    try:
        lease=acquire_gpu_lease('weight-space-reviewed-resume-'+model_name,timeout=3)
        ledger.begin(identifier,'discovery',request);atomic_json(out/'random'/(identifier+'-request.json'),request)
        try:
            meta=metadata(info['candidate'])
            with Forward(info['candidate'],context=34816,batch=256) as engine:
                for case in pending:
                    research_guard.require_gpu_unpaused();space(LAB)
                    path=out/'random'/(hashlib.sha256(case['id'].encode()).hexdigest()[:20]+'.json')
                    if path.exists():raise RuntimeError('A case appeared outside the reviewed checkpoint')
                    prompt=render(meta['template'],[{'role':'user','content':case['prompt']}],tools=case.get('tools'))
                    settings={k:v for k,v in info['spec']['sampling'].items() if k!='thinking'}
                    value=engine.generate(prompt,seed=item_seed(case['id']),progress=lambda n,seconds:print(json.dumps({'arm':'random','progress':case['id'],'tokens':n,'seconds':round(seconds,1)}),flush=True) if n%8192==0 else None,**settings)
                    value.pop('activations');value.update(id=case['id'],domain=case['domain'],grading=grade(case,value['text']))
                    if path.exists():raise RuntimeError('A case appeared during inference; existing file preserved')
                    atomic_json(path,value);arms['random'][case['id']]=value
                    print(json.dumps({'arm':'random','id':case['id'],'correct':value['grading']['correct'],'tokens':value['tokens'],'resumed':True}),flush=True)
            ledger.end(identifier,{'newly_completed':len(pending),'total_cases':len(arms['random']),'original_request_retained':True})
        except BaseException as exc:ledger.end(identifier,{'error':repr(exc)},False);raise
        scores={arm:{key:value['grading']['correct'] for key,value in rows.items()} for arm,rows in arms.items()}
        domains={}
        for domain in sorted({case['domain'] for case in info['cases']}):
            keys=[case['id'] for case in info['cases'] if case['domain']==domain]
            domains[domain]=paired_summary({k:scores['baseline'][k] for k in keys},{k:scores['candidate'][k] for k in keys})
        paired=paired_summary(scores['baseline'],scores['candidate']);control=paired_summary(scores['baseline'],scores['random'])
        qualified=paired['gain']>0 and sum(scores['candidate'].values())>sum(scores['random'].values()) and all(row['gain']>=0 for row in domains.values())
        receipts={arm:json.loads((out/arm/'candidate.edit.json').read_text()) for arm in ('candidate','random')}
        report={'paired':paired,'random_control':control,'domains':domains,'eligible_for_independent_confirmation':qualified,
                'latency_ratio':sum(v['seconds'] for v in arms['candidate'].values())/sum(v['seconds'] for v in arms['baseline'].values()),
                'latency_caveat':'Discovery timings may overlap CPU packaging; no final speed claim.',
                'model_receipts':receipts,'resumed_from_user_pause':True,'resumed_pass_id':identifier,'production_model_changed':False,
                'status':'Promising discovery result; independent confirmation and separate final benchmarks required.' if qualified else 'Tested hypothesis did not pass discovery. Original retained.'}
        atomic_json(out/'summary.json',report);gc.collect()
        candidate=info['candidate'];assert candidate.parent.resolve()==(out/'random').resolve() and sha(candidate)==receipts['random']['candidate_sha256']
        candidate.unlink();atomic_json(out/'random/candidate-retired.json',{'sha256':receipts['random']['candidate_sha256'],'original_modified':False,'reason':'Completed resumed comparison; reproducible disposable control copy.'})
        print(json.dumps(report),flush=True)
    finally:
        if lease:release_gpu_lease(lease)
        ledger.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True)
    mode=parser.add_mutually_exclusive_group(required=True);mode.add_argument('--check-only',action='store_true');mode.add_argument('--resume',action='store_true');args=parser.parse_args()
    if args.resume:research_guard.require_gpu_unpaused()
    info=inspect(args.model)
    if args.check_only:
        report={'passed':True,'mode':'CPU-only resume verification','model':args.model,'complete_arms':['baseline','candidate'],
                'completed_control_cases':len(info['arms']['random']),'pending_control_cases':len(info['cases'])-len(info['arms']['random']),
                'retained_control_sha256':info['request']['model_sha256'],'gpu_loaded':False,'paused':research_guard.gpu_paused()}
        atomic_json(ROOT/'Maintenance/Validation/Weight-Profiles-r65/resume-readiness.json',report);print(json.dumps(report),flush=True);return
    resume(args.model,info)
if __name__=='__main__':main()
