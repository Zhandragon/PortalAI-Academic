"""Portable SD1.5 images on Windows Vulkan or CPU; no Python ML dependencies."""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path, capture, ProfileLocked
from media_paths import media_runtime, media_reference
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import time
import uuid
import zlib

from runtime_policy import ROOT, GIB, atomic_json, portable_env, portable_path, require_space, run_probe
from runtime_policy import memory_info
from mission_runner import process_lock
from mission_supervisor import WorkerJob
from platform_runtime import python_path, worker_process_options

REVISION = "f89d9b13d730eabeede7314ce49dacd18d3c90c2"


def executable(root, backend):
    if backend not in ("vulkan", "cpu"): raise ValueError("Unknown image backend")
    platform_name='windows' if os.name=='nt' else 'linux'
    folder = root/("Runtime/StableDiffusion/"+platform_name+'-'+backend)
    receipt = json.loads((root/("Maintenance/Imports/sdcpp-"+platform_name+'-'+backend+".json")).read_text(encoding="utf-8"))
    if receipt.get("revision") != REVISION or not receipt.get("verified") or not receipt.get("installed_files"):
        raise RuntimeError("Image runtime has no matching verified import receipt")
    # Small runtime, so verify executables/DLLs before loading them, not model weights per job.
    for row in receipt["installed_files"]:
        path = portable_path(folder, row["path"])
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        if digest != row["sha256"]:
            raise RuntimeError("Image runtime integrity check failed: "+row["path"])
    exe = folder/("sd-cli.exe" if os.name=='nt' else 'sd-cli')
    if not exe.is_file(): raise RuntimeError("Image CLI is missing")
    return exe


def engine_plan(root, hw, requested="auto"):
    """Called after handoff. Shared GPU memory is also charged to available RAM."""
    if hw["system"] not in ("Windows","Linux") or hw["machine"].lower() not in ("amd64", "x86_64"):
        raise RuntimeError("The portable SD1.5 native image engine requires Windows/Linux x64")
    ram = hw["ram_available_bytes"]
    reasons = []
    if requested in ("auto", "sdcpp-vulkan"):
        try:
            exe = executable(root, "vulkan")
            probe = run_probe([str(exe), "--list-devices"])
            devices = re.findall(r"^(Vulkan\d+)\t([^\r\n]+)", probe, re.M)
            if not devices: raise RuntimeError("No working Vulkan device/driver")
            # Use the first device consistently, never sum separate adapters' budgets.
            device, name = devices[0]
            uma = re.search(r"^ggml_vulkan:\s*"+device[6:]+r"\s*=.*?\|\s*uma:\s*(\d)", probe, re.M)
            shared = not uma or uma[1] != "0"
            if ram < (10 if shared else 8)*GIB:
                raise RuntimeError("Vulkan SD1.5 needs 10 GiB available shared RAM, or 8 GiB with a dedicated GPU")
            # Runtime auto-fit handles live availability/segmentation. This is a
            # managed allocation budget, not an OS quota for driver/display memory.
            return {"engine": "sdcpp-vulkan", "backend": "vulkan", "device": device.lower(),
                    "device_name": name, "shared_memory": shared, "executable": str(exe),
                    "max_vram_gib": 3 if shared else 4,
                    "reason": "SD1.5 with automatic weight offloading; driver allocations are outside the managed budget"}
        except (OSError, ValueError, RuntimeError) as exc:
            if requested == "sdcpp-vulkan": raise RuntimeError(str(exc)) from exc
            reasons.append(str(exc))
    if ram < 8*GIB: raise RuntimeError("CPU SD1.5 needs at least 8 GiB available RAM after chat handoff")
    exe = executable(root, "cpu")
    if "CPU\t" not in run_probe([str(exe), "--list-devices"]):
        raise RuntimeError("Portable CPU image engine could not start")
    return {"engine": "sdcpp-cpu", "backend": "cpu", "device": "cpu", "executable": str(exe),
            "reason": "CPU SD1.5" + ("; Vulkan fallback: "+"; ".join(reasons) if reasons else "")}


def command(plan, root, prompt, negative, seed, output, steps=20):
    from sd15_variants import checkpoint
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000:
        raise ValueError("Image prompt must contain 1-16000 characters")
    if len(negative or "") > 16000: raise ValueError("Negative prompt exceeds 16000 characters")
    if "<lora:" in prompt.lower() or "<lora:" in (negative or "").lower():
        raise ValueError("This SD1.5 profile has no configured compatible LoRAs; do not use FLUX/Wan LoRAs with it")
    if not 1 <= steps <= 50: raise ValueError("Image steps must be between 1 and 50")
    if not 0 <= seed < 2**63: raise ValueError("Image seed must be between 0 and 2**63-1")
    backend = plan["device"]
    if plan["backend"] == "vulkan": backend = "te=cpu,vae=cpu,diffusion="+backend
    args = [plan["executable"], "-m", str(checkpoint(root, plan.get('model_variant', 'standard'))), "--backend", backend,
            "--auto-fit", "on", "--type", "f16", "--mmap", "-t", str(min(8, os.cpu_count() or 1)),
            "-p", prompt, "-n", negative or "", "-W", str(plan["width"]), "-H", str(plan["height"]),
            "--steps", str(steps), "--seed", str(seed), "--sampling-method", "euler", "-o", str(output)]
    if plan["backend"] == "vulkan":
        args += ["--max-vram", f"{plan['device']}={plan['max_vram_gib']}"]
    return args


def validate_png(path, width, height):
    """Bounded PNG integrity check, including compressed pixel stream and CRCs."""
    if path.stat().st_size > 16*1024**2: raise RuntimeError("Image output exceeds limit")
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n": raise RuntimeError("Invalid image output")
    pos = 8; packed = bytearray(); header = None; ended = False
    while pos+12 <= len(data):
        length = struct.unpack(">I", data[pos:pos+4])[0]
        kind = data[pos+4:pos+8]; chunk = data[pos+8:pos+8+length]
        if pos+12+length > len(data): raise RuntimeError("Truncated image output")
        crc = struct.unpack(">I", data[pos+8+length:pos+12+length])[0]
        if zlib.crc32(kind+chunk) & 0xffffffff != crc: raise RuntimeError("Corrupt image output")
        if kind == b"IHDR": header = struct.unpack(">IIBBBBB", chunk)
        if kind == b"IDAT": packed.extend(chunk)
        if kind == b"IEND": ended = True; break
        pos += 12+length
    if not ended or not header or header[:2] != (width, height) or header[2:] not in ((8, 2, 0, 0, 0), (8, 6, 0, 0, 0)):
        raise RuntimeError("Image output has unexpected dimensions/format")
    expected = height*(1+width*(3 if header[3] == 2 else 4))
    decoder = zlib.decompressobj(); pixels = decoder.decompress(packed, expected+1)
    if len(pixels) != expected or not decoder.eof: raise RuntimeError("Incomplete image pixels")


def cancel(root=ROOT):
    active = media_runtime(Path(root)) / "sdcpp-active.json"
    try:
        token = json.loads(active.read_text())["token"]
        if not re.fullmatch(r"[0-9a-f]{32}", token): raise ValueError("Invalid active image token")
        (active.parent/("sdcpp-"+token+".stop")).touch()
        return {"requested": True}
    except FileNotFoundError: return {"requested": False, "reason": "No active native image"}


def cleanup_abandoned(root):
    """Only while holding sdcpp.lock; never scan or delete arbitrary outputs."""
    runtime = media_runtime(root)
    active = runtime/"sdcpp-active.json"
    if not active.exists(): return
    token = json.loads(active.read_text(encoding="utf-8"))["token"]
    if not re.fullmatch(r"[0-9a-f]{32}", token): raise ValueError("Invalid abandoned image token; review required")
    (private_path(root, "Outputs/Images")/("sd15_"+token[:12]+".part.png")).unlink(missing_ok=True)
    (private_path(root, "Outputs/Videos")/("wan13_"+token[:12]+".part.avi")).unlink(missing_ok=True)
    (private_path(root, "Outputs/Videos")/("wan13_"+token[:12]+".part.mp4")).unlink(missing_ok=True)
    (private_path(root, "Outputs/SFX")/("mmaudio_"+token[:12]+".part.flac")).unlink(missing_ok=True)
    (private_path(root, "Outputs/Music")/("acestep_"+token[:12]+".part.flac")).unlink(missing_ok=True)
    (private_path(root, "Outputs/Music")/("musicgen_"+token[:12]+".part.flac")).unlink(missing_ok=True)
    (private_path(root, "Outputs/Videos/MuseTalk")/("musetalk_"+token[:12]+".part.mp4")).unlink(missing_ok=True)
    for suffix in (".gate", ".json", ".stop", ".log"):
        (runtime/("sdcpp-"+token+suffix)).unlink(missing_ok=True)
    active.unlink()


def generate(plan, prompt, negative=None, seed=52, root=ROOT, steps=20, timeout=900):
    result = run_generation(plan, lambda part: command(plan, Path(root), prompt, negative, seed, part, steps),
                            lambda part: validate_png(part, plan['width'], plan['height']), root=root, timeout=timeout)
    return {**result, 'seed': seed, 'steps': steps}


def run_generation(plan, build_command, validate, *, root=ROOT, timeout=900, kind='image', check_request=None):
    """One contained native job, shared by the small image and video profiles."""
    if kind not in ('image', 'video', 'sfx', 'music', 'musetalk'): raise ValueError('Unknown native output type')
    root = Path(root).resolve()
    context = capture(root)
    def check_profile():
        if check_request is not None: check_request()
        if capture(root) != context:
            raise ProfileLocked('The native media generation login ended before publication')
    runtime = media_runtime(root); runtime.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    folder, prefix, extension = {'image': ('Images', 'sd15_', '.png'),
        'video': ('Videos', 'wan13_', '.mp4'), 'sfx': ('SFX', 'mmaudio_', '.flac'),
        'music': ('Music', 'acestep_', '.flac'), 'musetalk': ('Videos/MuseTalk', 'musetalk_', '.mp4')}[kind]
    if kind == 'music' and plan['engine'] == 'musicgen-cpu': prefix = 'musicgen_'
    out = private_path(root, 'Outputs', context=context)/folder/(prefix+token[:12]+extension)
    part = out.with_name(out.stem+'.part'+extension)
    gate, request, stop, logpath = [runtime/("sdcpp-"+token+s) for s in (".gate", ".json", ".stop", ".log")]
    active = runtime/"sdcpp-active.json"
    proc = job = None
    published = False
    output_identity = None
    with process_lock(runtime/"sdcpp.lock"):
        check_profile()
        cleanup_abandoned(root)
        require_space(root, (64 if kind == 'image' else 256)*1024**2, for_outputs=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        argv = build_command(part)
        worker_env=portable_env(root)
        if os.name!='nt' and plan.get('engine') not in ('sdcpp-cpu','sdcpp-vulkan'):
            worker_env['PORTALAI_TORCH_BACKEND']='cpu' if plan.get('cpu_validation') else plan.get('backend','cpu')
        request_body = {('commands' if isinstance(argv[0], list) else 'command'): argv, 'gate': str(gate)}
        try:
            atomic_json(request, request_body)
            atomic_json(active, {"token": token, "backend": plan["backend"], "kind": kind, "started": time.time()})
            with logpath.open("wb") as log:
                proc = subprocess.Popen([str(python_path(root)), "-B", "-I",
                    str(root/"Agent/sdcpp_worker.py"), str(request)], cwd=root, env=worker_env,
                    stdin=subprocess.DEVNULL, stdout=log, stderr=log, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
                    **worker_process_options())
                job = WorkerJob(proc)
                if plan.get('max_memory_bytes'): job.limit_memory(plan['max_memory_bytes'])
                atomic_json(request, {**request_body, "worker_pid": proc.pid})
                gate.touch(); deadline = time.monotonic()+timeout
                while proc.poll() is None:
                    check_profile()
                    job.check()
                    if stop.exists(): raise RuntimeError("Native image generation stopped")
                    if time.monotonic() > deadline: raise TimeoutError("Native image generation timed out")
                    if logpath.stat().st_size > 4*1024**2: raise RuntimeError("Image log limit exceeded")
                    if plan.get('min_free_ram_bytes') and memory_info()[1] < plan['min_free_ram_bytes']:
                        raise RuntimeError('Generation stopped to preserve the configured free-RAM reserve')
                    require_space(root, for_outputs=True); time.sleep(.1)
            check_profile()
            if stop.exists(): raise RuntimeError("Native image generation stopped")
            if proc.returncode:
                raise RuntimeError("Native image engine failed: "+logpath.read_text(encoding="utf-8", errors="replace")[-2000:])
            validate(part)
            check_profile()
            if out.exists(): raise FileExistsError('Native output destination already exists; refusing to replace it')
            stat = part.stat(); output_identity = (stat.st_dev, stat.st_ino)
            part.rename(out)
            published = True
            check_profile()
            return {"files": [str(out)], "engine": plan["engine"]}
        except BaseException:
            if published and out.is_file() and not out.is_symlink():
                stat = out.lstat()
                if (stat.st_dev, stat.st_ino) == output_identity:
                    out.unlink()
            raise
        finally:
            if job: job.close()
            if proc:
                if proc.poll() is None: proc.kill()
                proc.wait(timeout=10)
            for path in (gate, request, stop, part, active): path.unlink(missing_ok=True)
            if kind == 'video': part.with_suffix('.avi').unlink(missing_ok=True)
            if logpath.exists():
                for attempt in range(10):
                    try: os.replace(logpath, runtime/"sdcpp-last.log"); break
                    except PermissionError:
                        if attempt == 9: break  # Preserve the original outcome; owned child handles can close late.
                        time.sleep(.1)
