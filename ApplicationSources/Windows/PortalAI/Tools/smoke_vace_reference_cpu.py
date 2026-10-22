"""Synthetic CPU graph inference only; never claims physical Radeon validation.

Requires an explicit marked validation directory. Reads only shared program/model
assets, and writes all inputs, caches, Comfy state and reports below that directory.
No production profile is opened or bypassed. Coordinate this model load with other
VM/model diagnostics; the process tree has a 12 GiB ceiling and a hard time limit.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from validation_artifacts import ValidationArtifacts, require_output_space
from runtime_policy import atomic_json, memory_info, portable_env
from mission_supervisor import WorkerJob
from platform_runtime import ffmpeg_path
from comfy_bridge import ComfyBridge
from _common import http_json
from profile_paths import _contained, _relative
from vace_reference import configure, validate_output
from probe_vace_tensor_load import job_memory


def log_tail(path, limit=12000):
    """Read bounded diagnostic evidence even when native code exits abruptly."""
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-limit))
            return stream.read(limit).decode('utf-8',errors='replace')
    except OSError:return ''


def failure_details(error, process, path):
    tail=log_tail(path)
    code=process.poll() if process is not None else None
    details={'error':str(error),'worker_exit_code_before_cleanup':code,'log_tail':tail}
    if code is not None:details['worker_exit_code_hex']=hex(code & 0xffffffff)
    for line in reversed(tail.splitlines()):
        if 'fatal exception:' in line.lower() or 'fatal python error:' in line.lower():
            details['transport_error']=str(error)
            details['error']=line.strip()
            details['failure_kind']='native_process_failure'
            break
    else:
        details['failure_kind']='worker_exit' if code is not None else 'diagnostic_error'
    return details


class SyntheticGraph(ComfyBridge):
    def __init__(self):
        # Only graph configuration is reused. No production root/profile client
        # initialization, input staging, output fetching or API methods are used.
        pass

    def workflow_file(self, path):
        if path != 'Workflows/API/Wan2.1_VACE_14B_V2V_API.json':
            raise ValueError('Unexpected diagnostic workflow')
        return json.loads((ROOT/path).read_text(encoding='utf-8'))


def build_command(folder, port):
    work=ROOT/'Generative/ComfyUI_windows_portable'
    directories={name:folder/name for name in ('base','input','output','temp','user')}
    for path in directories.values():path.mkdir(parents=True,exist_ok=True)
    model_paths=folder/'models.json'
    atomic_json(model_paths,{'portalai_shared_models':{
        'base_path':str(work/'ComfyUI/models'),'diffusion_models':'diffusion_models',
        'text_encoders':'text_encoders','vae':'vae'}})
    command=[str(work/'python_embeded/python.exe'),'-B','-s',str(ROOT/'Tools/vace_cpu_entry.py'),
             # Preserve FP16 weight storage on CPU; Comfy's manual-cast CPU
             # operations still compute in FP32. The default CPU loader would
             # double the 4 GiB UNet storage before inference.
             '--cpu','--fp16-unet','--disable-auto-launch','--listen','127.0.0.1','--port',str(port),
             '--disable-all-custom-nodes','--disable-api-nodes','--disable-metadata',
             '--disable-xformers','--disable-triton-backend','--disable-comfy-compiler',
             '--disable-async-offload','--cache-none','--preview-method','none','--log-stdout',
             '--base-directory',str(directories['base']),'--extra-model-paths-config',str(model_paths)]
    for name in ('input','output','temp','user'):command+=['--'+name+'-directory',str(directories[name])]
    return command,directories


def run(artifacts, timeout=600):
    if os.name!='nt':raise RuntimeError('This bounded diagnostic currently uses the bundled Windows Comfy interpreter')
    if not artifacts.synthetic:raise ValueError('An explicit synthetic artifacts directory is required')
    if not 30<=timeout<=600:raise ValueError('Diagnostic timeout must be 30..600 seconds')
    if memory_info()[1]<16*1024**3:raise RuntimeError('Diagnostic requires 16 GiB free host RAM')
    require_output_space(ROOT,artifacts,128*1024**2,for_outputs=True)
    folder=artifacts.path('vace-reference-'+uuid.uuid4().hex);folder.mkdir()
    with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    command,dirs=build_command(folder,port)
    source=dirs['input']/'synthetic.png'
    subprocess.run([str(ffmpeg_path(ROOT)),'-v','error','-nostdin','-y','-f','lavfi',
                    '-i','testsrc2=size=128x128:rate=1','-frames:v','1',str(source)],
                   capture_output=True,check=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    request={'source':str(source),'prompt':'A colorful geometric sculpture rotates slowly.',
             'width':128,'height':128,'frames':5,'fps':5,'seed':52,'conditioning':'reference-image'}
    workflow=configure(SyntheticGraph(),request,source.name)
    workflow['11']['inputs']['steps']=1  # Diagnostic cost only; production retains 20.
    atomic_json(folder/'workflow.json',workflow)
    report={'passed':False,'backend':'CPU diagnostic','physical_radeon_validated':False,
            'quality_validated':False,'frames':5,'size':[128,128],'steps':1,
            'unet_storage':'FP16 diagnostic flag; CPU manual-cast compute is FP32',
            'safetensors_cpu_backend':'pread (diagnostic process only)',
            'memory_ceiling_bytes':12*1024**3,'timeout_seconds':timeout,'folder':str(folder)}
    gate=folder/'gate';worker_request=folder/'worker.json'
    primitive=[command[0],'-B','-s',str(ROOT/'Tools/vace_cpu_primitive.py'),
               '--artifacts-dir',str(artifacts.path()),'--case',folder.name]
    # The same gated, limited process tree checks real small CPU operations
    # before it can launch Comfy or map any model weights.
    atomic_json(worker_request,{'commands':[primitive,command],'gate':str(gate)})
    env=portable_env(folder)
    for key in ('PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):env.pop(key,None)
    env.update(OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',HF_HUB_OFFLINE='1',
               TRANSFORMERS_OFFLINE='1',HF_DATASETS_OFFLINE='1')
    process=job=timer=None;started=time.monotonic();close_lock=threading.Lock()
    def terminate():
        with close_lock:
            if job and job.handle:
                try:report['job_memory']=job_memory(job)
                except OSError as exc:report['job_memory_error']=str(exc)
                job.close()
    def check():
        if time.monotonic()-started>=timeout:raise TimeoutError('CPU VACE diagnostic reached its hard timeout')
        if process.poll() is not None:
            raise RuntimeError('CPU Comfy worker exited with code '+str(process.returncode)+' ('+hex(process.returncode & 0xffffffff)+')')
        job.check()
        if memory_info()[1]<4*1024**3:raise RuntimeError('CPU diagnostic stopped at the free host RAM reserve')
    base='http://127.0.0.1:'+str(port)
    try:
        with (folder/'comfy.log').open('wb') as log:
            process=subprocess.Popen([str(ROOT/'Runtime/BootstrapPython/python.exe'),'-B','-I',
                str(ROOT/'Agent/sdcpp_worker.py'),str(worker_request)],cwd=folder,env=env,stdout=log,stderr=log,
                stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=WorkerJob(process);job.limit_memory(12*1024**3)
            timer=threading.Timer(timeout,terminate);timer.daemon=True;timer.start();gate.touch()
            from bounded_comfy import owned_listeners
            import service_manager as service
            while True:
                check()
                if not service.port_open(port):time.sleep(.25);continue
                owned_listeners(service,job,port)
                try:stats=http_json('GET',base+'/system_stats',timeout=2)
                except OSError:time.sleep(.25);continue
                if not stats.get('devices') or any(device.get('type')!='cpu' for device in stats['devices']):
                    raise RuntimeError('Diagnostic refused a non-CPU Comfy backend')
                report['devices']=stats['devices'];break
            owned_listeners(service,job,port)
            queued=http_json('POST',base+'/prompt',{'prompt':workflow,'client_id':uuid.uuid4().hex},timeout=15)
            prompt_id=queued.get('prompt_id')
            if not prompt_id:raise RuntimeError('Comfy refused the reference workflow: '+str(queued)[:2000])
            history_failures=0
            while True:
                check();owned_listeners(service,job,port)
                try:
                    history=http_json('GET',base+'/history/'+prompt_id,timeout=2)
                    history_failures=0
                except OSError as exc:
                    check()
                    evidence=failure_details(exc,process,folder/'comfy.log')
                    if evidence['failure_kind']=='native_process_failure':raise RuntimeError(evidence['error']) from exc
                    history_failures+=1
                    if history_failures>=10:
                        raise RuntimeError('Comfy history remained unavailable after 10 bounded requests: '+str(exc)) from exc
                    time.sleep(.25);continue
                if prompt_id in history:
                    entry=history[prompt_id];status=entry.get('status') or {}
                    if status.get('status_str')=='error':raise RuntimeError(str(status.get('messages'))[-2000:])
                    if status.get('completed') or status.get('status_str')=='success':break
                time.sleep(.5)
            items=ComfyBridge._collect_file_items(entry.get('outputs') or {})
            if len(items)!=1:raise RuntimeError('Reference diagnostic did not produce exactly one output')
            relative=_relative(str(items[0].get('subfolder',''))+'/'+items[0]['filename'] if items[0].get('subfolder') else items[0]['filename'])
            output=_contained(dirs['output'],dirs['output']/relative)
            duration=validate_output(ROOT,output,request)
            primitive_result=json.loads((folder/'primitive.json').read_text())
            if not primitive_result.get('passed'):raise RuntimeError('CPU dtype primitive did not pass')
            report.update(passed=True,output=str(output),duration_seconds=duration,primitive=primitive_result)
    except Exception as exc:report.update(failure_details(exc,process,folder/'comfy.log'))
    finally:
        if timer:timer.cancel()
        terminate()
        if process:
            report.setdefault('worker_exit_code_before_cleanup',process.poll())
            if process.poll() is None:process.kill()
            process.wait(timeout=10)
            report['worker_exit_code_after_cleanup']=process.returncode
            report['owned_process_cleanup_complete']=True
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        atomic_json(folder/'report.json',report)
        atomic_json(artifacts.path('vace-reference-cpu-latest.json'),report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--timeout',type=int,default=600)
    args=parser.parse_args()
    result=run(ValidationArtifacts(ROOT,args.artifacts_dir),args.timeout)
    print(json.dumps(result,ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
