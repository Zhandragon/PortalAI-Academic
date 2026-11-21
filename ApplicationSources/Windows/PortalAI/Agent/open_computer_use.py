"""Portable iFurySt/open-computer-use UIA adapter inside Desktop's grants."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def call(root,row,check,tool='get_app_state',snapshot=None,element=None,value=None):
    if os.name!='nt':raise RuntimeError('The installed scoped Open Computer Use adapter currently supports Windows')
    layer=Path(root)/'Runtime/ComputerUse/windows-x64'
    manifest=json.loads((layer/'manifest.json').read_text(encoding='utf-8'))
    script=layer/'runtime.ps1'
    if hashlib.sha256(script.read_bytes()).hexdigest()!=manifest['files']['runtime.ps1']:
        raise RuntimeError('Open Computer Use runtime changed; repair the portable package')
    from profile_paths import private_path
    from runtime_policy import portable_env
    from tool_process import ToolProcess
    folder=private_path(root,'Data/Runtime/ComputerUse')
    folder.mkdir(parents=True,exist_ok=True)
    request=folder/(uuid.uuid4().hex+'.json')
    payload={'tool':tool,'app':str(row['pid']),'expected_pid':row['pid'],
             'expected_created':row['created'],'windowHandle':row['window'],
             'include_ax':True,'include_screenshot':False,'text_limit':500,
             'max_tree_nodes':160,'max_tree_depth':24}
    if tool!='get_app_state':
        if tool not in ('click','set_value'):raise ValueError('Unsupported accessibility action')
        record=next((e for e in (snapshot or {}).get('elements',[]) if str(e['index'])==element),None)
        if record is None:raise ValueError('Use an element ID from a fresh state observation')
        payload.update(element=record,windowBounds=snapshot['windowBounds'],click_method='accessibility',mouse_button='left',click_count=1)
        if tool=='set_value':
            if not isinstance(value,str) or len(value)>2000 or '\0' in value:raise ValueError('Set at most 2000 text characters')
            payload['value']=value
    check();request.write_text(json.dumps(payload,ensure_ascii=True),encoding='utf-8')
    env=portable_env(root)
    for key in tuple(env):
        if key.startswith('OPEN_COMPUTER_USE_'):env.pop(key)
    env.update(TEMP=str(folder),TMP=str(folder),OPEN_COMPUTER_USE_ALLOW_GLOBAL_POINTER_FALLBACKS='0')
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    owner=None
    try:
        owner=ToolProcess(root,[str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(script),str(request)],cwd=folder,env=env,check=check,monitor=False)
        p=owner.start();deadline=time.monotonic()+35
        while True:
            check();owner.check()
            if time.monotonic()>deadline:raise TimeoutError('Computer action timed out; inspect its outcome before retrying')
            try:out,err=p.communicate(timeout=.1);break
            except subprocess.TimeoutExpired:pass
        check()
        if p.returncode or len(out)>512*1024:raise RuntimeError('Computer helper failed; outcome may be uncertain: '+err[-1200:])
        result=json.loads(out.lstrip('\ufeff'))
        if not result.get('ok'):raise RuntimeError(str(result.get('error','Computer operation failed'))[:1600])
        observed=result.get('snapshot')
        if observed and (observed.get('windowHandle')!=row['window'] or observed.get('app',{}).get('pid')!=row['pid']):
            raise RuntimeError('Computer observation target changed; inspect again without repeating input')
        return result
    finally:
        if owner:owner.close()
        request.unlink(missing_ok=True)
