"""Focused offline regressions; no production account, VM or model inference."""
import argparse
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Agent','ControlCenter','Maintenance/Tests')]
from validation_artifacts import ValidationArtifacts

MODULES=('test_cpu_music','test_persistence_readability_tk','test_mission_catalog_tk','test_mission_catalog','test_mission_schedule','test_persistence_supervisor','test_platform_metadata','test_media_defaults','test_settings_surfaces_tk','test_startup_settings',
 'test_music_amd_bridge',
 'test_native_flux','test_inline_chat_images','test_gui_polish',
 'test_model_variants','test_media_policy','test_image_effort','test_media_tool_api',
 'test_personal_model_policy','test_assistant_guidance','test_guidance_metadata',
 'test_sdcpp_bridge','test_scaled_media','test_remaining_media_routes','test_vace_reference',
 'test_chat_handoff','test_chat_handoff_effort_smoke','test_chat_completion_recovery',
 'test_chat_hydration','test_chat_effort_ui','test_chat_model_switch','test_effort_policy',
 'test_gui_maintenance','test_gui_stop_contract','test_writer_jobs',
 'test_account_media_commands','test_profile_media','test_runtime_policy','test_mission_runner',
 'test_small_model_chat','test_chat_zoom_tk','test_validation_artifacts','test_linux_iso_sources',
 'test_tool_protocol','test_nice_prompt_integration','test_chat_context_budget',
 'test_shutdown_lifecycle_tk','test_tts_policy','test_tts_cli')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    with artifacts.path('unittest.log').open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(MODULES))
    report={'passed':result.wasSuccessful(),'tests':result.testsRun,
            'skipped':[(str(t),reason) for t,reason in result.skipped],
            'failures':[(str(t),err) for t,err in result.failures],
            'errors':[(str(t),err) for t,err in result.errors], 'modules':MODULES,
            'scope':__doc__}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='modules'}));raise SystemExit(not result.wasSuccessful())
