"""Verify the actual 27B delta in a disposable root without touching live settings."""
import argparse,hashlib,json,shutil,sys
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--drive',choices=['D','E'],required=True);args=parser.parse_args()
root=Path(args.drive+':/PortalAI Windows')
sys.path[:0]=[str(root/'Tools/WeightSpace'),str(root/'Agent')]
from edit_profiles import prepare_profile,clear_prepared
from weight_edit_profiles import read_manifest,resolve_model
from experiment import sha,atomic_json,space
catalog=json.loads((root/'LLM/WeightEdits/EVALUATED-PROFILES.json').read_text())
profile=next(p for p in catalog['profiles'] if p['model']=='27-abliterated')
identifier=profile['profile_id'];source=root/'LLM/WeightEdits/Profiles'/(identifier+'.wsedit')
manifest=read_manifest(source);model=root/'LLM/models'/manifest['base_name']
base=root/'Maintenance/Validation/Weight-Final-r69'
fixture=base/'ProfileRoundtrip-27-abliterated'
assert not fixture.exists(), 'Existing fixture needs review'
assert fixture.resolve().parent==base.resolve()
space(base,model.stat().st_size+source.stat().st_size+64*1024**2)
folder=fixture/'LLM/WeightEdits/Profiles';folder.mkdir(parents=True)
archive=folder/source.name;shutil.copy2(source,archive);assert sha(archive)==profile['sha256']
original_before=sha(model);assert original_before==manifest['base_sha256']
# This isolated root has no server, account, GUI or loaded model. The live
# prepared cache and GPU lease are never used or altered by this CPU check.
prepared=prepare_profile(fixture,model,identifier)
candidate=Path(prepared['candidate'])
assert candidate.resolve().is_relative_to(fixture.resolve())
assert candidate.stat().st_size==model.stat().st_size and sha(candidate)==manifest['candidate_sha256']
selected=resolve_model(fixture,{'absolute_path':str(model)},{'weight_edit_profile':identifier})
assert Path(selected['absolute_path']).resolve()==candidate.resolve()
original=resolve_model(fixture,{'absolute_path':str(model)},{'weight_edit_profile':'original'})
assert Path(original['absolute_path']).resolve()==model.resolve()
assert sha(model)==original_before
assert clear_prepared(fixture,identifier) and not candidate.exists()
assert sha(archive)==profile['sha256'] and sha(source)==profile['sha256']
assert archive.resolve().parent==folder.resolve() and archive.resolve().is_relative_to(fixture.resolve())
archive.unlink()  # Only this newly created, checksum-verified validation copy.
report={'passed':True,'drive':args.drive,'profile_id':identifier,'model':'27-abliterated',
        'patch_sha256':profile['sha256'],'original_sha256':original_before,
        'reconstructed_candidate_sha256':manifest['candidate_sha256'],
        'original_unchanged':True,'selection_and_revert_resolve_correctly':True,
        'disposable_prepared_copy_removed_after_verification':True,
        'live_profile_preferences_or_prepared_cache_changed':False,
        'gpu_or_model_inference_used':False,'free_bytes':shutil.disk_usage(root).free}
atomic_json(base/'PROFILE-ROUNDTRIP-27-abliterated.json',report)
print(json.dumps(report),flush=True)
