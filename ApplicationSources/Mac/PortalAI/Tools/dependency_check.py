"""Offline import-origin checks in isolated bundled interpreters; no quarantine."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from maintenance_reports import save
from profile_paths import private_path

CHECKS = (
    ('GUI / Tk', 'Runtime/BootstrapPython/python.exe', (), ('tkinter', 'sqlite3')),
    ('Account runtime libraries', 'Runtime/BootstrapPython/python.exe', ('Runtime/AccountPython/packages',), ('cryptography', 'argon2', 'nacl')),
    ('Foundation', 'Runtime/BootstrapPython/python.exe', ('Agent', 'ControlCenter'),
     ('runtime_policy', 'mission_runner', 'mission_supervisor', 'mission_schedule', 'mission_memory', 'vm_runner', 'model_connection', 'web_tools', 'web_state',
      'chat_budgets', 'chat_progress', 'tool_protocol', 'profile_paths', 'profile_lazy_state', 'profile_hydration')),
    ('Native science', 'Runtime/BootstrapPython/python.exe', ('Runtime/SciencePackages',), ('numpy', 'sympy', 'scipy')),
    ('Science Workbench', 'Runtime/BootstrapPython/python.exe', ('Runtime/ScientificPython/packages',), ('numpy', 'sympy', 'scipy', 'openmm')),
    ('Piper CPU voice', 'Runtime/BootstrapPython/python.exe', ('Voice/Piper/packages',), ('piper', 'onnxruntime')),
    ('Speech transcription', 'Runtime/BootstrapPython/python.exe', ('SpeechToText/python_packages',), ('faster_whisper', 'ctranslate2')),
    ('Qwen voice packages', 'Runtime/BootstrapPython/python.exe', ('Voice/Qwen3-TTS/.venv/Lib/site-packages',), ('torch', 'qwen_tts')),
    ('ComfyUI', 'Generative/ComfyUI_windows_portable/python_embeded/python.exe', (), ('torch',)),
    ('MMAudio', 'Runtime/MMAudioPython/python.exe', ('Services/MMAudio',), ('torch', 'torchvision', 'torchaudio', 'av', 'mmaudio.eval_utils')),
    ('ACE-Step', 'Music/ACE-Step-1.5/python_embeded/python.exe', ('Music/ACE-Step-1.5',), ('torch', 'torchaudio', 'soundfile', 'acestep.audio_utils')),
    ('Windows music understanding / Demucs', 'MusicUnderstanding/runtime/python.exe', (),
     ('torch', 'torchaudio', 'soundfile', 'demucs.hf', 'demucs.apply', 'transformers', 'librosa')),
    ('Isolated Radeon packages', 'Runtime/BootstrapPython/python.exe', ('Runtime/AMDPython/packages',),
     ('torch', 'torchvision', 'torchaudio')),
    ('MuseTalk configured interpreter', 'Runtimes/Python310/cpython-3.10.21-windows-x86_64-none/python.exe', (), ('torch',)),
)

def platform_checks():
    if os.name=='nt':return CHECKS
    py='Runtime/LinuxPython/run-python'
    media=('Agent','Runtime/LinuxTorch/cpu','Runtime/LinuxPackages/kornia_compat',
           'Runtime/LinuxPackages/extras','Runtime/LinuxPackages/media')
    return (
        ('GUI / Tk',py,('Runtime/LinuxPackages/gui',),('tkinter','PIL','psutil')),
        ('Foundation',py,('Agent','ControlCenter'),next(entry[3] for entry in CHECKS if entry[0]=='Foundation')),
        ('Science Workbench',py,('Runtime/LinuxPackages/science',),('numpy','sympy','scipy','rdkit','openmm','cadquery','gmsh')),
        ('Piper CPU voice',py,media,('piper','onnxruntime')),
        ('Speech transcription',py,media,('faster_whisper','ctranslate2')),
        ('Linux media CPU import check',py,media,('torch','torchvision','torchaudio','kornia_rs','diffusers','qwen_tts','open_clip')),
    )


def check(root, entry):
    label, interpreter, layers, modules = entry
    if label == 'MuseTalk configured interpreter':
        sys.path.insert(0, str(root/'Agent'))
        from musetalk_runtime import probe
        try:
            result = probe(root)
            return {'label':label, 'status':'PASS' if result['ok'] else 'FAIL', 'detail':result['detail']}
        except Exception as exc:
            return {'label':label, 'status':'FAIL', 'detail':str(exc)}
    code = '''import importlib,json,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve()
sys.path[:0]=[str(root/x) for x in json.loads(sys.argv[2])]
rows=[]
for name in json.loads(sys.argv[3]):
 try:
  m=importlib.import_module(name);p=getattr(m,'__file__',None)
  rows.append({'module':name,'origin':p,'ok':bool(p) and Path(p).resolve().is_relative_to(root)})
 except Exception as e:rows.append({'module':name,'ok':False,'error':str(e)})
print(json.dumps({'rows':rows,'interpreter':sys.executable}))
raise SystemExit(0 if all(x['ok'] for x in rows) else 1)
'''
    env=os.environ.copy()
    for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','__PYVENV_LAUNCHER__'):env.pop(key,None)
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1',PIP_NO_INDEX='1',PYTHONDONTWRITEBYTECODE='1')
    if label == 'Qwen voice packages' and (root/'Tools/sox/sox.exe').is_file():
        env['PATH'] = str(root/'Tools/sox') + os.pathsep + env.get('PATH','')
    temporary=private_path(root,'Cache/tmp')
    for name in ('TEMP','TMP','TMPDIR'):env[name]=str(temporary)
    temporary.mkdir(parents=True,exist_ok=True)
    try:
        cp=subprocess.run([str(root/interpreter),'-B','-I','-c',code,str(root),json.dumps(layers),json.dumps(modules)],
                          cwd=root,capture_output=True,text=True,errors='replace',timeout=90,env=env,
                          creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        detail=(cp.stdout+'\n'+cp.stderr).strip()
        warning=cp.returncode==0 and ('could not be found' in detail.lower() or 'not recognized as' in detail.lower())
        return {'label':label,'status':'FAIL' if cp.returncode else 'WARN' if warning else 'PASS','detail':detail[-9000:]}
    except Exception as exc:return {'label':label,'status':'FAIL','detail':str(exc)}


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',required=True)
    ap.add_argument('--suite',choices=('standard','full'),default='full');ap.add_argument('--recover-only',action='store_true')
    ns=ap.parse_args();root=Path(ns.root).resolve();start=time.monotonic()
    journal=private_path(root,'Data/Maintenance/dependency_probe_journal.json')
    if journal.exists():
        print('FAIL: legacy quarantine journal remains. Preserve both held and original trees for reviewed recovery: '+str(journal))
        return 1
    if ns.recover_only:
        print('No legacy quarantine journal remains. Current checks never move dependency trees.');return 0
    checks=platform_checks()
    rows=[check(root,c) for c in (checks if ns.suite=='full' else checks[:5] if os.name=='nt' else checks[:4])]
    counts={s:sum(x['status']==s for x in rows) for s in ('PASS','WARN','FAIL')}
    data={'suite':ns.suite,'rows':rows,'counts':counts,'finished_cleanly':True,'elapsed_seconds':round(time.monotonic()-start,2),
          'coverage':'Fresh isolated processes, offline import/origin checks. No model generation; no OS network sandbox; no dependency-removal proof.',
          'deletion_authorized':False,'candidates':[]}
    text='PortalAI Dependency Isolation Test\n'+data['coverage']+'\n\n'+'\n'.join(f"[{r['status']}] {r['label']}: {r['detail']}" for r in rows)+f'\n\n{counts}\n'
    code=1 if counts['FAIL'] else 0;save(root,'dependency_probe',text,data,code);print(text);return code


if __name__=='__main__':raise SystemExit(main())
