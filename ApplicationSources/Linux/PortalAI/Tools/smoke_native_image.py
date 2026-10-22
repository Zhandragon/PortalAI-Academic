"""Bounded real CPU/Vulkan SD1.5 generation using the existing portable GPU lease."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from ai_tools import _exclusive_gpu
from media_policy import image_plan
from sdcpp_bridge import generate
from smoke_profile import SmokeProfile

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=["sdcpp-cpu", "sdcpp-vulkan"], required=True)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--steps", type=int, default=2)
    args = parser.parse_args(); start = time.monotonic()
    profile = SmokeProfile(ROOT)
    with _exclusive_gpu(None, "native-image-smoke"):
        plan = image_plan(engine=args.engine, width=args.size, height=args.size)
        result = generate(plan, "A blue ceramic teapot on a wooden table, studio photograph", seed=52, steps=args.steps)
    report = {"passed": True, "elapsed_seconds": round(time.monotonic()-start, 2), "plan": plan, "result": result,
              "scope": "Physical local host only; Vulkan on NVIDIA is not physical Radeon validation"}
    profile.save(args.engine+"-smoke.json", report)
    print(json.dumps(report, indent=2))
