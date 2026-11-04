"""Bounded native generations on natural, frozen discovery problems."""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2];ENGINE=ROOT/'Tools/WeightSpace'
sys.path[:0]=[str(LAB),str(ENGINE),str(ROOT/'Agent')]
from native_forward import Forward,metadata,render,item_seed
from experiment import Ledger,sha,space,atomic_json
from service_manager import acquire_gpu_lease,release_gpu_lease
from research_guard import require_gpu_unpaused
import research_guard
research_guard.LAB=LAB

def score(text,gold):
    source=ENGINE/'published/mathqa.py'
    request={'source':str(source),'sha256':sha(source),'text':text,'gold':gold}
    try:
        result=subprocess.run([sys.executable,'-B','-I',str(ENGINE/'math_grade.py')],input=json.dumps(request),capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError(result.stderr[-1000:])
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:return {'correct':False,'grading_error':'15-second external grading deadline exceeded'}

def loop_signals(text):
    words=text.lower().split();tail=words[-200:];counts={}
    for i in range(max(0,len(tail)-3)):
        key=tuple(tail[i:i+4]);counts[key]=counts.get(key,0)+1
    denominator=max(1,len(tail)-3)
    score=sum(v for v in counts.values() if v>=3)/denominator
    # Diagnostic only; no early stop or altered sampling from this signal.
    return {'repeated_tail_fraction':score,'repetitive_end':score>=.5}

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);p.add_argument('--pass-id',default='001-natural-discovery');a=p.parse_args()
    from maintenance_wait import wait_if_requested
    wait_if_requested(a.model)
    protocol=json.loads((LAB/'protocol.json').read_text());spec=protocol['models'][a.model]
    model=ROOT/'LLM/models'/spec['filename'];space(LAB)
    folder=LAB/'experiments'/a.model;folder.mkdir(parents=True,exist_ok=True)
    splits=json.loads((LAB/'splits.json').read_text());ids=splits['initial_discovery_ids']
    with (LAB/'practice.jsonl').open(encoding='utf-8') as stream:rows={r['id']:r for r in map(json.loads,stream) if r['id'] in ids}
    fingerprint=sha(model);meta=metadata(model)
    request={'base_sha256':fingerprint,'sampling':spec['sampling'],'ids':ids,'phase':'discovery','backend':'native llama.cpp quantized','capture':False,'split_sha256':sha(LAB/'splits.json')}
    ledger=Ledger(folder/'ledger.sqlite');lease=None
    if not ledger.begin(a.pass_id,'discovery',request):print('Already complete');ledger.close();return
    out=folder/a.pass_id;out.mkdir(exist_ok=False);atomic_json(out/'request.json',request)
    try:
        lease=acquire_gpu_lease('weight-space-'+a.model,timeout=3)
        with Forward(model,context=34816,batch=256) as engine:
            for identifier in ids:
                require_gpu_unpaused(LAB);space(LAB)
                row=rows[identifier];prompt=render(meta['template'],[{'role':'user','content':row['problem']+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}])
                settings={k:v for k,v in spec['sampling'].items() if k!='thinking'}
                generated=engine.generate(prompt,seed=item_seed(identifier),progress=lambda n,seconds:print(json.dumps({'progress':identifier,'tokens':n,'seconds':round(seconds,1)}),flush=True) if n%4096==0 else None,**settings)
                result={**generated,'id':identifier,'source':row['source'],'grading':score(generated['text'],row['answer']),**loop_signals(generated['text'])}
                result.pop('activations');result['prompt']=prompt
                target=out/(hashlib.sha256(identifier.encode()).hexdigest()[:20]+'.json');atomic_json(target,result)
                print(json.dumps({'model':a.model,'id':identifier,'correct':result['grading']['correct'],'tokens':result['tokens'],'finish':result['finish'],'seconds':round(result['seconds'],2),'loop':result['repetitive_end']}),flush=True)
        if sha(model)!=fingerprint:raise RuntimeError('Original changed during experiment')
        ledger.end(a.pass_id,{'results':len(ids),'base_unchanged':True})
        # This is a separate accounted forward pass. Failure localization does
        # not consume or expose any held-out confirmation questions.
        from diagnosis import propose
        records=[json.loads(path.read_text()) for path in out.glob('*.json') if path.name!='request.json']
        good=sum(r['grading']['correct'] and r['finish']=='stop' for r in records)
        bad=sum(not r['grading']['correct'] for r in records)
        if min(good,bad)>=4:
            localization=folder/'002-localization';localization.mkdir(exist_ok=False)
            ledger.begin('002-localization','discovery',{'base_sha256':fingerprint,'source_pass':a.pass_id,'method':'native outcome contrast and all-layer replay'})
            try:
                result=propose(model,records,localization,progress=lambda row:print(json.dumps(row),flush=True))
                ledger.end('002-localization',result)
            except BaseException as exc:
                ledger.end('002-localization',{'error':repr(exc)},False);raise
        else:
            atomic_json(folder/'localization-not-admitted.json',{'natural_successes':good,'natural_failures':bad,'reason':'Need at least four in each group; no invented failure examples or arbitrary direction.'})
            release_gpu_lease(lease);lease=None
            import extend_discovery
            extend_discovery.main()
    except BaseException as exc:
        if ledger.db.execute('SELECT status FROM runs WHERE id=?',(a.pass_id,)).fetchone()[0]=='running':ledger.end(a.pass_id,{'error':repr(exc)},False)
        raise
    finally:
        if lease:release_gpu_lease(lease)
        ledger.close()

if __name__=='__main__':main()
