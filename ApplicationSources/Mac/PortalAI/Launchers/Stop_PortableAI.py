from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

VERSION = "2026.10.16"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0)


def run(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                          creationflags=(CREATE_NO_WINDOW if os.name == "nt" else 0))


def port_pids(port: int) -> list[int]:
    if os.name != "nt":
        return []
    out = set()
    try:
        cp = run(["netstat", "-ano", "-p", "tcp"], 20)
        for line in (cp.stdout or "").splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP" or parts[3].upper() != "LISTENING":
                continue
            if parts[1].rsplit(":", 1)[-1] == str(int(port)):
                try: out.add(int(parts[4]))
                except Exception: pass
    except Exception:
        pass
    return sorted(out)


def cim_processes() -> list[dict]:
    if os.name != "nt":
        return []
    ps = (
        "$x=Get-CimInstance Win32_Process | Select-Object ProcessId,Name,ExecutablePath,CommandLine;"
        "$x|ConvertTo-Json -Compress"
    )
    try:
        cp = run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], 40)
        if cp.returncode != 0 or not (cp.stdout or "").strip():
            raise RuntimeError("Process inventory unavailable; cannot verify ownership")
        d = json.loads((cp.stdout or "").strip())
        if isinstance(d, dict): d=[d]
        return d if isinstance(d,list) else []
    except Exception as exc:
        raise RuntimeError("Cannot inspect process ownership") from exc


def kill(pid: int) -> tuple[bool,str]:
    if pid <= 0 or pid == os.getpid(): return False, "refused current/invalid PID"
    try:
        cp=run(["taskkill","/PID",str(pid),"/T","/F"],30)
        return cp.returncode==0,(cp.stdout or cp.stderr or "").strip()
    except Exception as exc:
        return False,f"{type(exc).__name__}: {exc}"


def owned_process(root: Path, row: dict) -> bool:
    """Use executable containment or an explicit owned PowerShell -File script."""
    from pathlib import PureWindowsPath
    try:
        sys.path.insert(0, str(root/'Agent'))
        from profile_shutdown import _argv
        from remote_lifecycle import is_bridge
        if is_bridge(root, {'executable':row.get('ExecutablePath'), 'argv':_argv(row.get('CommandLine') or '')}):
            return False
        executable = str(row.get("ExecutablePath") or "")
        if not executable: return False
        base=PureWindowsPath(str(root.resolve()))
        if PureWindowsPath(executable).is_relative_to(base): return True
        if PureWindowsPath(executable).name.lower() not in ('powershell.exe','pwsh.exe'): return False
        import ctypes
        shell=ctypes.WinDLL('shell32',use_last_error=True)
        shell.CommandLineToArgvW.argtypes=(ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_int))
        shell.CommandLineToArgvW.restype=ctypes.POINTER(ctypes.c_wchar_p)
        count=ctypes.c_int();args=shell.CommandLineToArgvW(str(row.get('CommandLine') or ''),ctypes.byref(count))
        if not args:return False
        try:
            tokens=[args[i] for i in range(count.value)]
            for i,token in enumerate(tokens[:-1]):
                if token.lower()=='-file':
                    if not PureWindowsPath(tokens[i+1]).is_absolute():return False
                    script=PureWindowsPath(str(Path(tokens[i+1]).resolve()))
                    return script.suffix.lower()=='.ps1' and any(script.is_relative_to(base/p) for p in ('Launchers','Agent'))
            return False
        finally:
            kernel=ctypes.WinDLL('kernel32');kernel.LocalFree.argtypes=(ctypes.c_void_p,);kernel.LocalFree(args)
    except (ValueError, TypeError): return False


def listener_map() -> dict:
    out = {}
    cp = run(["netstat", "-ano", "-p", "tcp"], 20)
    if cp.returncode != 0: raise RuntimeError("Cannot enumerate listeners")
    for line in (cp.stdout or "").splitlines():
        parts=line.split()
        if len(parts)>=5 and parts[0].upper()=="TCP" and parts[3].upper()=="LISTENING":
            try: out.setdefault(int(parts[1].rsplit(":",1)[-1]),set()).add(int(parts[4]))
            except ValueError: pass
    return {str(k):sorted(v) for k,v in out.items() if k in (_instance_port('qwen'),_instance_port('comfyui'),_instance_port('acestep'),_instance_port('gateway'),*range(_instance_port('preview'),(_instance_port('preview')+1)))}


def portable_process_pids(root: Path) -> tuple[set[int], list[dict]]:
    root_norm=os.path.normcase(str(root.resolve())).lower()
    needles=(
        "llama-server.exe","comfyui","acestep","qwen3-tts","stt_worker.py","musetalk","mmaudio",
        "media_server.py","media_preview_server.py","secure_agent_gateway.py","qwen_supervisor.py",
        "portableai_lifecycle_watcher","start_portableai_controller","start_qwen_hidden",
        "start_portableai_native","qwen_vram_watchdog.py","abort_watchdog.py","voice_abort_watchdog.py",
        "agent\\ai_tools.py","agent/ai_tools.py","scientific_tool_bridge.py","science_core.py","web_tools.py",
        "voice_worker.py","piper_worker.py","sdcpp_worker.py","sd-cli.exe","comfy_amd_entry.py","sfx_bridge.py","mmaudio_bridge.py","video_understanding_bridge.py",
        "music_understanding_bridge.py","science_activity_",
        "music_cpu_entry.py","radeon_edit_entry.py","audio_inpaint_amd_entry.py",
        "musicunderstanding\\runtime_driver.py","musicunderstanding/runtime_driver.py",
        "musicunderstanding\\clap_worker.py","musicunderstanding/clap_worker.py",
        "protein_design_worker.py","ffmpeg.exe","ffprobe.exe","kicad-cli.exe",
        "mission_supervisor.py", "mission_runner.py", "vm_runner.py", "qemu-system-x86_64.exe",
    )
    pids=set(); rows=[]
    for p in cim_processes():
        try: pid=int(p.get("ProcessId") or 0)
        except Exception: continue
        if not pid or pid==os.getpid(): continue
        cmd=str(p.get("CommandLine") or "")
        exe=str(p.get("ExecutablePath") or "")
        low=os.path.normcase(cmd).lower()
        exelow=os.path.normcase(exe).lower()
        belongs = owned_process(root, p)
        if not belongs: continue
        if "portableai_gui.py" in low or "stop_portableai.py" in low: continue
        if any(n.lower() in low or n.lower() in exelow for n in needles):
            pids.add(pid); rows.append({"pid":pid,"name":p.get("Name"),"command_line":cmd[:1600]})
    return pids,rows


def marker_pids(root: Path) -> set[int]:
    rt=root/"Agent"/".runtime"; out=set()
    for p in list(rt.glob("science_activity_*.json"))+list(rt.glob("qwen_handoff_*.json"))+[rt/"gpu_exclusive_owner.json"]:
        if not p.exists(): continue
        try:
            d=json.loads(p.read_text(encoding="utf-8",errors="replace"))
            for key in ("pid","owner_pid","watchdog_pid","listener_pid"):
                v=int(d.get(key) or 0)
                if v: out.add(v)
        except Exception: pass
    return out


def cleanup_runtime(root: Path) -> None:
    rt=root/"Agent"/".runtime"
    for name in ("gpu_model_state.json","gpu_exclusive_owner.json","gpu_exclusive.lock","service_pids.json",
                 "media_preview_port.txt","qwen_handoff_generation.json"):
        try:(rt/name).unlink(missing_ok=True)
        except Exception:pass
    for pat in ("science_activity_*.json","qwen_handoff_*.json","qwen_handoff_*.done","completed_*.marker"):
        for p in rt.glob(pat):
            try:p.unlink(missing_ok=True)
            except Exception:pass


def gpu_processes(root: Path) -> list[dict]:
    try:
        cp=run(["nvidia-smi","--query-compute-apps=pid,process_name,used_memory","--format=csv,noheader,nounits"],20)
        rows=[]
        for line in (cp.stdout or "").splitlines():
            parts=[x.strip() for x in line.split(",",2)]
            if len(parts)>=2:
                try: pid=int(parts[0])
                except Exception: continue
                rows.append({"pid":pid,"process_name":parts[1],"used_memory_mib":parts[2] if len(parts)>2 else "?"})
        return rows
    except Exception:return []


def main()->int:
    ap=argparse.ArgumentParser(description="Stop current-root PortalAI components and pause missions")
    ap.add_argument("--root",required=True);ap.add_argument("--include-opengui",action="store_true");ap.add_argument("--quiet",action="store_true")
    ns=ap.parse_args();root=Path(ns.root).resolve();warnings=[];attempts=[]
    if os.name!='nt':
        sys.path.insert(0,str(root/'Agent'))
        from linux_lifecycle import stop_all
        print(json.dumps(stop_all(root)));return 0
    if os.name != "nt":
        print("Windows Stop helper only; Linux full lifecycle is not provisioned.");return 1
    sys.path.insert(0,str(root/"Agent"))
    from mission_supervisor import pause_all
    try: pause_all(root)
    except Exception as exc:
        print(json.dumps({"success":False,"error":"Cannot persist mission pause: "+str(exc)}));return 1
    # Invalidate restoration before any watchdog/worker can finish a tool call.
    try:
        import service_manager
        with service_manager._qwen_lifecycle_mutex(timeout=30):
            from runtime_policy import atomic_json
            atomic_json(root/'Agent/.runtime/qwen_last_stop.json', {'stopped_at':time.time()})
            (root/"Agent/.runtime/qwen_handoff_generation.json").unlink(missing_ok=True)
    except Exception as exc:
        print(json.dumps({"success":False,"error":"Cannot invalidate model restoration: "+str(exc)}));return 1
    discovered,inventory=portable_process_pids(root)
    before=cim_processes();by_pid={int(x.get("ProcessId") or 0):x for x in before}
    ports=listener_map();foreign=[];pids=set(discovered)
    for port,listeners in ports.items():
        for pid in listeners:
            row=by_pid.get(pid,{})
            if owned_process(root,row):pids.add(pid)
            else:foreign.append({"port":port,"pid":pid,"name":row.get("Name")})
    for pid in marker_pids(root):
        row=by_pid.get(pid,{})
        if owned_process(root,row) and not any(x in str(row.get("CommandLine") or "").lower() for x in ("portableai_gui.py","control_center_bootstrap.py","stop_portableai.py")):
            pids.add(pid)
    # Recheck current identity immediately before terminating any candidate PID.
    current={int(x.get("ProcessId") or 0):x for x in cim_processes()}
    for pid in sorted(pids):
        row=current.get(pid,{})
        if not owned_process(root,row) or row.get("CommandLine")!=by_pid.get(pid,{}).get("CommandLine"):
            attempts.append({"pid":pid,"killed":False,"detail":"Process exited or identity changed; skipped"});continue
        if any(x in str(row.get("CommandLine") or "").lower() for x in ("portableai_gui.py","control_center_bootstrap.py","stop_portableai.py")):continue
        ok,detail=kill(pid);attempts.append({"pid":pid,"killed":ok,"detail":detail[-1000:]})
    remaining_owned=[];deadline=time.monotonic()+12
    while True:
        remaining_owned,remaining_rows=portable_process_pids(root)
        if not remaining_owned or time.monotonic()>=deadline:break
        time.sleep(.3)
    final_ports=listener_map()
    final_processes={int(x.get("ProcessId") or 0):x for x in cim_processes()}
    owned_listeners={pid for listeners in final_ports.values() for pid in listeners if owned_process(root,final_processes.get(pid,{}))}
    remaining_owned=set(remaining_owned)|owned_listeners
    success=not remaining_owned
    if success:cleanup_runtime(root)
    else:warnings.append("Owned workers remain; lifecycle evidence was preserved.")
    result={"success":success,"version":VERSION,"kill_attempts":attempts,
            "remaining_portable_pids":sorted(remaining_owned),"foreign_listeners_preserved":foreign,
            "remaining_listeners":listener_map(),"warnings":warnings,
            "note":"Chat cancellation belongs to the GUI; missions paused. Unrelated listeners do not make owned-component shutdown fail."}
    from runtime_policy import atomic_json
    atomic_json(root/"Agent/.runtime/native_startup_state.json",{"version":VERSION,"success":success,"stage":"stopped" if success else "stop_failed","stopped_at":time.time()})
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"Tools"));from maintenance_reports import save
    text=json.dumps(result,indent=2);save(root,"stop_components",text,result,0 if success else 1)
    if not ns.quiet:print(text)
    return 0 if success else 1

if __name__=="__main__":raise SystemExit(main())
