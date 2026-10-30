"""Actual local CPU vision on a synthetic Workspace screenshot; no desktop input."""
import argparse,base64,http.client,json,socket,subprocess,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from validation_artifacts import ValidationArtifacts
from mission_supervisor import WorkerJob


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime-root',type=Path,default=ROOT);p.add_argument('--image',type=Path,required=True);p.add_argument('--artifacts-dir',required=True);args=p.parse_args()
    root=args.runtime_root.resolve();image=args.image.resolve()
    if not image.is_relative_to(root/'Maintenance/Validation') or image.suffix.lower()!='.png':raise ValueError('Use an explicitly synthetic PNG under Maintenance/Validation')
    artifacts=ValidationArtifacts(root,args.artifacts_dir)
    with socket.socket() as reservation:reservation.bind(('127.0.0.1',0));port=reservation.getsockname()[1]
    alias='portalai-workspace-vision-'+uuid.uuid4().hex;key=uuid.uuid4().hex;job=None
    command=[str(root/'LLM/backends/windows-cpu/llama-server.exe'),'-m',str(root/'LLM/models/Qwen3VL-2B-Instruct-Q4_K_M.gguf'),
             '--mmproj',str(root/'LLM/models/mmproj-Qwen3VL-2B-Instruct-F16.gguf'),'--host','127.0.0.1','--port',str(port),'--alias',alias,
             '-c','4096','-ngl','0','--threads','3','--parallel','1','--no-warmup',
             '--no-mmproj-offload','--image-min-tokens','1024','--image-max-tokens','1024','--api-key',key]
    def request(path,payload=None):
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=90)
        try:
            conn.request('POST' if payload else 'GET',path,json.dumps(payload).encode() if payload else None,{'Content-Type':'application/json','Authorization':'Bearer '+key})
            response=conn.getresponse();raw=response.read(1024*1024)
            if response.status!=200:raise RuntimeError(str(response.status)+': '+raw.decode(errors='replace')[:300])
            return json.loads(raw)
        finally:conn.close()
    with artifacts.path('vision-server.log').open('w') as log:
        worker=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=root,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            job=WorkerJob(worker);job.limit_memory(8*1024**3);deadline=time.monotonic()+180
            while True:
                if worker.poll() is not None:raise RuntimeError('Owned vision server exited with code '+str(worker.returncode)+'; inspect synthetic server log')
                try:
                    data=request('/v1/models')
                    if data['data'][0]['id']!=alias:raise RuntimeError('Port identity mismatch')
                    break
                except (OSError,http.client.HTTPException,KeyError,RuntimeError):
                    if time.monotonic()>deadline:raise TimeoutError('Owned vision server did not become ready')
                    time.sleep(.3)
            payload={'model':alias,'messages':[{'role':'user','content':[{'type':'text','text':'Read the four tab button labels across the top of this Workspace screenshot. Return those four names only.'},
                      {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image.read_bytes()).decode()}}]}],
                     'max_tokens':128,'temperature':0,'stream':False,'chat_template_kwargs':{'enable_thinking':False}}
            start=time.monotonic();result=request('/v1/chat/completions',payload);choice=result['choices'][0];answer=choice['message'].get('content','')
            passed=choice.get('finish_reason')=='stop' and all(name in answer.lower() for name in ('knowledge','connections','workflows','computer'))
            report={'passed':passed,'synthetic_only':True,'local_model':'Qwen3-VL-2B-Instruct Q4_K_M','backend':'CPU','answer':answer,'elapsed_seconds':round(time.monotonic()-start,2),'desktop_actions_executed':False}
            artifacts.path('vision-smoke.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
            if not passed:raise RuntimeError('Local vision model did not correctly read all four labels')
        finally:
            if job:job.close()
            if worker.poll() is None:worker.kill()
            worker.wait(timeout=15)


if __name__=='__main__':main()
