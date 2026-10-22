from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Agent"))
from runtime_policy import build_plan, portable_env
from profile_paths import private_path
from media_paths import preview_url, owned_preview

VERSION = "15.133"
HOST = "127.0.0.1"
PORT = _instance_port('qwen')
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0)
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200 if os.name == "nt" else 0)
CREATE_BREAKAWAY_FROM_JOB = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000 if os.name == "nt" else 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0x00000008 if os.name == "nt" else 0)


def runtime_dir(root: Path) -> Path:
    p = root / "Agent" / ".runtime"
    p.mkdir(parents=True, exist_ok=True)
    return p


def clean_env() -> dict[str, str]:
    env = portable_env(Path(__file__).resolve().parents[1])
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def log(root: Path, message: str) -> None:
    text = str(message).replace("\r", " ").replace("\n", " | ")
    with (runtime_dir(root) / "native_startup.log").open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {text[:5000]}\n")


def port_open(port: int = PORT, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((HOST, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def powershell(script: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, errors="replace", timeout=timeout,
        creationflags=(CREATE_NO_WINDOW if os.name == "nt" else 0), env=clean_env(),
    )


def listener_pids(port: int = PORT) -> list[int]:
    if os.name != "nt":
        return []
    ps = (
        f"$x=Get-NetTCPConnection -LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -ExpandProperty OwningProcess -Unique; if($x){$x -join ','}"
    )
    try:
        cp = powershell(ps, 8)
        return sorted({int(x) for x in (cp.stdout or '').strip().split(',') if x.strip().isdigit()})
    except Exception:
        return []


def process_info(pid: int) -> dict:
    if os.name != "nt":
        return {"pid": int(pid)}
    ps = (
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\" -ErrorAction SilentlyContinue; "
        "if($p){[pscustomobject]@{pid=$p.ProcessId;name=$p.Name;exe=$p.ExecutablePath;cmd=$p.CommandLine}|ConvertTo-Json -Compress}"
    )
    try:
        cp = powershell(ps, 10)
        raw = (cp.stdout or '').strip()
        if raw:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {"pid": int(pid)}


def listener_info(port: int = PORT) -> list[dict]:
    return [process_info(pid) for pid in listener_pids(port)]


def is_portable_qwen(root: Path, info: dict) -> bool:
    name = str(info.get("name") or "").lower()
    exe = os.path.normcase(str(info.get("exe") or ""))
    cmd = os.path.normcase(str(info.get("cmd") or ""))
    r = os.path.normcase(str(root.resolve()))
    return (
        "llama-server" in name
        and (exe.startswith(r) or r in cmd)
        and ("qwen" in cmd or "\\llm\\" in exe)
    )


def http_json(path: str, timeout: float = 2.0):
    c = http.client.HTTPConnection(HOST, PORT, timeout=timeout)
    try:
        c.request("GET", path, headers={"Accept": "application/json", "Connection": "close"})
        r = c.getresponse()
        raw = r.read(512000)
        if r.status >= 400:
            return None
        return json.loads(raw.decode("utf-8", errors="replace")) if raw else {}
    except Exception:
        return None
    finally:
        try: c.close()
        except Exception: pass


def qwen_http_state() -> dict:
    if not port_open():
        return {"online": False, "ready": False, "sleeping": False, "state": "offline"}
    props = http_json("/props", 1.8)
    models = http_json("/v1/models", 2.5)
    sleeping = bool(isinstance(props, dict) and props.get("is_sleeping"))
    items = models.get("data") if isinstance(models, dict) else None
    ready = bool(items)
    model = None
    if ready:
        try: model = str(items[0].get("id") or "")
        except Exception: pass
    if not model and isinstance(props, dict):
        model = str(props.get("model_path") or "") or None
    state = "sleeping" if sleeping else "ready" if ready else "listening"
    return {"online": True, "ready": ready, "sleeping": sleeping, "state": state, "model": model, "props": props}


def kill_pid(pid: int) -> bool:
    if os.name != "nt": return False
    try:
        cp = subprocess.run(["taskkill.exe", "/PID", str(int(pid)), "/T", "/F"], capture_output=True,
                            text=True, errors="replace", timeout=20, creationflags=CREATE_NO_WINDOW)
        return cp.returncode == 0
    except Exception:
        return False


def process_inventory(root: Path) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    try:
        sys.path.insert(0, str(root / "ControlCenter"))
        from portableai_common import iter_processes, process_command_line  # type: ignore
        for pid, _exe in iter_processes():
            try: cmd = process_command_line(pid) or ""
            except Exception: cmd = ""
            if cmd: rows.append((int(pid), str(cmd)))
    except Exception:
        pass
    return rows


def stop_obsolete_respawners(root: Path) -> list[int]:
    """Stop only obsolete startup/supervisor jobs that can race port 8080."""
    if os.name != "nt": return []
    root_norm = os.path.normcase(str(root.resolve()))
    needles = (
        "qwen_supervisor.py",
        "portableai_lifecycle_watcher.py",
        "start_portableai_controller.py",
        "start_qwen_hidden.ps1",
    )
    # qwen_vram_watchdog is safe to remove only when no heavy persistent worker is active.
    if not port_open(_instance_port('comfyui')) and not port_open(_instance_port('acestep')):
        needles = needles + ("qwen_vram_watchdog.py",)
    killed: list[int] = []
    for pid, cmd in process_inventory(root):
        if pid == os.getpid():
            continue
        low = os.path.normcase(cmd).lower()
        if root_norm not in os.path.normcase(cmd):
            continue
        if any(n in low for n in needles):
            if kill_pid(pid): killed.append(pid)
    return killed


def wait_port_free(timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not port_open(): return True
        time.sleep(0.2)
    return not port_open()


def find_paths(root: Path) -> tuple[Path, Path, Path]:
    exe = root / "LLM" / "llamacpp" / "llama-server.exe"
    mdl = root / "LLM" / "models" / "Qwen3.8-27B-Q4_K_M.gguf"
    mm = root / "LLM" / "models" / "mmproj-Qwen3.8-27B-Standard-BF16.gguf"
    for p in (exe, mdl, mm):
        if not p.exists():
            raise FileNotFoundError(str(p))
    return exe.resolve(), mdl.resolve(), mm.resolve()


def verify_flags(exe: Path) -> None:
    cp = subprocess.run([str(exe), "--help"], capture_output=True, text=True, errors="replace", timeout=30,
                        creationflags=(CREATE_NO_WINDOW if os.name == "nt" else 0))
    helptext = (cp.stdout or "") + (cp.stderr or "")
    need = ["--no-mmproj-offload", "--sleep-idle-seconds", "--metrics"]
    missing = [x for x in need if x not in helptext]
    if missing:
        raise RuntimeError("This llama-server build is missing v15.128-era required flags: " + ", ".join(missing))


def baseline_command(root: Path) -> list[str]:
    return build_plan(root)["command"]


def tail(path: Path, lines: int = 100) -> str:
    try:
        arr = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(arr[-lines:])
    except Exception:
        return ""


def startup_failure(exe: Path, code: int, log_path: Path, offset: int) -> str:
    """Show only this attempt, including externally removed executable evidence."""
    try:
        with log_path.open('rb') as handle:
            handle.seek(offset)
            text = handle.read(256000).decode('utf-8', errors='replace')
        text = '\n'.join(text.splitlines()[-80:])
    except OSError:
        text = 'Startup log could not be read.'
    missing = (f' The executable disappeared during startup: {exe}. Check antivirus quarantine; '
               'restore only the verified bundle copy.' if not exe.is_file() else '')
    return f'Qwen exited before becoming healthy (exit code {code}).{missing}\n\n{text}'


def launch_baseline(root: Path) -> dict:
    plan = build_plan(root)
    exe = Path(plan["backend"]["executable"])
    mdl = Path(plan["model"]["absolute_path"])
    mm = plan["model"]["absolute_projector"]
    verify_flags(exe)
    cmd = plan["command"]
    (runtime_dir(root) / "hardware_launch_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    rtd = runtime_dir(root)
    qlog = rtd / "native_qwen_v15_133.log"
    log_offset = qlog.stat().st_size if qlog.exists() else 0
    with qlog.open("a", encoding="utf-8", errors="replace") as f:
        f.write(f"\n=== PortableAI v{VERSION} Qwen baseline {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        f.write(subprocess.list2cmdline(cmd) + "\n")
        f.flush()
        kwargs = dict(cwd=str(root), stdin=subprocess.DEVNULL, stdout=f, stderr=f,
                      env=clean_env(), close_fds=True)
        flags = 0
        if os.name == "nt":
            flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_BREAKAWAY_FROM_JOB
        try:
            p = subprocess.Popen(cmd, creationflags=flags, **kwargs)
        except OSError:
            flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
            p = subprocess.Popen(cmd, creationflags=flags, **kwargs)
    log(root, f"Started v15.128-compatible Qwen baseline pid={p.pid} flags=0x{flags:08x}")
    deadline = time.monotonic() + 300
    seen_port = False
    while time.monotonic() < deadline:
        rc = p.poll()
        if rc is not None:
            raise RuntimeError(startup_failure(exe, rc, qlog, log_offset))
        if port_open():
            seen_port = True
            state = qwen_http_state()
            if state.get("ready") or state.get("sleeping"):
                cmdline = subprocess.list2cmdline(cmd)
                (rtd / "qwen_launch_command.txt").write_text(cmdline + "\n", encoding="utf-8")
                (rtd / "qwen_launch_executable.txt").write_text(str(exe) + "\n", encoding="utf-8")
                return {"ready": True, "pid": p.pid, "profile": plan["model"]["id"] + "/" + plan["backend"]["backend"], "state": state,
                        "command": cmdline, "model": str(mdl), "mmproj": mm}
        time.sleep(0.35 if seen_port else 0.2)
    raise RuntimeError(("Qwen opened port 8080 but did not become API-ready within 5 minutes.\n\n").replace('port 8080', 'port '+str(_instance_port('qwen'))) + tail(qlog, 120))


def recover_or_adopt(root: Path, requested_at=None) -> dict:
    from chat_model_switch import prepare_startup
    result = prepare_startup(root, requested_at=requested_at, on_status=lambda message: log(root, message))
    model = result['model']
    return {'ready': True, 'already_running': not result['changed'], 'port': PORT,
            'profile': model['id'], 'model': model,
            'detail': model.get('label') or model['id']}


def ensure_preview(root: Path) -> dict:
    # Preview is deliberately non-critical to Qwen startup.
    for p in range(_instance_port('preview'), (_instance_port('preview')+1)):
        try:
            if not owned_preview(root,p):
                continue
            c = http.client.HTTPConnection(HOST, p, timeout=0.35)
            c.request("GET", preview_url(root, "/__health__"), headers={"Connection": "close"})
            r = c.getresponse(); raw = r.read(100000); c.close()
            data = json.loads(raw.decode("utf-8", errors="replace")) if raw else None
            if (r.status == 200 and isinstance(data, dict) and data.get("ok") and
                    Path(str(data.get('root', ''))).resolve() == private_path(root, 'Outputs').resolve()):
                return {"ready": True, "already_running": True, "port": p}
        except Exception:
            pass
    py = root / "Runtime" / "BootstrapPython" / "python.exe"
    candidates = [root/"Agent"/"media_server.py", root/"Agent"/"media_preview_server.py", root/"Services"/"media_preview_server.py"]
    server = next((p for p in candidates if p.exists()), None)
    if not py.exists() or server is None:
        return {"ready": False, "warning": "preview server not installed"}
    p = _instance_port('preview')
    if port_open(p): return {"ready": False, "warning": "preview port occupied"}
    logp = runtime_dir(root)/"media_preview.log"
    with logp.open("a", encoding="utf-8", errors="replace") as f:
        args = [str(py), "-u", str(server), "--root", str(private_path(root, 'Outputs').resolve()), "--host", HOST,
                "--port", str(p), "--pid-file", str(runtime_dir(root)/f"media_preview_{p}.pid")]
        flags = CREATE_NO_WINDOW | DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        proc = subprocess.Popen(args, cwd=str(root), stdin=subprocess.DEVNULL, stdout=f, stderr=f,
                                env=clean_env(), close_fds=True, creationflags=flags)
    return {"ready": True, "pid": proc.pid, "port": p, "starting": True}


def write_state(root: Path, state: dict) -> None:
    (runtime_dir(root)/"native_startup_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def preflight(root: Path) -> dict:
    plan = build_plan(root)
    return {
        "success": True, "version": VERSION, "root": str(root), "llama_server": plan["backend"]["executable"],
        "model": plan["model"]["absolute_path"], "mmproj": plan["model"]["absolute_projector"], "port_8080_open": port_open(),
        "listeners": listener_info() if port_open() else [],
        "baseline_command": subprocess.list2cmdline(plan["command"]), "hardware_plan": plan,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI v15.133 Qwen startup baseline restore")
    ap.add_argument("--root", required=True)
    ap.add_argument("--preflight", action="store_true")
    ap.add_argument("--requested-at", type=float)
    ns = ap.parse_args()
    root = Path(str(ns.root).strip().strip('"').rstrip('"')).resolve()
    rtd = runtime_dir(root)
    (rtd/"native_startup_active_version.txt").write_text(f"{VERSION}\n{Path(__file__).resolve()}\n", encoding="utf-8")
    if ns.preflight:
        try:
            print(json.dumps(preflight(root), indent=2)); return 0
        except Exception as exc:
            print(json.dumps({"success": False, "version": VERSION, "error": f"{type(exc).__name__}: {exc}"}, indent=2)); return 2
    requested_at = time.time() if ns.requested_at is None else ns.requested_at
    state = {"version": VERSION, "started_at": requested_at, "success": False, "stage": "starting-qwen",
             "helper_path": str(Path(__file__).resolve())}
    write_state(root, state)
    log(root, f"Native Startup v{VERSION} requested helper={Path(__file__).resolve()}")
    try:
        state["qwen"] = recover_or_adopt(root, requested_at=requested_at)
        from chat_model_switch import _guard
        _guard(root, requested_at)
        state["stage"] = "starting-preview"; write_state(root, state)
        state["preview"] = ensure_preview(root)
        try:
            from mission_supervisor import ensure_running
            state["missions"] = ensure_running(root)
        except Exception as exc:
            state["missions"] = {"started": False, "error": str(exc)}
        _guard(root, requested_at)
        state["success"] = True; state["stage"] = "ready"; state["finished_at"] = time.time(); write_state(root, state)
        log(root, f"Native Startup v{VERSION} completed profile={state['qwen'].get('profile')}")
        print(json.dumps(state, indent=2)); return 0
    except Exception as exc:
        state["success"] = False; state["stage"] = "failed"; state["finished_at"] = time.time()
        state["error"] = f"{type(exc).__name__}: {exc}"; write_state(root, state); log(root, "Native Startup FAILED: "+state["error"])
        with (rtd/"native_startup_error.log").open("a", encoding="utf-8", errors="replace") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {state['error'][:16000]}\n")
        print(json.dumps(state, indent=2)); return 2

if __name__ == "__main__":
    raise SystemExit(main())
