"""Speech admission for isolated CUDA/ROCm runtimes and basic CPU speech."""
from runtime_policy import ROOT, GIB, detect_hardware, load_effective_policy, portable_path
from media_policy import cuda_memory

PIPER_MODEL = "Voice/Piper/models/en_US-ljspeech-medium.onnx"


def with_amd_probe(hardware, root=ROOT):
    """Add an actual compute probe only for a live non-CUDA Windows recipient."""
    hw = dict(hardware)
    cuda = any(g.get("index", 0) == 0 and g.get("backend", "cuda") == "cuda" for g in hw.get("gpus", []))
    if hw.get('system')=='Linux':
        from linux_ml import probe
        hw['media_gpu']=probe(root,'cuda' if cuda else 'rocm')
        if not cuda:hw['amd_gpu']=hw['media_gpu']
        return hw
    if not cuda and hw.get("system") in ("Windows","Linux") and "amd_gpu" not in hw:
        from amd_runtime import probe
        hw["amd_gpu"] = probe(root)
    return hw


def qwen_preflight(hardware=None):
    """Reject unsupported recipients before evicting chat; free VRAM is checked later."""
    hw = hardware if hardware is not None else with_amd_probe(detect_hardware())
    device = next((g for g in hw.get("gpus", []) if g.get("index", 0) == 0 and g.get("backend", "cuda") == "cuda"), None)
    amd = hw.get("amd_gpu", {})
    cuda_fits = device and device.get("total_bytes", 0) >= 8*GIB
    if hw.get('system')=='Linux':cuda_fits=cuda_fits and hw.get('media_gpu',{}).get('compute_ok',False)
    amd_fits = amd.get("available") and amd.get("compute_ok") and amd.get("total_bytes", 0) >= 8*GIB
    if hw.get("system", "Windows") not in ("Windows","Linux") or not (cuda_fits or amd_fits):
        raise RuntimeError("Qwen voice requires Windows/Linux and an NVIDIA CUDA GPU or a compute-probed AMD ROCm GPU with at least 8 GiB addressable GPU memory. Use voice-say --engine piper for basic English CPU speech.")


def tts_needs_handoff(engine, hardware):
    """Try reclaiming PortalAI memory before downgrading a capable GPU host.

    This only decides whether to enter the existing owned-worker lease. Admission
    still uses freshly measured free memory AFTER that lease releases chat.
    """
    if engine not in {"auto", "piper", "qwen"}:
        raise ValueError("Voice engine must be auto, piper or qwen")
    if engine == "qwen":
        qwen_preflight(hardware)
        return True
    if engine == "auto":
        try:
            qwen_preflight(hardware)
            return True
        except RuntimeError:
            pass
    return hardware["ram_available_bytes"] < 3*GIB


def tts_plan(root=ROOT, engine=None, language="English", hardware=None, policy=None):
    cfg = policy if policy is not None else load_effective_policy(root)
    requested = engine or cfg.get("media", {}).get("voice_engine", "auto")
    if requested not in {"auto", "piper", "qwen"}: raise ValueError("Voice engine must be auto, piper or qwen")
    hw = hardware if hardware is not None else detect_hardware()
    if hardware is None and requested != "piper": hw = with_amd_probe(hw, root)
    if hw.get("system", "Windows") not in ("Windows","Linux") or hw.get("machine", "AMD64").lower() not in {"amd64", "x86_64"}:
        raise RuntimeError("Bundled speech synthesis targets Windows/Linux x64")
    english = language.lower().strip() in {"english", "en", "en-us", "en_us", "auto"}
    amd = hw.get("amd_gpu", {})
    cuda_fits = cuda_memory(hw) >= 8*GIB and hw["ram_available_bytes"] >= 6*GIB
    if hw.get('system')=='Linux':cuda_fits=cuda_fits and hw.get('media_gpu',{}).get('compute_ok',False)
    # UMA is shared with system RAM, never additional memory to add to it.
    amd_ram = 12*GIB if amd.get("shared_memory", True) else 6*GIB
    amd_fits = (amd.get("available") and amd.get("compute_ok") and
                amd.get("free_bytes", 0) >= 8*GIB and hw["ram_available_bytes"] >= amd_ram)
    qwen_fits = cuda_fits or amd_fits
    selected = ("qwen" if qwen_fits else "piper") if requested == "auto" else requested
    if selected == "qwen":
        if not qwen_fits: raise RuntimeError("Qwen voice needs 8 GiB free CUDA/ROCm GPU memory and 6 GiB available RAM (12 GiB for shared Radeon memory) after chat handoff. AMD also requires a successful compute probe. Use voice-say --engine piper for basic English CPU speech.")
        return {"engine": "qwen", "device": "cuda" if cuda_fits else "rocm", "speaker": "Ryan", "requested_engine": requested}
    if not english: raise RuntimeError("The installed Piper voice supports English only. Other languages need a suitable local voice or Qwen on a supported GPU; no substitution was made.")
    if hw["ram_available_bytes"] < 3*GIB: raise RuntimeError("CPU speech needs 3 GiB available RAM including the 2 GiB reserve")
    package='Voice/Piper/packages' if hw.get('system','Windows')=='Windows' else 'Runtime/LinuxPackages/extras'
    ort='Voice/Piper/packages' if hw.get('system','Windows')=='Windows' else 'Runtime/LinuxPackages/media'
    required = [PIPER_MODEL, PIPER_MODEL+".json", package+'/piper/__init__.py', ort+'/onnxruntime/__init__.py']
    if not all(portable_path(root, p).is_file() for p in required):
        raise RuntimeError("CPU voice assets are incomplete. Run Tools/import_voice_assets.py --install with the bundled Python.")
    return {"engine": "piper", "device": "cpu", "voice": "en_US-ljspeech-medium", "model_path": str(portable_path(root, PIPER_MODEL)),
            "requested_engine": requested, "language": "en-US", "capabilities": ["text-to-speech"],
            "limits": "One installed English voice; no voice cloning or natural-language voice design"}


def validate_text(text):
    if not isinstance(text, str) or not text.strip(): raise ValueError("Speech text is empty")
    if len(text.encode("utf-8")) > 4000: raise ValueError("Speech text exceeds 4000 UTF-8 bytes; split it into shorter passages")
    if "\x00" in text: raise ValueError("Speech text contains a NUL character")
    return text
