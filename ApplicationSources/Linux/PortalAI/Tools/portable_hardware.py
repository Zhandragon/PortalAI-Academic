"""Inspect or select a portable model without loading model weights."""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import atomic_json, build_plan, detect_hardware, load_policy, storage_budget, tool_plan


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--select", help="auto or a model ID in Agent/hardware_profiles.json; takes effect at next start")
    parser.add_argument("--backend", choices=["auto", "cpu", "cuda", "vulkan"])
    parser.add_argument("--inventory", action="store_true")
    args = parser.parse_args()
    policy = load_policy(ROOT)
    if args.select:
        if args.select not in ["auto"] + [m["id"] for m in policy["models"]]:
            parser.error("Unknown model ID")
        policy["selection"] = args.select
    if args.backend:
        policy["backend"] = args.backend
    if args.select or args.backend:
        atomic_json(ROOT / "Agent/hardware_profiles.json", policy)
    hw = detect_hardware()
    result = {"hardware": hw, "storage": storage_budget(ROOT), "policy": policy,
              "tools": {n: tool_plan(n, hw) for n in ["comfyui", "acestep", "science"]}}
    if not args.inventory:
        try:
            result["plan"] = build_plan(ROOT, hw, policy)
        except Exception as exc:
            result["error"] = str(exc)
    print(json.dumps(result, indent=2))
    return 1 if "error" in result else 0


if __name__ == "__main__":
    raise SystemExit(main())
