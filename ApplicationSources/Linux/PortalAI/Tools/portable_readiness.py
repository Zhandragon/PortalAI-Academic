"""Report local admission/probes separately from physical-machine validation."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"Agent"))
from runtime_policy import GIB, atomic_json, build_plan, detect_hardware, load_policy, require_space, select_model, storage_budget
from media_policy import image_plan, speech_plan
from tts_policy import tts_plan
from workload_compatibility import support_matrix
from profile_paths import private_path


def attempt(call):
    try: return {"admitted": True, "result": call()}
    except Exception as exc: return {"admitted": False, "reason": str(exc)}


def summary(plan):
    return {"backend": plan["backend"]["backend"], "device": plan["backend"]["device"],
            "model": plan["model"]["id"], "context_tokens": plan["model"]["context_tokens"],
            "gpu_layers": plan["model"]["gpu_layers"]}


def report(root=ROOT):
    hw = detect_hardware(); policy = load_policy(root)
    current = attempt(lambda: summary(build_plan(root, hardware=hw, policy=policy)))
    cpu_policy = {**policy, "backend": "cpu", "selection": "auto"}
    cpu = attempt(lambda: summary(build_plan(root, hardware={**hw, "gpus": []}, policy=cpu_policy)))
    scenarios = []
    for available in (4, 6, 8, 12):
        simulated = {**hw, "system": "Windows", "machine": "AMD64", "gpus": [],
                     "ram_total_bytes": max(8, available)*GIB, "ram_available_bytes": available*GIB}
        def estimate():
            m = select_model(root, simulated, {"backend": "cpu", "gpu": None}, cpu_policy)["selected"]
            return {"model": m["id"], "context_tokens": m["context_tokens"], "estimated_ram_bytes": m["estimated_ram_bytes"]}
        selected = attempt(estimate)
        scenarios.append({"available_ram_gib": available, "llm": selected,
                          "image": attempt(lambda: image_plan(root, "auto", hardware=simulated, engine="sdcpp-cpu")),
                          "voice": attempt(lambda: tts_plan(root, "auto", hardware=simulated, policy={})),
                          "speech": attempt(lambda: speech_plan(root, hardware=simulated, policy={"media": {"speech_model": "auto"}}))})
    return {"created_at": time.time(), "hardware": hw, "storage": storage_budget(root),
            "current_llm_probe_and_admission": current, "forced_cpu_probe_and_admission": cpu,
            "current_native_vulkan_image_admission": attempt(lambda: image_plan(root, engine="sdcpp-vulkan", hardware=hw)),
            "workload_support_not_inference_guarantees": support_matrix(),
            "cpu_memory_simulations_not_physical_tests": scenarios,
            "capabilities": [
                {"host": "Windows x64 NVIDIA", "status": "Local RTX 3090 execution tested; other NVIDIA systems need recipient validation",
                 "tools": "CUDA/CPU chat, image, transcription and spoken-audio paths; Windows scientific environment. Voice auto reclaims chat memory before choosing Qwen CUDA or Piper CPU. Individual heavy workloads still have limits."},
                {"host": "Windows x64 Radeon", "status": "Vulkan chat path installed; physical Radeon unvalidated",
                 "tools": "Native Vulkan SD1.5 images and small Wan text-to-video; isolated ROCm Qwen voice, staged MuseTalk, InstructPix2Pix/semantic-mask/VACE editing, framewise video inpaint, staged text/video SFX and ACE-Step turbo music adapters; explicit OpenMM OpenCL. Each has driver/compute and memory checks. Short CPU diagnostic MuseTalk/editing/video-SFX inference passed; this does not validate Radeon kernels. Whisper/Piper and CPU science remain alternatives."},
                {"host": "Windows x64 integrated GPU / CPU only", "status": "CPU inference tested on this desktop; physical laptop unvalidated",
                 "tools": "Small chat model, CPU transcription, Piper English speech and native Vulkan/CPU SD1.5 images subject to available RAM. CPU images can be slow. Integrated Vulkan depends on a working driver."},
                {"host": "Linux x64", "status": "GUI/media/science/VM payloads packaged; original GUI, selected CPU tools, supervision and account checks passed in an offline Linux guest; physical Linux unvalidated",
                 "tools": "Root PortalAI.sh launcher, bundled Tk/Python/FFmpeg/SoX, isolated CPU/CUDA/ROCm media layers, CPU science, Piper/Whisper and native image/video engines. Guest checks cover GUI, owned shell/science workers, Piper speech, Whisper Base inference, SD1.5 image, MAFFT and representative science. Synthetic PCM capture/null playback and controller-death cleanup passed; physical audio devices pending. ComfyUI CPU startup, VACE node registration and real model handoff/watchdog recovery passed in the offline guest; physical GPU workflows remain unvalidated. Linux chat uses bundled CPU/Vulkan; the pinned CUDA LLM build is not bundled. Secure VM has offline QEMU/Alpine payload, requires /dev/kvm, and rejects its absence; physical Linux KVM test pending. Offline CLAP and Demucs passed real Linux CPU inference. MOSS tiny-config audio/language forward passed; full 8B inference and physical specialist GPUs remain unvalidated. Specialists have independent memory admission and a 300-second complete-input limit. Bundled KiCad 9.0.2 with standard symbols, footprints and 3D libraries passed schematic SVG/BOM and component-inclusive STEP export in the offline guest."}],
            "persistence": {"windows": "Explicitly armed missions run until completion or action budget; scheduled waits and state persist on SSD",
                            "restart": "Opening PortalAI and signing in as the mission owner restarts armed work after unexpected interruption; Stop/Exit pauses work. Locked profiles cannot run missions. No OS login service. Computer must be on and SSD connected.",
                            "interrupted_effect": "Requires review; never automatically replayed",
                            "context": "Rolling tokenizer-budgeted evidence excerpts preserve complete objectives and on-disk history; numbered history retrieval; live 4B compaction/reload test passed",
                            "accounts": "Full missions only; explicitly configured dedicated IMAP/SMTP/EVM profiles and encrypted session-unlocked vault. Offline/simulated tests passed; no live account configured by this update.",
                            "vm": "Requires hardware virtualization: WHPX on Windows, /dev/kvm and delegated cgroups on Linux. Offline guest with no host mounts; model/controller stay on host. Linux KVM execution unvalidated."},
            "limits": ["Admission estimates and backend probes are not inference/performance guarantees.",
                       "Available RAM is RAM free after the OS and other apps, not the memory printed on the laptop box.",
                       "Media admission is re-evaluated after LLM handoff; scenarios do not imply simultaneous model residency.",
                       "Radeon adapters are installed but physical GPU inference is unvalidated. MuseTalk is bounded to 8 seconds/512px, video SFX to 8 seconds, VACE to 320px/17-frame chunks, and framewise inpaint to 8 seconds at 8 fps. Music is 10..30 seconds with CPU offloading and no 5Hz LM; imports/API/CPU components were checked, not Radeon music generation.",
                       "CPU diagnostic inference, offline guest tests and admission probes do not prove physical Radeon/laptop/Linux compatibility, multi-day LLM autonomy or account-business operation.",
                       "The 72-hour fixed-planner/mock-account endurance run was interrupted after 4590.45 seconds (76.5 minutes); its saved running status is stale and multi_day_completed is false.",
                       "Repeated October 10 host WHEA failures remain unexplained. Live model/GPU tests are bounded and sequential; deferred or interrupted tests must not be counted as passes.",
                       "Arbitrary full-mode shell commands can write outside managed storage checks; reserves are not an OS quota."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument('--stdout', action='store_true', help='Print a read-only result without saving a report')
    args = parser.parse_args(argv)
    destination = None if args.stdout else private_path(args.root, 'Data/Maintenance/portable-readiness.json')
    data = report(args.root)
    if destination is not None:
        require_space(args.root, for_outputs=True)
        atomic_json(destination, data)
    print(json.dumps(data, indent=2))


if __name__ == "__main__": main()
