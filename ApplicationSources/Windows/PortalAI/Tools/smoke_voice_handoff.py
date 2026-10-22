"""Validate automatic voice scaling and exact restoration of an owned chat server."""
import json
from pathlib import Path
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import atomic_json, portable_env, detect_hardware
from service_manager import _listener_identity, _wait_qwen_ready


def main():
    before = _listener_identity()
    if not before["portable_qwen"]: raise RuntimeError("Start the owned PortalAI chat server first")
    _wait_qwen_ready(300)
    hardware = detect_hardware()
    command = [sys.executable, "-B", str(ROOT/"Agent/ai_tools.py"), "voice-say",
               "Portal AI adapts to this computer, releases memory for each task, and restores the conversation.", "--engine", "auto"]
    proc = subprocess.Popen(command, cwd=ROOT, env=portable_env(ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    stdout, stderr = proc.communicate(timeout=600)
    result = json.loads(stdout)
    _wait_qwen_ready(300)
    after = _listener_identity()
    states = list((ROOT/"Agent/.runtime").glob(f"qwen_handoff_{proc.pid}_*.json"))
    state = json.loads(max(states, key=lambda p:p.stat().st_mtime).read_text()) if states else {}
    restored = bool(after["listeners"]) and before["listeners"][0]["command_line"] == after["listeners"][0]["command_line"]
    stopped = before["listeners"][0]["pid"] in state.get("killed_pids", [])
    audio = {}
    if result.get("success"):
        with wave.open(result["files"][0], "rb") as wav:
            audio = {"sample_rate": wav.getframerate(), "duration_seconds": wav.getnframes()/wav.getframerate()}
    report = {"passed": proc.returncode == 0 and result.get("success", False) and stopped and restored and audio.get("duration_seconds", 0)>0,
              "llm_was_stopped": stopped, "exact_command_restored": restored, "before": before, "after": after,
              "hardware_before": hardware, "voice_result": result, "audio": audio, "stderr": stderr[-3000:]}
    atomic_json(ROOT/"Maintenance/Reports/voice-auto-handoff.json", report)
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
