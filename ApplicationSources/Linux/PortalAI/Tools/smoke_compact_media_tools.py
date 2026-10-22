"""Bounded standalone 4B CPU tool recognition; no user's chat or media effects."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Agent','ControlCenter','Tools')]
from validation_artifacts import ValidationArtifacts
from runtime_policy import build_plan, load_policy, GIB
from assistant_guidance import host_guidance, media_preference_guidance
from native_chat import TOOLS
from media_tool_api import image_arguments, variant_catalog
from mission_supervisor import WorkerJob
from service_manager import _listening_pids


def run(artifacts, selected_case=None):
    if os.name != 'nt': raise RuntimeError('Standalone fixture currently uses Windows CPU containment')
    cfg=load_policy(ROOT)
    cfg.update(selection='qwen4-abliterated-q4',backend='cpu',context_tokens=8192)
    plan=build_plan(ROOT,policy=cfg)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    command=list(plan['command']);command[command.index('--port')+1]=str(port)
    command += ['--threads','2','--threads-batch','2','--no-warmup']
    env=os.environ.copy()
    for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV','PORTALAI_ACCOUNT_UNLOCK','PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH'):
        env.pop(key,None)
    temporary=artifacts.path('tmp');temporary.mkdir(exist_ok=True)
    env.update(TEMP=str(temporary),TMP=str(temporary))
    report={'passed':False,'scope':'Actual 4B abliterated CPU tool recognition; generated calls are NOT executed. No media inference or live GUI handoff.', 'checks':[]}
    process=job=None
    def owned():
        if process.poll() is not None: raise RuntimeError('Standalone CPU model exited')
        if set(_listening_pids(port)) != {process.pid}:raise RuntimeError('Test listener ownership mismatch')
    try:
        with artifacts.path('server.log').open('wb') as log:
            process=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=log,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
            job=WorkerJob(process);job.limit_memory(7*GIB)
            deadline=time.monotonic()+180
            while True:
                if process.poll() is not None:raise RuntimeError('CPU model exited; inspect synthetic server log')
                if time.monotonic()>deadline:raise TimeoutError('CPU model readiness timed out')
                try:
                    owned()
                    with urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as response:
                        if response.status==200:break
                except (OSError,RuntimeError):time.sleep(.3)
            print('Standalone 4B CPU model ready',flush=True)
            cases=[
                ('image','Create an original watercolor image of a blue teapot on a wooden table.','generate_image','standard'),
                ('uncensored_image','Use the uncensored image model to create a watercolor of a blue teapot.','generate_image','standard'),
                ('saved_uncensored','Create an original watercolor image of a blue teapot.','generate_image','uncensored'),
                ('nice_chooses','Create an oil painting of a blue teapot using DreamShaper 8 for its painting style.','generate_image','auto'),
                ('variants','Check which image-generation tools and uncensored variants are available to you.','available_tools','auto'),
                ('science','Use the science tool to calculate 2 + 2.','science','auto'),
                ('saved_flux','Create an original watercolor image of a blue teapot.','generate_image','auto'),
                ('repeat_flux','I saved FLUX in Media defaults. Generate the same image again with my current settings.','generate_image','auto'),
                ('history','An earlier tool already edited an image in this chat. Find its exact reported output path using the chat_history tool. Do not rerun the image edit or read the entire session file.','chat_history','auto'),
            ]
            for name,prompt,expected,media in cases:
                selected = ('saved_flux','repeat_flux') if selected_case=='image_settings' else (selected_case,)
                if selected_case is not None and name not in selected:continue
                owned()
                # Public synthetic policy, not a production account/session.
                policy={'variant_preference':'uncensored','media':{'media_variant':media,
                    'image_profile':'flux' if name in ('saved_flux','repeat_flux') else 'auto'}}
                with patch('runtime_policy.load_effective_policy',return_value=policy):
                    context=host_guidance(ROOT)+media_preference_guidance(ROOT)
                messages=[{'role':'system','content':context}]
                if name=='repeat_flux':
                    messages += [
                        {'role':'user','content':'Generate a watercolor of a blue teapot.'},
                        {'role':'assistant','content':None,'tool_calls':[{'id':'synthetic_old_image','type':'function',
                            'function':{'name':'generate_image','arguments':json.dumps({'prompt':'a blue teapot','profile':'sd15','variant':'uncensored'})}}]},
                        {'role':'tool','tool_call_id':'synthetic_old_image','content':json.dumps({'success':True,'hardware_profile':{'profile':'sd15'},'synthetic':True})},
                        {'role':'assistant','content':'The previous image used DreamShaper 8.'}]
                messages.append({'role':'user','content':prompt})
                payload={'model':'local','messages':messages, 'tools':TOOLS, 'tool_choice':'auto',
                         'temperature':0,'max_tokens':400,'chat_template_kwargs':{'enable_thinking':False}}
                request=Request(f'http://127.0.0.1:{port}/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
                with urlopen(request,timeout=150) as response:data=json.load(response)
                message=data['choices'][0]['message'];calls=message.get('tool_calls') or []
                passed=bool(calls and calls[0]['function']['name']==expected)
                if passed:
                    arguments=json.loads(calls[0]['function']['arguments'])
                    if expected=='generate_image':
                        image_arguments(arguments)
                        if name=='uncensored_image':passed=arguments.get('variant')=='uncensored'
                        if name=='image':passed=not any(key in arguments for key in ('width','height')) and arguments.get('variant','default') in ('default','standard')
                        if name=='saved_uncensored':passed=arguments.get('variant','default') in ('default','uncensored')
                        if name=='nice_chooses':passed=arguments.get('variant')=='uncensored' and arguments.get('profile','auto') in ('auto','sd15')
                        if name in ('saved_flux','repeat_flux'):
                            passed=arguments.get('profile','flux') in ('auto','flux') and not arguments.get('override_saved_profile',False)
                    elif expected=='available_tools':
                        variants=variant_catalog(ROOT,arguments.get('command'))
                        passed=any(row['id']=='flux-klein' for row in variants['models'])
                    elif expected=='chat_history':
                        passed=arguments.get('action')=='artifacts'
                report['checks'].append({'case':name,'media_setting':media,'passed':passed,'message':message})
                artifacts.path('result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
                print(json.dumps({'case':name,'passed':passed,'tool':calls[0]['function']['name'] if calls else None}),flush=True)
            report['passed']=bool(report['checks']) and all(row['passed'] for row in report['checks'])
    except Exception as exc:
        report['error']=str(exc)
    finally:
        if job:job.close()
        if process:
            if process.poll() is None:process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
        report['owned_test_process_stopped']=process is None or process.poll() is not None
        artifacts.path('result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--case',choices=('image','uncensored_image','saved_uncensored','nice_chooses','variants','science','saved_flux','repeat_flux','image_settings','history'))
    args=parser.parse_args();result=run(ValidationArtifacts(ROOT,args.artifacts_dir),args.case)
    print(json.dumps({key:value for key,value in result.items() if key!='checks'}))
    raise SystemExit(0 if result['passed'] else 1)
