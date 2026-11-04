"""Explicit, pause-aware continuation of the installed-model campaign.

Check-only planning is CPU-only. Running never clears a user pause, replays a
completed model, or guesses how to recover an unrecognized partial experiment.
"""
import argparse,json,sys
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2]
sys.path[:0]=[str(LAB),str(ROOT/'Tools/WeightSpace')]
from run_owned import run
import research_guard
research_guard.LAB=LAB
MODELS=['1.7-abliterated','4-standard','4-abliterated','27-standard','27-abliterated']

def model_plan(name):
    folder=LAB/'experiments'/name
    summary=folder/'004-generation-screen/summary.json'
    if summary.is_file():
        result=json.loads(summary.read_text())
        if result.get('production_model_changed') is not False:
            raise RuntimeError('Unexpected completed-screen evidence: '+name)
        return {'model':name,'action':'skip completed screen','summary':str(summary)}
    extended=folder/'EXTENDED-STATUS.json'
    causal=folder/'003-causal-screen/summary.json'
    if extended.is_file() and json.loads(extended.read_text()).get('qualified') is False:
        if (folder/'002-localization/localization.json').exists():raise RuntimeError('Conflicting localization admission evidence')
        return {'model':name,'action':'skip completed screen','reason':'No supported natural failure contrast; original retained.'}
    if causal.is_file() and json.loads(causal.read_text()).get('selected_for_generation','missing') is None:
        if (folder/'selected-recipe.json').exists():raise RuntimeError('Conflicting recipe admission evidence')
        return {'model':name,'action':'skip completed screen','reason':'No eligible site/dose; original retained.'}
    if not folder.exists() or not any(folder.iterdir()):
        return {'model':name,'action':'run discovery, causal, generation'}
    if name=='1.7-abliterated':
        from resume_generation import inspect
        info=inspect(name)
        return {'model':name,'action':'resume missing control cases',
                'completed_cases':len(info['arms']['random']),
                'pending_cases':len(info['cases'])-len(info['arms']['random'])}
    raise RuntimeError('Partial model needs explicit checkpoint reconciliation: '+name)

def main():
    parser=argparse.ArgumentParser()
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--check-only',action='store_true')
    modes.add_argument('--run',action='store_true')
    parser.add_argument('--start-at',choices=MODELS,default=MODELS[0])
    args=parser.parse_args()
    if args.run:research_guard.require_gpu_unpaused()
    first=LAB/'experiments/1.7-standard/004-generation-screen/summary.json'
    if not first.is_file():raise RuntimeError('First model screen must be complete')
    plan=[model_plan(name) for name in MODELS[MODELS.index(args.start_at):]]
    print(json.dumps({'mode':'CPU-only plan' if args.check_only else 'explicit GPU continuation',
                      'paused':research_guard.gpu_paused(),'models':plan}),flush=True)
    if args.check_only:return
    for entry in plan:
        research_guard.require_gpu_unpaused()
        name=entry['model']
        if entry['action']=='skip completed screen':continue
        if entry['action']=='resume missing control cases':
            code=run(LAB/'resume_generation.py',['--model',name,'--resume'],
                     LAB/('generation-'+name+'-resume.log'),timeout=21600)
            if code:raise RuntimeError(name+' resume failed with exit '+str(code))
        else:
            print(json.dumps({'starting':name}),flush=True)
            for script,label in [('discovery.py','discovery'),('causal_screen.py','causal'),('generation_screen.py','generation')]:
                research_guard.require_gpu_unpaused()
                code=run(LAB/script,['--model',name],LAB/(label+'-'+name+'.log'),timeout=21600)
                if code:raise RuntimeError(name+' '+label+' failed with exit '+str(code))
        print(json.dumps({'completed':name}),flush=True)

if __name__=='__main__':main()
