"""Bounded small-VACE and semantic-mask regression; records the actual backend."""
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import atomic_json,portable_env,memory_info
from mission_supervisor import WorkerJob
from ai_tools import _exclusive_gpu
from comfy_bridge import ComfyBridge
from radeon_edit import small_vace

def main():
    if memory_info()[1]<16*1024**3:raise RuntimeError('Scaled editing check requires 16 GiB free host RAM')
    token=uuid.uuid4().hex;folder=ROOT/'Cache/ScaledEditValidation'/token;folder.mkdir(parents=True)
    output=ROOT/'Outputs/Videos'/('scaled_edit_test_'+token[:8]);output.mkdir(parents=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    report={'passed':False,'backend':'Windows CUDA reference','physical_radeon_validated':False}
    process=job=None
    try:
        with _exclusive_gpu(None,'scaled-edit-regression'):
            work=ROOT/'Generative/ComfyUI_windows_portable'
            command=[str(work/'python_embeded/python.exe'),'-s',str(work/'ComfyUI/main.py'),'--disable-auto-launch',
                     '--listen','127.0.0.1','--port',str(port),'--disable-xformers','--disable-triton-backend',
                     '--disable-comfy-compiler','--disable-async-offload','--cache-none','--output-directory',str(output)]
            request=folder/'request.json';gate=folder/'gate'
            atomic_json(request,{'command':command,'gate':str(gate)})
            env=portable_env(ROOT);env.update(OMP_NUM_THREADS='2',MKL_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
            with (ROOT/'Maintenance/Reports/scaled-edit-live.log').open('wb') as log:
                process=subprocess.Popen([sys.executable,'-B',str(ROOT/'Agent/sdcpp_worker.py'),str(request)],
                    cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                job=WorkerJob(process);job.limit_memory(12*1024**3);gate.touch()
                bridge=ComfyBridge();bridge.base=f'http://127.0.0.1:{port}'
                bridge.ccfg={**bridge.ccfg,'output_dir':output.relative_to(ROOT).as_posix(),'timeout_seconds':600}
                deadline=time.monotonic()+120
                while True:
                    if process.poll() is not None:raise RuntimeError('Editing diagnostic exited; inspect log')
                    try:bridge.health();break
                    except Exception:
                        if time.monotonic()>deadline:raise TimeoutError('Editing diagnostic startup')
                        time.sleep(.5)
                source=ROOT/'Cache/MuseTalk/musetalk_6df3d05f9b834b6586ea589de5a791a6/video.mp4'
                name,staged=bridge.stage_input_file(source,'scaled_vace_test')
                wf=bridge.workflow_file('Workflows/API/Wan2.1_VACE_14B_V2V_API.json')
                bridge.configure_vace_video_edit(wf,name,'Preserve the person and motion. Warm studio lighting.',
                    seed=52,width=128,height=128,length=5,fps=5,fast=False)
                small_vace(wf);wf['11']['inputs']['steps']=2
                result=bridge.run(wf,output)
                if not result.get('files'):raise RuntimeError('Small VACE produced no video')
                report['vace']=result
                # Use a real portrait, not a synthetic colour patch, for segmentation.
                image=folder/'portrait.png'
                subprocess.run([str(ROOT/'Tools/ffmpeg/bin/ffmpeg.exe'),'-v','error','-i',str(source),'-frames:v','1','-vf','scale=320:-1',str(image)],check=True)
                uploaded=bridge.upload_image(image)
                wf=bridge.workflow_file('Workflows/API/SAM2_GroundingDINO_ObjectMask.json')
                wf['1']['inputs']['image']=uploaded;wf['4']['inputs']['prompt']='person'
                report['mask']=bridge.run(wf,output)
                sys.path.insert(0,str(work/'python_embeded/Lib/site-packages'))
                from PIL import Image
                if not any(Image.open(p).convert('L').getextrema()[1]>0 for p in report['mask'].get('files',[])):
                    raise RuntimeError('Semantic mask was empty')
                report['passed']=True
    except Exception as exc:report['error']=str(exc)
    finally:
        if job:job.close()
        if process:
            if process.poll() is None:process.kill()
            process.wait(timeout=10)
        atomic_json(ROOT/'Maintenance/Reports/scaled-edit-live.json',report)
    print(json.dumps(report));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
