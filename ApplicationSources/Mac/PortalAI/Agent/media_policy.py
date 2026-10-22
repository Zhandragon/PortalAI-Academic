"""Conservative admission and local model selection for portable media jobs.

Call after the LLM handoff: free VRAM, not installed VRAM, determines admission.
These estimates bound supported jobs; they do not promise speed or peak memory.
"""
from pathlib import Path
from runtime_policy import ROOT, GIB, detect_hardware, load_effective_policy, portable_path

SD15 = "Generative/ComfyUI_windows_portable/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors"
BASE_STT = "SpeechToText/models/whisper-base"


def cuda_memory(hw):
    # The bundled media engines use CUDA device 0. Never add GPUs together or
    # budget a different card from the one the engine will actually use.
    gpu = next((g for g in hw.get("gpus", []) if g.get("index", 0) == 0 and g.get("backend", "cuda") == "cuda"), None)
    return max(0, int(gpu.get("free_bytes", 0))) if gpu else 0


def image_plan(root=ROOT, profile=None, width=None, height=None, hardware=None, policy=None, engine=None, variant=None,
               respect_saved_profile=False):
    variant = 'standard'
    hw = hardware or detect_hardware()
    cfg = policy if policy is not None else load_effective_policy(root)
    from model_preferences import media_variant
    # Nice makes an explicit per-request choice in auto mode. The CLI itself
    # never guesses from prompt keywords or inherits the chat model preference.
    preference = variant or ('uncensored' if media_variant(cfg) == 'uncensored' else 'standard')
    if preference not in ('standard', 'uncensored'):
        raise ValueError('Image variant must be standard or uncensored')
    saved = cfg.get("media", {}).get("image_profile", "auto")
    requested = saved if respect_saved_profile and saved != 'auto' else (profile or saved)
    if requested not in ("auto", "sd15", "flux", "klein4"):
        raise ValueError("Image profile must be auto, sd15, flux or klein4")
    selection = {'saved_profile': saved, 'tool_requested_profile': profile,
                 'selection_source': 'saved' if saved != 'auto' and (respect_saved_profile or not profile)
                                     else 'automatic' if requested == 'auto' else 'explicit'}
    if requested == 'klein4':
        from native_flux import plan
        return {**plan(root, engine=engine or cfg.get('media', {}).get('image_engine', 'auto'), width=512 if width is None else width,
                       height=512 if height is None else height, variant=preference, hardware=hw), **selection}
    vram = cuda_memory(hw)
    cuda = any(g.get("index", 0) == 0 and g.get("backend", "cuda") == "cuda" for g in hw.get("gpus", []))
    engine = engine or cfg.get("media", {}).get("image_engine", "auto")
    if engine not in ("auto", "comfyui", "sdcpp-vulkan", "sdcpp-cpu"):
        raise ValueError("Unknown image engine")
    amd = hw.get("amd_gpu", {})
    if engine == "comfyui" and not cuda and hardware is None and hw.get("system") in ("Windows","Linux"):
        if hw.get('system')=='Linux':
            from linux_ml import probe
        else:
            from amd_runtime import probe
        amd = probe(root)
    rocm = bool(engine == "comfyui" and not cuda and amd.get("available") and amd.get("compute_ok"))
    if rocm:
        needed_ram = (12 if amd.get("shared_memory", True) else 6)*GIB
        if hw["ram_available_bytes"] < needed_ram or amd.get("free_bytes", 0) < 3*GIB:
            raise RuntimeError("ROCm SD1.5 needs 3 GiB free GPU memory and 6 GiB available RAM (12 GiB shared) after chat handoff")
    native = engine.startswith("sdcpp-") or (engine == "auto" and not cuda and
        (root/("Runtime/StableDiffusion/linux-cpu/sd-cli" if hw.get('system')=='Linux' else "Runtime/StableDiffusion/windows-cpu/sd-cli.exe")).is_file())
    native_plan = None
    if native:
        if requested == "flux": raise RuntimeError("The portable native image profile supports SD1.5 only; FLUX uses ComfyUI/CUDA")
        from sdcpp_bridge import engine_plan
        native_plan = engine_plan(root, hw, engine)
        cuda = False  # Native Vulkan shares no CUDA/PyTorch assumptions.
    ram = max(0, hw["ram_available_bytes"] - 2*GIB)
    large_fits = cuda and vram >= 16*GIB and ram >= 6*GIB
    if requested == 'auto' and large_fits and preference == 'uncensored':
        # Auto must budget the selected weights, including the larger encoder.
        from model_variants import require_flux_alternate
        try:
            require_flux_alternate(root, hw)
        except (OSError, RuntimeError):
            large_fits = False
    selected = ("flux" if large_fits else "sd15") if requested == "auto" else requested
    if selected == "flux":
        if not large_fits:
            raise RuntimeError("FLUX profile needs at least 16 GiB free CUDA VRAM and 8 GiB available RAM after handoff. Use the sd15 image profile.")
        default, max_side, max_pixels = 1024, 1536, 1024**2
        workflow = None  # Existing official/uncensored variant routing is retained.
    else:
        if not native_plan and (ram < (3*GIB if cuda else 6*GIB) or (cuda and vram < 3*GIB)):
            raise RuntimeError("SD1.5 needs 8 GiB available RAM on CPU, or 5 GiB RAM and 3 GiB free CUDA VRAM. Close other workloads and retry.")
        if not portable_path(root, SD15).is_file():
            raise RuntimeError("SD1.5 checkpoint is missing. Run Tools/import_media_assets.py --install with the bundled Python.")
        default, max_side, max_pixels = 512, (768 if cuda else 512), (768 if cuda else 512)**2
        workflow = "Workflows/API/SD15_T2I_Portable.json"
    w = default if width is None else int(width)
    h = default if height is None else int(height)
    if min(w, h) < 64 or w % 8 or h % 8 or max(w, h) > max_side or w*h > max_pixels:
        raise ValueError(f"{selected} image size must use multiples of 8, at least 64, at most {max_side} per side and {max_pixels} pixels. Dimensions were not silently changed.")
    return {"profile": selected, "requested_profile": requested, "backend": "cuda" if cuda else ("rocm" if rocm else "cpu"), "engine": "comfyui",
            "width": w, "height": h, "workflow": workflow,
            "reason": "Image profile admitted using available memory after LLM handoff", "free_cuda_bytes": vram,
            **(native_plan or {}), **selection}


def speech_plan(root=ROOT, model="auto", device="auto", hardware=None, policy=None):
    hw = hardware or detect_hardware()
    cfg = policy if policy is not None else load_effective_policy(root)
    if device not in ("auto", "cuda", "cpu"):
        raise ValueError("Speech device must be auto, cuda or cpu")
    requested = model
    if model == "auto":
        model = cfg.get("media", {}).get("speech_model", "auto")
    vram = cuda_memory(hw)
    # A saved large model must use its own admission floor, including when the
    # device is automatic. Do not admit it with Whisper Base's 1-GiB estimate.
    cuda_needed = (3 if model == 'large-v3-turbo' else 1)*GIB
    chosen = ("cuda" if vram >= cuda_needed else "cpu") if device == "auto" else device
    if chosen == "cuda" and vram < cuda_needed:
        raise RuntimeError(f"Whisper {model} CUDA requires at least {cuda_needed/GIB:g} GiB free VRAM")
    if model == "auto":
        model = "large-v3-turbo" if chosen == "cuda" and vram >= 3*GIB and hw["ram_available_bytes"] >= 6*GIB else "base"
    ram_needed = (3 if model == "base" else 6)*GIB
    if hw["ram_available_bytes"] < ram_needed:
        raise RuntimeError(f"Whisper {model} needs at least {ram_needed/GIB:g} GiB available RAM including reserve")
    if model == "base":
        path = portable_path(root, BASE_STT)
        if not all((path/name).is_file() for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")):
            raise RuntimeError("Portable Whisper Base is incomplete. Run Tools/import_media_assets.py --install.")
        model_path = str(path)
    else:
        # faster-whisper resolves installed aliases offline. No network fallback.
        model_path = model
    return {"model": model, "model_path": model_path, "device": chosen, "requested_model": requested,
            "reason": "CUDA uses the larger local model when memory permits; CPU defaults to Whisper Base"}
