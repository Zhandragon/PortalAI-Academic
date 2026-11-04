"""Reconcile the observed 4B norm rejection without replaying its baseline."""
import hashlib,json,os,shutil,sqlite3,sys
from pathlib import Path
LAB=Path(__file__).resolve().parent;ROOT=LAB.parents[2]
sys.path[:0]=[str(LAB),str(ROOT/'Tools/WeightSpace')]
from experiment import Ledger,atomic_json,sha,space
from edit_feasibility import choose,random_control

def prepare(name='4-standard'):
    if name!='4-standard':raise ValueError('Only the inspected 4-standard norm interruption is reconciled here')
    folder=LAB/'experiments'/name;out=folder/'004-generation-screen';marker=out/'feasibility-resume.json'
    if marker.exists():raise RuntimeError('Repair was already prepared; verify rather than replay')
    spec=json.loads((LAB/'protocol.json').read_text())['models'][name]
    model=ROOT/'LLM/models'/spec['filename'];fingerprint=sha(model)
    old_recipe=json.loads((folder/'selected-recipe.json').read_text());assert old_recipe['base_sha256']==fingerprint and old_recipe['dose']==4
    original_recipe_hash=sha(folder/'selected-recipe.json')
    cases=json.loads((out/'cases.json').read_text());ids={c['id'] for c in cases};records={}
    for path in (out/'baseline').glob('*.json'):
        row=json.loads(path.read_text())
        if 'grading' in row:
            assert row['id'] in ids and type(row['grading']['correct']) is bool
            records[path.name]={'id':row['id'],'sha256':sha(path)}
    assert {r['id'] for r in records.values()}==ids
    ledger=Ledger(folder/'ledger.sqlite')
    try:
        assert ledger.db.execute("SELECT status FROM runs WHERE id='gen-screen-baseline'").fetchone()==('complete',)
        failed=ledger.db.execute("SELECT status,evidence FROM runs WHERE id='cpu-materialize-candidate'").fetchone()
        assert failed[0]=='interrupted' and '15% per-matrix norm ceiling' in failed[1]
        assert not ledger.db.execute("SELECT id FROM runs WHERE id IN ('gen-screen-candidate','gen-screen-random')").fetchall()
        partial=out/'candidate/candidate.gguf.partial';assert partial.is_file() and partial.stat().st_size==model.stat().st_size
        assert set(p.name for p in partial.parent.iterdir())=={partial.name}
        report=json.loads((folder/'003-causal-screen/summary.json').read_text())
        chosen,checks=choose(model,folder/'002-localization',report['dose_results'],out,ledger,prefix='cpu-feasibility-reviewed')
        decision={'prior_recipe_sha256':original_recipe_hash,'prior_rejection':json.loads(failed[1]),'checks':checks,'selected':chosen,'selection_data':'Existing discovery loss only; no candidate answer or final benchmark was used.','matrix_norm_ceiling':.15}
        atomic_json(out/'feasibility-decision.json',decision)
        assert chosen is not None,'No feasible candidate; original evidence retained for a terminal report'
        recipe=json.loads((folder/'002-localization'/chosen['recipe']).read_text());recipe['dose']=chosen['dose']
        recipe.update(causal_screen_sha256=sha(folder/'003-causal-screen/summary.json'),feasibility_screen_sha256=sha(out/'feasibility-decision.json'),supersedes_recipe_sha256=original_recipe_hash)
        source=(out/'candidate').resolve();target=(out/'rejected-candidate-dose4').resolve();bound=out.resolve()
        assert source.parent==target.parent==bound and not target.exists()
        retained_hash=sha(partial);os.rename(source,target)
        for src,dst in [(folder/'selected-recipe.json',target/'selected-recipe.json'),(out/'random-recipe.json',target/'random-recipe.json')]:
            shutil.copy2(src,dst);assert sha(src)==sha(dst)
        atomic_json(folder/'selected-recipe.json',recipe);atomic_json(out/'random-recipe.json',random_control(recipe))
        marker_value={'model':name,'base_sha256':fingerprint,'selected_recipe_sha256':sha(folder/'selected-recipe.json'),'random_recipe_sha256':sha(out/'random-recipe.json'),'cases_sha256':sha(out/'cases.json'),'baseline_records':records,
                      'baseline_request_sha256':sha(out/'baseline/request.json'),'rejected_partial':{'path':'rejected-candidate-dose4/candidate.gguf.partial','sha256':retained_hash,'bytes':partial.stat().st_size if partial.exists() else (target/partial.name).stat().st_size},
                      'no_baseline_replay':True,'production_model_changed':False}
        atomic_json(marker,marker_value);space(LAB)
        print(json.dumps({'prepared':name,'chosen':chosen,'baseline_records_preserved':len(records),'rejected_partial_retained':True,'GPU_loaded':False}),flush=True)
    finally:ledger.close()

if __name__=='__main__':prepare()
