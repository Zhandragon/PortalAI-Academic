"""Offline routing/GUI regressions with disposable accounts and synthetic hardware.

No production login, media inference, physical GPU validation or live chat handoff.
"""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Agent','ControlCenter','Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts
from validate_media_previews import MODULES as BASE

FOCUSED=('test_media_policy','test_media_tool_api','test_image_effort','test_personal_model_policy',
         'test_nice_prompt_integration','test_assistant_guidance','test_science_backends','test_hardware_media_transitions',
         'test_workload_request','test_remaining_media_routes','test_mission_runner','test_chat_effort_ui')
MODULES=tuple(dict.fromkeys((*BASE,*FOCUSED,'test_native_video','test_audio_inpaint_scaled',
    'test_dialogue_portable','test_linux_music_understanding','test_linux_science_portable',
    'test_music_route_recovery','test_sd15_variants','test_amd_runtime','test_linux_handoff_watchdog',
    'test_navigation_activity','test_mission_modes','test_vm_runner','test_biology','test_coupled_physics',
    'test_kicad_linux','test_kicad_windows')))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--focused',action='store_true')
    args=parser.parse_args(); artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    modules=FOCUSED if args.focused else MODULES
    with artifacts.path('unittest.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
    report={'passed':result.wasSuccessful(),'tests':result.testsRun,'modules':modules,'scope':__doc__,
            'skipped':[(str(t),r) for t,r in result.skipped],
            'failures':[(str(t),err) for t,err in result.failures],
            'errors':[(str(t),err) for t,err in result.errors]}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='modules'}))
    return not result.wasSuccessful()

if __name__=='__main__':raise SystemExit(main())
