from __future__ import annotations
import argparse, json, os, re, socket, subprocess
from pathlib import Path

VERSION="2026.10.10"

def _port(port:int)->bool:
    try:
        with socket.create_connection(("127.0.0.1",int(port)),timeout=.15): return True
    except OSError:return False

def _commands(root:Path)->tuple[set[str],str|None]:
    p=root/"Agent"/"ai_tools.py"
    if not p.exists():return set(),"Agent/ai_tools.py missing"
    try:t=p.read_text(encoding="utf-8",errors="ignore")
    except Exception as e:return set(),str(e)
    return set(re.findall(r"add_parser\s*\(\s*['\"]([^'\"]+)['\"]",t,re.I|re.S)),None

def _pkg(packages:Path,*names:str)->bool:
    for name in names:
        if (packages/name).exists(): return True
        if any(packages.glob(name+"-*.dist-info")): return True
        if any(packages.glob(name.replace("-","_")+"-*.dist-info")): return True
    return False

def _gmsh(packages:Path)->bool:
    if not (packages/"gmsh.py").exists():return False
    return any(packages.rglob("libgmsh.so*")) or any(packages.glob("gmsh*.dll")) or any(packages.rglob("gmsh*.dll")) or any(packages.rglob("gmsh.dll"))

def detect(root:Path)->dict:
    root=Path(root).resolve(); cmds,cmd_err=_commands(root)
    linux=os.name!='nt'
    def ex(p):
        if linux:
            replacements={'LLM/llamacpp/llama-server.exe':'LLM/backends/linux-cuda/llama-server',
                'Runtime/AccountPython/packages/':'Runtime/AccountPython/linux-packages/',
                'Runtime/AMDPython/packages/':'Runtime/LinuxTorch/rocm7.2/',
                'Voice/Piper/packages/':'Runtime/LinuxPackages/extras/',
                'Maintenance/Imports/amd-runtime-lock.json':'Maintenance/Imports/linux-torch-rocm7.2.json'}
            for old,new in replacements.items():p=p.replace(old,new)
            p=p.replace('LLM/backends/windows-','LLM/backends/linux-').replace('/llama-server.exe','/llama-server')
            p=p.replace('Runtime/StableDiffusion/windows-','Runtime/StableDiffusion/linux-').replace('/sd-cli.exe','/sd-cli')
        return (root/p).exists()
    packages=root/('Runtime/LinuxPackages/science' if linux else 'Runtime/ScientificPython/packages')
    caps=[]
    def add(key,label,ok,detail):caps.append({"key":key,"label":label,"installed":bool(ok),"detail":detail})
    qserver=any(ex(p) for p in ("LLM/llamacpp/llama-server.exe","LLM/backends/windows-vulkan/llama-server.exe","LLM/backends/windows-cpu/llama-server.exe")); qmodel=(root/"LLM/models").exists() and any((root/"LLM/models").glob("*.gguf"))
    add("qwen","Qwen / llama.cpp",qserver and qmodel,"local llama-server + GGUF model")
    try:
        cfg=json.loads((root/"Agent/hardware_profiles.json").read_text(encoding="utf-8"))
        for m in cfg["models"]:
            ok=ex(m["path"]) and (not m.get("projector") or ex(m["projector"]))
            add("model_"+m["id"],"Chat model · "+m["id"],ok,m["path"]+"; presence only")
    except (OSError,ValueError,KeyError) as exc:add("model_policy","Adaptive model policy",False,str(exc))
    for backend,path in (("cuda","LLM/llamacpp/llama-server.exe"),("vulkan","LLM/backends/windows-vulkan/llama-server.exe"),("cpu","LLM/backends/windows-cpu/llama-server.exe")):
        add("backend_"+backend,"Chat backend · "+backend,ex(path),("Linux x64" if linux else "Windows x64")+"; presence only; driver/physical-host tests separate")
    add("missions","Persistent missions",ex("Agent/mission_supervisor.py"),"Explicitly armed missions, Windows jobs/Linux delegated cgroups; interrupted effects require review")
    add("mission_context","Mission rolling context",ex("Agent/mission_context.py"),"Tokenizer-budgeted evidence excerpts; full history on SSD; numbered history retrieval")
    add("mission_accounts","Dedicated mission accounts",ex("Agent/mission_accounts.py") and ex("Runtime/AccountPython/packages/eth_account/__init__.py"),"Full missions only; encrypted portable vault; IMAP/SMTP and EVM adapters; simulated/offline tests; live accounts must be configured")
    add("video_small","Wan 1.3B native video",ex("Agent/native_video.py") and ex("Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/wan2.1_t2v_1.3B_fp16.safetensors") and ex("Generative/ComfyUI_windows_portable/ComfyUI/models/text_encoders/umt5-xxl-encoder-Q4_K_M.gguf"),"Short silent text-to-video on Windows/Linux Vulkan/CPU; physical Radeon validation pending; 14/18 GiB free RAM")
    add("mission_vm","Offline VM shell runner",ex("Agent/vm_runner.py"),"Hardware virtualization/WHPX or KVM required; model/controller stay on host")
    add("image_cpu","SD1.5 CPU image profile",ex("Workflows/API/SD15_T2I_Portable.json") and ex("Generative/ComfyUI_windows_portable/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors"),"Memory admission required; no Radeon/CPU advanced video guarantee")
    add("stt_cpu","Whisper Base CPU profile",ex("SpeechToText/models/whisper-base/model.bin"),"Offline transcription subject to RAM")
    for backend in ("vulkan", "cpu"):
        add("image_native_"+backend,"SD1.5 native "+backend+" engine",ex("Runtime/StableDiffusion/windows-"+backend+"/sd-cli.exe"),"Native platform runtime present; driver/inference and RAM checks separate")
    add("native_chat","Native Chat",ex("ControlCenter/native_chat.py"),"native frontend + local history")
    add("local_accounts","Private user accounts",all(ex(p) for p in ("Agent/local_accounts.py","Agent/profile_workspace.py","ControlCenter/account_gate.py")),"Password login, admin-approved accounts and per-user files; encrypted when locked; active workspaces are not OS isolation")
    add("effort_controls","Chat and tool effort controls",ex("Agent/effort_policy.py") and ex("ControlCenter/chat_effort_ui.py"),"Separate settings; slow-hardware warnings/session unlock; hard memory/backend limits still apply")
    add("amd_torch","AMD ROCm media package layer",ex("Runtime/AMDPython/packages/torch/__init__.py") and ex("Maintenance/Imports/amd-runtime-lock.json"),"Qwen voice, MuseTalk, instruction/VACE editing, ComfyUI, music and text/video SFX adapters; actual AMD compute/driver/memory checks required; physical Radeon validation pending")
    add("memory","Context / persistent memory",ex("ControlCenter/persistent_memory.py"),"rolling context + cross-session memory")
    add("web","Web tools",ex("Agent/web_tools.py"),"search / fetch / research / image retrieval")
    add("preview","Media preview",any(ex(x) for x in ("Agent/media_server.py","Agent/media_preview_server.py","Services/media_preview_server.py")),"localhost generated-output preview")
    add("gpu_handoff","Dynamic GPU / VRAM handoff",ex("Agent/service_manager.py"),"exclusive GPU lease + generation-gated Qwen restore")
    add("image","FLUX image generation/edit",("image" in cmds or "edit" in cmds),"generation/edit/masking routes")
    add("video","Wan/VACE video",("video" in cmds and ("video-edit" in cmds or "video-range-edit" in cmds)),"generation + VACE/range editing")
    add("video_understanding","Video understanding",("video-understand" in cmds or "video-analyze" in cmds),"casual/forensic multimodal analysis")
    add("tts","Qwen3-TTS",any(x in cmds for x in ("voice-design","voice-clone","voice-custom")),"on-demand voice generation")
    add("tts_cpu","CPU speech / Piper", "voice-say" in cmds and ex("Voice/Piper/models/en_US-ljspeech-medium.onnx") and ex("Voice/Piper/packages/piper/__init__.py"), "offline English speech, CPU, no cloning/design")
    add("stt","Speech-to-text","transcribe" in cmds,"faster-whisper route")
    add("musetalk","MuseTalk / dialogue",any(x in cmds for x in ("lip-sync","dialogue-video","video-dialogue")),"lip-sync/dialogue routes")
    add("mmaudio","MMAudio / SFX",any(x in cmds for x in ("sfx","video-sfx","sound-video")),"Foley/SFX routes")
    add("music","ACE-Step music","music" in cmds,"on-demand music generation")
    add("music_understanding","Music understanding",any(x in cmds for x in ("music-understand","music-analyze")),"Deterministic analysis plus independently admitted MOSS/CLAP/Demucs specialists; reports which actually ran")

    science_core=ex("Scientific/science_core.py") and ex("Agent/scientific_tool_bridge.py") and "science" in cmds
    np=_pkg(packages,"numpy"); scipy=_pkg(packages,"scipy"); sympy=_pkg(packages,"sympy"); mpl=_pkg(packages,"matplotlib")
    rdkit=_pkg(packages,"rdkit"); bio=_pkg(packages,"Bio","biopython"); sbol=_pkg(packages,"sbol3"); openmm=_pkg(packages,"openmm"); pymunk=_pkg(packages,"pymunk"); ocp=_pkg(packages,"OCP","cadquery-ocp")
    gmsh=_gmsh(packages)
    add("science","Science Workbench",science_core,"deterministic on-demand science/engineering dispatcher")
    add("science_core","Science · math / stats / signal",science_core and np and scipy and sympy and mpl,"NumPy/SciPy/SymPy/Matplotlib; CPU/RAM on demand")
    cadquery=_pkg(packages,"cadquery")
    add("science_cad","Science · CAD / mesh",science_core and gmsh and ocp and cadquery,"CadQuery + OCP + Gmsh; CAD model/blueprint/mesh inspection")
    add("science_mechanical","Science · mechanical",science_core and scipy and pymunk,"beam, truss2d, rigid-body 2D simulation")
    add("science_electrical","Science · electrical",science_core,"DC/RC analysis; optional KiCad export is listed separately")
    kicad=(ex('Runtime/KiCad/linux-x64/bin/kicad-cli') and ex('Runtime/LinuxSystem/kicad/usr/bin/kicad-cli') if linux else
           any(ex(p) for p in ('Tools/KiCad/bin/kicad-cli.exe','Tools/KiCad/kicad-cli.exe')))
    add("science_kicad","Science · KiCad export",science_core and kicad,"Bundled CLI presence for this operating system; recipient runtime and design resource validation are separate")
    add("science_chem","Science · chemistry",science_core and rdkit,"RDKit describe/render/conformer")
    add("science_genomics","Science · genomics / circuits",science_core and bio and sbol,"BioPython alignment/translation + SBOL circuit export")
    add('science_biology','Science · biology workbench',science_core and bio and scipy and ex('Scientific/biology.py') and ex('Scientific/biology_tool.py'),
        'Plasmid assembly/GenBank, measured parts ranking, circuit/bioprocess CPU simulations; NCBI/iGEM online retrieval')
    add('science_design','Science · ProteinMPNN CPU design',science_core and ex('Scientific/protein_design.py') and ex('Maintenance/Imports/protein-mpnn.json') and ex('Runtime/ProteinDesign/vendor/vanilla_model_weights/v_48_020.pt'),
        'Pinned fixed-backbone single-chain CPU inverse folding; assets checked before use; no GPU or de novo fold backend')
    add("science_protein","Science · protein / OpenMM",science_core and openmm,"PDB inspect/render + OpenMM minimization")
    add("science_physics","Science · physics",science_core and scipy and pymunk,"projectile, spring-mass, rigid-body 2D")
    add("science_coupled_demo", "Science · coupled mechanics demo",
        science_core and np and ex('Scientific/coupled_physics.py') and ex('Scientific/coupled_physics_tool.py') and ex('Scientific/physics_viewer.py'),
        "Bounded CPU 2D/3D water-like liquid + elastic block + rigid object; offline playback; educational approximation, not validated CFD or air simulation")
    svc=(root/"Agent/service_manager.py")
    st=svc.read_text(encoding="utf-8",errors="ignore") if svc.exists() else ""
    plugins=packages/'OpenMM.libs/lib/plugins'
    cuda_plugin=(plugins/('libOpenMMCUDA.so' if linux else 'OpenMMCUDA.dll')).is_file()
    opencl_plugin=(plugins/('libOpenMMOpenCL.so' if linux else 'OpenMMOpenCL.dll')).is_file()
    add("science_cuda","Science · OpenMM CUDA plugin",science_core and openmm and cuda_plugin and "science_workload" in st and "openmm-cuda" in st,"Plugin presence plus leased route; driver/device compute still requires validation. A lease alone does not install CUDA support.")
    add("science_opencl","Science · OpenMM OpenCL plugin",science_core and openmm and opencl_plugin and "science_workload" in st,"Explicit protein.minimize platform=opencl; shared GPU lease; installed plugin does not prove Radeon driver compatibility")

    add("diagnostics","Diagnostics",ex("Tools/component_diagnostics.py") and ex("Tools/system_test.py") and ex("Tools/component_smoke.py"),"full + targeted + functional Science + per-component smoke checks")
    add("maintenance","Maintenance",ex("Tools/maintenance_storage.py") and ex("Tools/reference_integrity.py") and ex("Tools/dependency_probe_current.py"),"science-aware storage/duplicate audit + conservative cleanup + dependency/reference checks")

    add('knowledge','Local document knowledge',ex('Agent/knowledge_base.py') and ex('Runtime/Knowledge/model/manifest.json') and ex('Runtime/Knowledge/packages/pypdfium2/__init__.py'),'Workspace: transactional folder sync, PDF/Office/OCR, local semantic + keyword retrieval with source citations')
    add('mcp','MCP connections',ex('Agent/mcp_client.py') and ex('Runtime/Knowledge/packages/jsonschema/__init__.py'),'Workspace: stdio and Streamable HTTP tools, explicit per-account grants; pending effects require review')
    add('workflows','Reusable workflows',ex('Agent/workflows.py') and ex('ControlCenter/workspace_panel.py'),'Saved typed inputs, forward conditions, approval points and durable bounded step execution')
    add('computer','Native computer control',os.name=='nt' and ex('Agent/desktop_control.py'),'Windows visible-window grants per login; local vision screenshots and native mouse/keyboard/window actions. Other OS adapters unavailable.')
    services={"qwen":{"port":8080,"open":_port(8080)},"comfyui":{"port":8188,"open":_port(8188)},"acestep":{"port":8001,"open":_port(8001)}}
    pp=next((p for p in range(8765,8781) if _port(p)),None);services["preview"]={"port":pp,"open":pp is not None}
    # OpenWebUI is intentionally absent: it was removed from the current product surface.
    inventory={}
    for key,base in (("agent_python",root/"Agent"),("controlcenter_python",root/"ControlCenter"),("scientific_python",root/"Scientific")):
        inventory[key]=sorted(str(x.relative_to(root)).replace("\\","/") for x in base.glob("*.py")) if base.exists() else []
    rr=root/"Runtime"; inventory["runtimes"]=sorted(x.name for x in rr.iterdir() if x.is_dir() and not x.name.startswith(".")) if rr.exists() else []
    known={"status","version","service","preview","image","edit","mask","inpaint","autoedit","route","video","video-edit","video-range-edit","video-understand","video-analyze","vision-benchmark","video-vision-benchmark","music","music-understand","music-analyze","score-video","voice-design","voice-clone","voice-custom","transcribe","lip-sync","dialogue-video","video-dialogue","sfx","video-sfx","sfx-inpaint","sound-video","media-info","audio-edit","audio-mix","video-adjust","audio-inpaint","video-inpaint","mux","cancel","science"}
    known.add("voice-say")
    known.add("video-small")
    return {"version":VERSION,"commands":sorted(cmds),"command_error":cmd_err,"capabilities":caps,"services":services,"module_inventory":inventory,"unclassified_routes":sorted(cmds-known)}

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--json",action="store_true");ns=ap.parse_args();d=detect(Path(ns.root));print(json.dumps(d,indent=2) if ns.json else "\n".join(f"{'OK' if c['installed'] else '--'} {c['label']}: {c['detail']}" for c in d['capabilities']));return 0
if __name__=="__main__":raise SystemExit(main())
