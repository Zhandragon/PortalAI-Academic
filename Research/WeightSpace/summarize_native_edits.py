"""Reproducible bounded summaries; never select a dose using held-out answers."""
import hashlib,json,statistics
from pathlib import Path
LAB=Path(__file__).parent
def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):path.write_bytes((json.dumps(data,indent=2)+'\n').encode())
old=read(LAB/'NATIVE-PILOT-RESULTS.json')
old.update(status='all_six_native_selection_baselines_completed',completed_case_results=72,pending_models=[])
old['models']=[r for r in old['models'] if not r['model'].startswith('27-')]
for model in ('27-standard','27-abliterated'):
    folder=LAB/'native-27-after-game-v1';file=folder/(model+'-results.jsonl');rows=[json.loads(line) for line in file.read_text().splitlines()];manifest=read(folder/(model+'-manifest.json'))
    assert len(rows)==12
    old['models'].append({'model':model,'base_model_sha256':manifest['sha256'],'cases':12,'strict_passed':sum(r['passed'] for r in rows),'areas':{area:{'strict_passed':sum(r['passed'] for r in rows if r['area']==area),'cases':sum(r['area']==area for r in rows)} for area in ('math','coding','tool_use','reasoning')},'detector_repetition_flags':sum(r['repetition_suspected'] for r in rows),'output_token_cutoffs':sum(r['finish_reason']=='length' for r in rows),'median_seconds_per_case':statistics.median(r['seconds'] for r in rows),'failure_review':[],'raw_results_sha256':sha(file)})
old['limitations']=[s for s in old['limitations'] if not s.startswith(('No candidate adapter','GPU work was stopped','This report describes unchanged','The two 27B variants completed'))]
old['limitations']+=['This report describes unchanged selection baselines. Later native capture, causal calibration and held-out controls are recorded separately in NATIVE-EDIT-RESULTS.json.','The two 27B variants completed after the user freed VRAM. Their 12/12 pilot scores have a ceiling effect and do not establish general reliability.']
write(LAB/'NATIVE-PILOT-RESULTS.json',old)
models=[]
for label in ('1.7','1.7-abl','4','4-abl','27','27-abl'):
    folder=LAB/('causal-calibration-'+label+'-v1');report=read(folder/'report.json');rows=report['records'];assert len(rows)==24
    def contrast(row):return row['repetitive_loss_change']-row['productive_loss_change']
    eligible=[]
    for row in rows:
        if row['kind']!='candidate' or row['dose']==0:continue
        control=next(r for r in rows if r['kind']=='random-control' and (r['layer'],r['dose'])==(row['layer'],row['dose']))
        if row['productive_loss_change']<=.02 and contrast(row)>.01 and contrast(row)-contrast(control)>.01:eligible.append(row)
    record={'model':report['model'],'base_model_sha256':report['sha256'],'calibration_source':'four hand-authored counterfactual pairs; synthetic, not sampled natural failures','sites':sorted({r['layer'] for r in rows}),'adapter_evaluations':len(rows)*8,'zero_scale_checks_passed':all(max(abs(x) for x in r['per_sequence_loss_change'])<=.002 for r in rows if r['dose']==0),'calibration_candidates_eligible':len(eligible),'calibration_report_sha256':sha(folder/'report.json'),'adapter_bytes':sum(p.stat().st_size for p in folder.glob('*.gguf')),'production_accepted':False}
    plan=LAB/('task-controls-'+label+'-v1')
    if eligible:
        summary=read(plan/'summary.json');frozen=read(plan/'plan.json');record.update(selected_layer=frozen['candidate']['layer'],selected_dose=frozen['candidate']['dose'],heldout=summary['runs'],plan_sha256=sha(plan/'plan.json'),heldout_used_for_selection=False)
        for name,run in record['heldout'].items():
            manifest=read(plan/name/(report['model']+'-manifest.json'));run['raw_results_sha256']=sha(plan/name/(report['model']+'-results.jsonl'));run['sampling']=manifest['sampling']
        baseline=summary['runs']['baseline']['by_case'];candidate=summary['runs']['candidate']['by_case']
        record['rescued_cases']=[k for k,v in baseline.items() if not v and candidate[k]]
        record['regressed_cases']=[k for k,v in baseline.items() if v and not candidate[k]]
        record['reviewed_change']=('The standard candidate repairs missing-positive input mutation but regresses bracket nesting: a balance counter accepts ([)] instead of checking matching types.' if label=='1.7' else 'The abliterated candidate repairs bracket nesting but delivers FINAL: number on the divisor-count problem despite reasoning to 24. This is an answer-delivery regression, not incorrect arithmetic.')
        record['decision']='Do not deploy: this tiny one-seed pilot does not establish a robust net gain; any regressions must be resolved on new data.'
    else:record['decision']='Rejected at calibration: no dose passed the frozen candidate-versus-random and productive-loss gates.'
    models.append(record)
loop=read(LAB/'loop-followup-4-v1/summary.json')
loop['interpretation']='All three larger-budget selection follow-ups completed correctly. The original 3,072-token cutoff is not evidence of unavoidable nontermination. Prompt, model and sampling settings match, with three stated seeds; one-case fresh server ordering differs from the original multi-case run, so this does not isolate budget as the only causal variable.'
report={'status':'bounded_native_edit_experiment_completed_no_edits_promoted','production_models_changed':False,'accepted_edits':0,'broad_intelligence_gain_established':False,'selection_baseline_cases':72,'adapter_teacher_forced_evaluations':sum(r['adapter_evaluations'] for r in models),'heldout_generated_cases':sum(sum(run['cases'] for run in r.get('heldout',{}).values()) for r in models),'models':models,'larger_budget_followup':loop,'native_smoke_checks':[read(LAB/name) for name in ('native-smoke-cuda-1.7.json','native-smoke-cuda-27.json')],'native_abi_sha256':sha(LAB/'native-abi.json'),'limitations':['This adapts sparse rank-one weight interventions to the installed quantized llama.cpp models; it is not a bit-identical reproduction of the authors BF16 overwrite.','Synthetic teacher-forced pairs are an instrumentation/calibration probe, not a validated natural looping direction.','The same small held-out set was used across model variants; it is held out from direction/site/dose selection, not a fresh external benchmark.','One seed and twelve simple held-out tasks per variant are insufficient for statistical claims, broad intelligence improvement, or production promotion.','No GSM8K, MATH-500, IFEval, large coding benchmark or full PortalAI tool workflow has been evaluated in this run.','A failed candidate is retained only as research evidence; the original model remains selected in PortalAI.','Generation timing excludes model load and is descriptive; concurrent disk/network release work and run order prevent controlled speed claims.']}
for name in ('offline-native-D.log','offline-native-E.log'):
    log=(LAB/name).read_text();assert 'Ran 14 tests' in log and log.rstrip().endswith('OK')
e_smoke=read(LAB/'independent-E-native-smoke.json');assert e_smoke['max_logit_difference']==0
report['portable_validation']={'offline_checks_passed_per_drive':14,'independent_E_native_capture_smoke':e_smoke,'E_tested_with_own_interpreter_models_and_runtime':True}
write(LAB/'NATIVE-EDIT-RESULTS.json',report)
historical=read(LAB/'PILOT-RESULTS.json');historical['historical_report']=True
historical['limitations']=[s for s in historical['limitations'] if not s.startswith(('Native server comparison','Qwen3 1.7B/4B tensor mapping','No candidate was applied','This historical direct-Torch pilot'))]+['This historical direct-Torch pilot is superseded for deployment conclusions by native baseline and native-edit reports. Native capture now supports all six installed variants; no candidate is accepted.']
write(LAB/'PILOT-RESULTS.json',historical)
write(LAB/'FINAL-STATUS.json',{'status':report['status'],'gpu_manually_paused':False,'accepted_edits':0,'production_models_changed':False,'next_research':'Obtain diverse naturally sampled productive/looping pairs, preregister larger unseen evaluations and multiple seeds; do not tune on the already viewed pilot holdout.'})
print(json.dumps({'models':len(models),'adapter_evaluations':report['adapter_teacher_forced_evaluations'],'heldout_generations':report['heldout_generated_cases'],'accepted_edits':0}),flush=True)
