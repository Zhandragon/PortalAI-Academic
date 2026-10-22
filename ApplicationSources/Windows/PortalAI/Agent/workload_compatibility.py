"""Bundled workload support, distinct from driver probes and memory admission."""
from runtime_policy import detect_hardware

CUDA_ONLY = set()
ROCM_MEDIA = {'sfx', 'music', 'score-video', 'video-sfx', 'lip-sync', 'video-dialogue',
              'edit', 'mask', 'inpaint', 'autoedit', 'video', 'video-edit', 'video-inpaint',
              'audio-inpaint', 'sfx-inpaint', 'dialogue-video'}


def require_workload(command, hardware=None, *, native=False):
    """Reject unsupported GPU media before stopping chat or loading heavy weights.

    CUDA presence does not prove sufficient memory; job-specific admission follows
    the handoff. CPU science/FFmpeg/transcription/image paths remain independent.
    """
    if command not in CUDA_ONLY | ROCM_MEDIA: return
    hw = hardware or detect_hardware()
    if hw.get("system") not in ("Windows","Linux") or hw.get("machine", "").lower() not in ("amd64", "x86_64"):
        raise RuntimeError(f"{command}: this bundled media runtime requires Windows/Linux x64")
    if native:
        if command not in {'edit', 'inpaint', 'autoedit', 'video-inpaint'}:
            raise ValueError('No native edit route for ' + command)
        # Native plan still probes its executable/device and admits free memory
        # after handoff. Semantic masks have their own GPU admission.
        return
    if command in ('music', 'score-video'):
        # Music admission follows the saved/explicit engine after chat unload.
        # MusicGen CPU must remain reachable without a CUDA/ROCm preflight.
        return
    cuda = any(g.get("index", 0) == 0 and g.get("backend", "cuda") == "cuda" for g in hw.get("gpus", []))
    if hw.get('system')=='Linux':
        from linux_ml import probe
        gpu=hw.get('media_gpu',{}) if hardware is not None else probe(backend='cuda' if cuda else 'rocm')
        if not gpu.get('compute_ok'):raise RuntimeError(command+': Linux GPU compute probe failed; no implicit CPU substitution')
        if cuda:return
        if command in ROCM_MEDIA and gpu.get('available') and gpu.get('backend')=='rocm':return
    if not cuda:
        if command in ROCM_MEDIA:
            from amd_runtime import probe
            amd = hw.get('amd_gpu') if hardware is not None else probe()
            if amd and amd.get('available') and amd.get('compute_ok'): return
            raise RuntimeError(f'{command}: no working CUDA or ROCm GPU; the scaled media profile requires an actual AMD compute probe')
        raise RuntimeError(f"{command}: the installed implementation requires an NVIDIA CUDA GPU. "
            "No Radeon/CPU implementation is enabled for this operation. Available alternatives include SD1.5 images, "
            "Whisper Base transcription, English Piper speech, deterministic media edits and CPU science. "
            "A Vulkan chat/image backend does not provide CUDA support.")


def support_matrix():
    return [
        {"workload": "Chat / tools / persistent missions / scheduling / memory",
         "windows_nvidia": "CUDA with model/context/offload selection",
         "windows_radeon_igpu": "Vulkan with shared-memory accounting, or CPU; usually 4B/1.7B models",
         "windows_cpu": "4B/1.7B subject to available RAM; slower model affects mission throughput",
         "linux": "Portable Tk GUI, owned chat shell/science workers and headless supervision checked in an offline Linux guest. Delegated cgroup v2 required. CPU/Vulkan chat backends bundled; pinned Linux CUDA LLM backend not bundled. Real CPU model handoff, healthy restoration, watchdog recovery and Stop passed in the offline guest; physical Linux desktop/GPU execution remains unvalidated"},
        {"workload": "Text-to-image",
         "windows_nvidia": "FLUX when free memory fits; ComfyUI SD1.5 fallback; native CPU/Vulkan selectable",
         "windows_radeon_igpu": "Native SD1.5/DreamShaper8; explicit Klein4 standard/alternate encoder on Vulkan. Klein4 needs 16 GiB available shared RAM, or 12 GiB dedicated; working native device probe required",
         "windows_cpu": "SD1.5/DreamShaper8: 8 GiB available RAM. Klein4: 12 GiB, 128..512px; bounded CPU generation and reference editing passed",
         "linux": "Native CPU/Vulkan engines and SD1.5/DreamShaper8/Klein4 assets packaged. CPU SD1.5 passed offline guest inference. Klein4 and physical recipient Vulkan inference unvalidated"},
        {"workload": "Transcription / basic English speech",
         "windows_nvidia": "Whisper / Qwen3-TTS or CPU alternatives",
         "windows_radeon_igpu": "Whisper Base / Piper on CPU",
         "windows_cpu": "Whisper Base / Piper; RAM admission applies",
         "linux": "Actual Whisper Base CPU inference and Piper speech passed in offline Linux guest. FFplay null playback, synthetic PCM capture and parent-death cleanup passed; physical speaker/microphone validation pending"},
        {"workload": "Qwen voice synthesis, voice cloning/design",
         "windows_nvidia": "Qwen CUDA; free VRAM/RAM admission after handoff",
         "windows_radeon_igpu": "Isolated ROCm adapter; actual GPU compute probe and memory admission required; physical Radeon test pending",
         "windows_cpu": "Piper basic English speech only; no cloning/design",
         "linux": "Separate CPU/CUDA/ROCm Torch layers and Qwen dependencies packaged; imports checked; physical Linux GPU voice inference pending"},
        {"workload": "Instruction image editing / masked image editing",
         "windows_nvidia": "Original FLUX CUDA route; explicit --edit-profile klein4 uses native CPU/Vulkan; standard/alternate encoders",
         "windows_radeon_igpu": "Scaled auto uses native Klein4 CPU/Vulkan, 128..512px. 12 GiB free RAM, 16 GiB shared. Explicit mask supported; semantic --target still needs compute-probed GPU segmentation",
         "windows_cpu": "Native Klein4 whole-image/reference or explicit-mask editing; no CPU semantic target segmentation. Preserves unmasked pixels",
         "linux": "Same native Klein4 code/assets packaged; actual Linux inference unvalidated. Explicit --edit-profile pix2pix retains prior ROCm model"},
        {"workload": "Semantic masks and VACE video editing",
         "windows_nvidia": "CUDA implementations; workload memory limits and validation vary",
         "windows_radeon_igpu": "SAM2/GroundingDINO masks; VACE 1.3B up to 320px and 17 frames per chunk (8 GiB free GPU, 16/24 GiB free dedicated/shared-host RAM), with a 12 GiB worker memory ceiling. CPU diagnostic editing passed; physical Radeon inference pending. No separate content filter found in installed VACE graph",
         "windows_cpu": "Unavailable in this bundle; rejected before model handoff",
         "linux": "Shared scaled adapters, weights and isolated CUDA/ROCm packages installed; native Linux GPU workflows remain unvalidated"},
        {"workload": "MuseTalk lip-sync and framewise video inpainting",
         "windows_nvidia": "Existing CUDA MuseTalk and editing routes retained",
         "windows_radeon_igpu": "Staged MuseTalk: 0.2..8 seconds, 512px, 6 GiB free GPU and 12/20 GiB free dedicated/shared-host RAM. Masked framewise editing: up to 8 seconds at 8 fps, generated region scaled to 512px. Short MuseTalk CPU diagnostic passed; physical Radeon inference pending",
         "windows_cpu": "Klein4 framewise inpaint with an explicit mask is available under its CPU/RAM limits; temporal consistency is not guaranteed. MuseTalk remains GPU-only in product routes",
         "linux": "Portable shared adapters and dependencies installed; GPU MuseTalk/video-inpaint inference pending"},
        {"workload": "Image-conditioned video and range regeneration/append",
         "windows_nvidia": "Existing CUDA Wan generation retained; range splicing preserves source canvas and cadence",
         "windows_radeon_igpu": "Bounded VACE 1.3B reference conditioning at 128..320px, up to 17 frames per pass. Range generation chains passes and validates duration; 8 GiB free GPU plus 16/24 GiB dedicated/shared-host RAM. Physical Radeon inference pending",
         "windows_cpu": "No product CPU implementation; native video-small is text-only and does not replace image conditioning",
         "linux": "Shared VACE reference adapter and CUDA/ROCm packages installed; physical Linux GPU inference pending"},
        {"workload": "Music and short video scoring",
         "windows_nvidia": "Existing ACE-Step CUDA service and 5Hz LM route retained",
         "windows_radeon_igpu": "ACE-Step turbo ROCm adapter; 10..30 seconds, CPU offloading, no 5Hz LM; 6 GiB free GPU and 12/20 GiB free RAM; imports tested, physical inference pending",
         "windows_cpu": "MusicGen Small CPU: 1..30s explicit instrumentals, no lyrics, 10 GiB free RAM. No separate runtime filter; CC-BY-NC-4.0. Actual bounded Windows CPU generation/cancel checked",
         "linux": "Scaled ACE-Step GPU plus MusicGen Small CPU via bundled Linux CPU Torch; physical GPU and Linux MusicGen inference validation pending"},
        {"workload": "Music/audio understanding",
         "windows_nvidia": "Deterministic analysis and optional MOSS/CLAP/Demucs specialists; responses report which specialist actually ran",
         "windows_radeon_igpu": "Deterministic audio analysis; specialist GPU compatibility not established",
         "windows_cpu": "Deterministic audio analysis; specialist model memory and runtime requirements remain separate",
         "linux": "Offline CLAP ranking and Demucs vocal isolation passed real Linux CPU inference. MOSS tiny-config audio/DeepStack/language forward passed; full 8B and physical CUDA/ROCm inference remain unvalidated. Independent memory admission; complete clips up to 300 seconds"},
        {"workload": "Text/video-conditioned sound effects (sfx / video-sfx)",
         "windows_nvidia": "Existing large MMAudio CUDA route; auto preserves large_44k_v2",
         "windows_radeon_igpu": "Staged small MMAudio, 1..8 seconds; real BF16 compute, 6 GiB free GPU and 10/18 GiB free dedicated/shared-host RAM required. Text and video-conditioned CPU diagnostic inference passed; physical Radeon inference pending",
         "windows_cpu": "Explicit CPU diagnostic only; no product CPU substitution",
         "linux": "Shared staged small MMAudio adapter with isolated CUDA/ROCm packages; physical Linux GPU SFX inference pending"},
        {"workload": "Small silent text-to-video (video-small)",
         "windows_nvidia": "Wan 1.3B on native Vulkan or CPU; 256px / 17-frame default, automatic weight offloading",
         "windows_radeon_igpu": "Native Vulkan, quantized CPU T5 and CPU VAE; 18 GiB available shared RAM; physical Radeon test pending",
         "windows_cpu": "14 GiB available RAM; short bounded clips; slow; no image-conditioning or dialogue",
         "linux": "Native CPU/Vulkan engines and weights packaged; Linux video generation unvalidated"},
        {"workload": "Localized audio/SFX inpainting",
         "windows_nvidia": "Existing experimental spectrogram editing route retained",
         "windows_radeon_igpu": "Masked MMAudio for auto/general/SFX; ACE-Step native repaint for explicit music. Speech retains experimental spectral editing without intelligibility/voice guarantee. Real GPU admission, 12 GiB audio worker cap and 4 GiB free-RAM reserve; physical Radeon validation pending",
         "windows_cpu": "No production generative repair fallback",
         "linux": "Shared masked-audio/music-repaint/spectral adapters with isolated CUDA/ROCm packages. General repair: 0.05..6s region within 8s context window; music: 0.05..24s within 30s. Physical Linux GPU validation pending"},
        {"workload": "Combined image + dialogue + motion + lip sync",
         "windows_nvidia": "Existing Qwen voice + Wan + MuseTalk pipeline retained",
         "windows_radeon_igpu": "Sequential Qwen voice + VACE 1.3B reference-motion chunks + MuseTalk; optional ACE-Step music. 0.2..8s speech, 128..320px, 4..30 fps. Strictest stage needs 8 GiB free GPU and 16/24 GiB free dedicated/shared-host RAM; physical Radeon validation pending",
         "windows_cpu": "Not enabled; no still-image or text-only motion substitution",
         "linux": "Shared scaled pipeline and isolated CUDA/ROCm runtimes; physical Linux GPU end-to-end validation pending"},
        {"workload": "Media inspection, trim/mix/mux/resize and CPU science",
         "windows_nvidia": "CPU tools; leased OpenMM OpenCL available; CUDA plugin is not installed",
         "windows_radeon_igpu": "CPU tools plus explicit leased OpenMM OpenCL molecular minimization; driver and memory required; physical Radeon test pending",
         "windows_cpu": "CPU tools, subject to RAM and dataset size",
         "linux": "Bundled FFmpeg/SoX and Linux science packages. Offline guest checked FFmpeg, symbolic math, RDKit, CadQuery/Gmsh, OpenMM CPU and native MAFFT alignment. Physical OpenCL GPU testing pending. Bundled KiCad 9.0.2, standard symbol/footprint/3D libraries and isolated loader passed SVG/BOM/STEP exports with a bundled component model in the offline guest"},
        {"workload": "Image/video understanding",
         "windows_nvidia": "Installed 27B vision model plus projector must fit",
         "windows_radeon_igpu": "Small auto-selected text models have no vision; large vision model needs sufficient memory",
         "windows_cpu": "Small auto-selected text models have no vision; no lightweight vision fallback installed",
         "linux": "Not validated"},
        {"workload": "Secure VM shell",
         "windows_nvidia": "WHPX / hardware virtualization and available RAM required",
         "windows_radeon_igpu": "Same Windows virtualization requirements; GPU does not provide isolation",
         "windows_cpu": "Same requirements; no TCG or host-shell fallback",
         "linux": "QEMU and offline Alpine payload packaged; requires accessible /dev/kvm and delegated cgroups, no software-emulation/host-shell fallback. Physical Linux KVM execution unvalidated"},
    ]
