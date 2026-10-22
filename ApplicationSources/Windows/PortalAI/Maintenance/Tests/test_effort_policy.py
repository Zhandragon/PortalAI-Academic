import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Agent"))
import effort_policy as ep
import runtime_policy as rp


class EffortPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="Portal effort ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.policy = rp.load_policy(ROOT)
        self.policy.update(selection="auto", backend="auto", context_tokens=32768, variant_preference="standard")
        self.policy.pop("effort", None)
        scale = patch.object(rp, "GIB", 1024)
        scale.start()
        self.addCleanup(scale.stop)
        for model in self.policy["models"]:
            path = self.root / model["path"]
            path.parent.mkdir(parents=True, exist_ok=True)
            sizes = {"qwen1.7-abliterated-q8": 1.71, "qwen27-standard-q4": 17.67, "qwen27-q4": 15.7, "qwen27-q5": 18.2, "qwen4-abliterated-q4": 2.33, "qwen4-q4": 2.33, "qwen1.7-q8": 1.71, "qwen-vl2-q4": 1.03, "qwen-vl2-abliterated-q4": 1.03, "qwen-vl4-q4": 2.33, "qwen-vl4-abliterated-q4": 2.33}
            with path.open("wb") as output:
                output.truncate(int(sizes[model["id"]] * rp.GIB))
            if model.get("projector"):
                with (self.root / model["projector"]).open("wb") as output:
                    output.truncate(int(.87 * rp.GIB))
        self.hw = {"system": "Windows", "machine": "AMD64", "cpu_count": 8,
                   "ram_total_bytes": 32*rp.GIB, "ram_available_bytes": 24*rp.GIB,
                   "gpus": []}
        self.backend = {"backend": "cuda", "device": "CUDA0", "executable": "bundled",
                        "gpu": {"name": "RTX 4090", "total_bytes": 24*rp.GIB,
                                "free_bytes": 23*rp.GIB, "shared_memory": False}}
        choose = patch.object(rp, "choose_backend", side_effect=lambda *args: copy.deepcopy(self.backend))
        choose.start()
        self.addCleanup(choose.stop)
        disk = patch.object(rp.shutil, "disk_usage", return_value=rp.shutil._ntuple_diskusage(
            1000*rp.GIB, 700*rp.GIB, 300*rp.GIB))
        disk.start()
        self.addCleanup(disk.stop)
        (self.root / "Agent").mkdir()
        rp.atomic_json(self.root / "Agent/hardware_profiles.json", self.policy)

    def plan(self, level, **kwargs):
        return ep.require_chat_plan(level, self.root, hardware=self.hw,
                                    policy=self.policy, **kwargs)

    def test_fast_uses_1_7b_and_disables_thinking(self):
        plan = self.plan("fast")
        self.assertEqual(plan["selection"], "qwen1.7-q8")
        self.assertEqual(plan["completion_options"], {
            "max_tokens": 1024, "chat_template_kwargs": {"enable_thinking": False}})
        self.assertEqual(plan["tool_round_limit"], 4)

    def test_fast_missing_1_7b_falls_back_to_4b_in_automatic_mode(self):
        for model in self.policy['models']:
            if model['id'].startswith('qwen1.7-'):(self.root/model['path']).unlink()
        self.assertEqual(self.plan("fast")["selection"], "qwen4-q4")

    def test_fast_standard_is_independent_of_abliterated_availability(self):
        model=next(m for m in self.policy['models'] if m['id']=='qwen4-abliterated-q4')
        (self.root/model['path']).unlink()
        self.assertEqual(self.plan('fast')['selection'],'qwen1.7-q8')

    def test_fast_missing_standard_does_not_select_available_abliterated(self):
        standard=next(m for m in self.policy['models'] if m['id']=='qwen4-q4')
        (self.root/standard['path']).unlink()
        self.assertEqual(self.plan('fast')['selection'],'qwen1.7-q8')

    def test_explicit_alternate_selection_survives_effort_without_silent_fallback(self):
        self.policy['selection']='qwen4-abliterated-q4'
        for level in ('fast','balanced','deep'):
            self.assertEqual(self.plan(level)['selection'],'qwen4-abliterated-q4')
        model=next(m for m in self.policy['models'] if m['id']=='qwen4-abliterated-q4')
        (self.root/model['path']).unlink()
        with self.assertRaises(RuntimeError): self.plan('fast')

    def test_fast_does_not_fall_back_to_large_model(self):
        for model in self.policy["models"]:
            if model["id"].startswith("qwen27-"): continue
            (self.root / model["path"]).unlink()
        with self.assertRaisesRegex(RuntimeError, "No installed model fits"):
            self.plan("fast")

    def test_balanced_preserves_saved_manual_standard_choice(self):
        self.policy["selection"] = "qwen1.7-q8"
        old = copy.deepcopy(self.policy)
        plan = self.plan("balanced")
        self.assertEqual(plan["selection"], "qwen1.7-q8")
        self.assertTrue(plan["thinking"])
        self.assertEqual(plan["chat_template_kwargs"], {'enable_thinking': True, 'reasoning_effort': 'low'})
        self.assertEqual(plan['max_tokens'], 2048)
        self.assertEqual(self.policy, old)

    def test_every_effort_pins_standard_and_unknown_manual_selection_fails(self):
        self.policy['selection'] = 'qwen1.7-q8'
        for level in ('fast', 'balanced', 'deep'):
            self.assertEqual(self.plan(level)['selection'], 'qwen1.7-q8')
        self.policy['selection'] = 'removed-model'
        for level in ('fast', 'balanced', 'deep'):
            with self.assertRaises(RuntimeError):self.plan(level)

    def test_deep_uses_best_admitted_quant_and_thinking(self):
        plan = self.plan("deep")
        self.assertEqual(plan["selection"], "qwen27-standard-q4")
        self.assertTrue(plan["thinking"])
        self.assertEqual(plan["max_tokens"], 8192)
        self.assertEqual(plan["tool_round_limit"], 24)
        self.assertFalse(plan["requires_recheck"])

    def test_deep_small_context_reserves_half_for_input(self):
        self.policy["context_tokens"] = 2048
        plan = self.plan("deep")
        self.assertEqual(plan["max_tokens"], 1024)
        self.assertEqual(plan["input_token_reserve"], 1024)

    def test_missing_large_models_yields_small_deep_with_bounded_tokens(self):
        for model in self.policy["models"]:
            if not model["id"].startswith("qwen27-"): continue
            (self.root / model["path"]).unlink()
        plan = self.plan("deep")
        self.assertEqual(plan["selection"], "qwen4-q4")
        self.assertEqual(plan["context_tokens"], 8192)
        self.assertEqual(plan["max_tokens"], 4096)

    def test_cpu_requires_session_unlock(self):
        self.backend.update(backend="cpu", gpu=None)
        with self.assertRaisesRegex(RuntimeError, "Allow it for this session"):
            self.plan("deep")
        self.assertEqual(self.plan("deep", session_unlocked=True)["selection"], "qwen27-standard-q4")
        self.assertEqual(self.plan("balanced")["selection"], "qwen4-q4")

    def test_shared_radeon_requires_session_unlock(self):
        self.backend.update(backend="vulkan", device="Vulkan0")
        self.backend["gpu"].update(name="Radeon", shared_memory=True)
        with self.assertRaisesRegex(RuntimeError, "Allow it for this session"):
            self.plan("deep")
        self.assertTrue(self.plan("deep", session_unlocked=True)["slow_hardware"])

    def test_small_dedicated_gpu_requires_unlock(self):
        self.backend["gpu"]["total_bytes"] = 8 * rp.GIB
        with self.assertRaisesRegex(RuntimeError, "Allow it for this session"):
            self.plan("deep")

    def test_unlock_cannot_bypass_memory_reserves(self):
        self.backend.update(backend="cpu", gpu=None)
        self.hw["ram_available_bytes"] = 3*rp.GIB
        with self.assertRaisesRegex(RuntimeError, "memory reserves"):
            self.plan("deep", session_unlocked=True)

    def test_unlock_cannot_bypass_storage_floor(self):
        self.backend.update(backend="cpu", gpu=None)
        with patch.object(rp, "storage_budget", return_value={"allowed": False}):
            with self.assertRaisesRegex(RuntimeError, "free-space floor"):
                self.plan("deep", session_unlocked=True)

    def test_backend_failure_never_bypassed(self):
        with patch.object(rp, "choose_backend", side_effect=RuntimeError("driver unavailable")):
            with self.assertRaisesRegex(RuntimeError, "driver unavailable"):
                self.plan("deep", session_unlocked=True)

    def test_capacity_preview_does_not_downgrade_resident_chat(self):
        self.hw["ram_available_bytes"] = 3*rp.GIB
        self.backend["gpu"]["free_bytes"] = 2*rp.GIB
        preview = ep.capabilities(self.root, hardware=self.hw, policy=self.policy)
        deep = preview["profiles"]["deep"]
        self.assertEqual(deep["selection"], "qwen27-standard-q4")
        self.assertTrue(deep["requires_recheck"])
        self.assertTrue(deep["preview_only"])
        with self.assertRaisesRegex(RuntimeError, "memory reserves"):
            self.plan("deep")

    def test_permission_gate_does_not_require_free_memory(self):
        self.hw["ram_available_bytes"] = 0
        self.backend["gpu"]["free_bytes"] = 0
        result = ep.check_chat_permission("deep", self.root, hardware=self.hw, policy=self.policy)
        self.assertTrue(result["can_apply"])
        self.assertTrue(result["requires_recheck"])

    def test_cpu_preview_can_show_locked_but_installed(self):
        self.backend.update(backend="cpu", gpu=None)
        profile = ep.capabilities(self.root, hardware=self.hw, policy=self.policy)["profiles"]["deep"]
        self.assertTrue(profile["available"])
        self.assertTrue(profile["locked"])
        self.assertFalse(profile["can_apply"])

    def test_invalid_profile_has_no_side_effect(self):
        with self.assertRaises(ValueError):
            self.plan("unlimited")
        with self.assertRaises(ValueError):
            ep.save_preferences(self.root, chat="unlimited")
        self.assertNotIn("effort", rp.load_policy(self.root))

    def test_defaults_read_only_and_preferences_merge_only_requested_keys(self):
        original = rp.load_policy(self.root)
        self.assertEqual(ep.load_preferences(self.root), {"chat": "balanced", "tools": "balanced"})
        self.assertEqual(rp.load_policy(self.root), original)
        ep.save_preferences(self.root, tools="deep")
        ep.save_preferences(self.root, chat="fast")
        saved = rp.load_policy(self.root)
        self.assertEqual(saved.pop("effort"), {"chat": "fast", "tools": "deep"})
        self.assertEqual(saved, original)

    def test_old_unknown_preference_values_fall_back_without_rewrite(self):
        self.policy["effort"] = {"chat": "turbo", "tools": "fast"}
        rp.atomic_json(self.root / "Agent/hardware_profiles.json", self.policy)
        self.assertEqual(ep.load_preferences(self.root), {"chat": "balanced", "tools": "fast"})
        self.assertEqual(rp.load_policy(self.root)["effort"]["chat"], "turbo")

    def test_tool_hints_are_separate_and_require_adapter_and_admission(self):
        ep.save_preferences(self.root, tools="deep", chat="fast")
        hints = ep.tool_preferences(ep.load_preferences(self.root)["tools"])
        self.assertEqual(hints["level"], "deep")
        self.assertFalse(hints["applied"])
        self.assertTrue(hints["requires_adapter_support"])
        self.assertTrue(hints["requires_hardware_admission"])
        self.assertNotIn("duration", hints)

    def test_command_matches_existing_runtime_command(self):
        plan = self.plan("deep")
        cfg = {**self.policy, **plan["policy_overrides"]}
        baseline = rp.build_plan(self.root, self.hw, cfg)
        self.assertEqual(plan["command"], baseline["command"])

    def test_fast_tool_defaults_only_change_supported_budget(self):
        args = {"cmd": "video-sfx", "steps": 25, "duration": 6.5, "seed": 42,
                "cfg_strength": 4.5, "variant": "auto"}
        result = ep.apply_tool_effort("video-sfx", args, "fast", explicit_options=())
        self.assertEqual(result["steps"], 12)
        self.assertEqual(args["steps"], 25)
        self.assertEqual({k: v for k, v in result.items() if k != "steps"},
                         {k: v for k, v in args.items() if k != "steps"})

    def test_dict_values_explicit_by_default(self):
        args = {"steps": 19, "duration": 6}
        self.assertEqual(ep.apply_tool_effort("sfx", args, "fast"), args)

    def test_balanced_retains_existing_tool_defaults(self):
        args = {"steps": 28, "beam_size": 6}
        for cmd in ("video-small", "sfx", "transcribe"):
            self.assertEqual(ep.apply_tool_effort(cmd, args, "balanced", explicit_options=()), args)

    def test_explicit_cli_step_equals_and_abbreviations_are_preserved(self):
        for argv in (["sfx", "rain", "--steps", "19"], ["sfx", "rain", "--steps=19"],
                     ["sfx", "rain", "--ste", "19"]):
            args = {"cmd": "sfx", "steps": 19}
            result = ep.apply_tool_environment(args, argv, environ={"PORTALAI_TOOL_EFFORT": "fast"})
            self.assertEqual(result, args)

    def test_native_cli_keeps_defaults_without_gui_request(self):
        args = {"cmd": "sfx", "steps": 25}
        self.assertEqual(ep.apply_tool_environment(args, ["sfx", "rain"], environ={}), args)

    def test_deep_tool_requires_slow_session_permission_only_when_adding_default(self):
        self.backend.update(backend="cpu", gpu=None)
        with self.assertRaisesRegex(RuntimeError, "Allow it for this session"):
            ep.apply_tool_effort("transcribe", {"beam_size": 5}, "deep", explicit_options=(),
                                 root=self.root, hardware=self.hw, policy=self.policy)
        result = ep.apply_tool_effort("transcribe", {"beam_size": 5}, "deep", explicit_options=(),
                                      root=self.root, hardware=self.hw, policy=self.policy,
                                      session_unlocked=True)
        self.assertEqual(result["beam_size"], 8)
        # An explicitly requested numerical setting is independent of this default preference.
        self.assertEqual(ep.apply_tool_effort("transcribe", {"beam_size": 3}, "deep"), {"beam_size": 3})

    def test_science_and_stop_never_have_input_changed_or_blocked_by_effort_env(self):
        for command in ("science", "cancel", "status", "image", "lip-sync"):
            args = {"cmd": command, "json": '{"tolerance":1e-9,"iterations":300}'}
            self.assertEqual(ep.apply_tool_environment(args, [], environ={
                "PORTALAI_TOOL_EFFORT": "invalid"}), args)

    def test_tool_env_passes_only_explicit_session_unlock(self):
        for value, expected in (("1", True), ("0", False), ("true", False)):
            with patch.object(ep, "check_chat_permission") as permission:
                result = ep.apply_tool_environment({"cmd": "sfx", "steps": 25}, ["sfx", "rain"],
                    root=self.root, environ={"PORTALAI_TOOL_EFFORT": "deep",
                                             "PORTALAI_TOOL_EFFORT_UNLOCKED": value})
                self.assertEqual(result["steps"], 40)
                self.assertIs(permission.call_args.kwargs["session_unlocked"], expected)


if __name__ == "__main__":
    unittest.main()
