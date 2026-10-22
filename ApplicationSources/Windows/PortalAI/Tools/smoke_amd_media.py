"""Validate isolated ROCm ComfyUI on CPU here; this is NOT a Radeon GPU test."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from ai_tools import _exclusive_gpu
from comfy_bridge import ComfyBridge
from runtime_policy import atomic_json, portable_env
from service_manager import _listener_identity
from sdcpp_bridge import validate_png


def main():
    report = {"passed": False, "scope": "ROCm runtime with CPU image inference; not physical Radeon validation"}
    before = _listener_identity()
    output = ROOT/"Outputs/Images"/("amd_cpu_smoke_"+uuid.uuid4().hex[:8])
    output.mkdir(parents=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]
    started = time.monotonic()
    try:
        with _exclusive_gpu(None, "amd-comfy-cpu-validation"):
            command = [sys.executable, "-B", str(ROOT/"Agent/comfy_amd_entry.py"), "--portalai-cpu-validation",
                       "--cpu", "--disable-xformers", "--disable-triton-backend", "--disable-comfy-compiler",
                       "--disable-auto-launch", "--listen", "127.0.0.1", "--port", str(port),
                       "--cache-none", "--output-directory", str(output)]
            with (ROOT/"Maintenance/Reports/amd-comfy-smoke.log").open("wb") as log:
                proc = subprocess.Popen(command, cwd=ROOT, env=portable_env(ROOT), stdout=log, stderr=log,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    bridge = ComfyBridge(); bridge.base = f"http://127.0.0.1:{port}"
                    bridge.ccfg = {**bridge.ccfg, "output_dir": output.relative_to(ROOT).as_posix(), "timeout_seconds": 300}
                    deadline = time.monotonic()+120
                    while True:
                        if proc.poll() is not None: raise RuntimeError("AMD Comfy diagnostic exited; inspect amd-comfy-smoke.log")
                        try: stats = bridge.health(); break
                        except (OSError, ValueError, RuntimeError):
                            if time.monotonic()>deadline: raise TimeoutError("AMD Comfy diagnostic startup")
                            time.sleep(.5)
                    with urllib.request.urlopen(bridge.base+"/object_info", timeout=30) as response:
                        nodes = json.load(response)
                    missing = {}
                    for path in (ROOT/"Workflows/API").glob("*.json"):
                        workflow = json.loads(path.read_text(encoding="utf-8-sig"))
                        if isinstance(workflow, dict):
                            absent = sorted({row["class_type"] for row in workflow.values()
                                             if isinstance(row, dict) and "class_type" in row and row["class_type"] not in nodes})
                            if absent: missing[path.name] = absent
                    workflow = bridge.workflow_file("Workflows/API/SD15_T2I_Portable.json")
                    bridge.configure_t2i(workflow, "A blue teapot on a table", "", 128, 128, 52)
                    workflow["5"]["inputs"]["steps"] = 2
                    result = bridge.run(workflow, output)
                    for path in result["files"]: validate_png(Path(path), 128, 128)
                    report.update(stats=stats, missing_workflow_nodes=missing, result=result,
                                  package_layer_inference_passed=True)
                finally:
                    if proc.poll() is None: proc.terminate()
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=10)
        after = _listener_identity()
        exact = before["portable_qwen"] and any(a["command_line"] == b["command_line"] and a["pid"] != b["pid"]
            for a in before["listeners"] for b in after["listeners"])
        report.update(exact_chat_restored=exact, passed=bool(exact), elapsed_seconds=time.monotonic()-started)
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        atomic_json(ROOT/"Maintenance/Reports/amd-comfy-smoke.json", report)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
