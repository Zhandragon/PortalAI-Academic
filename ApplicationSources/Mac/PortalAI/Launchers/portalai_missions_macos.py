"""Headless macOS mission and schedule entry with owned process-group lifetime."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("mission", "schedule", "supervisor", "preflight"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if any(value == "--root" or value.startswith("--root=") for value in args.arguments):
        parser.error("This launcher uses its own portable root; --root overrides are not accepted")
    command = args.arguments[0] if args.arguments else ""
    if args.component == "mission" and command in ("run", "worker"):
        parser.error("Arm the top-level mission through supervisor arm; direct workers are not exposed")
    if sys.platform != "darwin":
        raise RuntimeError("This launcher requires macOS")
    from runtime_policy import portable_env
    os.environ.update(portable_env(ROOT))
    from macos_job import preflight
    if args.component == "preflight":
        result = {"ready": True, **preflight(), "physical_macos_tested": False,
                  "metal_backend": (ROOT / "LLM/backends/macos-metal/bin/llama-server").is_file(),
                  "optional_media_and_vm": "not included in the first macOS package"}
        print(json.dumps(result, indent=2))
        return
    needs_worker = ((args.component == "supervisor" and command in ("arm", "run")) or
                    (args.component == "schedule" and command == "enable"))
    if needs_worker:
        preflight()
    script = {"mission": "mission_runner.py", "schedule": "mission_schedule.py",
              "supervisor": "mission_supervisor.py"}[args.component]
    sys.argv = [script, *args.arguments]
    os.chdir(ROOT)
    runpy.run_path(str(ROOT / "Agent" / script), run_name="__main__")


if __name__ == "__main__":
    main()
