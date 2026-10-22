from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url
import argparse, os, sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    sys.path.insert(0, str(root / 'Agent'))
    from profile_paths import private_path, capture
    capture(root)
    sys.path.insert(0, str(root / "ControlCenter"))
    from portableai_common import find_opengui, hidden_popen, log_line, port_open, pythonw_executable, runtime_dir

    runtime = runtime_dir(root)
    log = runtime / "portableai_launcher.log"
    def logmsg(s): log_line(log, s)

    llama = root / "LLM" / "llamacpp" / "llama-server.exe"
    model = root / "LLM" / "models" / "Qwen3.8-27B-Q4_K_M.gguf"
    mmproj = root / "LLM" / "models" / "mmproj-Qwen3.8-27B-Standard-BF16.gguf"
    supervisor = root / "Launchers" / "Qwen_Supervisor.py"
    watcher = root / "Launchers" / "PortableAI_Lifecycle_Watcher.py"
    for p in (llama, model, mmproj, supervisor, watcher):
        if not p.exists():
            logmsg(f"ERROR: Required file missing: {p}")
            return 2

    logmsg("Starting PortableAI session (AV-clean Python controller).")

    # Lightweight Outputs server: same port/root as current Control Center.
    if not port_open(_instance_port('preview')):
        media_server = root / "Agent" / "media_server.py"
        embedded = root / "Generative" / "ComfyUI_windows_portable" / "python_embeded" / "python.exe"
        preview_python = embedded if embedded.exists() else Path(sys.executable)
        if media_server.exists():
            try:
                pidfile = runtime / "media_preview.pid"
                p = hidden_popen([
                    str(preview_python), "-u", str(media_server), "--root", str(private_path(root, 'Outputs')),
                    "--host", "127.0.0.1", "--port", str(_instance_port('preview')), "--pid-file", str(pidfile)
                ], cwd=root)
                logmsg((f"Started media preview server on :8765, PID {p.pid}").replace(':8765', ':'+str(_instance_port('preview'))))
            except Exception as exc:
                logmsg(f"Media preview server start failed: {exc}")
        else:
            logmsg("Media preview server skipped: Agent\\media_server.py missing.")
    else:
        logmsg(("Media preview server :8765 is already running.").replace(':8765', ':'+str(_instance_port('preview'))))

    opengui = find_opengui()
    if not opengui:
        logmsg("ERROR: OpenGUI.exe was not found.")
        return 3
    (runtime / "opengui_path.txt").write_text(str(opengui), encoding="utf-8")

    try:
        os.startfile(str(opengui))  # normal visible application launch; no shell interpreter
        logmsg(f"Opened OpenGUI immediately: {opengui}")
    except Exception as exc:
        logmsg(f"ERROR: failed to open OpenGUI: {exc}")
        return 4

    py = pythonw_executable()
    try:
        p = hidden_popen([py, str(watcher), "--root", str(root), "--opengui-path", str(opengui)], cwd=root)
        logmsg(f"Lifecycle watcher armed, PID {p.pid}.")
    except Exception as exc:
        logmsg(f"WARNING: lifecycle watcher failed to start: {exc}")

    if not port_open(_instance_port('qwen')):
        try:
            p = hidden_popen([
                py, str(supervisor), "--root", str(root), "--gpu-layers", "32",
                "--idle-sleep", "300", "--context", "32768"
            ], cwd=root)
            logmsg(f"Started hidden Qwen supervisor in background, PID {p.pid}.")
        except Exception as exc:
            logmsg(f"ERROR: Qwen supervisor failed to start: {exc}")
            return 5
    else:
        logmsg(("Qwen port 8080 is already open.").replace('port 8080', 'port '+str(_instance_port('qwen'))))

    logmsg("Controller finished; Qwen may still be loading.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
