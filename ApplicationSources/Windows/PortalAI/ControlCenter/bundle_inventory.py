"""Current portable capabilities for Settings, Installed and diagnostics."""
from pathlib import Path
import json
import sys
import platform
import stat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Agent"))
from runtime_policy import load_policy, portable_path, runtime_candidates, storage_budget

MODEL_LABELS = {"qwen1.7-abliterated-q8": "Qwen 3 · 1.7B Abliterated · Q8_0 · text",
                "qwen27-standard-q4": "Qwen 3.8 · 27B Standard · Q4_K_M · vision",
                "qwen27-q4": "Qwen 3.8 · 27B Abliterated · Q4_K_M · vision",
                "qwen27-q5": "Qwen 3.8 · 27B Abliterated · Q5_K_M · vision",
                "qwen4-q4": "Qwen 3 · 4B Standard · Q4_K_M · text",
                "qwen4-abliterated-q4": "Qwen 3 · 4B Abliterated · Q4_K_M · text",
                "qwen1.7-q8": "Qwen 3 · 1.7B Standard · Q8_0 · text",
                "qwen-vl2-q4": "Qwen 3 VL · 2B Standard · image companion",
                "qwen-vl2-abliterated-q4": "Qwen 3 VL · 2B Abliterated · image companion",
                "qwen-vl4-q4": "Qwen 3 VL · 4B Standard · image companion",
                "qwen-vl4-abliterated-q4": "Qwen 3 VL · 4B Abliterated · image companion"}


def file_state(path):
    """Public inventory is advisory; one unavailable component must not stop login."""
    try:
        info = path.stat()
        return ('INSTALLED', info.st_size) if stat.S_ISREG(info.st_mode) else ('MISSING', 0)
    except FileNotFoundError:
        return 'MISSING', 0
    except PermissionError:
        return 'INACCESSIBLE', 0
    except OSError:
        return 'UNAVAILABLE', 0


def inventory(root, *, policy=None):
    root = Path(root)
    policy = load_policy(root) if policy is None else policy
    models = []
    for model in policy["models"]:
        p = portable_path(root, model["path"])
        projector = portable_path(root, model["projector"]) if model.get("projector") else None
        state, size = file_state(p)
        if state == 'INSTALLED' and projector is not None:
            state, _ = file_state(projector)
        installed = state == 'INSTALLED'
        models.append({**model, "label": MODEL_LABELS.get(model["id"], model["id"]),
                       "installed": installed, "state": state, "bytes": size})
    states = {k: file_state(p)[0] for k, p in runtime_candidates(root, platform.system()).items()}
    return {"policy": policy, "models": models, "storage": storage_budget(root),
            "backends": {k: state == 'INSTALLED' for k, state in states.items()},
            "backend_states": states}


def installed_rows(root):
    root=Path(root);system=platform.system();linux=system=='Linux'
    d = inventory(root)
    rows = {"model_" + m["id"]: ("INSTALLED" if m["installed"] else m.get('state', 'NOT INSTALLED'),
            f"{m['bytes']/1024**3:.2f} GiB · {m['path']}" if m["installed"] else "Optional model; excluded from automatic selection") for m in d["models"]}
    from academic_policy import MODEL_COUNTERPARTS, NOTICE
    for model_id in MODEL_COUNTERPARTS:
        rows['model_' + model_id] = ('EXCLUDED', 'Unavailable in Academic; intentionally omitted.')
    rows['fluxAlt'] = ('EXCLUDED', 'Unavailable in Academic; intentionally omitted.')
    for name, present in d["backends"].items():
        rows["backend_" + name] = ("INSTALLED" if present else "MISSING", f"Bundled {platform.system()} x64 backend; driver/host validation separate")
        state = d.get('backend_states', {}).get(name)
        if state in ('INACCESSIBLE', 'UNAVAILABLE'):
            rows['backend_' + name] = (state, 'Runtime files cannot be accessed; check portable runtime permissions before use')
        elif linux and name=='cuda' and not present:
            rows['backend_cuda']=('NOT INSTALLED','No matching verified pinned Linux CUDA LLM artifact bundled; NVIDIA Linux chat can use Vulkan; CUDA media layer is separate')
    def present(*paths):
        try:return all((root/path).exists() for path in paths)
        except OSError:return False
    def verified_receipt(relative):
        try:return json.loads((root/relative).read_text(encoding='utf-8')).get('verified') is True
        except (OSError,ValueError,AttributeError):return False
    def add(key,ok,detail):rows[key]=('INSTALLED' if ok else 'CHECK',detail)
    python='Runtime/LinuxPython/run-python' if linux else 'Runtime/BootstrapPython/python.exe'
    loader='Runtime/LinuxSystem/rootfs/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
    runtime_ok=present(python) and (not linux or present(loader))
    torch='Runtime/LinuxTorch/rocm7.2/torch/__init__.py' if linux else 'Runtime/AMDPython/packages/torch/__init__.py'
    gpu_layer=present(torch) or (linux and present('Runtime/LinuxTorch/cu128/torch/__init__.py'))
    qemu='Runtime/QEMU/linux-x64/bin/qemu-system-x86_64' if linux else 'Runtime/QEMU/windows-x64/qemu-system-x86_64.exe'
    piper='Runtime/LinuxPackages/extras/piper/__init__.py' if linux else 'Voice/Piper/packages/piper/__init__.py'
    add('missions',present('Agent/mission_supervisor.py'),
        'Armed missions, schedules, scoped memory and interrupted-action review; '+('delegated cgroup v2 required' if linux else 'Windows Job ownership'))
    add('vmMode',runtime_ok and present('Agent/vm_runner.py',qemu,'Runtime/VM/alpine-3.24.2/boot/vmlinuz-virt','Runtime/VM/alpine-3.24.2/boot/initramfs-virt'),
        'QEMU/Alpine offline shell payload; '+('accessible /dev/kvm and delegated cgroups required; physical KVM test pending' if linux else 'WHPX hardware virtualization required')+'; no network/host mounts; controller stays on host')
    add('piperCpu',runtime_ok and present(piper,'Voice/Piper/models/en_US-ljspeech-medium.onnx','Voice/Piper/models/en_US-ljspeech-medium.onnx.json','Voice/Piper/models/MODEL_CARD'),
        'English CPU speech; no cloning/design; '+('actual offline Linux guest speech checked' if linux else 'memory admission after chat unload'))
    cpu_torch='Runtime/LinuxTorch/cpu/torch/__init__.py' if linux else 'Runtime/ProteinDesign/windows-cpu/torch/__init__.py'
    add('musicCpu',runtime_ok and present(cpu_torch,'Agent/music_cpu_entry.py','Music/MusicGen-small/model.safetensors','Music/MusicGen-small/tokenizer.json') and verified_receipt('Maintenance/Imports/musicgen-small-model-safetensors.json'),
        'MusicGen Small CPU: 1–30s instrumentals, 10 GiB free RAM, no GPU or sung lyrics; CC-BY-NC-4.0. '+('Linux inference pending' if linux else 'bounded CPU generation/cancel checked'))
    add('sd15Cpu',present('Generative/ComfyUI_windows_portable/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors'),
        'Shared SD1.5 checkpoint; native CPU/Vulkan runtime required; subject to available RAM')
    for backend,key in (('vulkan','imageVulkan'),('cpu','imageNativeCpu')):
        engine='Runtime/StableDiffusion/'+('linux-' if linux else 'windows-')+backend+'/sd-cli'+('' if linux else '.exe')
        ok=present(engine) and (not linux or present(engine+'.bin',loader))
        add(key,ok,'SD1.5 '+backend.upper()+' engine for '+system+' x64; 512px maximum; '+
            ('driver and memory checks; physical Radeon/Linux Vulkan pending' if backend=='vulkan' else '8 GiB available RAM; CPU guest image checked' if linux else '8 GiB available RAM'))
    add('amdTorch',runtime_ok and present(torch),
        ('Isolated Linux ROCm 7.2 / Torch 2.11; separate CPU and CUDA 12.8 layers: '+
         ('present' if present('Runtime/LinuxTorch/cpu/torch/__init__.py','Runtime/LinuxTorch/cu128/torch/__init__.py') else 'check files')
         if linux else 'Isolated Windows ROCm 10.1 / Torch 2.14')+
        '; Qwen voice, MuseTalk, editing, music and text/video SFX adapters; real compute required, physical Radeon test pending')
    ffmpeg='Runtime/FFmpeg/linux-x64/bin/' if linux else 'Tools/ffmpeg/bin/'
    suffix='' if linux else '.exe'
    add('mediaEdit',present('Agent/media_edit_bridge.py',ffmpeg+'ffmpeg'+suffix,ffmpeg+'ffprobe'+suffix) and (not linux or present(loader,'Runtime/LinuxSystem/rootfs/usr/bin/ffmpeg')),
        'Bundled '+system+' FFmpeg/ffprobe: inspect, trim, mix, resize and mux; generation is a separate workload')
    add('musetalk',present('Agent/musetalk_bridge.py','Agent/musetalk_amd_entry.py','Video/MuseTalk/models/musetalkV15/unet.pth','Video/MuseTalk/models/dwpose/dw-ll_ucoco_384.onnx') and (not linux or runtime_ok and gpu_layer),
        'CUDA route retained; scaled ROCm/Linux adapter: 0.2..8 seconds, 512px, staged weights; CPU diagnostic passed, physical Radeon/Linux GPU pending')
    for key in ('sfx','videoSfx'):
        add(key,present('Agent/mmaudio_staged.py','Services/MMAudio/weights/mmaudio_small_44k.pth') and (not linux or runtime_ok and gpu_layer),
            'Text/video-conditioned MMAudio; scaled ROCm/Linux profile: 1..8 seconds, BF16 compute probe, 6 GiB free GPU; CPU diagnostic passed, physical Radeon/Linux GPU pending')
    add('vace',present('Agent/radeon_edit.py','Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.1_vace_1.3B_fp16.safetensors') and (not linux or runtime_ok and gpu_layer),
        'VACE 14B CUDA retained; scaled ROCm/Linux 1.3B: 320px, 17-frame chunks, 8 GiB free GPU; physical Radeon/Linux GPU pending')
    for key in ('imageEdit','inpaint','videoInpaint'):
        add(key,present('Agent/radeon_edit.py','Models/InstructionEdit/model_index.json','Models/InstructionEdit/unet/diffusion_pytorch_model.fp16.safetensors') and (not linux or runtime_ok and gpu_layer),
            'CUDA routes retained; scaled ROCm/Linux InstructPix2Pix edits/masks at 512px; framewise video up to 8 seconds at 8 fps; physical GPU validation pending')
    add('scienceBiology', present('Scientific/biology.py','Scientific/biology_tool.py'),
        'Plasmid assembly, GenBank features, measured parts ranking, circuits and bioprocess CPU simulations; NCBI/iGEM require network for new records')
    add('scienceDesign', present('Scientific/protein_design.py','Runtime/ProteinDesign/vendor/vanilla_model_weights/v_48_020.pt','Maintenance/Imports/protein-mpnn.json'),
        'ProteinMPNN fixed-backbone single-chain CPU design; pinned assets verified before use; no new-fold generation or GPU design backend')
    add('scienceCoupled', present('Scientific/coupled_physics.py','Scientific/coupled_physics_tool.py','Scientific/physics_viewer.py'),
        'Bounded CPU liquid/elastic/rigid educational simulation with offline viewer; not validated CFD')
    add('scienceKicad', present('Runtime/KiCad/linux-x64/bin/kicad-cli' if linux else 'Tools/KiCad/bin/kicad-cli.exe'),
        'KiCad 9.0.2 CLI with stock libraries; SVG/BOM/STEP exports checked '+
        ('in the offline Linux guest' if linux else 'on Windows CPU')+
        '; source/project validity and physical recipient runtime remain separate checks')
    if not linux:
        plugins = 'Runtime/ScientificPython/packages/OpenMM.libs/lib/plugins/'
        cuda, opencl = present(plugins+'OpenMMCUDA.dll'), present(plugins+'OpenMMOpenCL.dll')
        add('scienceGpu', opencl or cuda, 'CPU default; OpenCL plugin '+('present' if opencl else 'absent')+
            '; CUDA plugin '+('present' if cuda else 'absent')+'. Explicit GPU minimization uses the shared lease; driver/device validation is separate.')
    if linux:
        packages='Runtime/LinuxPackages/science/'
        foundation=runtime_ok and present('Scientific/science_core.py','Agent/scientific_tool_bridge.py')
        kicad_ok=runtime_ok and present('Runtime/KiCad/linux-x64/bin/kicad-cli',
            'Runtime/LinuxSystem/kicad/usr/bin/kicad-cli',
            'Runtime/LinuxSystem/kicad/usr/lib/kicad/ld-linux-x86-64.so.2',
            'Runtime/LinuxSystem/kicad/usr/lib/kicad/_eeschema.kiface',
            'Runtime/LinuxSystem/kicad/usr/lib/kicad/_pcbnew.kiface',
            'Runtime/LinuxSystem/kicad-resources/usr/share/kicad/symbols/Device.kicad_sym',
            'Runtime/LinuxSystem/kicad-resources/usr/share/kicad/footprints/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod',
            'Runtime/LinuxSystem/kicad-resources/usr/share/kicad/3dmodels/Resistor_SMD.3dshapes/R_0805_2012Metric.step') and all(
                verified_receipt(path) for path in ('Maintenance/Imports/linux-system-kicad.json',
                                                   'Maintenance/Imports/linux-system-kicad-resources.json'))
        for key,required,detail in (
            ('science',(), 'Portable Linux science dispatcher; selected CPU workflows checked in offline guest'),
            ('scienceCore',('numpy','scipy','sympy','matplotlib'),'Linux NumPy/SciPy/SymPy/Matplotlib; on-demand CPU/RAM'),
            ('scienceCad',('cadquery','OCP','gmsh.py','libgmsh.so.4.15'),'Linux CadQuery/OCP/Gmsh; representative CAD/mesh guest checks passed'),
            ('scienceMech',('scipy','pymunk'),'Linux beam/truss and rigid-body CPU tools'),
            ('scienceElectrical',('numpy',),'DC/RC CPU analysis; '+('Linux KiCad CLI, libraries and resources packaged; SVG/BOM/STEP exports checked in offline CPU guest' if kicad_ok else 'optional Linux KiCad export payload missing/incomplete')),
            ('scienceChem',('rdkit',),'Linux RDKit; representative molecule calculation checked in guest'),
            ('scienceGenomics',('Bio','sbol3'),'Linux BioPython/SBOL and native MAFFT; actual guest alignment passed'),
            ('scienceProtein',('openmm',),'Linux OpenMM CPU guest calculation passed; physical OpenCL GPU unvalidated'),
            ('sciencePhysics',('scipy','pymunk'),'Linux numerical and rigid-body CPU tools'),
        ):
            add(key,foundation and present(*(packages+p for p in required)),detail)
        add('scienceGpu',foundation and present(packages+'openmm'),
            'OpenMM auto uses CPU; explicit OpenCL uses the GPU lease; driver/probe required, physical Linux GPU validation pending')
        add('stt',runtime_ok and present('Runtime/LinuxPackages/extras/faster_whisper/__init__.py','SpeechToText/models/whisper-base/model.bin'),
            'Linux faster-whisper / CTranslate2 and Base model; actual CPU inference passed in offline Linux guest; physical audio devices pending')
        add('voice',runtime_ok and gpu_layer and present('Voice/Qwen3-TTS/qwen_tts_runner.py'),
            'Linux Qwen voice adapter with isolated CUDA/ROCm layers; imports checked, physical GPU voice pending; English Piper is separate')
        from music_understanding_runtime import available
        music_ok=runtime_ok and present('Agent/music_understanding_enhanced.py',
            'Agent/music_understanding_runtime.py','MusicUnderstanding/runtime_driver.py',
            'Runtime/LinuxTorch/cpu/torch/__init__.py','Runtime/LinuxTorch/cpu/torchaudio/__init__.py',
            'Runtime/LinuxPackages/media/transformers/__init__.py',
            'Runtime/LinuxPackages/media/soundfile.py') and verified_receipt('Maintenance/Imports/linux-torch-cpu.json')
        specialists={label:bool(music_ok and available(root,kind)[0]) for label,kind in
                     (('CLAP','clap'),('Demucs','separate-vocals'),('MOSS','moss'))}
        detail='; '.join(label+(' packaged' if ok else ' missing/incomplete') for label,ok in specialists.items())
        detail+='; CLAP/Demucs CPU guest inference checked; full MOSS and physical GPU inference unvalidated; independent RAM/device admission'
        status='INSTALLED' if all(specialists.values()) else 'PARTIAL' if runtime_ok and present('Agent/music_understanding_enhanced.py') else 'CHECK'
        rows['musicUnderstand']=(status,detail)
    return rows


def media_model_files(root):
    """Include complete checkpoints and adapters, not just denoiser files."""
    base = Path(root)/"Generative/ComfyUI_windows_portable/ComfyUI/models"
    groups = {}
    for category in ("diffusion_models", "checkpoints", "loras"):
        folder = base/category
        rows = []
        if folder.is_dir():
            for p in sorted(folder.rglob("*")):
                if p.is_file() and p.suffix.lower() in {".safetensors", ".gguf", ".ckpt", ".pt", ".pth"}:
                    if not p.resolve().is_relative_to(base.resolve()):
                        continue
                    hint = " [Vulkan / CPU / NVIDIA fallback]" if category == "checkpoints" and p.name == "v1-5-pruned-emaonly.safetensors" else ""
                    rows.append(f"{p.relative_to(base).as_posix()}{hint} · {p.stat().st_size/1024**3:.2f} GiB")
        groups[category] = rows
    extra=[]
    edit=Path(root)/'Models/InstructionEdit'
    if (edit/'model_index.json').is_file() and (edit/'unet/diffusion_pytorch_model.fp16.safetensors').is_file():
        size=sum(p.stat().st_size for p in edit.rglob('*.safetensors'))
        extra.append(f'Models/InstructionEdit [InstructPix2Pix; scaled instruction/masked edits]· {size/1024**3:.2f} GiB')
    return groups["checkpoints"] + groups["diffusion_models"]+extra, groups["loras"]
