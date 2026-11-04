"""Matched native generations, after candidate/site/dose selection is frozen."""
import argparse,json,sys
from pathlib import Path
from types import SimpleNamespace
LAB=Path(__file__).parent;sys.path.insert(0,str(LAB))
from benchmark import run
p=argparse.ArgumentParser();p.add_argument('--plan',required=True);a=p.parse_args()
folder=(LAB/a.plan).resolve()
if not folder.is_relative_to(LAB.resolve()):raise ValueError('Use a portable research plan')
plan=json.loads((folder/'plan.json').read_text());assert plan['frozen_before_task_evaluation'] and plan['split']=='heldout'
for label,adapter in [('baseline',None),('candidate',folder/plan['adapters']['candidate']),('random-control',folder/plan['adapters']['random-control'])]:
    run(SimpleNamespace(models=[plan['model']],output=(folder/label).relative_to(LAB).as_posix(),split='heldout',tokens=plan['max_tokens'],tls=False,adapter=adapter))
summary={'model':plan['model'],'production_accepted':False,'original_weights_modified':False,'runs':{}}
for label in ('baseline','candidate','random-control'):
    rows=[json.loads(line) for line in (folder/label/(plan['model']+'-results.jsonl')).read_text().splitlines()]
    summary['runs'][label]={'cases':len(rows),'passed':sum(r['passed'] for r in rows),'cutoffs':sum(r['finish_reason']=='length' for r in rows),'seconds':sum(r['seconds'] for r in rows),'by_case':{r['id']:r['passed'] for r in rows}}
(folder/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary),flush=True)
