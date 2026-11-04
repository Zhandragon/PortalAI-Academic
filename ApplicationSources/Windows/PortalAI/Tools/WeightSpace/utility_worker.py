"""Portable worker for model inspection, direct edits and paired task evaluation."""
import sys
if __name__=='__main__' and sys.stdin.readline().strip()!='start':raise SystemExit('Owned start gate required')
import argparse,hashlib,json,time
from pathlib import Path
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path[:0]=[str(HERE),str(ROOT/'Agent')]
from experiment import atomic_json,sha,space,Ledger,paired_summary

def campaign_ledger(model,request,work):
    import re
    campaign=request.get('campaign','default')
    if not isinstance(campaign,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',campaign):raise ValueError('Invalid campaign identifier')
    return Ledger(ROOT/'Maintenance/WeightSpace'/sha(model)/campaign/'ledger.sqlite')

def main():
    p=argparse.ArgumentParser();p.add_argument('request',type=Path);a=p.parse_args()
    if a.request.stat().st_size>16*1024**2:raise ValueError('Request too large')
    request=json.loads(a.request.read_text());work=a.request.parent.resolve();space(work)
    import research_guard
    research_guard.LAB=work
    from quantized_edit import inventory,materialize
    action=request['action'];model=Path(request['model']).resolve(strict=True)
    if action=='save-profile':
        from edit_profiles import export_profile
        recipe_file=Path(request['recipe'])
        if recipe_file.stat().st_size>8*1024**2:raise ValueError('Recipe exceeds 8 MiB')
        recipe=json.loads(recipe_file.read_text(encoding='utf-8-sig'))
        result=export_profile(ROOT,model,Path(request['candidate']),recipe,label=request['label'],
                              progress=lambda done,total:print(json.dumps({'bytes':done,'total':total}),flush=True))
        result['message']='Exact edit profile saved. Prepare it, then select it in PortalAI Settings → Chat models. Original weights remain the default.'
        atomic_json(work/'profile-result.json',result);print(json.dumps(result),flush=True);return
    if action in ('prepare-profile','clear-prepared'):
        from edit_profiles import prepare_profile,clear_prepared
        from service_manager import acquire_gpu_lease,release_gpu_lease,_qwen_lifecycle_mutex
        from chat_model_switch import _owned_listener,_argv
        lease=acquire_gpu_lease('weight-profile-cache',timeout=3)
        try:
            # Coordinate with chat loading and other GPU users before removing
            # any derived cache. Unknown listener ownership fails closed.
            with _qwen_lifecycle_mutex():
                in_use=[]
                for row in _owned_listener().get('listeners',[]):
                    args=_argv(row.get('command_line',''))
                    if '-m' not in args or args.index('-m')+1>=len(args):raise RuntimeError('Cannot identify the loaded model; cache left untouched')
                    in_use.append(args[args.index('-m')+1])
                if action=='prepare-profile':
                    result=prepare_profile(ROOT,model,request['profile_id'],in_use=in_use,
                                           progress=lambda done,total:print(json.dumps({'segments':done,'total':total}),flush=True))
                    result['message']='Prepared. Select this profile in PortalAI Settings → Chat models, then Save. Choose Original weights there to revert on the next request.'
                else:
                    result={'removed':clear_prepared(ROOT,request['profile_id'],in_use=in_use),'original_modified':False,
                            'message':'Prepared copy cleared; compact profile and original weights retained. Select Original weights in Settings, or prepare the profile again.'}
        finally:release_gpu_lease(lease)
        atomic_json(work/'profile-result.json',result);print(json.dumps(result),flush=True);return
    if action=='inspect':
        result=inventory(model);result['model_sha256']=sha(model)
        atomic_json(work/'inspection.json',result);print(json.dumps(result),flush=True);return
    if action=='edit':
        recipe_file=Path(request['recipe'])
        if recipe_file.stat().st_size>8*1024**2:raise ValueError('Recipe exceeds 8 MiB')
        recipe=json.loads(recipe_file.read_text(encoding='utf-8-sig'))
        output=work/'candidate.gguf'
        ledger=campaign_ledger(model,request,work);identifier=work.name+'-edit'
        ledger.begin(identifier,'cpu',{'request':request,'recipe_sha256':sha(recipe_file)})
        try:
            result=materialize(model,recipe,output,progress=lambda name,done,total:print(json.dumps({'tensor':name,'rows':done,'total':total}),flush=True) if done==total or done%512==0 else None)
            ledger.end(identifier,result)
        except BaseException as exc:ledger.end(identifier,{'error':repr(exc)},False);raise
        finally:ledger.close()
        print(json.dumps(result),flush=True);return
    if action=='diagnose':
        from diagnosis import propose
        from service_manager import acquire_gpu_lease,release_gpu_lease
        report_path=Path(request['baseline_report']).resolve(strict=True)
        settings=json.loads((report_path.parent/'settings.json').read_text())
        if settings['base_sha256']!=sha(model):raise ValueError('Discovery report is for a different model')
        records=[json.loads(path.read_text()) for path in (report_path.parent/'baseline').glob('*.json')]
        ledger=campaign_ledger(model,request,work);identifier=work.name+'-localization';ledger.begin(identifier,'discovery',request);lease=None
        try:
            lease=acquire_gpu_lease('weight-space-localization',timeout=3)
            result=propose(model,records,work,progress=lambda row:print(json.dumps(row),flush=True))
            atomic_json(work/'report.json',result);ledger.end(identifier,result);print(json.dumps(result),flush=True)
        except BaseException as exc:ledger.end(identifier,{'error':repr(exc)},False);raise
        finally:
            if lease:release_gpu_lease(lease)
            ledger.close()
        return
    if action not in ('evaluate','compare'):raise ValueError('Unsupported utility action')
    from evaluation import grade,read_cases
    from native_forward import Forward,metadata,render,item_seed
    from service_manager import acquire_gpu_lease,release_gpu_lease
    cases=read_cases(request['cases']);meta=metadata(model)
    sampling=request.get('sampling',{'temperature':.6,'top_p':.95,'top_k':20,'max_tokens':32768,'presence_penalty':1.5 if meta['architecture']=='qwen35' else 0.})
    models={'baseline':model}
    if action=='compare':
        candidate=Path(request['candidate']).resolve(strict=True)
        evidence=json.loads(candidate.with_suffix('.edit.json').read_text())
        if evidence['base_sha256']!=sha(model) or evidence['candidate_sha256']!=sha(candidate):raise ValueError('Candidate does not match its original and edit evidence')
        models['candidate']=candidate
    ledger=campaign_ledger(model,request,work);pass_id=work.name+'-evaluation';fingerprint={'request':request,'base_sha256':sha(model),'cases_sha256':sha(request['cases'])}
    if not ledger.begin(pass_id,'discovery',fingerprint):return
    atomic_json(work/'settings.json',fingerprint);results={};lease=None
    try:
        lease=acquire_gpu_lease('weight-space-utility',timeout=3)
        for arm,path in models.items():
            results[arm]={};arm_dir=work/arm;arm_dir.mkdir(exist_ok=False)
            with Forward(path,context=34816,batch=256) as engine:
                for case in cases:
                    research_guard.require_gpu_unpaused();space(work)
                    prompt=render(meta['template'],[{'role':'user','content':case['prompt']}],tools=case.get('tools'))
                    value=engine.generate(prompt,seed=item_seed(case['id']),**sampling);value.pop('activations')
                    try:value['grading']=grade(case,value['text'])
                    except Exception as exc:raise RuntimeError('Invalid benchmark evidence: grader failed for '+case['id']+': '+str(exc)) from exc
                    value['id']=case['id'];value['kind']=case['kind'];value['domain']=case.get('domain',case['kind']);value['prompt']=prompt
                    atomic_json(arm_dir/(hashlib.sha256(case['id'].encode()).hexdigest()[:20]+'.json'),value)
                    results[arm][case['id']]=value['grading']['correct']
                    print(json.dumps({'arm':arm,'id':case['id'],'correct':value['grading']['correct'],'tokens':value['tokens'],'seconds':round(value['seconds'],2)}),flush=True)
        report={'scores':{key:{'correct':sum(values.values()),'cases':len(values)} for key,values in results.items()},'production_model_changed':False,'scope':'User-provided task set; not a general intelligence certification.'}
        if action=='compare':report['paired']=paired_summary(results['baseline'],results['candidate'])
        atomic_json(work/'report.json',report);ledger.end(pass_id,report)
        print(json.dumps(report),flush=True)
    except BaseException as exc:
        ledger.end(pass_id,{'error':repr(exc)},False);raise
    finally:
        if lease:release_gpu_lease(lease)
        ledger.close()

if __name__=='__main__':main()
