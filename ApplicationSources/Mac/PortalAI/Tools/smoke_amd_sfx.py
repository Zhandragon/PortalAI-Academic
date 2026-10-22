"""Real small MMAudio inference using ROCm packages on CPU (not Radeon validation)."""
import json
from pathlib import Path
import sys
import time
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from ai_tools import _exclusive_gpu
from sfx_amd_bridge import plan,generate
from runtime_policy import atomic_json

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--video');args=parser.parse_args()
    started=time.monotonic()
    report={'passed':False,'physical_radeon_test':False}
    try:
        with _exclusive_gpu(None,'amd-audio-cpu-validation'):
            profile=plan(cpu_validation=True)
            result=generate(profile,'Rain falling on a window',duration=1,num_steps=2,video=args.video)
        report.update(passed=True,profile=profile,result=result,seconds=round(time.monotonic()-started,2))
    except Exception as exc:
        report['error']=str(exc);raise
    finally:atomic_json(ROOT/('Maintenance/Reports/amd-sfx-video-smoke.json' if args.video else 'Maintenance/Reports/amd-sfx-smoke.json'),report)
    print(json.dumps(report,indent=2))
