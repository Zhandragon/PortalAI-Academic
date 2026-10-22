"""Read one checkpoint tensor on CPU under the existing 12 GiB diagnostic cap.

This is a loader probe, not model inference. It never modifies the model file or
opens a private profile. All generated artifacts require an explicit test folder.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from runtime_policy import atomic_json, memory_info, portable_env
from validation_artifacts import ValidationArtifacts, require_output_space

ASSET=ROOT/'Generative/ComfyUI_windows_portable/ComfyUI/models/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors'
CEILING=12*1024**3


def job_memory(job):
    """Capture actual committed-memory peaks before the job handle is closed."""
    from ctypes import wintypes
    info=type(job.info)()
    query=job.lib.QueryInformationJobObject
    query.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p]
    query.restype=wintypes.BOOL
    if not query(job.handle,9,ctypes.byref(info),ctypes.sizeof(info),None):
        raise OSError(ctypes.get_last_error(),'Cannot query diagnostic job memory')
    return {'limit_bytes':int(info.job_memory),'peak_process_bytes':int(info.peak_process),
            'peak_job_bytes':int(info.peak_job)}


def child(folder,backend,rocm_layer=False):
    import faulthandler
    faulthandler.enable()
    def phase(name,**values):
        record={'phase':name,**values}
        atomic_json(folder/'phase.json',record)
        print(json.dumps(record),flush=True)
    phase('import')
    if rocm_layer:
        sys.path[:0]=[str(ROOT/'Runtime/AMDPython/packages'),
                     str(ROOT/'Generative/ComfyUI_windows_portable/python_embeded/Lib/site-packages')]
    import torch
    import safetensors
    if rocm_layer and (not torch.version.hip or not Path(torch.__file__).resolve().is_relative_to(ROOT/'Runtime/AMDPython/packages')):
        raise RuntimeError('Scalar loader probe did not load the isolated ROCm Torch layer')
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    phase('before_safe_open',torch=torch.__version__,torch_origin=str(torch.__file__),hip=torch.version.hip,
          safetensors=safetensors.__version__,file_size=ASSET.stat().st_size,backend=backend,rocm_cpu_reader=rocm_layer)
    from comfy_safetensors import windows_rocm_cpu_reader
    with windows_rocm_cpu_reader(True) if rocm_layer else nullcontext():
        options={} if backend=='auto' else {'backend':backend}
        with safetensors.safe_open(str(ASSET),framework='pt',device='cpu',**options) as weights:
            key=weights.keys()[0]
            phase('before_get_tensor',key=key)
            tensor=weights.get_tensor(key)
            phase('after_get_tensor',key=key,dtype=str(tensor.dtype),shape=list(tensor.shape))
            value=float(tensor.reshape(-1)[0].item())
            phase('complete',key=key,dtype=str(tensor.dtype),shape=list(tensor.shape),first_value=value,
                  torch=torch.__version__,hip=torch.version.hip,torch_origin=str(torch.__file__),rocm_cpu_reader=rocm_layer)
    return 0


def run(artifacts,backend='mmap',rocm_layer=False):
    if os.name!='nt' or not artifacts.synthetic:raise ValueError('Explicit synthetic Windows probe required')
    if memory_info()[1]<16*1024**3:raise RuntimeError('Probe requires 16 GiB free host RAM')
    require_output_space(ROOT,artifacts,1024**2,for_outputs=True)
    from mission_supervisor import WorkerJob
    folder=artifacts.path('tensor-load-'+uuid.uuid4().hex);folder.mkdir()
    command=[str(ROOT/'Generative/ComfyUI_windows_portable/python_embeded/python.exe'),'-B','-s',
             str(Path(__file__).resolve()),'--artifacts-dir',str(artifacts.path()),'--child',folder.name,'--backend',backend]
    if rocm_layer:
        command[0]=str(ROOT/'Runtime/BootstrapPython/python.exe');command[2]='-I';command.append('--rocm-layer')
    gate=folder/'gate';request=folder/'request.json'
    atomic_json(request,{'command':command,'gate':str(gate)})
    env=portable_env(folder)
    for key in ('PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):env.pop(key,None)
    env.update(OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2',CUDA_VISIBLE_DEVICES='-1',HIP_VISIBLE_DEVICES='-1',
               HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    report={'passed':False,'full_model_loaded':False,'backend':'cpu','folder':str(folder),
            'memory_ceiling_bytes':CEILING,'timeout_seconds':60,'loader_backend':backend,'rocm_cpu_reader':rocm_layer,
            'physical_radeon_validated':False}
    process=job=None;started=time.monotonic()
    try:
        with (folder/'probe.log').open('wb') as log:
            process=subprocess.Popen([str(ROOT/'Runtime/BootstrapPython/python.exe'),'-B','-I',
                str(ROOT/'Agent/sdcpp_worker.py'),str(request)],cwd=folder,env=env,stdout=log,stderr=log,
                stdin=subprocess.DEVNULL,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            job=WorkerJob(process);job.limit_memory(CEILING);gate.touch()
            while process.poll() is None:
                report['job_memory']=job_memory(job)
                if time.monotonic()-started>60:raise TimeoutError('Loader probe reached its 60 second ceiling')
                if memory_info()[1]<4*1024**3:raise RuntimeError('Loader probe reached host free RAM reserve')
                time.sleep(.1)
            report['job_memory']=job_memory(job)
            report['exit_code']=process.returncode
            report['exit_code_hex']=hex(process.returncode & 0xffffffff)
            report['phase']=json.loads((folder/'phase.json').read_text()) if (folder/'phase.json').exists() else None
            report['passed']=process.returncode==0 and report['phase'] and report['phase'].get('phase')=='complete'
    except Exception as exc:report['error']=str(exc)
    finally:
        if job:
            if job.handle:report['job_memory']=job_memory(job)
            job.close()
        if process:
            if process.poll() is None:process.kill()
            process.wait(timeout=10)
        report['elapsed_seconds']=round(time.monotonic()-started,3)
        atomic_json(folder/'report.json',report)
        atomic_json(artifacts.path('tensor-load-latest.json'),report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--child')
    parser.add_argument('--backend',choices=('mmap','pread','auto'),default='mmap')
    parser.add_argument('--rocm-layer',action='store_true')
    args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    if args.child:
        folder=artifacts.path(args.child)
        if folder.parent!=artifacts.path() or not folder.is_dir() or not folder.name.startswith('tensor-load-'):
            raise ValueError('Existing synthetic tensor case required')
        return child(folder,args.backend,args.rocm_layer)
    result=run(artifacts,args.backend,args.rocm_layer);print(json.dumps(result,ensure_ascii=True))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
