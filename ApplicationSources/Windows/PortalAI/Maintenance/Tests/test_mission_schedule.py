import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
from mission_runner import Missions, MissionContextError
from mission_schedule import Schedules, pause_schedules
from mission_supervisor import Supervisor, pause_all, read_policy, arm, ensure_running
from mission_memory import Memory


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='Portal mission schedule ');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);(self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}}))
        self.store=Missions(self.root);self.schedules=Schedules(self.root)

    def schedule(self, **kwargs):
        s=self.schedules.create('Check and remember progress',first_run_at=100,**kwargs)
        self.schedules.enable(s['id']);return s

    def test_create_is_paused(self):
        self.schedules.create('Do not run')
        self.schedules.tick(now=100000000000)
        self.assertEqual(self.store.list(),[])

    def test_due_only_and_no_overlapping_or_duplicate_runs(self):
        s=self.schedule(interval_seconds=60)
        self.schedules.tick(now=99);self.assertEqual(self.store.list(),[])
        self.schedules.tick(now=100);first=self.store.list()[0]
        self.schedules.tick(now=99999)
        self.assertEqual(len(self.store.list()),1)
        self.assertTrue(read_policy(self.store,first['id'])['enabled'])
        self.assertEqual(first['schedule_id'],s['id'])

    def test_missing_materialized_run_reuses_checkpointed_id(self):
        s=self.schedule()
        # Simulate process death after the schedule checkpoint but before mission creation.
        with patch.object(self.schedules,'_ensure_run',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.schedules.tick(now=100)
        saved=self.schedules.load(s['id']);self.assertEqual(self.store.list(),[])
        self.schedules.tick(now=101)
        self.assertEqual(self.store.list()[0]['id'],saved['active_run'])
        self.assertEqual(self.schedules.load(s['id'])['runs_started'],1)

    def test_pending_effect_blocks_later_occurrences(self):
        s=self.schedule();self.schedules.tick(now=100)
        m=self.store.list()[0];m['pending_action']={'action':'shell','command':'uncertain'};self.store.save(m)
        self.schedules.tick(now=99999)
        self.assertEqual(len(self.store.list()),1)
        self.assertFalse(self.schedules.enabled(self.schedules.load(s['id'])))
        self.assertEqual(self.schedules.load(s['id'])['status'],'needs_review')

    def test_completion_coalesces_missed_runs_and_honors_run_limit(self):
        s=self.schedule(interval_seconds=60,max_runs=2);self.schedules.tick(now=100)
        m=self.store.list()[0];self.store.run(m['id'],model=lambda _:{'action':'complete'})
        self.schedules.tick(now=10000);s=self.schedules.load(s['id'])
        self.assertEqual(s['next_run_at'],10060);self.assertIsNone(s['active_run'])
        self.schedules.tick(now=10060);self.assertEqual(len(self.store.list()),2)
        m=self.store.load(self.schedules.load(s['id'])['active_run'])
        self.store.run(m['id'],model=lambda _:{'action':'complete'})
        self.schedules.tick(now=10061)
        self.assertEqual(self.schedules.load(s['id'])['status'],'complete')
        with self.assertRaises(ValueError):self.schedules.enable(s['id'])

    def test_stop_fence_survives_restart_and_enabling_another_schedule(self):
        a=self.schedule();b=self.schedule();pause_all(self.root)
        self.assertFalse(Schedules(self.root).any_enabled())
        self.schedules.enable(a['id']);self.schedules.tick(now=100)
        self.assertEqual(len(self.store.list()),1)
        self.assertFalse(self.schedules.enabled(self.schedules.load(b['id'])))

    def test_epoch_change_during_creation_cannot_arm_late_run(self):
        s=self.schedule();original=self.store.create
        def create(*args,**kwargs):
            result=original(*args,**kwargs);pause_schedules(self.root);return result
        with patch.object(self.schedules.store,'create',side_effect=create):self.schedules.tick(now=100)
        m=self.store.list()[0];self.assertFalse(read_policy(self.store,m['id'])['enabled'])
        self.assertEqual(Supervisor(self.root).selection()[0],[])

    def test_future_schedule_keeps_supervisor_alive_without_model_calls(self):
        s=self.schedules.create('Future',first_run_at=9999999999);self.schedules.enable(s['id'])
        with patch('mission_supervisor.subprocess.Popen') as launch:
            self.assertTrue(Supervisor(self.root,model_ready=lambda:False).tick())
            launch.assert_not_called()

    def test_bad_checkpoint_does_not_hide_other_missions_or_replay_old_copy(self):
        a=self.store.create('Good');b=self.store.create('Damaged')
        self.store.save(b);(self.store.folder(b['id'])/'mission.json').write_text('{broken')
        self.assertEqual([m['id'] for m in self.store.list()],[a['id']])
        self.assertEqual(self.store.load_errors[0]['mission'],b['id'])
        self.assertTrue((self.store.folder(b['id'])/'mission.previous.json').exists())
        with self.assertRaises(ValueError):self.store.load(b['id'])

    def test_corrupt_typed_fields_do_not_break_other_scheduled_work(self):
        s=self.schedule();bad=self.schedule()
        raw=self.schedules.load(bad['id']);raw['runs_started']='broken';self.schedules.save(raw)
        original=self.schedules.path(bad['id']).read_bytes()
        self.schedules.tick(now=100)
        self.assertEqual(len(self.store.list()),1)
        self.assertEqual(self.store.list()[0]['schedule_id'],s['id'])
        self.assertEqual(self.schedules.path(bad['id']).read_bytes(),original)
        self.assertEqual([r for r in self.schedules.list() if r['id']==bad['id']][0]['status'],'needs_review')

    def test_invalid_mission_sort_values_are_quarantined(self):
        good=self.store.create('Good');arm(self.root,good['id'])
        bad=self.store.create('Bad');arm(self.root,bad['id'])
        bad['next_run_at']='tomorrow';self.store.save(bad)
        controller=Supervisor(self.root)
        self.assertEqual(controller.selection()[0],[good['id']])
        self.assertEqual(controller.store.load_errors[0]['mission'],bad['id'])

    def test_bad_run_policy_does_not_block_start_or_stop_of_healthy_work(self):
        bad=self.store.create('Bad policy');good=self.store.create('Healthy')
        arm(self.root,good['id'])
        (self.store.folder(bad['id'])/'run-policy.json').write_text('[]')
        with patch('mission_supervisor.subprocess.Popen') as launch:
            launch.return_value.pid=123
            self.assertTrue(ensure_running(self.root)['started']);launch.assert_called_once()
        pause_all(self.root)
        self.assertEqual(self.store.load(good['id'])['status'],'paused')
        self.assertFalse(read_policy(self.store,good['id'])['enabled'])

    def test_no_progress_action_stops_before_fourth_effect(self):
        m=self.store.create('Stalled')
        with patch.object(self.store,'execute',return_value='done') as effect:
            m=self.store.run(m['id'],steps=5,model=lambda _:{'action':'note','text':'same'})
        self.assertEqual(effect.call_count,3);self.assertEqual(m['status'],'needs_review')
        self.assertIsNone(m['pending_action'])

    def test_searchable_memory_survives_process_reconstruction(self):
        m=self.store.create('Memory');Memory(self.store,m).remember('checkpoint','Trial 7 produced a blue crystal')
        result=Memory(Missions(self.root),self.store.load(m['id'])).recall('crystal')
        self.assertEqual(result[0]['key'],'checkpoint');self.assertEqual(result[0]['provenance']['mission'],m['id'])
        self.assertFalse(result[0]['provenance']['verified'])

    def test_memory_shared_across_schedule_runs_but_not_other_missions(self):
        s=self.schedule();a=self.store.create('First',schedule_id=s['id']);b=self.store.create('Second',schedule_id=s['id'])
        Memory(self.store,a).remember('done','Completed batch one')
        self.assertEqual(Memory(self.store,b).recall('batch')[0]['key'],'done')
        other=self.store.create('Unrelated');self.assertEqual(Memory(self.store,other).recall(),[])
        b['mode']='full'
        with self.assertRaises(PermissionError):Memory(self.store,b).recall()

    def test_memory_budget_and_fts_query_are_bounded(self):
        m=self.store.create('Memory');memory=Memory(self.store,m)
        memory.remember('key','A result')
        self.assertEqual(memory.recall('" OR * - [ ]'),[])
        with self.assertRaises(ValueError):memory.remember('key','x'*8001)
        with patch.object(memory,'MAX_ENTRIES',1):
            with self.assertRaises(RuntimeError):memory.remember('other','result')
        self.assertEqual(memory.recall()[0]['text'],'A result')


if __name__=='__main__':unittest.main()
