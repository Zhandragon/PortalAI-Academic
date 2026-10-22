"""Read-only source evidence, not a universal model-behavior or license audit."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Tools'))
from validation_artifacts import ValidationArtifacts

TREES={
 'voice':'Voice/Qwen3-TTS/python/cpython-3.12.14-windows-x86_64-none/Lib/site-packages/qwen_tts',
 'music':'Music/ACE-Step-1.5/acestep',
 'sfx':'Services/MMAudio/mmaudio'}
ROUTES={
 'vace':['Agent/vace_reference.py','Agent/radeon_edit.py','Workflows/API/Wan2.1_VACE_14B_V2V_API.json'],
 'voice':['Voice/Qwen3-TTS/qwen_tts_runner.py','Agent/tts_policy.py'],
 'music':['Agent/music_amd_bridge.py','Agent/acestep_amd_entry.py'],
 'sfx':['Agent/sfx_amd_bridge.py','Agent/mmaudio_worker.py','Agent/mmaudio_staged.py'],
 'musetalk':['Agent/musetalk_bridge.py','Agent/musetalk_amd_bridge.py'],
 'pix2pix':['Agent/radeon_edit_entry.py']}
PATTERN=re.compile(r'safety_checker|\bnsfw\b|censor|moderation|banned_words|profanity',re.I)

def audit():
    rows=[]
    for family,paths in ROUTES.items():
        sources=[ROOT/p for p in paths]
        if family in TREES:sources+=list((ROOT/TREES[family]).rglob('*.py'))
        entries=[];matches=[]
        for path in sorted(set(sources)):
            if not path.is_file():raise FileNotFoundError(path)
            data=path.read_bytes();relative=path.relative_to(ROOT).as_posix()
            entries.append({'path':relative,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
            for i,line in enumerate(data.decode('utf-8-sig').splitlines(),1):
                if PATTERN.search(line):matches.append({'path':relative,'line':i,'text':line.strip()[:300]})
        rows.append({'family':family,'files':entries,'keyword_matches':matches})
    return {'scope':__doc__,'date':'2026-10-12','source_evidence':rows,
            'interpretation':'Installed local calls/graphs reviewed: no separate prompt/output content classifier or runtime rejection stage found. Pix2Pix explicitly disables its optional safety checker. Keyword scanning alone is not proof; learned refusals, training exclusions and unsupported concepts are not tested. Hosted service policies and model licenses are separate.'}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir);report=audit()
    artifacts.path('specialist-source-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps([{'family':r['family'],'files':len(r['files']),'keyword_matches':r['keyword_matches']} for r in report['source_evidence']]))
