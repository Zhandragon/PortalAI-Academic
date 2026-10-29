"""Failure injection at the execution/result checkpoint boundary."""
import sys
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
import test_persistence_supervisor as fixtures
from mission_runner import Missions
from mission_supervisor import Supervisor, arm, disarm


class CrashRecoveryTests(unittest.TestCase):
    setUp = fixtures.PersistenceTests.setUp

    def test_failed_result_publication_retains_pending_action_for_review(self):
        mission = self.store.create('Record one local effect')
        action = {'action': 'note', 'text': 'effect happened'}
        original_save = self.store.save
        failed = False

        def save(value):
            nonlocal failed
            if value['history'] and not value['pending_action'] and not failed:
                failed = True
                raise OSError('Injected result replacement failure')
            return original_save(value)

        with patch.object(self.store, 'save', side_effect=save):
            result = self.store.run(mission['id'], steps=1, model=lambda _: action)
        self.assertTrue(failed)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['pending_action'], action)
        self.assertEqual(result['history'], [])
        self.assertEqual(result['steps'], 0)
        self.assertEqual((self.store.folder(mission['id'])/'notes.txt').read_text().count('effect happened'), 1)
        with self.assertRaisesRegex(ValueError, 'reviewed-action'):
            self.store.resume(mission['id'])
        with patch.object(Missions, 'execute') as execute:
            Missions(self.root).run(mission['id'], model=lambda _: action)
            execute.assert_not_called()

    def test_post_commit_index_failure_does_not_roll_back_saved_result(self):
        mission = self.store.create('Complete once')
        original_save = self.store.save
        failed = False

        def save(value):
            nonlocal failed
            original_save(value)
            if value['history'] and not failed:
                failed = True
                raise OSError('Injected failure after checkpoint commit')

        with patch.object(self.store, 'save', side_effect=save):
            result = self.store.run(mission['id'], steps=1, model=lambda _: {'action':'complete','text':'done'})
        self.assertEqual(result['status'], 'complete')
        self.assertIsNone(result['pending_action'])
        self.assertEqual(result['steps'], 1)
        self.assertEqual(len(result['history']), 1)

    def test_unreadable_result_checkpoint_is_not_overwritten_from_memory(self):
        mission = self.store.create('Preserve damaged evidence')
        original_save = self.store.save
        path = self.store.checkpoint_path(mission['id'])

        def save(value):
            if value['history'] and not value['pending_action']:
                path.write_text('{damaged evidence')
                raise OSError('Injected storage loss')
            return original_save(value)

        with patch.object(self.store, 'save', side_effect=save):
            with self.assertRaises(ValueError):
                self.store.run(mission['id'], steps=1, model=lambda _: {'action':'note','text':'one effect'})
        self.assertEqual(path.read_text(), '{damaged evidence')

    def test_worker_crashes_are_bounded_across_supervisor_recreation(self):
        mission = self.store.create('Fail before execution')
        for count in range(1, 5):
            result = Supervisor(self.root).reconcile(mission['id'], 'Injected worker exit')
            self.assertEqual(result['worker_failures'], count)
            self.assertEqual(result['status'], 'waiting' if count < 4 else 'needs_review')
        with patch.object(self.store, 'execute') as execute:
            self.store.run(mission['id'])
            execute.assert_not_called()


@unittest.skipUnless(os.name == 'nt', 'Real Job Object tests require Windows; native Linux/macOS acceptance is separate')
class ProcessRecoveryTests(unittest.TestCase):
    setUp = fixtures.PersistenceTests.setUp

    def supervisor(self):
        controller = Supervisor(self.root, worker_command=[sys.executable, '-B',
            str(ROOT/'Maintenance/Tests/mission_fault_worker.py'), '--root', str(self.root)],
            model_ready=lambda: True)
        self.addCleanup(controller.finish_worker, cancelled=True)
        return controller

    def pump_until(self, controller, predicate, seconds=12):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            controller.tick()
            if predicate():
                return
            time.sleep(.05)
        self.fail('Supervisor did not reach the expected state before the test deadline')

    def test_elapsed_timeout_kills_worker_and_autonomously_completes_in_new_process(self):
        mission = self.store.create('stall-once')
        mid = mission['id']; folder = self.store.folder(mid)
        arm(self.root, mid); controller = self.supervisor()
        self.pump_until(controller, lambda: (folder/'first-worker-pid.txt').exists())
        first = controller.worker
        # Accelerate only the timeout/backoff clocks. Recovery still uses tick(),
        # OS job termination, persisted state, Popen and the production runner.
        controller.started -= 481
        with patch('mission_supervisor.WORKER_RETRY_BASE_SECONDS', .01):
            self.pump_until(controller, lambda: self.store.load(mid)['status'] == 'complete')
        self.assertIsNotNone(first.poll())
        self.assertNotEqual((folder/'first-worker-pid.txt').read_text(),
                            (folder/'recovered-worker-pid.txt').read_text())
        self.assertEqual(self.store.load(mid)['worker_failures'], 1)

    def test_crash_after_side_effect_survives_restart_without_duplicate(self):
        mission = self.store.create('crash-after-effect'); mid = mission['id']
        arm(self.root, mid); controller = self.supervisor()
        self.pump_until(controller, lambda: self.store.load(mid)['status'] == 'needs_review')
        self.assertIsNotNone(self.store.load(mid)['pending_action'])
        controller.finish_worker()
        restarted = self.supervisor()
        for _ in range(3):
            restarted.tick()
        self.assertEqual((self.store.folder(mid)/'effect-count.txt').read_text(), '1')
        self.assertIsNone(restarted.worker)

    def test_stop_of_stalled_worker_never_relaunches(self):
        mission = self.store.create('stall-once'); mid = mission['id']
        arm(self.root, mid); controller = self.supervisor()
        folder = self.store.folder(mid)
        self.pump_until(controller, lambda: (folder/'first-worker-pid.txt').exists())
        first = controller.worker
        disarm(self.root, mid)
        controller.tick()
        self.assertIsNotNone(first.poll())
        self.assertEqual(self.store.load(mid)['status'], 'paused')
        self.assertIsNone(controller.worker)
        self.assertFalse((folder/'recovered-worker-pid.txt').exists())


if __name__ == '__main__':
    unittest.main()
