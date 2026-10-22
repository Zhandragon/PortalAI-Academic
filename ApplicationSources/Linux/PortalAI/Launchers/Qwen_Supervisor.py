from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url
import argparse, os, subprocess, sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--gpu-layers", type=int, default=32)
    ap.add_argument("--idle-sleep", type=int, default=300)
    ap.add_argument("--context", type=int, default=32768)
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    sys.path.insert(0, str(root / "ControlCenter"))
    from portableai_common import hidden_popen, runtime_dir

    llama = root / "LLM" / "llamacpp" / "llama-server.exe"
    model = root / "LLM" / "models" / "Qwen3.8-27B-Q4_K_M.gguf"
    mmproj = root / "LLM" / "models" / "mmproj-Qwen3.8-27B-Standard-BF16.gguf"
    for p in (llama, model, mmproj):
        if not p.exists():
            return 2

    runtime = runtime_dir(root)
    stdout_path = runtime / "qwen_server.log"
    stderr_path = runtime / "qwen_server_error.log"
    pid_path = runtime / "qwen_pid.txt"
    helper_pid_path = runtime / "qwen_helper_pid.txt"
    helper_pid_path.write_text(str(os.getpid()), encoding="ascii")

    args = [
        str(llama), "-m", str(model), "--mmproj", str(mmproj),
        "--no-mmproj-offload", "-ngl", str(ns.gpu_layers), "-c", str(ns.context),
        "--sleep-idle-seconds", str(ns.idle_sleep), "--metrics",
        "--host", "127.0.0.1", "--port", str(_instance_port('qwen')),
    ]
    # Register exact launch state for the AV-clean service manager's fail-safe
    # Qwen restoration path. This is only used after validating the listener EXE.
    try:
        (runtime / "qwen_launch_command.txt").write_text(subprocess.list2cmdline(args) + "\n", encoding="utf-8")
        (runtime / "qwen_launch_executable.txt").write_text(str(llama.resolve()) + "\n", encoding="utf-8")
    except Exception:
        pass

    out = stdout_path.open("w", encoding="utf-8", buffering=1)
    err = stderr_path.open("w", encoding="utf-8", buffering=1)
    try:
        proc = hidden_popen(args, cwd=root, stdout=out, stderr=err)
        pid_path.write_text(str(proc.pid), encoding="ascii")
        return int(proc.wait())
    finally:
        out.close(); err.close()
        for p in (pid_path, helper_pid_path):
            try: p.unlink(missing_ok=True)
            except Exception: pass

if __name__ == "__main__":
    raise SystemExit(main())
