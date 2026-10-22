"""Run bounded synthetic navigation/account/lifecycle regressions with a report."""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Maintenance/Tests','ControlCenter','Agent')]
from validation_artifacts import ValidationArtifacts

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('modules',nargs='*');args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    modules=args.modules or ['test_navigation_activity','test_settings_surfaces_tk','test_chat_settings_layout_tk',
        'test_chat_layout_tk','test_chat_zoom_tk','test_chat_effort_ui','test_gui_maintenance','test_gui_stop_contract',
        'test_gui_diagnostic_status','test_runtime_policy','test_mission_catalog_tk','test_mission_catalog',
        'test_mission_schedule','test_persistence_supervisor','test_chat_handoff','test_chat_context_budget',
        'test_platform_metadata','test_gui_polish','test_kicad_windows','test_kicad_linux',
        'test_shutdown_lifecycle_tk','test_account_presentation_tk','test_account_gate','test_writer_jobs']
    with artifacts.path('tests.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(modules))
    report={'synthetic_only':True,'modules':modules,'run':result.testsRun,'passed':result.wasSuccessful(),
            'failures':[str(t) for t,_ in result.failures],'errors':[str(t) for t,_ in result.errors],
            'skipped':[(str(t),why) for t,why in result.skipped]}
    artifacts.path('tests.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
