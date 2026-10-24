"""Opt-in adaptive scheduling without replay, permission or Stop bypass."""
import json,sys,time,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Maintenance/Tests')]
import test_mission_schedule as fixtures
from mission_runner import MissionContextError
from mission_supervisor import disarm
from mission_schedule import pause_schedules
from mission_recovery import recover

class AutonomousRecoveryTests(unittest.TestCase):
    setUp=fixtures.ScheduleTests.setUp
    def start(self,enabled=True,steps=8,limit=3):
        s=self.schedules.create('Inspect a business report and advance one useful task',first_run_at=0,interval_seconds=60,max_steps=steps,max_runs=limit)
        self.schedules.set_autonomous_recovery(s['id'],enabled)
        self.schedules.enable(s['id']);self.schedules.tick()
        return self.schedules.load(s['id'])
    def ready(self,mid):
        m=self.store.load(mid);m['next_run_at']=0;self.store.save(m)
    def test_disabled_defaults_require_review_and_policy_toggle_never_starts(self):
        s=self.schedules.create('No automatic start')
        self.assertNotIn('autonomous_recovery',s)
        self.schedules.set_autonomous_recovery(s['id'],True)
        self.assertFalse(self.schedules.any_enabled());self.assertEqual(self.store.list(),[])
        s=self.start(False)
        m=self.store.run(s['active_run'],model=lambda _:{'action':'read_file','path':'workspace/business.md'})
        self.assertEqual(m['status'],'needs_review');self.assertIsNotNone(m['pending_action'])
    def test_failed_read_replans_with_evidence_then_completes_without_fake_success(self):
        s=self.start();mid=s['active_run']
        m=self.store.run(mid,model=lambda _:{'action':'read_file','path':'workspace/business.md'})
        self.assertEqual(m['status'],'waiting');self.assertIsNone(m['pending_action'])
        self.assertEqual(m['history'],[]);self.assertEqual(m['steps'],1)
        self.assertIn('PermissionError',m['recovery_history'][-1]['error'])
        self.ready(mid)
        m=self.store.run(mid,model=lambda _:{'action':'note','text':'Use an authorized alternative input'})
        self.assertIn('Use an authorized alternative input',(self.store.folder(mid)/'notes.txt').read_text())
        m=self.store.run(mid,model=lambda _:{'action':'complete','text':'This bounded fixture is done'})
        self.schedules.tick();self.assertEqual(self.schedules.load(s['id'])['runs_completed'],1)
    def test_planner_failure_uses_budget_and_next_heartbeat_without_backlog(self):
        s=self.start(steps=1,limit=2);mid=s['active_run']
        def fail(_):raise MissionContextError('Identical action; choose another strategy')
        m=self.store.run(mid,model=fail);self.assertEqual(m['status'],'budget_exhausted')
        self.schedules.tick(now=1000);s=self.schedules.load(s['id'])
        self.assertTrue(self.schedules.enabled(s));self.assertEqual(s['runs_completed'],0)
        self.assertEqual(s['history'][-1]['status'],'budget_exhausted')
        self.assertEqual(s['next_run_at'],1060);self.assertEqual(len(self.store.list()),1)
        self.schedules.tick(now=1060);s=self.schedules.load(s['id'])
        self.assertNotEqual(s['active_run'],mid);self.assertEqual(len(self.store.list()),2)
        self.store.run(s['active_run'],model=fail);self.schedules.tick(now=1120)
        s=self.schedules.load(s['id']);self.assertFalse(self.schedules.enabled(s));self.assertEqual(s['runs_started'],2)
    def test_uncertain_shell_never_replayed_or_cleared(self):
        s=self.start();m=self.store.load(s['active_run'])
        m.update(pending_action={'action':'shell','command':'effectful operation'},status='running');self.store.save(m)
        before=m['pending_action'].copy()
        m=self.store.run(m['id'],model=lambda _:self.fail('Must not plan'))
        self.schedules.tick();self.assertEqual(m['pending_action'],before)
        self.assertEqual(m['status'],'needs_review');self.assertFalse(self.schedules.any_enabled())
    def test_agent_pause_stops_schedule_and_records_reason(self):
        s=self.start();m=self.store.run(s['active_run'],model=lambda _:{'action':'pause','text':'No authorized input can resolve this objective'})
        self.assertEqual(m['status'],'paused');self.assertTrue(m['agent_pause'])
        self.schedules.tick();s=self.schedules.load(s['id'])
        self.assertFalse(self.schedules.enabled(s));self.assertIn('No authorized input',s['error'])
        self.store.resume(m['id']);self.assertNotIn('agent_pause',self.store.load(m['id']))
    def test_stop_epoch_disabled_policy_and_direct_stop_prevent_recovery(self):
        for change in ('epoch','toggle','stop'):
            s=self.start();m=self.store.load(s['active_run'])
            if change=='epoch':pause_schedules(self.root)
            elif change=='toggle':self.schedules.set_autonomous_recovery(s['id'],False)
            else:disarm(self.root,m['id'])
            m=self.store.load(m['id']);before=json.dumps(m,sort_keys=True)
            self.assertFalse(recover(self.store,m,'Read failed'))
            self.assertEqual(json.dumps(m,sort_keys=True),before)
    def test_policy_revocation_during_recovery_does_not_mutate_checkpoint(self):
        s=self.start();m=self.store.load(s['active_run']);before=json.dumps(m,sort_keys=True)
        with patch('mission_recovery.schedule_for',side_effect=[s,None]):
            self.assertFalse(recover(self.store,m,'Read failed'))
        self.assertEqual(json.dumps(m,sort_keys=True),before)
        self.assertEqual(json.dumps(self.store.load(m['id']),sort_keys=True),before)
    def test_legacy_read_only_review_can_replan_but_stop_cannot(self):
        s=self.start();m=self.store.load(s['active_run'])
        m.update(status='needs_review',pending_action={'action':'read_file','path':'workspace/business.md'},error='Old failed read');self.store.save(m)
        self.schedules.tick();m=self.store.load(m['id'])
        self.assertEqual(m['status'],'waiting');self.assertIsNone(m['pending_action'])
        disarm(self.root,m['id']);self.schedules.tick()
        self.assertFalse(self.schedules.any_enabled());self.assertTrue((self.store.folder(m['id'])/'STOP').exists())

    def test_next_occurrence_context_retains_failed_outcome_without_claiming_success(self):
        from mission_context import build_messages
        from test_mission_context import tokenizer
        s=self.start(steps=1)
        self.store.run(s['active_run'],model=lambda _:{'action':'read_file','path':'workspace/business.md'})
        self.schedules.tick(now=1000);self.schedules.tick(now=1060)
        s=self.schedules.load(s['id']);m=self.store.load(s['active_run'])
        messages=build_messages(self.store,m,'Rules',[],'',8192,tokenizer)
        context=json.loads(messages[1]['content'])['scheduled_run']
        self.assertEqual(context['occurrence'],2);self.assertEqual(context['previous_runs_completed'],0)
        self.assertEqual(context['previous_run_outcome'][0]['status'],'budget_exhausted')
        self.assertIn('later occurrence',context['rule'])
        self.assertIn('PermissionError',json.dumps(context['previous_run_outcome']))

    def test_execution_checkpoint_failure_is_not_misreported_as_safe_planning_failure(self):
        s=self.start();mid=s['active_run'];original=self.store.save
        def fail_once(m):
            if m.get('pending_action') and m.get('status')=='running':raise OSError('Disk write failed')
            return original(m)
        with patch.object(self.store,'save',side_effect=fail_once):
            m=self.store.run(mid,model=lambda _:{'action':'note','text':'Do not execute'})
        self.assertEqual(m['status'],'needs_review');self.assertNotIn('recovery_history',m)
        self.assertFalse((self.store.folder(mid)/'notes.txt').exists())

    def test_previous_run_evidence_is_read_only_and_checks_schedule_identity(self):
        s=self.start(steps=1);mid=s['active_run']
        self.store.run(mid,steps=1,model=lambda _:{'action':'note','text':'Verified receipt from prior occurrence'})
        self.store.run(mid,steps=1,model=lambda _:self.fail('Budget already used'))
        self.schedules.tick(now=1000);self.schedules.tick(now=1060)
        s=self.schedules.load(s['id']);m=self.store.load(s['active_run'])
        action={'action':'previous_run','start':1,'count':1}
        result=json.loads(self.store.execute(m,action))
        self.assertEqual(result['records'][0]['action']['text'],'Verified receipt from prior occurrence')
        before=(self.store.folder(mid)/'mission.json').read_bytes()
        self.store.execute(m,action)
        self.assertEqual((self.store.folder(mid)/'mission.json').read_bytes(),before)
        bad=self.store.create('Unrelated record');s['history'][-1]['mission']=bad['id'];self.schedules.save(s)
        with self.assertRaisesRegex(ValueError,'identity mismatch'):self.store.execute(m,action)

if __name__=='__main__':unittest.main()
