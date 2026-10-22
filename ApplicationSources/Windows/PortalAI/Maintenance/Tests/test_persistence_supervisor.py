import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"Agent"))
from mission_runner import Missions, MissionContextError, compact_context, process_lock
from mission_supervisor import Supervisor, arm, disarm, pause_all, read_policy, ensure_running


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Portal persistent test ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"Agent").mkdir()
        (self.root/"Agent/hardware_profiles.json").write_text(json.dumps({"storage": {"minimum_free_gib": 0, "minimum_free_fraction": 0, "output_reserve_gib": 0}}))
        self.store = Missions(self.root)

    def test_history_is_bounded_objective_preserved(self):
        history = [{"action": {"action": "note", "text": "界"*20000}, "result": "x"*12000} for _ in range(100)]
        context = compact_context("Exact original objective", history, [], "facts"*1000, 3000)
        self.assertLessEqual(len(json.dumps(context, ensure_ascii=False).encode()), 3000)
        self.assertEqual(context["objective"], "Exact original objective")
        self.assertTrue(context["history_compacted"])
        self.assertEqual(len(history), 100)

    def test_objective_is_not_silently_truncated(self):
        with self.assertRaises(MissionContextError): compact_context("x"*5000, [], [], "", 1000)
        with self.assertRaises(ValueError): self.store.create("x"*16001)

    def test_planning_failure_retries_without_executing(self):
        m = self.store.create("retry")
        with patch.object(self.store, "execute") as execute:
            result = self.store.run(m["id"], model=lambda _: (_ for _ in ()).throw(ConnectionError("offline")))
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["steps"], 0)
        self.assertIsNone(result["pending_action"])
        self.assertGreater(result["next_run_at"], time.time())
        execute.assert_not_called()

    def test_repeated_planning_failure_eventually_needs_review(self):
        m = self.store.create("retry")
        for _ in range(6):
            m["next_run_at"] = 0; self.store.save(m)
            m = self.store.run(m["id"], model=lambda _: (_ for _ in ()).throw(ConnectionError("offline")))
        self.assertEqual(m["status"], "needs_review")
        self.assertEqual(m["steps"], 0)
        self.assertEqual(m["planning_failures"], 6)

    def test_context_failure_does_not_retry_forever(self):
        m = self.store.create("too long")
        m = self.store.run(m["id"], model=lambda _: (_ for _ in ()).throw(MissionContextError("too long")))
        self.assertEqual(m["status"], "needs_review")

    def test_effect_failure_is_never_auto_retried(self):
        m = self.store.create("effect")
        with patch.object(self.store, "execute", side_effect=RuntimeError("unknown")):
            m = self.store.run(m["id"], model=lambda _: {"action": "note", "text": "effect"})
        self.assertEqual(m["status"], "needs_review")
        self.assertIsNotNone(m["pending_action"])

    def test_child_created_during_parent_stop_cannot_execute(self):
        parent = self.store.create("parent")
        self.store.stop(parent["id"])
        child = self.store.create("late child", parent=parent["id"], depth=1)
        with patch.object(self.store, "execute") as execute:
            result = self.store.run(child["id"], model=lambda _: {"action": "note", "text": "no"})
        self.assertEqual(result["status"], "paused")
        execute.assert_not_called()

    def test_stop_cancels_a_future_wait_immediately(self):
        m = self.store.create("wait")
        m = self.store.run(m["id"], model=lambda _: {"action": "wait", "seconds": 86400})
        self.store.stop(m["id"])
        self.assertEqual(self.store.run(m["id"])["status"], "paused")

    def test_stop_after_completion_checkpoint_preserves_completion(self):
        m = self.store.create("finish")
        arm(self.root, m["id"])
        self.store.run(m["id"], model=lambda _: {"action": "complete", "text": "done"})
        disarm(self.root, m["id"])
        Supervisor(self.root).reconcile(m["id"])
        self.assertEqual(self.store.load(m["id"])["status"], "complete")

    def test_disarm_checkpoints_waiting_children(self):
        p = self.store.create("parent")
        c = self.store.create("child", parent=p["id"], depth=1)
        p["children"] = [c["id"]]; self.store.save(p)
        self.store.run(c["id"], model=lambda _: {"action": "wait", "seconds": 86400})
        disarm(self.root, p["id"])
        self.assertEqual(self.store.load(c["id"])["status"], "paused")

    def test_parent_surfaces_child_failure(self):
        p = self.store.create("parent"); c = self.store.create("child", parent=p["id"], depth=1)
        p["children"] = [c["id"]]; self.store.save(p)
        c["status"] = "needs_review"; self.store.save(c)
        self.assertEqual(self.store.run(p["id"])["status"], "needs_review")

    def test_only_armed_root_and_its_children_are_selected(self):
        p = self.store.create("armed"); c = self.store.create("child", parent=p["id"], depth=1)
        p["children"] = [c["id"]]; self.store.save(p); self.store.create("unarmed")
        arm(self.root, p["id"])
        roots, candidates = Supervisor(self.root).selection()
        self.assertEqual(roots, [p["id"]])
        self.assertEqual({m["id"] for _,m in candidates}, {p["id"], c["id"]})

    def test_arm_cannot_bypass_review_or_change_execution_mode(self):
        m = self.store.create("armed"); m["pending_action"] = {"action": "note"}; self.store.save(m)
        with self.assertRaises(ValueError): arm(self.root, m["id"])
        m["pending_action"] = None; self.store.save(m); arm(self.root, m["id"])
        m["mode"] = "full"; self.store.save(m)
        self.assertEqual(Supervisor(self.root).selection()[0], [])
        self.assertFalse(read_policy(self.store, m["id"])["enabled"])

    def test_pause_all_prevents_automatic_next_launch_resume(self):
        m = self.store.create("armed"); arm(self.root, m["id"])
        pause_all(self.root)
        self.assertEqual(self.store.load(m["id"])["status"], "paused")
        with patch("mission_supervisor.subprocess.Popen") as start:
            self.assertFalse(ensure_running(self.root)["started"])
            start.assert_not_called()

    def test_abandoned_pending_effect_is_quarantined(self):
        m = self.store.create("armed"); arm(self.root, m["id"])
        m["pending_action"] = {"action": "note", "text": "uncertain"}; self.store.save(m)
        Supervisor(self.root, model_ready=lambda: True).tick()
        self.assertEqual(self.store.load(m["id"])["status"], "needs_review")

    def test_execution_lock_prevents_competing_mission_actions(self):
        m = self.store.create("competing")
        with process_lock(self.store.base/"execution.lock"):
            with self.assertRaises(OSError): self.store.run(m["id"], model=lambda _: {"action": "complete"})


if __name__ == "__main__": unittest.main()
