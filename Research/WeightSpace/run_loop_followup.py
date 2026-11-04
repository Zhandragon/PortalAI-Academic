"""Distinguish a selection-case cutoff from an unresolved loop using more budget.

No adapter is selected here and no held-out case is used to tune an edit.
The 6,144-token checks fit the existing 8,192-token native context.
"""
import json,sys
from pathlib import Path
from types import SimpleNamespace
LAB=Path(__file__).parent;sys.path.insert(0,str(LAB))
from benchmark import run
folder=LAB/'loop-followup-4-v1'
folder.mkdir(exist_ok=False)
plan={'model':'4-standard','case_ids':['c2'],'split':'selection','seeds':[20261103,20261104,20261105],'max_tokens':6144,'adapter':None,'purpose':'Larger-budget follow-up of the original standard 4B interval-merging cutoff; not an intelligence benchmark or held-out evaluation.'}
(folder/'plan.json').write_text(json.dumps(plan,indent=2))
records=[]
for seed in plan['seeds']:
    path=folder/str(seed)
    run(SimpleNamespace(models=[plan['model']],output=path.relative_to(LAB).as_posix(),split='selection',tokens=plan['max_tokens'],tls=False,adapter=None,seed=seed,case_ids=plan['case_ids']))
    row=json.loads((path/(plan['model']+'-results.jsonl')).read_text())
    records.append({'seed':seed,**{key:row[key] for key in ('id','passed','seconds','finish_reason','usage','repetition_suspected','grading')}})
report={**plan,'results':records,'production_weights_changed':False}
(folder/'summary.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
