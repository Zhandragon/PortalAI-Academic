"""Real lifecycle check in disposable public-asset roots, never a user account."""
import argparse, hashlib, json, os, shutil, subprocess, sys, threading, time, urllib.request
from pathlib import Path

HERE=Path(__file__).resolve().parent

def prepare(root):
    fixture=root/'Maintenance/Validation/Coding-Specialist-20261107/handoff-fixture'
    if fixture.exists():raise RuntimeError('Fixture exists; inspect before reuse')
    for p in (root/'Agent').rglob('*.py'):
        if '.runtime' in p.parts or '__pycache__' in p.parts:continue
        dest=fixture/p.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
    policy=json.loads((root/'Agent/hardware_profiles.json').read_text(encoding='utf-8'))
    ids={'qwen27-q4','swift27-abliterated-q4'}
    policy['models']=[m for m in policy['models'] if m['id'] in ids]
    policy.update(selection='qwen27-q4',backend='cuda',context_tokens=32768,coding_routing='automatic',weight_edit_profile='original')
    for m in policy['models']:
        if m['id']=='swift27-abliterated-q4':m['coding_route_validated']=True # Test fixture only, not live acceptance.
        for key in ('path','projector'):
            path=root/m[key];dest=fixture/m[key];dest.parent.mkdir(parents=True,exist_ok=True)
            os.link(path,dest)
    for sub in ('LLM/llamacpp','Runtime/BootstrapPython'):
        for path in (root/sub).rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts:continue
            dest=fixture/path.relative_to(root);dest.parent.mkdir(parents=True,exist_ok=True);os.link(path,dest)
    (fixture/'Agent/hardware_profiles.json').write_text(json.dumps(policy,indent=2),encoding='utf-8')
    (fixture/'Agent/instance-settings.json').write_text(json.dumps({'name':'Swift handoff verification','ports':{'qwen':0}}),encoding='utf-8')
    return fixture

def run(root):
    sys.dont_write_bytecode=True;sys.path.insert(0,str(root/'Agent'))
    import chat_model_switch as switch, service_manager as service, instance_runtime
    from runtime_policy import load_policy
    from chat_priority import Foreground
    cancel=threading.Event();events=[];foreground=Foreground(root)
    records={};original=(root/'Agent/hardware_profiles.json').read_bytes()
    def status(message):print(message,flush=True);events.append({'at':time.time(),'message':message})
    def infer():
        req=urllib.request.Request(instance_runtime.url('qwen','/v1/chat/completions'),data=json.dumps({
            'messages':[{'role':'user','content':'Reply with exactly READY.'}], 'max_tokens':24,
            'temperature':0,'chat_template_kwargs':{'enable_thinking':False}}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=60) as r:value=json.load(r)
        text=value['choices'][0]['message']['content'];assert 'READY' in text,text
        return text
    def tool_check():
        messages=[{'role':'user','content':'Read app.py with the read_file tool before suggesting a fix. Do not guess its contents.'}]
        tool={'type':'function','function':{'name':'read_file','description':'Read a source file.',
              'parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}}
        def send():
            payload={'messages':messages,'tools':[tool],'max_tokens':512,'temperature':0,
                     'chat_template_kwargs':{'enable_thinking':False}}
            req=urllib.request.Request(instance_runtime.url('qwen','/v1/chat/completions'),
                 data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=90) as r:return json.load(r)['choices'][0]['message']
        first=send();calls=first.get('tool_calls') or []
        assert len(calls)==1 and calls[0]['function']['name']=='read_file',first
        assert json.loads(calls[0]['function']['arguments'])['path']=='app.py',first
        messages += [first,{'role':'tool','tool_call_id':calls[0]['id'],'content':'def add(a, b):\n    return a - b\n# Requirement: return the sum of a and b.'},
                     {'role':'user','content':'Now show the corrected Python function. No further file reads are needed.'}]
        second=send();assert 'a + b' in (second.get('content') or ''),second
        return {'passed':True,'tool_called':'read_file','tool_calls_executed':0,'fixture_reply':second.get('content')}
    try:
        assert not service._listener_identity()['open'],'Fixture listener unexpectedly occupied'
        foreground.acquire(cancel,lambda:None,status)
        records['general']=switch.prepare_chat(root,'deep',cancel_event=cancel,on_status=status)
        records['general_reply']=infer()
        records['specialist']=switch.prepare_request(root,'deep',cancel_event=cancel,on_status=status,
                            messages=[{'role':'user','content':'Implement a Python function and tests.'}])
        assert records['specialist']['model']['id']=='swift27-abliterated-q4',records['specialist']
        assert records['specialist'].get('coding_route'),'Automatic route was skipped'
        records['specialist_reply']=infer()
        records['tool_protocol']=tool_check()
        records['returned']=switch.finish_request(root,records['specialist'],cancel_event=cancel,on_status=status)
        assert records['returned']['model']['id']=='qwen27-q4'
        records['returned_reply']=infer()
        assert (root/'Agent/hardware_profiles.json').read_bytes()==original,'Saved settings changed'
        records['passed']=True
    finally:
        # All processes belong to this disposable root and its unique port.
        identity=service._listener_identity()
        if identity['open']:
            assert identity['portable_qwen'],'Foreign listener left untouched'
            with service._qwen_lifecycle_mutex():service._stop_qwen_listener()
        foreground.close()
        records.update(root=str(root),events=events,production_accounts_accessed=False)
        (root.parent/('handoff-'+root.drive[0]+'.json')).write_text(json.dumps(records,indent=2),encoding='utf-8')
    print(json.dumps({'root':str(root),'passed':records.get('passed',False)}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--prepare',action='store_true');a=p.parse_args()
    if a.prepare:print(prepare(a.root))
    else:run(a.root)
