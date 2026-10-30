"""Regressions for launch/setup failures before any mission action executes."""
import sys
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
import test_mission_schedule as fixtures
from mission_schedule import Schedules
from mission_supervisor import Supervisor, arm, disarm
from runtime_policy import atomic_json


class SetupRecoveryTests(unittest.TestCase):
    setUp = fixtures.ScheduleTests.setUp

    def failing_policy(self, path, value):
        if path.name == 'run-policy.json':
            self.policy_attempts += 1
            raise OSError('Injected policy publication failure')
        return atomic_json(path, value)

    def schedule(self):
        s = self.schedules.create('Synthetic setup recovery', first_run_at=100)
        self.schedules.enable(s['id'])
        self.policy_attempts = 0
        return s['id']

    def test_existing_checkpoint_honors_setup_backoff_across_restart(self):
        sid = self.schedule()
        with patch('mission_schedule.atomic_json', side_effect=self.failing_policy):
            self.schedules.tick(now=100)
            saved = self.schedules.load(sid)
            self.assertEqual(saved['setup_failures'], 1)
            self.assertEqual(saved['next_run_at'], 130)
            self.assertTrue(self.store.checkpoint_path(saved['active_run']).exists())
            Schedules(self.root).tick(now=101)
            self.assertEqual(self.policy_attempts, 1)
            self.assertEqual(self.schedules.load(sid)['next_run_at'], 130)

    def test_policy_failures_increase_delay_then_reuse_same_occurrence(self):
        sid = self.schedule()
        with patch('mission_schedule.atomic_json', side_effect=self.failing_policy):
            for count, now, next_at in ((1, 100, 130), (2, 130, 190), (3, 190, 310)):
                Schedules(self.root).tick(now=now)
                saved = self.schedules.load(sid)
                self.assertEqual(saved['setup_failures'], count)
                self.assertEqual(saved['next_run_at'], next_at)
        mid = saved['active_run']
        Schedules(self.root).tick(now=310)
        saved = self.schedules.load(sid)
        self.assertEqual(saved['active_run'], mid)
        self.assertEqual(saved['runs_started'], 1)
        self.assertEqual(saved['setup_failures'], 0)
        self.assertNotIn('error', saved)
        self.assertEqual(len(self.store.list()), 1)

    def test_backoff_still_observes_stop_pending_effect_and_completion(self):
        for state in ('stop', 'pending', 'complete'):
            with self.subTest(state=state):
                sid = self.schedule()
                with patch('mission_schedule.atomic_json', side_effect=self.failing_policy):
                    self.schedules.tick(now=100)
                m = self.store.load(self.schedules.load(sid)['active_run'])
                if state == 'stop':
                    disarm(self.root, m['id'])
                elif state == 'pending':
                    m['pending_action'] = {'action':'shell','command':'uncertain effect'}
                    self.store.save(m)
                else:
                    self.store.run(m['id'], model=lambda _: {'action':'complete'})
                self.schedules.tick(now=101)
                saved = self.schedules.load(sid)
                if state == 'complete':
                    self.assertIsNone(saved['active_run'])
                    self.assertEqual(saved['runs_completed'], 1)
                else:
                    self.assertEqual(saved['status'], 'needs_review')
                    self.assertFalse(self.schedules.enabled(saved))
                    if state == 'pending':
                        self.assertEqual(self.store.load(m['id'])['pending_action'], m['pending_action'])

    def test_launch_failure_cleans_up_and_retries_with_persisted_limit(self):
        mission = self.store.create('Synthetic launch failure')
        mid = mission['id']
        arm(self.root, mid)
        controller = Supervisor(self.root, worker_command=['unused'], model_ready=lambda: True)
        self.addCleanup(controller.finish_worker, cancelled=True)
        with patch('account_connections.start_account_process', side_effect=OSError('Injected process creation failure')) as launch:
            for count in range(1, 5):
                controller.tick()
                self.assertIsNone(controller.log)
                self.assertIsNone(controller.worker)
                self.assertIsNone(controller.mid)
                saved = self.store.load(mid)
                self.assertEqual(saved['worker_failures'], count)
                self.assertEqual(saved['status'], 'waiting' if count < 4 else 'needs_review')
                self.assertIsNone(saved['pending_action'])
                self.assertEqual(saved['steps'], 0)
                controller.tick()
                self.assertEqual(launch.call_count, count)
                saved['next_run_at'] = 0
                self.store.save(saved)
                controller = Supervisor(self.root, worker_command=['unused'], model_ready=lambda: True)
                self.addCleanup(controller.finish_worker, cancelled=True)
            controller.tick()
            self.assertEqual(launch.call_count, 4)

    def test_keyboard_interrupt_closes_log_and_does_not_retry(self):
        m = self.store.create('Interrupt launch')
        arm(self.root, m['id'])
        controller = Supervisor(self.root, worker_command=['unused'], model_ready=lambda: True)
        self.addCleanup(controller.finish_worker, cancelled=True)
        with patch('account_connections.start_account_process', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):controller.tick()
        self.assertIsNone(controller.log)
        self.assertIsNone(controller.mid)
        self.assertNotIn('worker_failures', self.store.load(m['id']))

    def test_failure_checkpoint_write_error_is_not_mistaken_for_lock_contention(self):
        m = self.store.create('Do not retry without a durable failure record')
        controller = Supervisor(self.root, worker_command=['unused'], model_ready=lambda: True)
        with patch.object(controller.store, 'save', side_effect=OSError('Failure checkpoint unavailable')):
            with self.assertRaisesRegex(OSError, 'Failure checkpoint unavailable'):
                controller.reconcile(m['id'], 'Worker launch failed')
        self.assertNotIn('worker_failures', self.store.load(m['id']))

    @unittest.skipUnless(os.name == 'nt', 'Native Windows worker acceptance')
    def test_failed_spawn_then_real_worker_resumes_without_user_action(self):
        import account_connections
        m = self.store.create('stall-once'); mid = m['id']
        # Select the completing branch of the fixed synthetic planner.
        (self.store.folder(mid)/'first-worker-pid.txt').write_text('synthetic earlier attempt')
        arm(self.root, mid)
        controller = Supervisor(self.root, worker_command=[sys.executable, '-B',
            str(ROOT/'Maintenance/Tests/mission_fault_worker.py'), '--root', str(self.root)], model_ready=lambda: True)
        self.addCleanup(controller.finish_worker, cancelled=True)
        real_launch = account_connections.start_account_process
        attempts = 0
        def launch(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:raise OSError('Transient spawn failure')
            return real_launch(*args, **kwargs)
        with patch('account_connections.start_account_process', side_effect=launch), patch('mission_supervisor.WORKER_RETRY_BASE_SECONDS', .01):
            deadline = time.monotonic()+12
            while time.monotonic()<deadline:
                controller.tick()
                if self.store.load(mid)['status']=='complete':break
                time.sleep(.05)
            else:self.fail('Real worker did not resume after launch failure')
        self.assertEqual(attempts, 2)
        self.assertEqual(self.store.load(mid)['steps'], 1)
        self.assertEqual(self.store.load(mid)['worker_failures'], 1)

    @unittest.skipUnless(os.name == 'nt', 'Native Windows worker acceptance')
    def test_containment_failure_kills_gated_worker_without_executing(self):
        import account_connections
        m = self.store.create('Do not execute');mid = m['id']
        arm(self.root, mid)
        controller = Supervisor(self.root, worker_command=[sys.executable, '-B',
            str(ROOT/'Maintenance/Tests/mission_fault_worker.py'), '--root', str(self.root)], model_ready=lambda: True)
        self.addCleanup(controller.finish_worker, cancelled=True)
        processes = []
        real_launch = account_connections.start_account_process
        def launch(*args, **kwargs):
            process = real_launch(*args, **kwargs)
            processes.append(process)
            return process
        with patch('account_connections.start_account_process', side_effect=launch), patch('mission_supervisor.WorkerJob', side_effect=OSError('Containment unavailable')):
            controller.tick()
        self.assertEqual(len(processes), 1)
        self.assertIsNotNone(processes[0].poll())
        self.assertIsNone(controller.log)
        self.assertFalse((self.store.folder(mid)/'notes.txt').exists())
        self.assertEqual(self.store.load(mid)['worker_failures'], 1)


if __name__ == '__main__':
    unittest.main()
