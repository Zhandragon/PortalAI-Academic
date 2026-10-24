"""Exit must revoke work after hydration admission closes, without reading histories."""
import hashlib,json,os,subprocess,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
import test_lazy_missions as lazy_fixtures
from mission_supervisor import pause_all,arm,read_policy
from profile_paths import ProfileLocked

class ShutdownFences(unittest.TestCase):
    setUp=lazy_fixtures.LazyMissionTests.setUp
    tearDown=lazy_fixtures.LazyMissionTests.tearDown
    records=lazy_fixtures.LazyMissionTests.records
    reopen=lazy_fixtures.LazyMissionTests.reopen
    assert_dormant=lazy_fixtures.LazyMissionTests.assert_dormant

    def prepare_records(self):
        missions,schedules,records,s=self.records()
        arm(self.root,records[0]['id']);arm(self.root,records[1]['id']);schedules.enable(s['id']);s=schedules.load(s['id'])
        missions,schedules=self.reopen()
        self.runtime.pause_hydration()
        return missions,schedules,records,s

    def test_exit_fences_dormant_records_without_restoring_checkpoint_bodies(self):
        missions,schedules,records,s=self.prepare_records()
        self.assert_dormant(records,s)
        pause_all(self.root)
        self.assert_dormant(records,s)
        for m in records:
            self.assertTrue((missions.base/m['id']/'STOP').exists())
            self.assertFalse(read_policy(missions,m['id'])['enabled'])
        from mission_schedule import epoch
        self.assertNotEqual(s['epoch'],epoch(self.root))
        # Resume one root after a later sign-in; the other must remain fenced.
        missions,schedules=self.reopen()
        missions.resume(records[0]['id']);arm(self.root,records[0]['id'])
        self.assertFalse(read_policy(missions,records[1]['id'])['enabled'])
        self.assertTrue(missions.stopped(missions.load(records[1]['id'])))
        self.assertFalse(schedules.enabled(schedules.load(s['id'])))

    def test_real_stop_child_can_finish_while_broker_is_paused(self):
        missions,schedules,records,s=self.prepare_records()
        import mission_supervisor
        code="import sys;from pathlib import Path;sys.path[:0]="+repr([str(Path(mission_supervisor.__file__).parent),*sys.path])+";from mission_supervisor import pause_all;print(len(pause_all(Path("+repr(str(self.root))+"))))"
        result=subprocess.run([sys.executable,'-B','-I','-X','utf8','-c',code],env=dict(os.environ),capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(result.stdout.strip(),'3')
        self.assert_dormant(records,s)
        receipt=self.runtime.close(self.session,writers_stopped=True)
        self.assertTrue(receipt['sealed'])
        self.assertEqual(json.loads(self.runtime.marker.read_text())['state'],'closed')

    def test_uncertain_action_is_preserved_and_cannot_auto_resume(self):
        missions,schedules,records,s=self.records()
        m=records[0];m.update(status='needs_review',pending_action={'action':'note','text':'possibly written'})
        missions.save(m)
        raw=(missions.base/m['id']/'mission.json').read_bytes()
        missions,schedules=self.reopen();self.runtime.pause_hydration();pause_all(self.root)
        missions,schedules=self.reopen();loaded=missions.load(m['id'])
        self.assertEqual(loaded['pending_action'],m['pending_action'])
        self.assertEqual((missions.base/m['id']/'mission.json').read_bytes(),raw)
        with self.assertRaises(ValueError):arm(self.root,m['id'])
        with self.assertRaises(ValueError):missions.resume(m['id'])

    def test_ended_login_cannot_change_stop_controls(self):
        missions,schedules,records,s=self.records()
        with patch.dict(os.environ,{'PORTALAI_PROFILE_EPOCH':'0'*32}):
            with self.assertRaises(ProfileLocked):pause_all(self.root)
        self.assertFalse((missions.base/'supervisor.stop').exists())
        self.assertTrue(all(not (missions.base/m['id']/'STOP').exists() for m in records))

    def test_corrupt_policy_is_preserved_behind_stop(self):
        missions,schedules,records,s=self.records();p=missions.base/records[0]['id']/'run-policy.json';p.write_text('broken')
        missions,schedules=self.reopen();self.runtime.pause_hydration();pause_all(self.root)
        self.assertEqual(p.read_text(),'broken');self.assertTrue(p.with_name('STOP').exists())

class FailureDisplay(unittest.TestCase):
    def test_failed_timer_stops_and_phase_is_retained(self):
        import tkinter as tk
        from shutdown_ui import ShutdownStatus
        from test_modal_surfaces_tk import LIGHT
        from tk_fixture_cleanup import finish_tk_fixture
        app=tk.Tk();status=ShutdownStatus(app,LIGHT,lambda:None)
        try:
            status.begin();status.update('Stopping mission workers')
            status.failure('PermissionError');app.update()
            self.assertIsNone(status.timer)
            self.assertIn('Stopping mission workers',status.phase.cget('text'))
            self.assertIn('PermissionError',status.phase.cget('text'))
            before=status.elapsed.cget('text');status._tick();self.assertEqual(status.elapsed.cget('text'),before)
            self.assertTrue(before.startswith('Stopped after:'))
            status.begin();self.assertFalse(status.failed);self.assertIsNotNone(status.timer)
        finally:status.finish();finish_tk_fixture(app)

if __name__=='__main__':unittest.main()
