from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from capability_registry import detect
from lifecycle_probe import handoff_state, probe_qwen
from science_smoke import run_suite as run_science_suite

VERSION = "2026.10.16"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0)


def run(args, cwd, timeout=40):
    return subprocess.run(
        args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=(CREATE_NO_WINDOW if os.name == "nt" else 0),
    )


def R(status, label, detail=""):
    return {"status": status, "label": label, "detail": detail}


def main() -> int:
    ap = argparse.ArgumentParser(description="PortalAI current platform system checks; media inference remains separate")
    ap.add_argument("--root", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--skip-science-functional", action="store_true")
    ns = ap.parse_args()
    root = Path(ns.root).resolve()
    if os.name!='nt':
        from linux_system_test import main as linux_main
        return linux_main(root,ns.json,not ns.skip_science_functional)
    rows = []

    py = root / "Runtime" / "BootstrapPython" / "python.exe"
    ai = root / "Agent" / "ai_tools.py"
    rows.append(R("PASS" if py.exists() else "FAIL", "Portable BootstrapPython", str(py)))

    reg = detect(root)
    cmds = reg.get("commands") or []
    rows.append(R("PASS" if cmds else "FAIL", f"ai_tools command registry ({len(cmds)})", ", ".join(cmds) if cmds else str(reg.get("command_error"))))

    if py.exists() and ai.exists():
        for label, args in (
            ("ai_tools version", [str(py), str(ai), "version"]),
            ("service status", [str(py), str(ai), "service", "status"]),
            ("science status", [str(py), str(ai), "science", "status"]),
        ):
            try:
                cp = run(args, root, 90)
                txt = ((cp.stdout or "") + ("\n" + cp.stderr if cp.stderr else "")).strip()
                rows.append(R("PASS" if cp.returncode == 0 else "FAIL", label, txt[-5000:]))
            except Exception as exc:
                rows.append(R("FAIL", label, f"{type(exc).__name__}: {exc}"))

    try:
        q = probe_qwen(root)
        status = "FAIL" if q.get("state") == "conflict" else ("PASS" if q.get("active") else "WARN")
        rows.append(R(status, "Qwen lifecycle", f"state={q.get('state')} active={q.get('active')} sleeping={q.get('sleeping')} listeners={q.get('listeners')}"))
    except Exception as exc:
        rows.append(R("FAIL", "Qwen lifecycle", str(exc)))

    hs = handoff_state(root)
    cur = hs.get("current_generation")
    rows.append(R("WARN" if cur else "PASS", "Qwen handoff state", json.dumps(cur)[:3000] if cur else "no active generation"))

    required = {
        "Hardened VRAM watchdog": "Agent/qwen_vram_watchdog.py",
        "Service manager": "Agent/service_manager.py",
        "Stop all": "Launchers/Stop_PortableAI.py",
        "Full/targeted diagnosis": "Tools/component_diagnostics.py",
        "Fresh-machine readiness": "Tools/fresh_machine_validator.py",
        "Media stack verifier": "Tools/media_stack_verify.py",
        "Science functional test": "Tools/science_smoke.py",
        "Science core": "Scientific/science_core.py",
        "Science bridge": "Agent/scientific_tool_bridge.py",
        "Control Center": "ControlCenter/PortableAI_GUI.py",
    }
    for label, rel in required.items():
        rows.append(R("PASS" if (root / rel).exists() else "FAIL", label, rel))
    from diagnostic_catalog import source_rows,SOURCE_ONLY
    for component in sorted(SOURCE_ONLY):rows.extend(source_rows(root,component))
    from installed_feature_checks import rows as feature_rows
    rows.extend(feature_rows(root))

    # v15.134c model/tool contract checks: these catch the specific regression where
    # Science executed instantly but Qwen spent minutes discovering routes/re-parsing output.
    fast_marker = "PORTABLEAI_SCIENCE_FAST_ROUTING_v15_134c"
    align_marker = "PORTABLEAI_GENOME_ALIGN_STRUCTURED_v15_134c"
    try:
        ai_text = ai.read_text(encoding="utf-8", errors="replace") if ai.exists() else ""
        bridge_path = root / "Agent" / "scientific_tool_bridge.py"
        bridge_text = bridge_path.read_text(encoding="utf-8", errors="replace") if bridge_path.exists() else ""
        core_path = root / "Scientific" / "science_core.py"
        core_text = core_path.read_text(encoding="utf-8", errors="replace") if core_path.exists() else ""
        masters = sorted(root.glob("PortableAI_Master_Instructions_v*.txt"), key=lambda p: int(__import__('re').search(r"_v(\d+)\.txt$", p.name, __import__('re').I).group(1)) if __import__('re').search(r"_v(\d+)\.txt$", p.name, __import__('re').I) else -1)
        master_text = masters[-1].read_text(encoding="utf-8", errors="replace") if masters else ""
        rows.append(R("PASS" if fast_marker in ai_text else "FAIL", "Science direct-routing · ai_tools metadata", "specific-operation-first / no status-first contract"))
        rows.append(R("PASS" if fast_marker in bridge_text else "FAIL", "Science terminal-result metadata", "successful deterministic results tell Qwen to answer rather than re-probe"))
        rows.append(R("PASS" if align_marker in core_text else "FAIL", "Genome alignment structured result", "matches / mismatches / gaps / identity fields"))
        rows.append(R("PASS" if fast_marker in master_text else "FAIL", "Master instructions · Science fast routing", masters[-1].name if masters else "no master instructions found"))
        native_path = root / "ControlCenter" / "native_chat.py"
        native_text = native_path.read_text(encoding="utf-8", errors="replace") if native_path.exists() else ""
        native_marker = "PORTABLEAI_NATIVE_SCIENCE_ROUTING_v15_134c"
        rows.append(R("PASS" if native_marker in native_text else "WARN", "Native Chat · Science fast routing host note", "specific-operation-first / terminal-result contract" if native_marker in native_text else "master instructions remain authoritative, but Native Chat host-note reinforcement is absent"))
    except Exception as exc:
        rows.append(R("FAIL", "Science routing contract", f"{type(exc).__name__}: {exc}"))

    for c in [c for c in reg["capabilities"] if c["key"].startswith("science")]:
        rows.append(R("PASS" if c["installed"] else "WARN", c["label"], c["detail"]))

    science = None
    if not ns.skip_science_functional:
        try:
            science = run_science_suite(root)
            for x in science["rows"]:
                rows.append(R(x["status"], "Functional · " + x["label"], x.get("detail", "")))
        except Exception as exc:
            rows.append(R("FAIL", "Science Workbench functional suite", f"{type(exc).__name__}: {exc}"))

    try:
        cp = run(["nvidia-smi", "--query-gpu=name,driver_version,memory.total,memory.used", "--format=csv,noheader"], root, 15)
        rows.append(R("PASS" if cp.returncode == 0 else "WARN", "NVIDIA GPU / driver", (cp.stdout or cp.stderr or "").strip()))
    except Exception as exc:
        rows.append(R("WARN", "NVIDIA GPU / driver", str(exc)))

    rows.append(R("WARN" if (root / "OpenWebUI").exists() else "PASS", "Legacy OpenWebUI files", "Legacy runtime/data retained for review; not the current GUI. Do not delete as empty residue." if (root / "OpenWebUI").exists() else "not present"))

    for rel in (
        "Documentation/Control_Center_Guide.md",
        "Documentation/Lifecycle_and_VRAM.md",
        "Documentation/Science_Workbench.md",
        "Documentation/Maintenance.md",
        "Documentation/Diagnostics.md",
    ):
        rows.append(R("PASS" if (root / rel).exists() else "WARN", f"Documentation · {Path(rel).name}", rel))

    sys.path.insert(0, str(root / "Agent"))
    sys.path.insert(0, str(root / "ControlCenter"))
    from bundle_inventory import inventory
    from workload_compatibility import support_matrix
    from sdcpp_bridge import executable as image_executable
    from runtime_policy import run_probe
    try:
        receipt = json.loads((root/"Maintenance/Imports/amd-runtime-lock.json").read_text(encoding="utf-8"))
        installed = (root/"Runtime/AMDPython/packages/torch/__init__.py").is_file() and receipt.get("status") in ("installed-unvalidated-on-Radeon", "validated")
        rows.append(R("PASS" if installed else "WARN", "Isolated AMD media package layer",
                      "ROCm 10.1 / Torch 2.14, " + str(len(receipt.get("assets", []))) + " pinned assets; installation receipt only. Actual Radeon compute and per-tool validation are separate."))
    except (OSError, ValueError) as exc:
        rows.append(R("WARN", "Isolated AMD media package layer", str(exc)))
    for backend in ("cpu", "vulkan"):
        try:
            exe = image_executable(root, backend)
            devices = run_probe([str(exe), "--list-devices"])
            present = ("CPU\t" if backend == "cpu" else "Vulkan0\t") in devices
            rows.append(R("PASS" if present else "WARN", "Native SD1.5 " + backend + " runtime",
                          "Files hash-verified; device probe only, not image inference. " + devices[-1200:]))
        except Exception as exc:
            rows.append(R("FAIL" if backend == "cpu" else "WARN", "Native SD1.5 " + backend + " runtime", str(exc)))
    try:
        current=inventory(root)
        for m in current["models"]:
            rows.append(R("PASS" if m["installed"] else "WARN", "Model · " + m["label"], m["path"] + (" (optional; not installed)" if not m["installed"] else "")))
        for b, installed in current["backends"].items():
            rows.append(R("PASS" if installed else "WARN", "Bundled backend · " + b, "Presence only; driver/inference validation separate"))
        rows.append(R("PASS" if current["storage"]["allowed"] else "FAIL", "SSD reserves", json.dumps(current["storage"])))
        for label, path in (("Settings page","ControlCenter/settings_page.py"),("Persistent supervisor","Agent/mission_supervisor.py"),("Mission schedules","Agent/mission_schedule.py"),("Scoped mission memory","Agent/mission_memory.py"),("Schedule controls","ControlCenter/schedule_settings.py"),("Portable web recovery","Agent/web_state.py"),("Mission mode contracts","Agent/mission_modes.py"),("Offline VM runner","Agent/vm_runner.py"),("Native launcher","PortalAI.exe")):
            rows.append(R("PASS" if (root/path).is_file() else "FAIL",label,path))
        from mission_modes import MODES
        rows.append(R("PASS", "Per-mission access modes", str(list(MODES))))
    except Exception as exc:rows.append(R("FAIL", "Current foundation inventory", str(exc)))
    try:
        locks=json.loads((root/"Agent/.runtime/component_runtime_locks.json").read_text(encoding="utf-8"))
        failures=[name for name,info in locks.get("components",{}).items() if info.get("status")=="PROBE_FAILED"]
        if failures:rows.append(R("WARN","Last private-runtime inventory failures",", ".join(failures)+"; run targeted component diagnosis. Cached evidence, not a new inference test."))
    except (OSError,ValueError): pass
    from vision_diagnostics import rows as vision_rows
    rows.extend(vision_rows(root))
    counts = {s: sum(1 for x in rows if x["status"] == s) for s in ("PASS", "WARN", "FAIL")}
    result = {
        "version": VERSION,
        "platform": platform.platform(),
        "counts": counts,
        "rows": rows,
        "registry": reg,
        "science_functional": science,
        "workload_support_not_inference_guarantees": support_matrix(),
        "coverage": "Structural/live state plus lightweight science checks. Media inference, physical GPU compatibility, profile security and mission endurance are not proven by this report.",
    }

    from maintenance_reports import save
    report_text="\n".join(f"[{x['status']}] {x['label']}: {x['detail']}" for x in rows)+f"\n\n{counts}\n"
    save(root,"system_test",report_text,result,1 if counts["FAIL"] else 0)
    if ns.json:
        print(json.dumps(result, indent=2))
    else:
        print("=" * 76)
        print(f"PortableAI v{VERSION} System Test")
        print("=" * 76)
        for x in rows:
            print(f"[{x['status']:<4}] {x['label']}")
            if x["detail"]:
                print("       " + str(x["detail"]).replace("\n", "\n       "))
        print("-" * 76)
        print(f"PASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}")
        print("Coverage: structural/live state plus lightweight science checks. Media model inference and GPU science are not run here. CUDA/OpenCL plugin visibility, native image device probes and AMD installation receipts do not prove physical Radeon compatibility.")

    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
