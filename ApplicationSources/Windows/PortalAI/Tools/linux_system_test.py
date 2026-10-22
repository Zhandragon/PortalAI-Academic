"""Recipient-side Linux diagnostics. Presence, imports and GPU proof stay distinct."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

def rows(root,component='All',imports=True):
    sys.path.insert(0,str(root/'Agent'))
    from platform_runtime import python_path,ffmpeg_path
    from runtime_policy import storage_budget
    result=[]
    def add(status,label,detail):result.append({'status':status,'label':label,'detail':str(detail)})
    from diagnostic_catalog import resolve,source_rows,COVERAGE
    try:selection=resolve(component)
    except ValueError as exc:return [{'status':'FAIL','label':'Unknown diagnostic component','detail':str(exc)}]
    key=selection['argument']
    if key!='all':
        result.extend(source_rows(root,component))
        if key!='qwen':
            if imports:
                from dependency_check import check,platform_checks
                labels={'science':{'Science Workbench'},'cpu_speech':{'Piper CPU voice'},
                        'stt':{'Speech transcription'},'chat_ui':{'GUI / Tk','Foundation'},
                        'accounts':{'Foundation'},'missions':{'Foundation'}}
                selected=labels.get(key,{'Linux media CPU import check'} if key in
                    {'comfyui','flux','vace','ace','music_understanding','tts','musetalk','mmaudio','media_editing'} else set())
                result.extend(check(root,entry) for entry in platform_checks() if entry[0] in selected)
            add('WARN','Targeted Linux validation scope',COVERAGE+' Shared CPU media imports do not validate the selected model or Radeon execution.')
            return result
    if component.lower() in ('all','qwen'):
        from lifecycle_probe import probe_qwen
        state=probe_qwen(root);add('PASS' if state.get('ready') else 'WARN','Model state',state['state'])
        for backend in ('cpu','vulkan','cuda'):
            file=root/f'LLM/backends/linux-{backend}/llama-server'
            present=file.is_file() and os.access(file,os.X_OK)
            add('PASS' if present else 'WARN' if backend=='cuda' else 'FAIL','Linux LLM '+backend,
                str(file) if present or backend!='cuda' else 'No verified pinned Linux CUDA LLM build bundled; NVIDIA Linux chat can use the bundled Vulkan backend.')
    if key=='qwen':return result
    result.extend(source_rows(root,'All'))
    for file,args in ((ffmpeg_path(root),['-version']),(ffmpeg_path(root,True),['-version']),
                      (root/'Runtime/SoX/linux-x64/bin/sox',['--version'])):
        try:
            cp=subprocess.run([str(file),*args],capture_output=True,text=True,timeout=20)
            add('PASS' if cp.returncode==0 else 'FAIL',file.name,(cp.stdout or cp.stderr)[-1500:])
        except Exception as exc:add('FAIL',file.name,exc)
    budget=storage_budget(root);add('PASS' if budget['allowed'] else 'FAIL','SSD reserves',json.dumps(budget))
    from linux_job import preflight
    try:add('PASS','Worker ownership',preflight())
    except Exception as exc:add('FAIL','Worker ownership',exc)
    from vm_runner import preflight as vm_preflight
    try:add('PASS','Secure VM preflight',vm_preflight(root,verify=False))
    except Exception as exc:add('WARN','Secure VM unavailable on this recipient',exc)
    if imports:
        from dependency_check import check,platform_checks
        result.extend(check(root,c) for c in platform_checks())
    add('WARN','Validation scope','Imports and executable probes do not validate physical Radeon/NVIDIA inference, camera/audio devices or KVM guest execution.')
    return result

def main(root,json_output=False,imports=True):
    from maintenance_reports import save
    from capability_registry import detect
    result_rows=rows(root,imports=imports)
    counts={s:sum(r['status']==s for r in result_rows) for s in ('PASS','WARN','FAIL')}
    result={'platform':platform.platform(),'counts':counts,'rows':result_rows,'registry':detect(root)}
    text='\n'.join(f"[{r['status']}] {r['label']}: {r['detail']}" for r in result_rows)
    code=1 if counts['FAIL'] else 0;save(root,'system_test',text,result,code)
    print(json.dumps(result,indent=2) if json_output else text);return code
