"""Freeze one calibration-selected candidate before looking at held-out tasks."""
import argparse,hashlib,json,sys
from pathlib import Path
LAB=Path(__file__).parent;sys.path.insert(0,str(LAB))
from sparse_edit import gguf,np,save_adapter
p=argparse.ArgumentParser();p.add_argument('--calibration',required=True);p.add_argument('--output',required=True);a=p.parse_args()
source=(LAB/a.calibration).resolve();destination=(LAB/a.output).resolve()
if not source.is_relative_to(LAB.resolve()) or not destination.is_relative_to(LAB.resolve()) or destination.exists():raise ValueError('Use a new portable control plan')
report=json.loads((source/'report.json').read_text())
def contrast(row):return row['repetitive_loss_change']-row['productive_loss_change']
eligible=[]
for row in report['records']:
    if row['kind']!='candidate' or row['dose']==0:continue
    control=next(r for r in report['records'] if r['kind']=='random-control' and (r['layer'],r['dose'])==(row['layer'],row['dose']))
    if row['productive_loss_change']<=.02 and contrast(row)>.01 and contrast(row)-contrast(control)>.01:eligible.append(row)
if not eligible:raise ValueError('No calibration candidate separated repetitive text from its matched random control; no candidate selected')
chosen=max(eligible,key=contrast);destination.mkdir()
adapters={}
for kind in ('candidate','random-control'):
    path=source/f'layer-{chosen["layer"]}-{kind}.gguf';meta=json.loads(path.with_suffix('.json').read_text())
    if meta['relative_matrix_delta_at_scale_1']*chosen['dose']>.15:raise ValueError('Scaled candidate exceeds perturbation limit')
    reader=gguf.GGUFReader(str(path),'r');arrays={t.name:np.array(t.data,copy=True) for t in reader.tensors}
    name=meta['tensor'];fa=arrays[name+'.lora_a'];fb=arrays[name+'.lora_b']*chosen['dose']
    output=destination/(kind+'.gguf')
    save_adapter(output,meta['architecture'],[(name,fa,fb)],{**meta,'dose':chosen['dose'],'calibration_report_sha256':hashlib.sha256((source/'report.json').read_bytes()).hexdigest(),'heldout_used_for_selection':False})
    adapters[kind]=output.name
plan={'model':report['model'],'candidate':chosen,'adapters':adapters,'frozen_before_task_evaluation':True,'split':'heldout','seeds':[20261103],'max_tokens':3072,'production_acceptance':False,'acceptance_note':'A 12-case diagnostic cannot establish broad intelligence gains. Do not install even if this pilot improves. Require expanded unseen tasks, repeat seeds, natural failure pairs and no material regression.','comparisons':['unchanged baseline','calibration-selected candidate','norm-matched random control']}
(destination/'plan.json').write_text(json.dumps(plan,indent=2));print(json.dumps(plan),flush=True)
