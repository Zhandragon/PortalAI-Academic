"""Portable hardware/model selection. Standard library only; no host installs.

Memory estimates are admission limits, not promises of model performance.
GPU support is established by probing the selected bundled runtime.
"""
from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import ctypes
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

GIB = 1024 ** 3
ROOT = Path(__file__).resolve().parents[1]
SMALL_VISION_RUNTIME_REVISION = '2026-10-16-huihui-min1024'
SMALL_VISION_IDS = frozenset(('qwen-vl2-q4', 'qwen-vl2-abliterated-q4',
                              'qwen-vl4-q4', 'qwen-vl4-abliterated-q4'))


def small_vision_settings(model: dict) -> dict:
    """Minimum image quality and conservative CPU encoder admission, not a benchmark."""
    if model.get('id') not in SMALL_VISION_IDS or not model.get('projector'):
        return {}
    if model.get('id') == 'qwen-vl2-abliterated-q4' and (
            Path(str(model.get('path', '')).replace('\\', '/')).name ==
            'Qwen3-VL-2B-Instruct-abliterated.Q4_K_M.gguf' or
            Path(str(model.get('projector', '')).replace('\\', '/')).name ==
            'Qwen3-VL-2B-Instruct-abliterated.mmproj-f16.gguf'):
        raise RuntimeError('The previous 2B Abliterated vision pair failed image acceptance. '
                           'Install and configure the verified Huihui replacement; attachments were preserved.')
    requested = int(model.get('image_min_tokens', 1024))
    if not 0 <= requested <= 8192:
        raise ValueError('Small vision image_min_tokens must be between 0 and 8192')
    minimum = max(1024, requested)
    return {'image_min_tokens': minimum,
            'min_context_tokens': max(4096, minimum * 2 + 1024),
            # Projectors run on CPU (--no-mmproj-offload). This is additional
            # RAM headroom, separate from weights, KV/compute and OS reserves.
            'image_buffer_bytes': int(GIB * .5 * minimum / 1024)}


def small_vision_command_options(model: dict) -> list[str]:
    settings = small_vision_settings(model)
    return ['--image-min-tokens', str(settings['image_min_tokens'])] if settings else []


def portable_path(root: Path, relative: str) -> Path:
    # Accept config written on either OS, and reject drive-qualified/escaping paths.
    if re.match(r"^[A-Za-z]:", relative):
        raise ValueError("Configuration paths must be relative to the SSD")
    p = (root / relative.replace("\\", "/")).resolve()
    if not p.is_relative_to(root.resolve()):
        raise ValueError("Configuration path escapes the portable root")
    return p


def load_policy(root: Path = ROOT) -> dict:
    policy = json.loads((root / "Agent/hardware_profiles.json").read_text(encoding="utf-8"))
    if sys.platform == "darwin":
        path = root / "Maintenance/Imports/macos-storage-policy.json"
        try:
            mac_policy = json.loads(path.read_text(encoding="utf-8"))
            storage = mac_policy["storage"]
            minimum = int(storage["minimum_free_gib"])
            fraction = float(storage["minimum_free_fraction"])
            output = int(storage["output_reserve_gib"])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("The macOS storage reserve policy is missing or invalid") from exc
        if minimum < 1 or output < 0 or not 0 < fraction < 1:
            raise RuntimeError("The macOS storage reserve policy is outside supported limits")
        policy["storage"] = {"minimum_free_gib": minimum,
                             "minimum_free_fraction": fraction,
                             "output_reserve_gib": output}
    from academic_policy import enforce_policy
    return enforce_policy(policy)


def load_effective_policy(root: Path = ROOT) -> dict:
    from model_preferences import effective
    return effective(root, load_policy(root))


def model_variant(model):
    return 'uncensored' if model.get('variant') in ('abliterated', 'uncensored') else 'standard'


def automatic_models(policy):
    from academic_policy import enforce_policy
    policy = enforce_policy(policy)
    preference = policy.get('variant_preference', 'standard')
    if preference not in ('standard', 'uncensored'):
        raise ValueError('Unknown model variant preference')
    return [m for m in policy['models'] if
            (m.get('automatic', True) is not False and model_variant(m) == 'standard') or
            (preference == 'uncensored' and m.get('automatic_uncensored') is True)]


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def portable_env(root: Path = ROOT, *, include_account_unlock: bool = False, before_login: bool = False) -> dict:
    env = os.environ.copy()
    if not include_account_unlock or before_login:
        env.pop('PORTALAI_ACCOUNT_UNLOCK', None)
    env.pop('PORTALAI_CONNECTION_UNLOCK', None)
    env.pop('PORTALAI_CONNECTION_INPUT', None)
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
               HF_HUB_DISABLE_TELEMETRY="1", HF_HUB_DISABLE_IMPLICIT_TOKEN="1")
    for key, rel in {"HF_HOME": "Cache/huggingface", "XDG_CACHE_HOME": "Cache",
                     "TORCH_HOME": "Cache/torch", "PIP_CACHE_DIR": "Cache/pip",
                     "TEMP": "Cache/tmp", "TMP": "Cache/tmp", "TMPDIR": "Cache/tmp"}.items():
        from profile_paths import is_private, private_path
        if before_login and key in ('TEMP', 'TMP', 'TMPDIR'):
            p = root / 'Cache/Bootstrap'
        else:
            p = private_path(root, rel) if is_private(rel) else root / rel
        p.mkdir(parents=True, exist_ok=True)
        env[key] = str(p)
    return env


def run_probe(args: list[str], timeout: int = 15) -> str:
    try:
        cwd=None
        if os.name!='nt':
            from platform_runtime import linux_elf_command
            args,cwd=linux_elf_command(ROOT,args)
        cp = subprocess.run(args, cwd=cwd, capture_output=True, text=True, errors="replace",
                            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return cp.stdout + "\n" + cp.stderr if cp.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _windows_memory_status():
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
            (n, ctypes.c_ulonglong) for n in ("total", "available", "page_total", "page_available",
                                             "virtual_total", "virtual_available", "extended")]
    m = Memory()
    m.length = ctypes.sizeof(m)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise OSError("Unable to read available Windows memory and commit headroom")
    return m


def memory_info() -> tuple[int, int]:
    if os.name == "nt":
        m = _windows_memory_status()
        return m.total, m.available
    if sys.platform == "darwin":
        packages = ROOT / "Runtime/MacPackages/gui"
        if packages.is_dir() and str(packages) not in sys.path:
            sys.path.insert(0, str(packages))
        try:
            import psutil
            info = psutil.virtual_memory()
            return int(info.total), int(info.available)
        except Exception as exc:
            raise RuntimeError("macOS memory checks need the bundled psutil runtime") from exc
    data = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        k, v = line.split(":", 1)
        data[k] = int(v.strip().split()[0]) * 1024
    return data["MemTotal"], data.get("MemAvailable", data["MemFree"])


def detect_hardware() -> dict:
    total, available = memory_info()
    gpus = []
    raw = run_probe(["nvidia-smi", "--query-gpu=index,name,memory.total,memory.free", "--format=csv,noheader,nounits"])
    for line in raw.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 4:
            try:
                gpus.append({"index": int(parts[0]), "name": parts[1], "backend": "cuda",
                             "total_bytes": int(parts[2]) * 1024**2, "free_bytes": int(parts[3]) * 1024**2})
            except ValueError:
                pass
    result = {"system": platform.system(), "machine": platform.machine(), "cpu_count": os.cpu_count() or 1,
              "ram_total_bytes": total, "ram_available_bytes": available, "gpus": gpus}
    if os.name == 'nt':
        status = _windows_memory_status()
        result.update(commit_total_bytes=int(status.page_total), commit_available_bytes=int(status.page_available))
    return result


def storage_budget(root: Path = ROOT, policy: dict | None = None, additional_bytes: int = 0,
                   for_outputs: bool = False) -> dict:
    cfg = (policy or load_policy(root))["storage"]
    usage = shutil.disk_usage(root)
    floor = max(int(float(cfg["minimum_free_gib"]) * GIB),
                int(float(cfg["minimum_free_fraction"]) * usage.total))
    output = max(0, int(float(cfg["output_reserve_gib"]) * GIB))
    if floor < 0 or not 0 <= float(cfg["minimum_free_fraction"]) < 1 or additional_bytes < 0:
        raise ValueError("Invalid storage reserve or size")
    reserve = floor + (0 if for_outputs else output)
    return {"total_bytes": usage.total, "free_bytes": usage.free, "minimum_free_bytes": floor,
            "output_reserve_bytes": output, "download_budget_bytes": max(0, usage.free - floor - output),
            "allowed": usage.free - additional_bytes >= reserve}


def require_space(root: Path, additional_bytes: int = 0, for_outputs: bool = False) -> dict:
    result = storage_budget(root, additional_bytes=additional_bytes, for_outputs=for_outputs)
    if not result["allowed"]:
        raise RuntimeError("SSD reserve would be crossed; move outputs or free space before continuing")
    return result


def runtime_candidates(root: Path, system: str) -> dict[str, Path]:
    if system == "Windows":
        return {"cuda": root / "LLM/llamacpp/llama-server.exe",
                "vulkan": root / "LLM/backends/windows-vulkan/llama-server.exe",
                "cpu": root / "LLM/backends/windows-cpu/llama-server.exe"}
    if system == "Linux":
        return {b: root / f"LLM/backends/linux-{b}/llama-server" for b in ("cuda", "vulkan", "cpu")}
    if system == "Darwin":
        server = root / "LLM/backends/macos-metal/bin/llama-server"
        return {"metal": server, "cpu": server}
    raise RuntimeError(f"Unsupported OS: {system}. Bundled backends target Windows/Linux x86-64 and macOS x64/arm64")


def runtime_installation_issues(exe: Path) -> list[str]:
    """Check the Windows split-server runtime before invoking its entry point.

    Older monolithic servers and Unix shared-library layouts are left to the
    bounded runtime probe. This check reads only bundled executable metadata.
    """
    try:
        if not exe.is_file():
            return [f"Missing runtime entry point: {exe}"]
        if exe.suffix.lower() != '.exe':
            return []
        folder = exe.parent
        split = (0 < exe.stat().st_size < 65536 or
                 (folder / 'llama-server-impl.dll').is_file())
        if not split:
            return []
        required = ('llama-server-impl.dll', 'llama.dll', 'llama-common.dll',
                    'ggml.dll', 'ggml-base.dll', 'mtmd.dll')
        return [f"Missing or empty runtime library: {folder / name}" for name in required
                if not (folder / name).is_file() or (folder / name).stat().st_size == 0]
    except OSError as exc:
        return [f"Cannot inspect runtime {exe}: {exc}"]


def choose_backend(root: Path, hardware: dict, requested: str = "auto", probe: bool = True) -> dict:
    machine = hardware["machine"].lower()
    is_mac = hardware.get("system") == "Darwin"
    if machine not in (("amd64", "x86_64", "arm64", "aarch64") if is_mac else ("amd64", "x86_64")):
        raise RuntimeError("This bundle currently contains x86-64 runtimes, plus macOS arm64 support")
    candidates = runtime_candidates(root, hardware["system"])
    order = [requested] if requested != "auto" else (["metal", "cpu"] if is_mac else ["cuda", "vulkan", "cpu"])
    diagnostics = []
    for backend in order:
        exe = candidates.get(backend)
        try:
            present = exe is not None and exe.is_file()
        except OSError:
            present = False
        if not present:
            diagnostics.append(f"{backend}: runtime entry point missing or inaccessible: {exe}")
            continue
        issues = runtime_installation_issues(exe)
        if issues:
            diagnostics.extend(issues)
            continue
        devices = run_probe([str(exe), "--list-devices"]) if probe else ""
        if backend == "cuda":
            for gpu in sorted(hardware["gpus"], key=lambda g: g["free_bytes"], reverse=True):
                device = f"CUDA{gpu['index']}"
                if not probe or re.search(r"\b" + device + r":", devices):
                    return {"backend": backend, "executable": str(exe), "device": device, "gpu": gpu,
                            "diagnostics": diagnostics}
        elif backend == "vulkan":
            # llama.cpp reports usable heap capacity; do not trust Win32's truncated AdapterRAM.
            matches = re.findall(r"(Vulkan\d+):\s*(.*?)\s*\((\d+) MiB,\s*(\d+) MiB free\)", devices)
            if matches:
                dev, name, total, free = max(matches, key=lambda m: int(m[3]))
                # Vulkan heap size can include shared system RAM, especially on laptops.
                # Only a matching dedicated NVIDIA probe establishes separate VRAM here.
                dedicated = any(g["name"].strip() == name.strip() for g in hardware["gpus"])
                return {"backend": backend, "executable": str(exe), "device": dev, "diagnostics": diagnostics,
                        "gpu": {"name": name, "total_bytes": int(total)*1024**2, "free_bytes": int(free)*1024**2,
                                "shared_memory": not dedicated}}
        elif backend == "metal":
            devices_found = re.findall(r"^(Metal\d+):", devices, flags=re.M)
            if devices_found or not probe:
                return {"backend": backend, "executable": str(exe), "diagnostics": diagnostics,
                        "device": devices_found[0] if devices_found else "Metal0",
                        "gpu": {"name": "Apple Metal", "total_bytes": hardware["ram_total_bytes"],
                                "free_bytes": hardware["ram_available_bytes"], "shared_memory": True}}
        elif backend == "cpu" and (not probe or run_probe([str(exe), "--version"])):
            return {"backend": backend, "executable": str(exe), "device": "none", "gpu": None,
                    "diagnostics": diagnostics}
        diagnostics.append(f"{backend}: installed, but no usable device/runtime probe succeeded")
    raise RuntimeError(f"No working bundled {requested} backend for {hardware['system']}; " + '; '.join(diagnostics))


def select_model(root: Path, hardware: dict, backend: dict, policy: dict) -> dict:
    from academic_policy import enforce_policy
    policy = enforce_policy(policy)
    selection = policy.get("selection", "auto")
    requested_context = int(policy.get("context_tokens", 8192))
    if not 512 <= requested_context <= 32768:
        raise ValueError("context_tokens must be between 512 and 32768")
    # Leave memory for the OS and apps; a single GPU is budgeted, never the sum of GPUs.
    ram_budget = max(0, hardware["ram_available_bytes"] - 2 * GIB)
    gpu = backend.get("gpu")
    gpu_budget = max(0, gpu["free_bytes"] - 2 * GIB) if gpu else 0
    accepted, rejected = [], []
    for model in policy["models"]:
        if selection == "auto" and model not in automatic_models(policy):
            rejected.append({"id": model["id"], "reason": "explicit model selection required"})
            continue
        if selection != "auto" and model["id"] != selection:
            continue
        try:
            image_settings = small_vision_settings(model)
        except RuntimeError as exc:
            rejected.append({'id': model['id'], 'reason': str(exc)})
            continue
        path = portable_path(root, model["path"])
        projector = portable_path(root, model["projector"]) if model.get("projector") else None
        if not path.is_file() or (projector and not projector.is_file()):
            rejected.append({"id": model["id"], "reason": "model or projector not installed"})
            continue
        weights = path.stat().st_size
        context = min(requested_context, int(model.get("max_context_tokens", 32768)))
        contexts = [context]
        if selection == "auto" and model.get("cpu_auto", False):
            contexts.extend(c for c in (4096, 2048) if c < context)
        reason = "insufficient available RAM/VRAM with reserves"
        for context in contexts:
            if context < image_settings.get('min_context_tokens', 0):
                reason = ('Small vision image tokens require at least ' +
                          str(image_settings['min_context_tokens']) + ' context tokens')
                continue
            # Account for context/compute buffers conservatively; hybrid architectures vary.
            overhead = int((float(model.get("buffer_base_gib", 1.5)) + context / 8192 * float(model.get("buffer_per_8192_gib", 1))) * GIB)
            layers = int(model["layers"])
            offload = min(layers + 1, max(0, math.floor((gpu_budget - overhead) / max(1, weights) * (layers + 1))))
            gpu_weights = weights * offload / (layers + 1)
            ram_needed = int(weights - gpu_weights + overhead + (projector.stat().st_size if projector else 0)
                             + image_settings.get('image_buffer_bytes', 0))
            if gpu and gpu.get("shared_memory", False):
                ram_needed += int(gpu_weights)
            if ram_needed > ram_budget: continue
            if selection == "auto" and offload < layers + 1 and not model.get("cpu_auto", False):
                reason = "large model requires full GPU fit in automatic mode; manual selection permits partial offload"
                continue
            accepted.append({**model, **image_settings, "absolute_path": str(path), "absolute_projector": str(projector) if projector else None,
                             "gpu_layers": offload, "context_tokens": context, "estimated_ram_bytes": ram_needed,
                             "estimated_gpu_bytes": int(gpu_weights + overhead) if offload else 0})
            break
        else:
            rejected.append({"id": model["id"], "reason": reason})
    if not accepted:
        details = '; '.join(backend.get('diagnostics', []))
        raise RuntimeError("No installed model fits the current memory budget: " + json.dumps(rejected) +
                           f". Selected backend: {backend.get('backend', 'unspecified')}." +
                           (" Runtime diagnostics: " + details if details else ""))
    preferred = policy.get('variant_preference', 'standard')
    result = max(accepted, key=lambda m: (model_variant(m) == preferred, m.get("priority", 0)))
    if selection == 'auto':
        result['variant_reason'] = ('Saved ' + preferred + ' preference' if model_variant(result) == preferred
                                    else 'Standard fallback: no installed uncensored model fits current hardware')
    return {"selected": result, "rejected": rejected}


def build_plan(root: Path = ROOT, hardware: dict | None = None, policy: dict | None = None,
               probe: bool = True) -> dict:
    root = root.resolve()
    hw = hardware or detect_hardware()
    cfg = policy if policy is not None else load_effective_policy(root)
    backend = choose_backend(root, hw, cfg.get("backend", "auto"), probe)
    selection = select_model(root, hw, backend, cfg)
    m = selection["selected"]
    command = [backend["executable"], "-m", m["absolute_path"], "-ngl", str(m["gpu_layers"]),
               "-c", str(m["context_tokens"]), "--parallel", "1", "--jinja", "--metrics",
               "--sleep-idle-seconds", "300", "--host", "127.0.0.1", "--port", str(_instance_port('qwen'))]
    command += ["--device", backend["device"]]
    if m["absolute_projector"]:
        command += ["--mmproj", m["absolute_projector"], "--no-mmproj-offload"]
        command += small_vision_command_options(m)
    return {"hardware": hw, "backend": backend, "model": m, "command": command,
            "storage": storage_budget(root, cfg), "rejected": selection["rejected"]}


def tool_plan(name: str, hardware: dict | None = None) -> dict:
    hw = hardware or detect_hardware()
    cuda = next((g.get("total_bytes", 0) for g in hw["gpus"]
                 if g.get("index", 0) == 0 and g.get("backend", "cuda") == "cuda"), 0)
    if name == "comfyui":
        if not cuda:
            amd = hw.get("amd_gpu", {})
            if hardware is None and hw.get("system") in ("Windows","Linux"):
                if hw.get('system')=='Linux':
                    from linux_ml import probe
                else:
                    from amd_runtime import probe
                amd = probe()
            if amd.get("available") and amd.get("compute_ok"):
                if hw["ram_available_bytes"] < (12 if amd.get("shared_memory", True) else 6)*GIB or amd.get("free_bytes", 0) < 3*GIB:
                    raise RuntimeError("AMD ComfyUI needs 3 GiB free GPU memory and 6 GiB available RAM (12 GiB for shared memory) after handoff")
                return {"backend": "rocm", "args": ["--lowvram", "--disable-xformers", "--use-split-cross-attention",
                        "--disable-triton-backend", "--disable-comfy-compiler", "--disable-async-offload",
                        "--reserve-vram", "2", "--cache-none"],
                        "warning": "ROCm compute probe passed; individual workflows still require memory admission and Radeon validation"}
            return {"backend": "cpu", "args": ["--cpu"], "warning": "CPU image/video generation may be very slow"}
        args = ["--lowvram"] if cuda < 12 * GIB else []
        warning = "GPU lease and LLM handoff required"
        if hw.get('system') == 'Windows':
            # CUDA allocations and host staging can exhaust Windows commit while
            # physical RAM still looks plentiful. Budget after the LLM handoff;
            # leave 6 GiB for runtime startup, transfer buffers and other apps.
            # The installed DynamicVRAM loader ignores --lowvram, so use its
            # explicit headroom control rather than changing frames or quality.
            commit = int(hw.get('commit_available_bytes', hw['ram_available_bytes']))
            budget = max(0, commit - 6 * GIB)
            headroom = max(0, math.ceil((cuda - budget) / GIB))
            if headroom:
                if budget < 4 * GIB:
                    raise RuntimeError('ComfyUI conservative Windows commit admission leaves less than 4 GiB for CUDA '
                                       'after reserving 6 GiB for startup and host buffers. '
                                       'Close memory-heavy applications or review virtual memory on a permanent drive; '
                                       'free RAM alone does not measure this limit.')
                args += ['--disable-pinned-memory', '--vram-headroom', str(headroom)]
                warning += f'; Windows commit-aware loading reserves {headroom} GiB GPU headroom and disables the pinned host cache'
        return {"backend": "cuda", "args": args, "warning": warning}
    if name == "science":
        return {"backend": "cpu", "args": [], "warning": "OpenMM CUDA/OpenCL remain explicit opt-ins through the existing lease"}
    if name == "acestep":
        return {"backend": "cuda" if cuda >= 8*GIB else "unavailable", "args": [],
                "warning": "Bundled ACE-Step is validated only for Windows/CUDA with at least 8 GiB VRAM"}
    raise ValueError("Unknown workload")
