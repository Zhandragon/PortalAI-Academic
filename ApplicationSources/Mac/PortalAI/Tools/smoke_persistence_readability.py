"""Capture labeled persistence sheets using disposable records, never user missions."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Tools','Agent','ControlCenter','Maintenance/Tests')]
from test_persistence_readability_tk import PersistenceReadabilityTests, Missions, Schedules
from mission_settings import show_mission_settings
from schedule_settings import show_schedule_settings
from test_settings_surfaces_tk import LIGHT, DARK
from smoke_account_panels import capture_window
from validation_artifacts import ValidationArtifacts


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir);images=[]
    for kind, factory in (('missions',show_mission_settings),('schedules',show_schedule_settings)):
        fixture=PersistenceReadabilityTests();fixture.setUp()
        try:
            fixture.sheet=factory(fixture.app,fixture.root,LIGHT,embedded=True)
            fixture.app.update()
            images.append(capture_window(fixture.app,artifacts.path(kind+'-empty.png')))
            if kind=='missions':
                record=Missions(fixture.root).create('Summarize the bundled synthetic report without changing any files')
                tree=fixture.sheet.mission_tree
            else:
                record=Schedules(fixture.root).create('Check the synthetic report for changes','observe',12,3600,None,3)
                tree=fixture.sheet.schedule_tree
            fixture.sheet.refresh_records();tree.selection_set(record['id']);tree.event_generate('<<TreeviewSelect>>')
            fixture.app.update()
            images.append(capture_window(fixture.app,artifacts.path(kind+'-selected.png')))
            fixture.sheet.apply_palette(DARK);fixture.app.geometry('600x720+30+30');fixture.app.update()
            images.append(capture_window(fixture.app,artifacts.path(kind+'-narrow-dark.png')))
        finally:fixture.tearDown()
    report={'passed':True,'scope':'Synthetic Tk and disposable records only; no missions or schedules started','screenshots':images}
    artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
