"""Run bounded Linux guest checks while owned chat is handed off and restored."""
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json,portable_env
from service_manager import acquire_gpu_lease,release_gpu_lease,qwen_gpu_handoff_begin,qwen_gpu_handoff_end
sys.path.insert(0,str(Path(__file__).resolve().parent))
from validation_artifacts import ValidationArtifacts,add_artifact_arguments


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    add_artifact_arguments(parser,media=True)
    options=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,options.artifacts_dir)
    forwarded=[]
    if options.artifacts_dir:forwarded+=['--artifacts-dir',str(artifacts.base)]
    if options.media_iso:forwarded+=['--media-iso',options.media_iso]
    from profile_paths import capture
    capture(ROOT)  # Synthetic report routing never authorizes touching a locked chat.
    lease=acquire_gpu_lease('linux-packaging-validation');state=None
    report={'passed':False}
    try:
        state=qwen_gpu_handoff_begin('linux-packaging-validation')
        result=subprocess.run([sys.executable,'-B','-I',str(ROOT/'Tools/run_linux_packaging.py'),'--media',
            '--cases','genomics,media-gui,media-tools,owned-tools,comfy,supervision,ml-imports',*forwarded],cwd=ROOT,env=portable_env(ROOT),timeout=920)
        report['guest']=json.loads(artifacts.path('linux-media-guest.json').read_text())
        report['passed']=result.returncode==0 and report['guest']['passed']
    finally:
        try:
            report['restoration']=qwen_gpu_handoff_end(state)
            if state and state.get('active'):report['passed']=report['passed'] and report['restoration'].get('ready',False)
        finally:
            release_gpu_lease(lease)
            atomic_json(artifacts.path('linux-handoff-validation.json'),report)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
