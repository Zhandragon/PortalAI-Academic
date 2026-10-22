from __future__ import annotations
import argparse,json,os,re,socket,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from capability_registry import detect
from lifecycle_probe import probe_qwen,port_pids_windows
from science_smoke import run_suite as run_science_suite
from diagnostic_catalog import resolve, source_rows, SOURCE_ONLY, COVERAGE
from installed_feature_checks import FEATURES, rows as feature_rows
VERSION="2026.10.11"; CREATE_NO_WINDOW=getattr(subprocess,"CREATE_NO_WINDOW",0x08000000 if os.name=="nt" else 0)
def run(args,cwd,timeout=20,env=None):
    return subprocess.run(args,cwd=str(cwd),capture_output=True,text=True,errors="replace",timeout=timeout,env=env,creationflags=(CREATE_NO_WINDOW if os.name=="nt" else 0))
def row(status,label,detail=""):return {"status":status,"label":label,"detail":detail}
def _port(p):
    try:
        with socket.create_connection(("127.0.0.1",int(p)),timeout=.2):return True
    except OSError:return False
def _ai_commands(root):
    try:t=(root/"Agent/ai_tools.py").read_text(encoding="utf-8",errors="ignore")
    except Exception:return set()
    return set(re.findall(r"add_parser\s*\(\s*['\"]([^'\"]+)['\"]",t,re.I|re.S))
def _exists_any(root,*rels):return any((root/x).exists() for x in rels)
def _dir_nonempty(p):
    try:return p.is_dir() and next(p.iterdir(),None) is not None
    except Exception:return False

def component_rows(root:Path,component:str,*,science_functional=True)->list[dict]:
    try:
        selection=resolve(component)
    except ValueError as exc:
        return [row('FAIL','Unknown diagnostic component',str(exc))]
    component=selection['label']
    if selection['argument'] in FEATURES:return feature_rows(root,selection['argument'])
    if selection['argument'] in ('small_vision','vision_integrity'):
        from vision_diagnostics import rows as vision_rows
        return vision_rows(root,verify=selection['argument']=='vision_integrity' and science_functional)
    if selection['argument']=='activity' and science_functional:
        from activity_probe import rows as activity_rows
        return source_rows(root,component) + activity_rows()
    if selection['argument'] in SOURCE_ONLY:
        result=source_rows(root,component)
        if selection['argument']=='biology':
            from science_extension_checks import rows as extension_rows
            result.extend(extension_rows(root))
        return result
    if os.name!='nt' and selection['argument']!='web':
        from linux_system_test import rows
        result = rows(Path(root).resolve(),component,imports=science_functional)
        if selection['argument']=='all':
            for name in sorted(SOURCE_ONLY): result.extend(source_rows(root,name))
            result.extend(feature_rows(root))
        return result
    root=Path(root).resolve();cmds=_ai_commands(root);c=component.lower().strip();rows=[]
    def add(s,l,d=""):rows.append(row(s,l,d))
    if c in ("all","qwen"):
        q=probe_qwen(root);add("FAIL" if q.get('state')=='conflict' else "PASS" if q.get("active") else "WARN","Qwen listener/ownership",f"state={q.get('state')} ready={q.get('ready')} sleeping={q.get('sleeping')} listeners={len(q.get('listeners') or [])}")
        add("PASS" if _exists_any(root,"LLM/llamacpp/llama-server.exe","LLM/backends/windows-vulkan/llama-server.exe","LLM/backends/windows-cpu/llama-server.exe") else "FAIL","Qwen llama-server","portable executable")
        add("PASS" if _dir_nonempty(root/"LLM/models") else "FAIL","Qwen model directory","LLM/models")
    if c in ("all","comfyui"):
        base=root/"Generative/ComfyUI_windows_portable";ok=base.exists() and _exists_any(root,"Generative/ComfyUI_windows_portable/ComfyUI/main.py","Generative/ComfyUI_windows_portable/run_nvidia_gpu.bat")
        add("PASS" if ok else "FAIL","ComfyUI portable runtime",str(base))
        listening=_port(8188)
        add("WARN" if listening else "PASS","ComfyUI port observation",'Port 8188 is open; ownership/health not established by this check.' if listening else 'Port 8188 idle; no running service to validate.')
        add("PASS" if _dir_nonempty(root/"Workflows/API") else "WARN","ComfyUI API workflows","Workflows/API")
    if c in ("all","ace-step","acestep","ace"):
        base=root/"Music/ACE-Step-1.5";add("PASS" if base.exists() else "FAIL","ACE-Step source/runtime",str(base));add("PASS" if _dir_nonempty(base/"checkpoints") else "WARN","ACE-Step checkpoints","checkpoint directory")
        add("PASS" if "music" in cmds else "FAIL","ACE-Step route","ai_tools music")
    if c in ("all","qwen3-tts","tts"):
        pys=[root/"Runtime/BootstrapPython/python.exe"]
        py=next((x for x in pys if x.exists()),None);models=root/"Voice/Qwen3-TTS/models";add("PASS" if py else "WARN","Qwen3-TTS interpreter",str(py or 'not found')+" + local Voice/Qwen3-TTS/.venv/Lib/site-packages (copied venv launcher not used)")
        add("PASS" if _dir_nonempty(models) else "FAIL","Qwen3-TTS models",str(models));add("PASS" if any(x in cmds for x in ("voice-design","voice-clone","voice-custom")) else "FAIL","Qwen3-TTS routes","voice-design/clone/custom")
    if c in ("all","musetalk"):
        if science_functional:
            try:
                sys.path.insert(0,str(root/'Agent'))
                from musetalk_runtime import probe
                result=probe(root)
                add("PASS" if result['ok'] else "FAIL","MuseTalk configured runtime imports",result['detail'])
            except Exception as exc:add("FAIL","MuseTalk configured runtime imports",str(exc))
        else:
            add("PASS" if (root/'Agent/musetalk_runtime.py').is_file() else "FAIL","MuseTalk configured runtime source","Presence only; imports skipped in structural mode.")
        source=_exists_any(root,"Video/MuseTalk","MuseTalk","Video/MuseTalk-1.5","Generative/MuseTalk");add("PASS" if source else "FAIL","MuseTalk source/runtime","portable MuseTalk tree")
        add("PASS" if (root/"Agent/musetalk_bridge.py").exists() else "FAIL","MuseTalk bridge","Agent/musetalk_bridge.py");add("PASS" if {"lip-sync","dialogue-video","video-dialogue"}.issubset(cmds) else "WARN","MuseTalk/dialogue routes",str(sorted({"lip-sync","dialogue-video","video-dialogue"}&cmds)))
    if c in ("all","mmaudio"):
        source=any((root/x/"demo.py").exists() for x in ("Services/MMAudio","Engines/MMAudio","External/MMAudio","ThirdParty/MMAudio","Tools/MMAudio","MMAudio","Agent/MMAudio")); py=next((root/x for x in ("Runtime/MMAudioPython/python.exe","Runtime/MMAudioPython/Scripts/python.exe","Runtime/MMAudio/python.exe","Runtime/Python312_MMAudio/python.exe","Agent/.runtime/mmaudio/python.exe") if (root/x).exists()), root/"Runtime/MMAudioPython/python.exe")
        add("PASS" if source else "FAIL","MMAudio source","portable source tree");add("PASS" if py.exists() else "FAIL","MMAudio portable runtime",str(py));add("PASS" if (root/"Agent/sfx_bridge.py").exists() else "FAIL","MMAudio bridge","Agent/sfx_bridge.py")
        add("PASS" if any(x in cmds for x in ("sfx","video-sfx","sfx-inpaint")) else "FAIL","MMAudio/SFX routes",str(sorted({"sfx","video-sfx","sfx-inpaint"}&cmds)))
    if c in ("all","stt"):
        add("PASS" if (root/"Agent/stt_bridge.py").exists() else "FAIL","STT bridge","Agent/stt_bridge.py");add("PASS" if "transcribe" in cmds else "FAIL","STT route","transcribe")
        add("PASS" if _dir_nonempty(root/"SpeechToText") else "WARN","STT portable data/runtime","SpeechToText")
    if c in ("all","media preview","preview"):
        imp=next((root/x for x in ("Agent/media_server.py","Agent/media_preview_server.py","Services/media_preview_server.py") if (root/x).exists()),None);listeners=[p for p in range(8765,8781) if _port(p)]
        add("PASS" if imp else "FAIL","Media preview implementation",str(imp or 'missing'));add("PASS" if "preview" in cmds else "WARN","Preview route","ai_tools preview");add("WARN" if listeners else "PASS","Preview port observation",'No listener; idle.' if not listeners else f"Open ports {listeners}; ownership, authorization and seeking are not validated by this check.")
    if c in ("all","flux image","flux","image"):
        have={"image","edit","mask","inpaint"}&cmds; modeldir=root/"Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models"
        add("PASS" if {"image","edit"}.issubset(cmds) else "FAIL","FLUX generation/edit routes",str(sorted(have)))
        add("PASS" if modeldir.exists() and any(modeldir.glob("flux*")) else "WARN","FLUX checkpoints","diffusion_models/flux*")
    if c in ("all","wan/vace video","wan","vace","video"):
        need={"video","video-edit","video-range-edit"};add("PASS" if need.issubset(cmds) else "WARN","Wan/VACE routes",str(sorted(need&cmds)))
        add("PASS" if (root/"Workflows/API").exists() and any((root/"Workflows/API").glob("*VACE*")) else "WARN","VACE workflows","Workflows/API/*VACE*")
    if c in ("all","media editing","media"):
        need={"media-info","audio-edit","audio-mix","video-adjust","audio-inpaint","video-inpaint"};add("PASS" if {"media-info","audio-edit","audio-mix","video-adjust"}.issubset(cmds) else "WARN","Deterministic media-edit routes",str(sorted(need&cmds)));add("PASS" if (root/"Agent/media_edit_bridge.py").exists() else "FAIL","Media edit bridge","Agent/media_edit_bridge.py")
    if c in ("all","music understanding","music-understanding"):
        add("PASS" if any(x in cmds for x in ("music-understand","music-analyze")) else "FAIL","Music understanding route",str(sorted({"music-understand","music-analyze"}&cmds)));add("PASS" if (root/"Agent/music_understanding_bridge.py").exists() else "FAIL","Music understanding bridge","Agent/music_understanding_bridge.py")
    if c in ("all","web tools","web"):
        add("PASS" if all((root/p).exists() for p in ('Agent/web_tools.py','Agent/web_state.py')) else "FAIL","Web tools implementation","Source presence only. Select Web tools for a live provider check.")
        if c!='all' and science_functional:
            try:
                sys.path.insert(0,str(root/'Agent'))
                from platform_runtime import python_path
                result=run([str(python_path(root)),'-B','-I',str(root/'Agent/web_tools.py'),'selftest'],root,timeout=50)
                data=json.loads(result.stdout)
                add('PASS' if result.returncode==0 and data.get('success') else 'FAIL','Live web search',json.dumps(data))
            except Exception as exc:add('FAIL','Live web search',str(exc))
    if c in ("all","science"):
        if not science_functional:
            from science_extension_checks import rows as extension_rows
            rows.extend(extension_rows(root))
        if science_functional:
            try:
                res=run_science_suite(root);rows.extend(res.get("rows") or [])
            except Exception as e:add("FAIL","Science functional suite",f"{type(e).__name__}: {e}")
        else:
            reg=detect(root);sci=[x for x in reg.get("capabilities",[]) if x.get("key","").startswith("science")];add("PASS" if sci and all(x.get("installed") for x in sci if x.get("key")!="science_cuda") else "WARN","Science structural inventory",f"{sum(bool(x.get('installed')) for x in sci)}/{len(sci)} science capability rows installed")
    if c=='all':
        from vision_diagnostics import rows as vision_rows
        rows.extend(vision_rows(root))
        for name in sorted(SOURCE_ONLY):rows.extend(source_rows(root,name))
        rows.extend(feature_rows(root))
    if not rows:add("FAIL","Unknown diagnostic component",component)
    return rows
def run_suite(root:Path,component="All",science_functional=True):
    rows=component_rows(root,component,science_functional=science_functional);counts={s:sum(x.get("status")==s for x in rows) for s in ("PASS","WARN","FAIL")};return {"version":VERSION,"component":component,"counts":counts,"rows":rows,'coverage':COVERAGE}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--component",default="All");ap.add_argument("--structural-only",action="store_true");ap.add_argument("--json",action="store_true");ns=ap.parse_args();res=run_suite(Path(ns.root),ns.component,not ns.structural_only)
    if ns.json:print(json.dumps(res,indent=2))
    else:
        print("="*76);print(f"PortableAI v{VERSION} Component Smoke · {ns.component}");print("="*76)
        for x in res["rows"]:print(f"[{x['status']}] {x['label']}: {x.get('detail','')}")
        print("\n"+" ".join(f"{k}={v}" for k,v in res["counts"].items()))
    return 1 if res["counts"]["FAIL"] else 0
if __name__=="__main__":raise SystemExit(main())
