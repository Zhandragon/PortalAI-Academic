"""Publish only bounded diagnostic summaries, not local generation traces."""
import hashlib,json,statistics
from pathlib import Path
lab=Path(__file__).parent;run=lab/'direct-probe-selection-v2'
rows=[json.loads(line) for line in (run/'results.jsonl').read_text(encoding='utf-8').splitlines()]
manifest=json.loads((run/'manifest.json').read_text())
assert len(rows)==12 and len({r['id'] for r in rows})==12
areas={area:{'strict_passed':sum(r['passed'] for r in rows if r['area']==area),'cases':sum(r['area']==area for r in rows)} for area in ('math','coding','tool_use','reasoning')}
report={'status':'pilot_completed_no_model_edits','models_inventoried':6,'model':'1.7-standard','base_model_sha256':manifest['base_sha256'],'backend':manifest['backend'],'native_runtime':False,'production_models_changed':False,'accepted_edits':0,'model_quality_gains_established':False,'cases':len(rows),'strict_passed':sum(r['passed'] for r in rows),'areas':areas,'suspected_repetition_cases':sum(r['repetition_suspected'] for r in rows),'token_or_time_cutoffs':sum(r['cutoff'] for r in rows),'median_seconds_per_case':statistics.median(r['seconds'] for r in rows),'total_generation_seconds':sum(r['seconds'] for r in rows),'sampling':manifest['generation'],'failure_review':[
 {'case':'m3','category':'output_format','finding':'Correct numeric value 48, but emitted FINAL: number. 48; strict format check failed. Do not classify this as incorrect arithmetic.'},
 {'case':'c2','category':'coding_constraint','finding':'Merged intervals but sorted the input list in place despite the explicit no-mutation requirement.'},
 {'case':'t1','category':'tool_selection','finding':'Selected downloading a known default avatar instead of reading the identified profile. Synthetic schema, not a full PortalAI harness test.'}
], 'limitations':['Only twelve selection cases on one dequantized BF16 probe; not a general benchmark or six-model comparison.','No loop-suppression direction was fitted: this valid pilot did not produce a repetition case.','The initial probe run omitted generation EOS IDs, was invalidated, and is excluded from all counts and direction fitting.','Native server comparison remains interrupted pending review of the disappearing executable; restored from independently pinned E copy.','Qwen3 1.7B/4B tensor mapping verified, but activation collection remains unvalidated. The 27B qwen35 activation backend is not implemented.','No candidate was applied, validated, promoted or distributed as a model improvement.'],'results_file_sha256':hashlib.sha256((run/'results.jsonl').read_bytes()).hexdigest()}
(lab/'PILOT-RESULTS.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k not in ('failure_review','limitations')}),flush=True)
