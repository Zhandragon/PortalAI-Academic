"""Bounded, offline synthesis using the installed Qwen runner and local assets.

Only explicit marked synthetic outputs are written. Acquires the shared GPU
lease; refuses an active owned chat server rather than touching an owner's chat.
The audit hook is diagnostic, not an OS sandbox. No private account is opened.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import runpy
import struct
import subprocess
import sys
import time
import traceback
import wave

ROOT=Path(__file__).resolve().parents[1]


def dll_paths():
    k=ctypes.WinDLL('kernel32',use_last_error=True);p=ctypes.WinDLL('psapi',use_last_error=True)
    k.GetCurrentProcess.restype=wintypes.HANDLE
    p.EnumProcessModules.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.HMODULE),wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
    p.GetModuleFileNameExW.argtypes=[wintypes.HANDLE,wintypes.HMODULE,wintypes.LPWSTR,wintypes.DWORD]
    handle=k.GetCurrentProcess();modules=(wintypes.HMODULE*4096)();size=wintypes.DWORD()
    if not p.EnumProcessModules(handle,modules,ctypes.sizeof(modules),ctypes.byref(size)):raise ctypes.WinError()
    if size.value>ctypes.sizeof(modules):raise RuntimeError('DLL inventory overflow')
    result=[]
    for module in modules[:size.value//ctypes.sizeof(wintypes.HMODULE)]:
        buf=ctypes.create_unicode_buffer(32768)
        if not p.GetModuleFileNameExW(handle,module,buf,len(buf)):raise ctypes.WinError()
        result.append(buf.value)
    return sorted(set(result))


def worker(args):
    if sys.stdin.readline().strip()!='RUN':raise RuntimeError('Worker ownership gate not opened')
    denied=[ROOT/'Voice/Qwen3-TTS/python',ROOT/'Voice/Qwen3-TTS/python-bin']
    other=Path(('E:' if ROOT.drive.upper()=='D:' else 'D:')+'/PortalAI Windows')
    denied.append(other)
    attempts=[]
    def forbidden(path):
        if not isinstance(path,(str,bytes,os.PathLike)):return False
        path=os.path.normcase(os.path.abspath(os.fsdecode(path)))
        return any(path==os.path.normcase(str(d)) or path.startswith(os.path.normcase(str(d))+os.sep) for d in denied)
    def audit(event,values):
        if event in ('socket.connect','socket.getaddrinfo','socket.sendto'):
            attempts.append({'event':event});raise PermissionError('Offline diagnostic')
        if event in ('open','os.listdir','os.scandir','ctypes.dlopen') and values and forbidden(values[0]):
            attempts.append({'event':event,'path':os.fsdecode(values[0])});raise PermissionError('Retired or other-drive dependency')
    sys.addaudithook(audit)
    runner=ROOT/'Voice/Qwen3-TTS/qwen_tts_runner.py'
    output=args.artifacts_dir/(args.kind+'.wav')
    command=[str(runner),args.kind,'--text',args.text,'--language','English','--output',str(output)]
    if args.kind=='custom':command+=['--speaker','Ryan']
    elif args.kind=='design':command+=['--description','A clear adult narrator speaking calmly in English.']
    else:command+=['--reference-audio',str(args.artifacts_dir/'custom.wav'),'--ref-text',args.text]
    sys.argv=command
    started=time.monotonic();error=None
    try:
        runpy.run_path(str(runner),run_name='__main__')
    except SystemExit as exc:
        if exc.code not in (0,None):error='Runner exited '+str(exc.code)
    except BaseException:
        error=traceback.format_exc()
    origins={name:str(mod.__file__) for name,mod in list(sys.modules.items()) if getattr(mod,'__file__',None)}
    dlls=dll_paths()
    bad_modules={name:path for name,path in origins.items() if forbidden(path)}
    bad_dlls=[path for path in dlls if forbidden(path)]
    primary={name:origins.get(name) for name in ('torch','qwen_tts','transformers','soundfile','numpy','filelock')}
    layer=ROOT/'Voice/Qwen3-TTS/.venv/Lib/site-packages'
    wrong_layer={name:path for name,path in primary.items() if not path or not Path(path).resolve().is_relative_to(layer.resolve())}
    result={'passed':not error and not attempts and not bad_modules and not bad_dlls and not wrong_layer,
            'error':error,'kind':args.kind,'seconds':round(time.monotonic()-started,3),'python':sys.executable,
            'primary_origins':primary,'module_origins':origins,'loaded_dlls':dlls,
            'denied_attempts':attempts,'bad_modules':bad_modules,'bad_dlls':bad_dlls,'wrong_layer':wrong_layer}
    (args.artifacts_dir/(args.kind+'-worker.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if result['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',type=Path,required=True)
    parser.add_argument('--worker',action='store_true')
    parser.add_argument('--kind',choices=('custom','design','clone'))
    parser.add_argument('--text',default='This is Portal AI speaking from its portable drive.')
    parser.add_argument('--require-legacy-absent',action='store_true')
    args=parser.parse_args()
    if args.worker:return worker(args)
    sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
    from validation_artifacts import ValidationArtifacts
    from mission_supervisor import WorkerJob
    from service_manager import acquire_gpu_lease,release_gpu_lease,_listener_identity
    from runtime_policy import memory_info,detect_hardware
    from tts_policy import tts_plan
    from voice_bridge import VoiceBridge
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    if args.require_legacy_absent and (ROOT/'Voice/Qwen3-TTS/python').exists():raise RuntimeError('Legacy tree still exists')
    if any(artifacts.path(kind+'.wav').exists() for kind in ('custom','design','clone')):raise RuntimeError('Use a fresh artifacts directory')
    bridge=object.__new__(VoiceBridge);bridge.root=ROOT;bridge.voice_root=ROOT/'Voice/Qwen3-TTS'
    python=bridge._python()
    report={'passed':False,'root':str(ROOT),'checks':[],'scope':__doc__,'legacy_absent':not (bridge.voice_root/'python').exists()}
    lease=None
    try:
        lease=acquire_gpu_lease('synthetic-qwen-consolidation',timeout=30)
        if _listener_identity()['portable_qwen']:raise RuntimeError('Owned chat active; run the disposable handoff test instead')
        policy=json.loads((ROOT/'Agent/hardware_profiles.json').read_text(encoding='utf-8-sig'))
        report['admission']=tts_plan(ROOT,'qwen',hardware=detect_hardware(),policy=policy)
        env=dict(os.environ)
        for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):
            env.pop(key,None)
        temp=artifacts.path('tmp');temp.mkdir(exist_ok=True)
        env.update(TEMP=str(temp),TMP=str(temp),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
                   HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_IMPLICIT_TOKEN='1',HF_HUB_DISABLE_TELEMETRY='1',PORTALAI_TORCH_BACKEND='cuda')
        for key in ('HF_HOME','HUGGINGFACE_HUB_CACHE','TRANSFORMERS_CACHE','TORCH_HOME','XDG_CACHE_HOME'):
            env[key]=str(artifacts.path('cache')/key)
        for kind in ('custom','design','clone'):
            # Recheck the application's own admission policy before every model.
            tts_plan(ROOT,'qwen',hardware=detect_hardware(),policy=policy)
            print(json.dumps({'phase':'synthesis','kind':kind,'drive':ROOT.drive}),flush=True)
            command=[str(python),'-u','-B','-I','-X','faulthandler',str(Path(__file__).resolve()),'--worker','--kind',kind,'--artifacts-dir',str(artifacts.base),'--text',args.text]
            proc=job=None
            with artifacts.path(kind+'.log').open('x',encoding='utf-8') as log:
                try:
                    proc=subprocess.Popen(command,cwd=ROOT,env=env,stdin=subprocess.PIPE,stdout=log,stderr=log,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
                    job=WorkerJob(proc);job.limit_memory(14*1024**3)
                    proc.stdin.write('RUN\n');proc.stdin.close()
                    deadline=time.monotonic()+360
                    while proc.poll() is None:
                        if memory_info()[1]<2*1024**3:raise RuntimeError('Live voice test reached the 2-GiB free-RAM reserve')
                        if time.monotonic()>deadline:raise TimeoutError('Voice diagnostic timed out')
                        time.sleep(.2)
                    if proc.returncode:raise RuntimeError(kind+' worker failed with exit '+str(proc.returncode)+'; inspect '+str(artifacts.path(kind+'.log')))
                finally:
                    if job:job.close()
                    if proc and proc.poll() is None:proc.kill();proc.wait(timeout=10)
            data=json.loads(artifacts.path(kind+'-worker.json').read_text())
            if not data['passed']:raise RuntimeError(kind+' dependency-origin check failed')
            output=artifacts.path(kind+'.wav')
            with wave.open(str(output),'rb') as wav:
                duration=wav.getnframes()/wav.getframerate()
                assert wav.getsampwidth()==2 and wav.getnchannels()==1
                samples=struct.unpack('<'+'h'*wav.getnframes(),wav.readframes(wav.getnframes()))
            peak=max(abs(n) for n in samples);rms=(sum(n*n for n in samples)/len(samples))**.5
            if duration<.3 or rms<10:raise RuntimeError(kind+' produced empty or silent audio')
            row={'kind':kind,'passed':True,'duration':duration,'peak':peak,'rms':round(rms,3),'seconds':data['seconds'],'sha256':hashlib.sha256(output.read_bytes()).hexdigest()}
            report['checks'].append(row);print(json.dumps(row),flush=True)
        report['passed']=True
    except BaseException:
        report['error']=traceback.format_exc()
    finally:
        if lease:release_gpu_lease(lease)
        artifacts.path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'report':str(artifacts.path('report.json')),'error':report.get('error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
