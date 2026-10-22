from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path

COMPONENT_HINTS={
 'bootstrap': ('Runtime/BootstrapPython/python.exe',),
 'comfyui': ('Generative/ComfyUI_windows_portable/python_embeded/python.exe','Generative/ComfyUI_windows_portable/python_embeded/python3.exe'),
 'qwen3_tts': ('Runtime/BootstrapPython/python.exe',),
 'mmaudio': ('Runtime/MMAudioPython/python.exe','Runtime/MMAudioPython/Scripts/python.exe'),
 'musetalk': ('Runtimes/Python310/cpython-3.10.21-windows-x86_64-none/python.exe',),
 'ace_step': ('Music/ACE-Step-1.5/python_embeded/python.exe','Music/ACE-Step-1.5/.venv/Scripts/python.exe','Music/ACE-Step/.venv/Scripts/python.exe','ACE-Step/.venv/Scripts/python.exe','Generative/ACE-Step/.venv/Scripts/python.exe'),
}

def probe(exe, layers=()):
    code="""import json,sys\nr={'python':sys.version.split()[0],'executable':sys.executable}\ntry:\n import torch; r.update(torch=getattr(torch,'__version__',None),torch_cuda=getattr(torch.version,'cuda',None),cuda_available=bool(torch.cuda.is_available()))\nexcept Exception:r['torch']='not-importable'\nprint(json.dumps(r))"""
    code="import sys;sys.path[:0]="+repr([str(p) for p in layers])+"\n"+code
    try:
        env=os.environ.copy()
        for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','__PYVENV_LAUNCHER__'):
            env.pop(key,None)
        env['PYTHONNOUSERSITE']='1'
        env['PATH']=str(Path(exe).parent)+os.pathsep+env.get('PATH','')
        cp=subprocess.run([str(exe),'-I','-c',code],capture_output=True,text=True,timeout=25,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if cp.returncode==0:return json.loads(cp.stdout.strip().splitlines()[-1])
        return {'error':(cp.stderr or cp.stdout)[-1200:]}
    except Exception as e:return {'error':repr(e)}

def first(root, rels):
    for r in rels:
        p=root/r
        if p.exists(): return p

def discover_extra(root, claimed):
    extras=[]
    for base in ('Runtime','Voice','SpeechToText','Video','Music','Generative'):
        d=root/base
        if not d.exists(): continue
        for p in d.rglob('python.exe'):
            try:
                rp=str(p.resolve()).lower()
                low=str(p).lower().replace('/','\\')
                if '\\lib\\venv\\scripts\\nt\\python.exe' in low: continue
                if rp not in claimed: extras.append(p)
            except Exception: pass
    return extras[:50]

def stt_info(root):
    try:
        sys.path.insert(0,str(root/'Tools'))
        import stt_runtime
        d=stt_runtime.resolve(root,repair=False,write=True)
        if str(d.get('status','')).startswith('LOCKED'):
            return {
                'status':d.get('status'),
                'path':d.get('interpreter'),
                'package_layer':d.get('package_layer'),
                'python':d.get('python'),
                'faster_whisper':d.get('faster_whisper'),
                'ctranslate2':d.get('ctranslate2'),
                'av':d.get('av'),
                'cuda_available':d.get('cuda_available'),
            }
        return {'status':d.get('status','UNRESOLVED'),'path':None,'package_layer':None}
    except Exception as exc:
        return {'status':'UNRESOLVED','path':None,'error':repr(exc)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ns=ap.parse_args(); root=Path(ns.root).resolve()
    data={'schema':2,'policy':'preserve-existing-component-runtimes; bootstrap is orchestration-only; STT is explicitly pinned','components':{}}
    claimed=set()
    for name,hints in COMPONENT_HINTS.items():
        p=first(root,hints)
        if p:
            claimed.add(str(p.resolve()).lower()); layers=[root/'Voice/Qwen3-TTS/.venv/Lib/site-packages'] if name=='qwen3_tts' else []
            if name == 'musetalk':
                sys.path.insert(0,str(root/'Agent'))
                import musetalk_runtime
                layers=[root/musetalk_runtime.PACKAGES]
                checked=musetalk_runtime.probe(root)
                info=probe(p,layers) if checked['ok'] else {'error':checked['detail']}
            else:
                info=probe(p,layers)
            info['path']=str(p.relative_to(root)); info['status']='PROBE_FAILED' if info.get('error') else 'LOCKED'
            if layers:info['package_layer']=str(layers[0].relative_to(root))
        else: info={'path':None,'status':'NOT_DETECTED'}
        data['components'][name]=info
    stt=stt_info(root); data['components']['stt']=stt
    if stt.get('path'):
        try: claimed.add(str((root/stt['path']).resolve()).lower())
        except Exception: pass
    extras=[]
    for p in discover_extra(root,claimed):
        info={'path':str(p.relative_to(root)),'status':'UNVALIDATED','detail':'Unclassified interpreter retained for review; not executed automatically'}; extras.append(info)
    data['unclassified_private_pythons']=extras
    out=root/'Agent'/'.runtime'/'component_runtime_locks.json'; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(data,indent=2),encoding='utf-8')
    print('PortalAI component runtime inventory 2026.10.09')
    print('='*76)
    for n,i in data['components'].items():
        bits=[i.get('status',''),i.get('path') or '']
        if i.get('package_layer'): bits.append('packages '+str(i['package_layer']))
        if i.get('python'): bits.append('Python '+i['python'])
        if i.get('torch') and i['torch']!='not-importable': bits.append('torch '+str(i['torch']))
        if i.get('torch_cuda'): bits.append('CUDA '+str(i['torch_cuda']))
        if i.get('faster_whisper'): bits.append('faster-whisper '+str(i['faster_whisper']))
        print(f'{n:14} '+ ' | '.join(x for x in bits if x))
    if extras: print(f'\nUnclassified private Python runtimes: {len(extras)} (recorded, not modified)')
    print('\nNo existing component ML Python environment was upgraded or unified.\nReport:',out)
    return 0 if str(stt.get('status','')).startswith('LOCKED') and not any(x.get('status')=='PROBE_FAILED' for x in data['components'].values()) else 2
if __name__=='__main__': raise SystemExit(main())
