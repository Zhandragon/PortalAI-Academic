from __future__ import annotations
import argparse,json,os,re,shutil,sys
sys.path.insert(0,str(__import__("pathlib").Path(__file__).resolve().parent))
from pathlib import Path
VERSION="2026.10.16"
def rotate(root,text,data):
 from maintenance_reports import save
 save(root,"media_stack_verify",text,data,1 if data['counts']['FAIL'] else 0)
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--json",action="store_true");ns=ap.parse_args();r=Path(ns.root).resolve();rows=[]
 try:t=(r/"Agent/ai_tools.py").read_text(encoding="utf-8",errors="ignore")
 except Exception:t=""
 cmds=set(re.findall(r"add_parser\s*\(\s*['\"]([^'\"]+)['\"]",t,re.I|re.S))
 def add(label,need=(),files=(),any_route=False):
  routes=(bool(set(need)&cmds) if any_route else set(need).issubset(cmds));fok=all((r/f).exists() for f in files);rows.append({"status":"PASS" if routes and fok else ("WARN" if routes or fok else "FAIL"),"label":label,"detail":f"routes={sorted(set(need)&cmds)} files={'ok' if fok else 'missing'}"})
 add("FLUX generation/edit",("image","edit"),("Agent/comfy_bridge.py",));add("Image masking/inpaint",("mask","inpaint"),("Agent/comfy_bridge.py",));add("Wan generation + VACE/range",("video","video-edit","video-range-edit"),("Agent/comfy_bridge.py",));add("Video understanding",("video-understand",),("Agent/video_understanding_bridge.py",),True);add("Visible dialogue / MuseTalk",("lip-sync","dialogue-video","video-dialogue"),("Agent/musetalk_bridge.py",));add("MMAudio SFX/Foley/inpaint",("sfx","video-sfx","sfx-inpaint"),("Agent/sfx_bridge.py",));add("ACE-Step music",("music",),());add("Music understanding",("music-understand",),("Agent/music_understanding_bridge.py",),True);add("Qwen3-TTS",("voice-design","voice-clone","voice-custom"),(),True);add("Speech-to-text",("transcribe",),("Agent/stt_bridge.py",));add("Deterministic media editing",("media-info","audio-edit","audio-mix","video-adjust"),("Agent/media_edit_bridge.py",));add("Diffusive media inpainting",("audio-inpaint","video-inpaint"),("Agent/media_edit_bridge.py",));add("Media preview",("preview",),(),True)
 add("CPU SD1.5 image profile",("image",),("Agent/media_policy.py","Workflows/API/SD15_T2I_Portable.json","Generative/ComfyUI_windows_portable/ComfyUI/models/checkpoints/v1-5-pruned-emaonly.safetensors"))
 add("CPU Whisper Base profile",("transcribe",),("SpeechToText/models/whisper-base/model.bin","Agent/media_policy.py"))
 piper_package='Voice/Piper/packages/piper/__init__.py' if os.name=='nt' else 'Runtime/LinuxPackages/extras/piper/__init__.py'
 add("CPU Piper English speech",("voice-say",),("Voice/Piper/models/en_US-ljspeech-medium.onnx",piper_package,"Agent/tts_policy.py"))
 for backend in ("cpu", "vulkan"):
  runtime='Runtime/StableDiffusion/'+('windows-' if os.name=='nt' else 'linux-')+backend+('/sd-cli.exe' if os.name=='nt' else '/sd-cli')
  add("Native SD1.5 "+backend+" image runtime",("image",),("Agent/sdcpp_bridge.py",runtime))
 add('Native small-video route',('video-small',),('Agent/native_video.py',))
 add('Scaled audio/video editing adapters',('audio-inpaint','sfx-inpaint','dialogue-video'),('Agent/audio_inpaint_amd_bridge.py','Agent/dialogue_portable.py','Agent/vace_reference.py'))
 add('Inline media controls',('preview',),('ControlCenter/native_media_player.py','Agent/media_server.py'))
 from installed_feature_checks import rows as feature_rows, MEDIA_FEATURES
 for feature in MEDIA_FEATURES:rows.extend(feature_rows(r,feature))
 from vision_diagnostics import rows as vision_rows
 rows.extend(vision_rows(r))
 coverage='Structural route/file presence only; no dependency imports, checkpoint integrity validation, media inference, physical GPU validation or playback test.'
 counts={s:sum(x['status']==s for x in rows) for s in ('PASS','WARN','FAIL')};data={"version":VERSION,"rows":rows,"commands":sorted(cmds),"counts":counts,'coverage':coverage};text="="*76+f"\nPortableAI v{VERSION} Media Stack Verification\n"+"="*76+'\n'+coverage+'\n\n'+"\n".join(f"[{x['status']}] {x['label']}: {x['detail']}" for x in rows)+f"\n\nPASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}\n";rotate(r,text,data)
 if ns.json:print(json.dumps(data,indent=2))
 else:print(text)
 return 1 if counts['FAIL'] else 0
if __name__=="__main__":raise SystemExit(main())
