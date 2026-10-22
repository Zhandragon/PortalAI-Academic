import json
import io
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
from mission_runner import Missions


class MissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Missions(Path(self.temp.name))

    def test_persistence_and_complete(self):
        m = self.store.create("Test")
        m = self.store.run(m["id"], model=lambda _: {"action": "complete", "text": "checked"})
        self.assertEqual(Missions(self.store.root).load(m["id"])["status"], "complete")

    def test_full_planner_receives_independent_saved_media_setting(self):
        m=self.store.create('Synthetic media planning', 'full')
        policy={'variant_preference':'uncensored','media':{'media_variant':'standard','image_profile':'flux'}}
        (self.store.root/'Agent').mkdir(exist_ok=True)
        (self.store.root/'Agent/hardware_profiles.json').write_text(json.dumps({**policy,
            'storage':{'minimum_free_gib':1,'minimum_free_fraction':0.0001,'output_reserve_gib':1}}))
        requests=[]
        def response(root, url, payload=None, **kwargs):
            if url.endswith('/health'):data={'status':'ok'}
            elif url.endswith('/props'):data={'default_generation_settings':{'n_ctx':8192}}
            elif url.endswith('/apply-template'):data={'prompt':payload['messages'][0]['content']}
            elif url.endswith('/tokenize'):data={'tokens':list(range(100))}
            elif url.endswith('/v1/chat/completions'):
                requests.append(payload)
                data={'choices':[{'message':{'content':'{"action":"note","text":"planned"}'}}]}
            else:raise AssertionError('Unexpected model endpoint: '+url)
            return data
        with patch('runtime_policy.load_effective_policy',return_value=policy), \
             patch('chat_priority.planning_json',side_effect=response):
            action=self.store.model_action(m)
        self.assertEqual(action['action'],'note')
        self.assertEqual(len(requests),1)
        payload=requests[0]
        prompt=payload['messages'][0]['content']
        self.assertIn('chat=uncensored; media=standard',prompt)
        self.assertIn('Academic policy permits standard models only.',prompt)
        self.assertNotIn('Media auto permits a supported per-request --uncensored',prompt)
        self.assertIn('Never switch on refusal or replay uncertain effects',prompt)
        self.assertIn('image_profile=flux',prompt)
        self.assertIn('Named Images stays pinned',prompt)

    def test_full_mission_child_honors_named_image_defaults(self):
        mission=self.store.create('Synthetic environment probe','full')
        (self.store.root/'Agent').mkdir(exist_ok=True)
        (self.store.root/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{
            'minimum_free_gib':1,'minimum_free_fraction':0.0001,'output_reserve_gib':1}}))
        command=subprocess.list2cmdline([sys.executable,'-B','-c',
            'import os;print(os.environ.get("PORTALAI_CHAT_IMAGE_DEFAULTS"))'])
        result=json.loads(self.store.execute(mission,{'action':'shell','command':command}))
        self.assertEqual((result['exit_code'],result['output'].strip()),(0,'1'))

    def test_interrupted_action_never_replayed(self):
        m = self.store.create("Test", "full")
        m["pending_action"] = {"action": "shell", "command": "do-something"}
        self.store.save(m)
        with patch.object(self.store, "execute") as execute:
            self.assertEqual(self.store.run(m["id"])["status"], "needs_review")
            execute.assert_not_called()

    def test_observe_cannot_execute_shell(self):
        m = self.store.create("Test")
        with self.assertRaises(PermissionError):
            self.store.execute(m, {"action": "shell", "command": "echo should-not-run"})

    def test_vm_does_not_silently_run_on_host(self):
        with self.assertRaises(RuntimeError):
            self.store.create("Test", "vm")

    def test_budget_and_wait_survive_reload(self):
        m = self.store.create("Test", max_steps=1)
        m = self.store.run(m["id"], model=lambda _: {"action": "wait", "seconds": 60})
        self.assertEqual(m["status"], "waiting")
        with patch.object(self.store, "model_action") as model:
            self.store.run(m["id"])
            model.assert_not_called()
        m["next_run_at"] = 0
        self.store.save(m)
        self.assertEqual(self.store.run(m["id"])["status"], "budget_exhausted")

    def test_stop_file_prevents_next_action(self):
        m = self.store.create("Test")
        (self.store.folder(m["id"]) / "STOP").touch()
        with patch.object(self.store, "model_action") as model:
            self.assertEqual(self.store.run(m["id"])["status"], "paused")
            model.assert_not_called()

    def test_source_read_cannot_escape_root(self):
        m = self.store.create("Test")
        with self.assertRaises(ValueError):
            self.store.execute(m, {"action": "read_file", "path": "../outside.txt"})

    def test_subtask_depth_is_bounded(self):
        m = self.store.create("Test", depth=3)
        with self.assertRaises(RuntimeError):
            self.store.execute(m, {"action": "subtask", "objective": "recurse"})

    def test_stop_arriving_during_model_call_prevents_action(self):
        m = self.store.create("Test", "full")
        def model(_):
            self.store.stop(m["id"])
            return {"action": "shell", "command": "must not execute"}
        with patch.object(self.store, "execute") as execute:
            result = self.store.run(m["id"], model=model)
        execute.assert_not_called()
        self.assertEqual(result["status"], "paused")

    def test_stop_also_stops_children_and_review_is_explicit(self):
        parent = self.store.create("Parent")
        child = self.store.create("Child", parent=parent["id"], depth=1)
        parent["children"].append(child["id"])
        self.store.save(parent)
        self.store.stop(parent["id"])
        self.assertTrue((self.store.folder(child["id"]) / "STOP").exists())
        child["pending_action"] = {"action": "note", "text": "unknown outcome"}
        child["status"] = "needs_review"
        self.store.save(child)
        with self.assertRaises(ValueError):
            self.store.resume(child["id"])
        result = self.store.resume(child["id"], "skip")
        self.assertEqual(result["steps"], 1)
        self.assertIsNone(result["pending_action"])
        self.assertFalse((self.store.folder(child["id"]) / "STOP").exists())


if __name__ == "__main__":
    unittest.main()
