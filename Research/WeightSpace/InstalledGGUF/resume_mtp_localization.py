"""Explicit reconciliation of the reviewed inactive-MTP capture failure only."""
import sys
if __name__ == '__main__' and sys.stdin.readline().strip() != 'start':
    raise SystemExit('Owned start gate required')
import json
import shutil
from pathlib import Path

LAB = Path(__file__).resolve().parent
ROOT = LAB.parents[2]
sys.path[:0] = [str(LAB), str(ROOT/'Tools/WeightSpace'), str(ROOT/'Agent')]
import research_guard
research_guard.LAB = LAB
from experiment import Ledger, atomic_json, sha, space
from extend_discovery import records
from diagnosis import propose
from service_manager import acquire_gpu_lease, release_gpu_lease


def main():
    research_guard.require_gpu_unpaused()
    correction = json.loads((LAB/'MTP-CAPTURE-CORRECTION.json').read_text())
    assert sha(ROOT/'Tools/WeightSpace/native_forward.py') == correction['native_forward_sha256']
    assert correction['generation_sampling_and_prompt_rendering_unchanged']
    for drive in ('D', 'E'):
        check = json.loads((ROOT/f'Maintenance/Validation/Weight-MTP-r69/metadata-{drive}.json').read_text())
        assert check['passed'] and check['tests'] == 8 and check['skipped'] == 0
    folder = LAB/'experiments/27-abliterated'
    model = ROOT/'LLM/models/Qwen3.8-27B-Abliterated-Q4_K_M.gguf'
    fingerprint = sha(model)
    assert fingerprint == '935796865642fdc705f0f24459db3163c9f7f434f7e53650574d5c52d9b70813'
    saved = records(folder)
    assert len(saved) == 56 and sum(r['grading']['correct'] for r in saved) == 49
    assert len({r['id'] for r in saved}) == 56
    for name in ('001-natural-discovery', '001b-natural-discovery'):
        assert json.loads((folder/name/'request.json').read_text())['base_sha256'] == fingerprint
    localization = folder/'002-localization'
    assert localization.resolve().is_relative_to(folder.resolve()) and localization.is_dir()
    assert not any(localization.iterdir()), 'Unexpected partial outputs require separate review'
    assert not (folder/'003-causal-screen').exists() and not (folder/'selected-recipe.json').exists()
    ledger = Ledger(folder/'ledger.sqlite')
    lease = None
    pass_id = '002-localization-mtp-resume-1'
    try:
        rows = ledger.db.execute('SELECT id,status,evidence FROM runs ORDER BY created').fetchall()
        assert [(r[0],r[1]) for r in rows] == [
            ('001-natural-discovery','complete'), ('001b-natural-discovery','complete'),
            ('002-localization','interrupted')], rows
        assert 'Missing replay graph sites' in rows[-1][2]
        archive = folder/'reviewed-interruptions/mtp-capture-1'
        assert archive.resolve().is_relative_to(folder.resolve()) and not archive.exists()
        space(folder)
        archive.mkdir(parents=True)
        shutil.copy2(folder/'ledger.sqlite', archive/'ledger-before.sqlite')
        assert sha(folder/'ledger.sqlite') == sha(archive/'ledger-before.sqlite')
        frozen = {p.relative_to(LAB).as_posix():sha(p) for name in ('001-natural-discovery','001b-natural-discovery')
                  for p in sorted((folder/name).glob('*.json'))}
        for name in ('protocol.json','splits.json','practice.jsonl','causal_screen.py',
                     'REFERENCE-FORMAT-CORRECTION.json','MTP-CAPTURE-CORRECTION.json'):
            frozen[name] = sha(LAB/name)
        request = {'base_sha256':fingerprint,'replaces_interrupted_pass':'002-localization',
                   'reason':'Main decoder omits one NextN/MTP block; capture metadata repaired.',
                   'frozen_inputs':frozen,'native_forward_sha256':correction['native_forward_sha256'],
                   'discovery_answers_regenerated':False,'new_pass_accounted':True}
        atomic_json(archive/'reconciliation.json',request)
        localization.rename(archive/'empty-localization')
        localization.mkdir()
        assert ledger.begin(pass_id,'discovery',request)
        lease = acquire_gpu_lease('weight-space-mtp-localization-resume',timeout=3)
        try:
            result = propose(model,saved,localization,progress=lambda row:print(json.dumps(row),flush=True))
            assert all(sha(LAB/name)==digest for name,digest in frozen.items())
            assert sha(model)==fingerprint
            result.update({'original_hash_verified_after':True,'frozen_inputs_unchanged':True})
            ledger.end(pass_id,result)
            atomic_json(folder/'MTP-RESUME.json',{'passed':True,'request':request,'result':result})
            print(json.dumps(result),flush=True)
        except BaseException as exc:
            ledger.end(pass_id,{'error':repr(exc)},False)
            raise
    finally:
        if lease: release_gpu_lease(lease)
        ledger.close()


if __name__ == '__main__':
    main()
