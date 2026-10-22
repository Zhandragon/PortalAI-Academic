from __future__ import annotations
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from capability_registry import detect
from lifecycle_probe import probe_qwen,handoff_state,port_pids_windows
from component_smoke import run_suite as smoke_suite
from diagnostic_catalog import resolve, COVERAGE
VERSION="2026.10.11";CREATE_NO_WINDOW=getattr(subprocess,"CREATE_NO_WINDOW",0x08000000 if os.name=="nt" else 0)
def run(args,cwd,timeout=30):return subprocess.run(args,cwd=str(cwd),capture_output=True,text=True,errors="replace",timeout=timeout,creationflags=(CREATE_NO_WINDOW if os.name=="nt" else 0))
def tail(p,n=5000):
 try:return p.read_text(encoding='utf-8',errors='replace')[-n:]
 except Exception:return ''
def gpu():
 try:
  cp=run(["nvidia-smi","--query-gpu=name,driver_version,memory.total,memory.used,utilization.gpu","--format=csv,noheader"],Path.cwd(),15);return (cp.stdout or cp.stderr or '').strip()
 except Exception as e:return f"nvidia-smi unavailable: {e}"
def rotate(root,key,text,data):
    from maintenance_reports import save
    save(root,key,text,data,1 if data.get('smoke',{}).get('counts',{}).get('FAIL',0) else 0)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--component',default='All');ap.add_argument('--json',action='store_true');ap.add_argument('--structural-only',action='store_true');ns=ap.parse_args();root=Path(ns.root).resolve()
 try:selection=resolve(ns.component)
 except ValueError as exc:ap.error(str(exc))
 comp=selection['label'];reg=detect(root);q=probe_qwen(root);smoke=smoke_suite(root,comp,science_functional=not ns.structural_only);rt=root/'Agent/.runtime';logs={}
 logmap={'Qwen':['native_startup.log','native_startup_error.log','native_qwen.log','qwen_vram_handoff.log'],'Science':['qwen_vram_handoff.log'],'ComfyUI':['comfyui.log'],'ACE-Step':['acestep.log'],'All':['native_startup.log','native_startup_error.log','native_qwen.log','qwen_vram_handoff.log','worker_launch.log','media_preview.log']};names=logmap.get(comp,[]) or (['worker_launch.log','media_preview.log'] if comp in ('Qwen3-TTS','MuseTalk','MMAudio','STT','Media Preview') else [])
 for n in names:
  p=rt/n
  if p.exists():logs[n]=tail(p)
 report={'version':VERSION,'component':comp,'qwen':q,'handoff':handoff_state(root),'gpu':gpu(),'registry':reg,'smoke':smoke,'logs':logs,'coverage':COVERAGE}
 lines=['='*78,f"PortableAI v{VERSION} {'Full' if comp=='All' else 'Targeted'} Diagnosis · {comp}",'='*78,'',COVERAGE,'',f"Component smoke: {smoke['counts']}"]
 for x in smoke['rows']:lines.append(f"[{x['status']}] {x['label']}: {x.get('detail','')}")
 if comp in ('All','Qwen'):lines += ['',f"Qwen: state={q.get('state')} ready={q.get('ready')} sleeping={q.get('sleeping')} model={q.get('model')}","Handoff: "+json.dumps(report['handoff'],indent=2)]
 if comp=='All':
  lines += ['','Capability registry:']+[f"{'OK' if c['installed'] else '--'} {c['label']}: {c['detail']}" for c in reg['capabilities']]
 lines += ['',"GPU: "+report['gpu']]
 for n,t in logs.items():lines += ['',f"--- {n} ---",t]
 text='\n'.join(lines)+'\n';rotate(root,selection['report_key'],text,report)
 if ns.json:print(json.dumps(report,indent=2))
 else:print(text)
 return 1 if smoke['counts']['FAIL'] else 0
if __name__=='__main__':raise SystemExit(main())
