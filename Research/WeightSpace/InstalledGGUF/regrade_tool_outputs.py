"""Repair native XML/JSON tool scoring from saved text, preserving every prior record."""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
LAB=Path(__file__).resolve().parent
ROOT=LAB.parents[2]
sys.path[:0]=[str(ROOT/'Tools/WeightSpace')]
from evaluation import grade
from experiment import Ledger,atomic_json,sha,paired_summary

def read(p):return json.loads(p.read_text())

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    assert args.model in read(LAB/'protocol.json')['models']
    folder=LAB/'experiments'/args.model
    out=folder/'004-generation-screen'
    old_summary=read(out/'summary.json')
    cases=read(out/'cases.json');case_map={case['id']:case for case in cases}
    assert len(case_map)==len(cases)==old_summary['paired']['n']
    assert old_summary['production_model_changed'] is False
    archive=folder/'reviewed-grading-corrections/tool-formats-v2'
    assert not archive.exists(),'A prior correction exists; inspect its receipt before any retry'
    scores={};changes=[];all_record_hashes={}
    for arm in ('baseline','candidate','random'):
        scores[arm]={}
        records=[p for p in (out/arm).glob('*.json') if p.name not in ('request.json','candidate.edit.json','edit-profile.json','candidate-retired.json')]
        records=[(p,read(p)) for p in records]
        records=[(p,row) for p,row in records if 'id' in row and 'grading' in row]
        assert {row['id'] for _,row in records}==set(case_map) and len(records)==len(cases)
        for path,row in records:
            relative=path.relative_to(folder).as_posix()
            assert path.name==hashlib.sha256(row['id'].encode()).hexdigest()[:20]+'.json'
            all_record_hashes[relative]=sha(path)
            corrected=grade(case_map[row['id']],row['text']) if case_map[row['id']]['kind']=='tool' else row['grading']
            assert type(corrected['correct']) is bool
            scores[arm][row['id']]=corrected['correct']
            if case_map[row['id']]['kind']=='tool':
                assert corrected['tools_executed'] is False and corrected['grader_version']=='qwen-tool-formats-v2'
                revised={**row,'grading':corrected,'grading_correction':{
                    'version':'qwen-tool-formats-v2','previous':row['grading'],
                    'original_record_sha256':all_record_hashes[relative],
                    'archive':'reviewed-grading-corrections/tool-formats-v2/'+relative}}
                # The generated text, tokens, finish, time, seed and model evidence stay exact.
                assert {k:v for k,v in revised.items() if k not in ('grading','grading_correction')}=={k:v for k,v in row.items() if k!='grading'}
                changes.append({'path':path,'relative':relative,'value':revised,'id':row['id'],'arm':arm,
                                'before':row['grading']['correct'],'after':corrected['correct']})
    domains={}
    for domain in sorted({case['domain'] for case in cases}):
        ids=[case['id'] for case in cases if case['domain']==domain]
        domains[domain]=paired_summary({k:scores['baseline'][k] for k in ids},{k:scores['candidate'][k] for k in ids})
    paired=paired_summary(scores['baseline'],scores['candidate'])
    random=paired_summary(scores['baseline'],scores['random'])
    eligible=paired['gain']>0 and sum(scores['candidate'].values())>sum(scores['random'].values()) and all(row['gain']>=0 for row in domains.values())
    preview={'model':args.model,'cases':len(cases),'counts_before':{
        'baseline':old_summary['paired']['baseline_correct'],'candidate':old_summary['paired']['candidate_correct'],
        'random':old_summary['random_control']['candidate_correct']},
        'counts_after':{arm:sum(values.values()) for arm,values in scores.items()},
        'changed_correctness':[{'arm':r['arm'],'id':r['id'],'before':r['before'],'after':r['after']} for r in changes if r['before']!=r['after']],
        'eligible_after':eligible,'new_inference':False,'tools_executed':False}
    print(json.dumps(preview),flush=True)
    if not args.apply:return
    for drive in ('D','E'):
        check=read(ROOT/f'Maintenance/Validation/Weight-MTP-r69/tool-formats-{drive}.json')
        assert check['passed'] and check['tests']==31 and not check['skipped']
    ledger=Ledger(folder/'ledger.sqlite')
    identifier='cpu-tool-format-regrade-v2'
    try:
        assert not ledger.db.execute("SELECT id FROM runs WHERE status='running'").fetchall(),'Model is still being evaluated'
        request={'reason':'Qwen35 native XML tool syntax was rejected by a JSON-only offline grader.',
                 'cases_sha256':sha(out/'cases.json'),'summary_before_sha256':sha(out/'summary.json'),
                 'source_sha256':{name:sha(ROOT/'Tools/WeightSpace'/name) for name in ('evaluation.py','tool_call_format.py')},
                 'records_before':all_record_hashes,'same_frozen_cases_and_outputs':True,'new_inference':False}
        archive.mkdir(parents=True)
        shutil.copy2(folder/'ledger.sqlite',archive/'ledger-before.sqlite')
        assert sha(folder/'ledger.sqlite')==sha(archive/'ledger-before.sqlite')
        for path in [out/'summary.json']+[row['path'] for row in changes]:
            backup=archive/path.relative_to(folder)
            backup.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,backup);assert sha(path)==sha(backup)
        atomic_json(archive/'request.json',request)
        assert ledger.begin(identifier,'cpu',request)
        try:
            for row in changes:
                assert sha(row['path'])==all_record_hashes[row['relative']]
                atomic_json(row['path'],row['value'])
            revised={**old_summary,'paired':paired,'random_control':random,'domains':domains,
                     'eligible_for_independent_confirmation':eligible,
                     'status':'Promising discovery result; independent confirmation and separate final benchmarks still required.' if eligible else 'Tested hypothesis did not pass the discovery screen. No production replacement.',
                     'tool_format_correction':'TOOL-FORMAT-CORRECTION.json'}
            atomic_json(out/'summary.json',revised)
            receipt={**preview,'applied':True,'request':request,'summary_after_sha256':sha(out/'summary.json'),
                     'corrected_record_hashes':{row['relative']:sha(row['path']) for row in changes},
                     'original_grades_and_ledger_retained':True,'generation_content_unchanged':True,
                     'non_tool_record_hashes_unchanged':all(sha(folder/rel)==digest for rel,digest in all_record_hashes.items() if rel not in {r['relative'] for r in changes})}
            assert receipt['non_tool_record_hashes_unchanged']
            atomic_json(folder/'TOOL-FORMAT-CORRECTION.json',receipt)
            ledger.end(identifier,{'correctness_changes':len(preview['changed_correctness']),'eligible_after':eligible,'receipt_sha256':sha(folder/'TOOL-FORMAT-CORRECTION.json')})
        except BaseException as exc:
            ledger.end(identifier,{'error':repr(exc)},False)
            raise
    finally:ledger.close()

if __name__=='__main__':main()
