"""Collect additional distinct natural cases if initial outcomes cannot localize a direction."""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2]
sys.path[:0]=[str(LAB),str(ROOT/'Tools/WeightSpace'),str(ROOT/'Agent')]
import research_guard
research_guard.LAB=LAB
from native_forward import Forward,metadata,render,item_seed
from experiment import Ledger,sha,space,atomic_json
from service_manager import acquire_gpu_lease,release_gpu_lease
from discovery import score,loop_signals
from diagnosis import propose

def records(folder):
    return [json.loads(p.read_text()) for d in sorted(folder.glob('001*-natural-discovery')) for p in d.glob('*.json') if p.name!='request.json']

def main():
    p=argparse.ArgumentParser();p.add_argument('--model',required=True);a=p.parse_args()
    folder=LAB/'experiments'/a.model;existing=records(folder)
    if (folder/'002-localization/localization.json').is_file():return
    spec=json.loads((LAB/'protocol.json').read_text())['models'][a.model]
    model=ROOT/'LLM/models'/spec['filename'];fingerprint=sha(model)
    splits=json.loads((LAB/'splits.json').read_text());excluded=set(json.loads((LAB/'discovery-exclusions.json').read_text())['excluded_ids'])
    seen={r['id'] for r in existing};eligible=set(splits['all_discovery_ids'])-excluded-seen
    # Stable source-stratified follow-up, independent of candidate outcomes.
    ids=[]
    for prefix,n in [('aime_',16),('math_',8),('gsm8k_',8)]:
        ids.extend(sorted((k for k in eligible if k.startswith(prefix)),key=lambda k:hashlib.sha256(('extra-v1'+k).encode()).hexdigest())[:n])
    with (LAB/'practice.jsonl').open(encoding='utf-8') as stream:rows={r['id']:r for r in map(json.loads,stream) if r['id'] in ids}
    out=folder/'001b-natural-discovery';ledger=Ledger(folder/'ledger.sqlite');lease=None
    request={'ids':ids,'base_sha256':fingerprint,'sampling':spec['sampling'],'reason':'Additional natural successes/failures, no synthetic continuations.'}
    if not ledger.begin('001b-natural-discovery','discovery',request):ledger.close();return
    out.mkdir(exist_ok=False);atomic_json(out/'request.json',request)
    try:
        lease=acquire_gpu_lease('weight-space-extra-'+a.model,timeout=3)
        meta=metadata(model)
        with Forward(model,context=34816,batch=256) as engine:
            for identifier in ids:
                research_guard.require_gpu_unpaused();space(LAB)
                row=rows[identifier];prompt=render(meta['template'],[{'role':'user','content':row['problem']+'\nPlease reason step by step, and put your final answer within \\boxed{}.'}])
                settings={k:v for k,v in spec['sampling'].items() if k!='thinking'}
                value=engine.generate(prompt,seed=item_seed(identifier),**settings);value.pop('activations')
                value.update(id=identifier,source=row['source'],prompt=prompt,grading=score(value['text'],row['answer']),**loop_signals(value['text']))
                atomic_json(out/(hashlib.sha256(identifier.encode()).hexdigest()[:20]+'.json'),value)
                print(json.dumps({'id':identifier,'correct':value['grading']['correct'],'tokens':value['tokens']}),flush=True)
        ledger.end('001b-natural-discovery',{'results':len(ids),'base_unchanged':sha(model)==fingerprint})
        combined=records(folder);good=sum(r['grading']['correct'] and r['finish']=='stop' for r in combined);bad=sum(not r['grading']['correct'] for r in combined)
        if min(good,bad)<4:
            atomic_json(folder/'EXTENDED-STATUS.json',{'good':good,'bad':bad,'qualified':False,'reason':'No supported natural-failure contrast; retain the original.'});return
        work=folder/'002-localization';work.mkdir(exist_ok=False)
        ledger.begin('002-localization','discovery',{'base_sha256':fingerprint,'source_passes':['001-natural-discovery','001b-natural-discovery']})
        try:result=propose(model,combined,work,progress=lambda v:print(json.dumps(v),flush=True));ledger.end('002-localization',result)
        except BaseException as exc:ledger.end('002-localization',{'error':repr(exc)},False);raise
    except BaseException as exc:
        if ledger.db.execute('SELECT status FROM runs WHERE id=?',('001b-natural-discovery',)).fetchone()[0]=='running':ledger.end('001b-natural-discovery',{'error':repr(exc)},False)
        raise
    finally:
        if lease:release_gpu_lease(lease)
        ledger.close()

if __name__=='__main__':main()
