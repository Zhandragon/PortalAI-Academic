"""Real CPU model startup, mic STT and owned stop/restore in a synthetic root."""
import json,os,subprocess,sys,time
from pathlib import Path
from urllib.request import Request,urlopen
ROOT=Path(__file__).with_name('listener-fixture').resolve()
assert json.loads((ROOT/'fixture-manifest.json').read_text())['no_owner_accounts']
assert Path(sys.executable).resolve()==ROOT/'Runtime/BootstrapPython/python.exe'
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Tools')]
for k in ('PYTHONHOME','PYTHONPATH','PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):os.environ.pop(k,None)
os.environ.update(PORTABLEAI_ROOT=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',TEMP=str(ROOT/'Cache/tmp'),TMP=str(ROOT/'Cache/tmp'))
from instance_runtime import InstanceSession,port
session=InstanceSession(ROOT);session.start()
import service_manager as service
from chat_model_switch import prepare_startup
from chat_voice import VoiceIO
from piper_bridge import synthesize
report={'passed':False,'scope':'Actual Windows CPU model startup, typed inference, microphone transcription code path with synthetic speech, model stop/restore; no owner account or physical microphone', 'checks':[]}
def save(name,**data):
    report['checks'].append({'name':name,**data});print(json.dumps(report['checks'][-1]),flush=True)
    Path(__file__).with_name('live-report.json').write_text(json.dumps(report,indent=2))
try:
    result=prepare_startup(ROOT,on_status=lambda t:print(t,flush=True))
    before=service._listener_identity();assert before['portable_qwen'] and service._qwen_health_ready()
    save('real prepare_startup healthy',passed=True,model=result['model']['id'],pid=before['listeners'][0]['pid'],port=port('qwen'))
    body={'model':'local','messages':[{'role':'user','content':'Reply with the words: voice test ready.'}],'max_tokens':40,'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}
    with urlopen(Request(f'http://127.0.0.1:{port("qwen")}/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'}),timeout=180) as response:answer=json.load(response)['choices'][0]['message']['content']
    assert answer.strip();save('typed message actual inference',passed=True,reply=answer)
    audio=synthesize('This is a microphone transcription test from the portable drive.',root=ROOT)['files'][0]
    text=VoiceIO(ROOT,lambda:None).transcribe(audio)
    assert 'microphone' in text.lower() and 'portable' in text.lower(),text
    after=service._listener_identity();assert after['listeners'][0]['pid']==before['listeners'][0]['pid'] and service._qwen_health_ready()
    save('mic CPU transcription leaves chat server running',passed=True,text=text,same_pid=True)
    state=service.qwen_gpu_handoff_begin('synthetic-listener-regression')
    assert state['active'] and not service.port_open(port('qwen'))
    restored=service.qwen_gpu_handoff_end(state,timeout=180)
    assert restored['ready'] and service._qwen_health_ready() and restored['pid']!=before['listeners'][0]['pid']
    save('real owned stop and healthy restore',passed=True,old_pid=before['listeners'][0]['pid'],new_pid=restored['pid'])
    with Path(__file__).with_name('chat-handoff-smoke.log').open('w',encoding='utf-8') as log:
        cp=subprocess.run([sys.executable,'-B','-I',str(ROOT/'Tools/smoke_chat_handoff.py'),'--case','error','--effort',os.environ.get('PORTALAI_VALIDATION_EFFORT','fast'),'--report','listener-error-handoff.json'],stdout=log,stderr=subprocess.STDOUT,timeout=900)
    save('existing NativeChat live tool handoff smoke',passed=cp.returncode==0,exit_code=cp.returncode)
    assert cp.returncode==0,'See chat-handoff-smoke.log'
    report['passed']=True
finally:
    try:
        stopped=service._stop_qwen_listener()
        save('fixture server cleanup',passed=not service.port_open(port('qwen')),stopped_pids=stopped)
    finally:
        session.close()
        Path(__file__).with_name('live-report.json').write_text(json.dumps(report,indent=2))
