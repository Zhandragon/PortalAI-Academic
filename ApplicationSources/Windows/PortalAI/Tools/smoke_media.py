"""Real CPU image and CPU/CUDA speech smoke tests using only bundled runtimes."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import atomic_json, portable_env
from comfy_bridge import ComfyBridge
from stt_bridge import SttBridge
from ai_tools import _exclusive_gpu
from service_manager import status, _qwen_health_ready


def cpu_image():
    port = 18188
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("Media test port is occupied; refusing to interfere")
    base = ROOT/"Generative/ComfyUI_windows_portable"
    command = [str(base/"python_embeded/python.exe"), "-B", "-s", str(base/"ComfyUI/main.py"),
               "--cpu", "--port", str(port), "--listen", "127.0.0.1", "--disable-auto-launch", "--windows-standalone-build"]
    logpath = ROOT/"Maintenance/Reports/media-cpu-comfy.log"
    with logpath.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(command, cwd=base, env=portable_env(ROOT), stdout=log, stderr=log,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            bridge = ComfyBridge()
            bridge.base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic()+150
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"CPU Comfy exited {proc.returncode}; see {logpath}")
                try:
                    health = bridge.health()
                    break
                except Exception:
                    if time.monotonic() > deadline: raise TimeoutError("CPU Comfy readiness timeout")
                    time.sleep(.5)
            assert health["devices"][0]["type"] == "cpu", health["devices"]
            wf = bridge.workflow_file("Workflows/API/SD15_T2I_Portable.json")
            bridge.configure_t2i(wf, "A red cube on a white table", "", 128, 128, 42)
            # Functional check, not an image-quality benchmark.
            wf["5"]["inputs"]["steps"] = 2
            started = time.monotonic()
            result = bridge.run(wf, ROOT/"Maintenance/Reports/media-samples")
            for filename in result["files"]:
                assert Path(filename).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
            return {"passed": True, "devices": health["devices"], "seconds": round(time.monotonic()-started, 2), **result}
        finally:
            if proc.poll() is None:
                proc.terminate()
                try: proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


def main():
    folder = ROOT/"Maintenance/Reports/media-samples"
    folder.mkdir(parents=True, exist_ok=True)
    report = {"qwen_before": status("qwen"), "checks": []}
    def save(name, result):
        report["checks"].append({"name": name, **result})
        atomic_json(ROOT/"Maintenance/Reports/media-smoke.json", report)
        print(json.dumps({"name": name, **result}), flush=True)
    try:
        with _exclusive_gpu(None, "portable-media-smoke"):
            report["qwen_during_handoff"] = status("qwen")
            save("forced CPU image inference", cpu_image())
            source = folder/"silence.wav"
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(16000)
                audio.writeframes(b"\0\0"*16000*2)
            for device in ("cpu", "auto"):
                r = SttBridge().transcribe(source, model="auto", device=device, language="en", vad=False, beam_size=1, output_dir=folder)
                assert r["success"]
                if device == "cpu": assert r["device"] == "cpu" and r["model"] == "base"
                save(f"speech {device} inference", {"passed": True, "evidence": r, "accuracy_test": False})
    except Exception as exc:
        save("smoke failure", {"passed": False, "error": f"{type(exc).__name__}: {exc}"})
    finally:
        report["qwen_after"] = status("qwen")
        before = report["qwen_before"]["qwen"]["running"]
        report["restore_required"] = before
        report["restore_passed"] = _qwen_health_ready() if before else None
        atomic_json(ROOT/"Maintenance/Reports/media-smoke.json", report)
    return 0 if report["restore_passed"] is not False and all(c["passed"] for c in report["checks"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
