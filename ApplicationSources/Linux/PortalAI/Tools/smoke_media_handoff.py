"""Run the real image CLI with a running chat server and verify exact restoration."""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import atomic_json, portable_env
from service_manager import _listener_identity, _wait_qwen_ready, status


def main():
    before = _listener_identity()
    if not before["portable_qwen"]:
        raise RuntimeError("Start the owned PortalAI chat server before this lifecycle test")
    _wait_qwen_ready(300)
    command = [sys.executable, "-B", str(ROOT/"Agent/ai_tools.py"), "image",
               "A red wooden cube on a white table, studio photograph", "--profile", "sd15",
               "--width", "128", "--height", "128", "--seed", "43"]
    proc = subprocess.Popen(command, cwd=ROOT, env=portable_env(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stdout, stderr = proc.communicate(timeout=600)
    result = json.loads(stdout)
    _wait_qwen_ready(300)
    after = _listener_identity()
    states = list((ROOT/"Agent/.runtime").glob(f"qwen_handoff_{proc.pid}_*.json"))
    handoff = json.loads(max(states, key=lambda p:p.stat().st_mtime).read_text()) if states else {}
    same_command = bool(after["listeners"]) and before["listeners"][0]["command_line"] == after["listeners"][0]["command_line"]
    stopped = before["listeners"][0]["pid"] in handoff.get("killed_pids", [])
    report = {"passed": proc.returncode == 0 and result.get("success", False) and stopped and same_command,
              "llm_was_stopped": stopped, "exact_command_restored": same_command, "before": before, "after": after,
              "image_result": result, "comfy_after": status("comfyui"), "stderr": stderr[-3000:]}
    report["passed"] &= not report["comfy_after"]["comfyui"]["running"]
    atomic_json(ROOT/"Maintenance/Reports/media-handoff-smoke.json", report)
    print(json.dumps({k:report[k] for k in ("passed", "llm_was_stopped", "exact_command_restored", "comfy_after")}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
