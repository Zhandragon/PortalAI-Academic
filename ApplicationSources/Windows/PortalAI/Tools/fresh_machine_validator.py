from __future__ import annotations
import argparse,json,os,re,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from capability_registry import detect
from component_smoke import run_suite as component_smoke
VERSION="2026.10.10";CREATE_NO_WINDOW=getattr(subprocess,"CREATE_NO_WINDOW",0x08000000 if os.name=="nt" else 0)
def run(args,cwd,timeout=60):return subprocess.run(args,cwd=str(cwd),capture_output=True,text=True,errors="replace",timeout=timeout,creationflags=(CREATE_NO_WINDOW if os.name=="nt" else 0))
def rotate(root,text,data):
 from maintenance_reports import save
 return save(root,'fresh_machine_validation',text,data,1 if data['counts']['FAIL'] else 0)

def required_paths(root):
 sys.path.insert(0,str(root/'Agent'))
 from platform_runtime import python_path,ffmpeg_path
 return [('Portable Python',python_path(root)),('FFmpeg',ffmpeg_path(root)),
         ('Control Center',root/'ControlCenter/PortableAI_GUI.py'),('Agent tools',root/'Agent/ai_tools.py'),
         ('Science core',root/'Scientific/science_core.py'),('Science bridge',root/'Agent/scientific_tool_bridge.py'),
         ('Science package layer',root/('Runtime/ScientificPython/packages' if os.name=='nt' else 'Runtime/LinuxPackages/science'))]
def main():
 ap=argparse.ArgumentParser();ap.add_argument("--root",required=True);ap.add_argument("--run-system-test",action="store_true");ap.add_argument("--json",action="store_true");ns=ap.parse_args();root=Path(ns.root).resolve();rows=[]
 def add(s,l,d=""):rows.append({"status":s,"label":l,"detail":d})
 add("PASS" if os.name=="nt" or sys.platform.startswith('linux') else "FAIL","Host OS",'Windows and Linux x64 packages are supported; current host: '+sys.platform)
 try:
  for l,p in required_paths(root):add("PASS" if p.exists() else "FAIL",l,str(p.relative_to(root)))
 except Exception as exc:add('FAIL','Platform runtime paths',str(exc))
 try:
  cp=run(["nvidia-smi","--query-gpu=name,driver_version","--format=csv,noheader"],root,15);add("PASS" if cp.returncode==0 else "WARN","Optional NVIDIA driver",(cp.stdout or cp.stderr or "").strip())
 except Exception as e:add("WARN","Optional NVIDIA driver",str(e))
 sys.path.insert(0,str(root/'Agent'))
 from runtime_policy import build_plan
 try:
  p=build_plan(root);add("PASS","Current hardware/model admission",f"{p['model']['id']} / {p['backend']['backend']} / {p['model']['context_tokens']} tokens; estimate only")
 except Exception as e:add("WARN","Current hardware/model admission",str(e))
 add("WARN","Recipient validation","Windows and Linux GUI/media/science/VM packages are present as inventoried, with bounded offline guest evidence. This check does not establish physical Radeon, integrated-GPU, 4090, desktop/audio-device or Linux KVM success. Vulkan chat does not enable CUDA media; VM execution requires real hardware virtualization.")
 reg=detect(root);missing=[x['label'] for x in reg['capabilities'] if not x['installed'] and x['key'] not in {'science_cuda'}]
 add("PASS" if not missing else "WARN","Dynamic capability inventory",f"{len(reg['capabilities'])-len(missing)}/{len(reg['capabilities'])} detected; missing/partial: {', '.join(missing[:20])}")
 smoke=component_smoke(root,"All",science_functional=False);add("FAIL" if smoke['counts']['FAIL'] else 'WARN' if smoke['counts']['WARN'] else "PASS","Portable component runtime anchors",str(smoke['counts'])+'; structural checks and observed listeners only, no media imports or inference')
 # recursively inspect first-party launch/control code only; skip third-party/runtime/package trees.
 leaks=[];pats=[("absolute user path",re.compile(r"[A-Za-z]:\\Users\\[^\\\"']+",re.I)),("host ffmpeg probe",re.compile(r"shutil\.which\(\s*['\"]ffmpeg",re.I)),("host env path",re.compile(r"LOCALAPPDATA|%APPDATA%|%LOCALAPPDATA%",re.I))]
 for base in (root/"Agent",root/"ControlCenter",root/"Launchers",root/"Tools",root/"Scientific"):
  if not base.exists():continue
  for p in base.rglob('*'):
   if not p.is_file() or p.suffix.lower() not in {'.py','.ps1','.bat','.cmd','.vbs'}:continue
   low=str(p).lower()
   if any(x in low for x in ('site-packages','__pycache__','backups')):continue
   try:t=p.read_text(encoding='utf-8',errors='ignore')
   except Exception:continue
   for kind,pat in pats:
    if pat.search(t):leaks.append(f"{kind}: {p.relative_to(root)}")
 add("WARN" if leaks else "PASS","Host-dependency first-party source scan","\n".join(sorted(set(leaks))[:120]) if leaks else "no common hard host paths detected")
 if ns.run_system_test:
  from platform_runtime import python_path
  st=root/"Tools/system_test.py";py=python_path(root)
  try:
   cp=run([str(py),str(st),"--root",str(root)],root,300);add("PASS" if cp.returncode==0 else "WARN","Current System Test",((cp.stdout or '')+('\n'+cp.stderr if cp.stderr else ''))[-12000:])
  except Exception as e:add("WARN","Current System Test",str(e))
 counts={s:sum(x['status']==s for x in rows) for s in ('PASS','WARN','FAIL')};data={"version":VERSION,"counts":counts,"rows":rows};text="="*76+f"\nPortableAI v{VERSION} Fresh-machine Readiness\n"+"="*76+"\nTarget: Windows/Linux x64; use installed platform CUDA, Vulkan or CPU routes according to memory/driver availability. Presence and admission checks are not physical-machine validation.\n\n"+"\n".join(f"[{x['status']}] {x['label']}: {x['detail']}" for x in rows)+f"\n\nPASS={counts['PASS']} WARN={counts['WARN']} FAIL={counts['FAIL']}\n";rotate(root,text,data)
 if ns.json:print(json.dumps(data,indent=2))
 else:print(text)
 return 1 if counts['FAIL'] else 0
if __name__=="__main__":raise SystemExit(main())
