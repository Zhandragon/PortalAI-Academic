"""Exercise downloaded small model on each installed Windows backend, one at a time."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import atomic_json, portable_env


def run(backend):
    exe = ROOT / f"LLM/backends/windows-{backend}/llama-server.exe"
    model = ROOT / "LLM/models/Qwen3-1.7B-Q8_0.gguf"
    port = 18089
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:
            raise RuntimeError("Test port is occupied; refusing to interfere")
    logpath = ROOT / f"Maintenance/Reports/smoke-{backend}.log"
    with logpath.open("w", encoding="utf-8") as log:
        command = [str(exe), "-m", str(model), "-ngl", "0" if backend == "cpu" else "99", "-c", "2048",
                   "--parallel", "1", "--jinja", "--host", "127.0.0.1", "--port", str(port)]
        if backend == "cpu":
            command += ["--device", "none"]
        proc = subprocess.Popen(command, cwd=exe.parent, env=portable_env(ROOT), stdout=log, stderr=log,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            deadline = time.monotonic() + 150
            ready = False
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"Backend exited {proc.returncode}; see {logpath}")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                        ready = json.load(response).get("status") == "ok"
                    if ready:
                        break
                except Exception:
                    time.sleep(.5)
            if not ready:
                raise RuntimeError("Backend readiness timeout")
            payload = {"messages": [{"role": "user", "content": "What is 2 + 2? Reply only with the numeral."}],
                       "temperature": 0, "max_tokens": 32, "chat_template_kwargs": {"enable_thinking": False}}
            request = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                                             json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
            started = time.monotonic()
            with urllib.request.urlopen(request, timeout=120) as response:
                data = json.load(response)
            text = data["choices"][0]["message"]["content"].strip()
            result = {"backend": backend, "passed": text == "4", "reply": text,
                      "seconds": round(time.monotonic()-started, 3), "usage": data.get("usage")}
            return result
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["cpu", "vulkan", "all"], default="all")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("This smoke script currently verifies the Windows CPU/Vulkan builds")
    rows = []
    for backend in (["cpu", "vulkan"] if args.backend == "all" else [args.backend]):
        print("Testing " + backend, flush=True)
        try:
            result = run(backend)
        except Exception as exc:
            result = {"backend": backend, "passed": False, "error": str(exc)}
        rows.append(result)
        print(json.dumps(result), flush=True)
    atomic_json(ROOT / "Maintenance/Reports/backend-smoke.json", {"results": rows})
    return 0 if all(r["passed"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
