"""Mission access boundaries shared by execution, the GUI and readiness reports.

These modes apply to persistent missions, not ordinary chat tools. Only VM shell
actions are OS-isolated; the model and controller always remain on the host.
"""
from pathlib import Path
import time
import uuid

from runtime_policy import ROOT, atomic_json, require_space
from profile_paths import private_path

MODES = ("observe", "vm", "full")
PROFILES = {
    "observe": {
        "label": "Observe · no shell",
        "description": "Source/documentation reads, installation diagnostics and notes. No shell commands. A capability restriction, not an OS sandbox.",
        "shell_location": None, "os_isolation": False,
    },
    "vm": {
        "label": "VM · isolated shell",
        "description": "Hardware-backed offline Linux shell as an unprivileged guest. 8 MiB persistent workspace; no host mounts, network, GPU or host tools. Model/controller stay on the host.",
        "shell_location": "guest", "os_isolation": "shell actions only",
    },
    "full": {
        "label": "Full · host access",
        "description": "Unrestricted host commands with your current Windows/Linux user permissions, including files and network. No automatic administrator elevation and no OS sandbox.",
        "shell_location": "host", "os_isolation": False,
    },
}
COMMON = ("note(text)", "remember(key,text)", "recall(query)", "history(start,count)", "previous_run(start,count)", "complete(text)", "pause(text)", "wait(seconds,text)", "subtask(objective)")
ACTIONS = {
    "observe": ("read_file(path)", "diagnostics()", "message(target,text)", "inbox(after)", *COMMON),
    "vm": ("shell(command)", *COMMON),
    "full": ("read_file(path)", "diagnostics()", "message(target,text)", "inbox(after)", "web(operation,parameters)", *COMMON, "shell(command)", "account(profile,operation,parameters)"),
}


def profile(mode):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Unknown mission execution mode")
    return {"id": mode, **PROFILES[mode]}


def allowed_actions(mode):
    profile(mode)
    return ACTIONS[mode]


def authorize_action(mode, action):
    allowed = {signature.split("(", 1)[0] for signature in allowed_actions(mode)}
    if not isinstance(action, str) or action not in allowed:
        raise PermissionError(f"Action {action!r} is not available in {mode} mode")


def readiness(root=ROOT, probe=False):
    """Inspect VM prerequisites; optionally boot a fresh, bounded offline guest.

    Never installs Windows features, elevates, starts a host shell fallback or
    passes host credentials. An unavailable VM stays unavailable.
    """
    from vm_runner import preflight, run_command
    root = Path(root).resolve()
    result = {
        "created_at": time.time(), "scope": "Persistent missions only; regular chat tools run on the host",
        "modes": [profile(mode) for mode in MODES],
        "vm": {"ready": False, "probe_requested": bool(probe), "guest_executed": False},
        "limits": ["The host model/controller and normal chat are outside the VM.",
                   "The guest has BusyBox shell tools; host multimedia/science packages and accounts are unavailable.",
                   "Windows requires firmware virtualization and Windows Hypervisor Platform, with PortalAI non-elevated.",
                   "The Linux host VM runtime is not provisioned or validated yet."]}
    try:
        result["vm"]["preflight"] = preflight(root)
        if probe:
            folder = private_path(root,'Data/VMTests')/("readiness-"+uuid.uuid4().hex)
            # Results travel through the existing data-only VM transport.
            command = "test \"$(id -u)\" = 1000 && test \"$(ls /sys/class/net)\" = lo && test ! -e /mnt/c && test ! -e /mnt/d && printf 'PORTAL_VM_READY\\n'"
            evidence = run_command(command, folder, root=root)
            result["vm"].update(evidence=evidence, state_folder=folder.relative_to(root).as_posix(), guest_executed=True)
            if evidence["exit_code"] != 0 or "PORTAL_VM_READY" not in evidence["output"]:
                raise RuntimeError("The guest readiness probe did not pass")
        result["vm"].update(ready=True, assurance="live guest probe" if probe else "prerequisites checked; guest not booted")
    except Exception as exc:
        result["vm"].update(ready=False, error=f"{type(exc).__name__}: {exc}")
    return result


def check_and_save(root=ROOT, probe=False):
    root = Path(root).resolve()
    require_space(root, for_outputs=True)
    result = readiness(root, probe)
    atomic_json(root/"Maintenance/Reports/execution-modes.json", result)
    return result
