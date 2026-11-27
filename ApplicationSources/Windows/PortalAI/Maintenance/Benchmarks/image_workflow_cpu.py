"""Replay planner transitions and image previews without a model, network or GUI.

Pass --baseline <git commit> and --pillow-packages <existing package directory>.
Counts are structural opportunities, NOT measured model speed or quality.
"""
import argparse
import ctypes
import gc
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tracemalloc
from types import ModuleType, SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
REPO=ROOT.parents[2]
REL='ApplicationSources/Windows/PortalAI/ControlCenter/media_planning.py'


def memory():
    if sys.platform!='win32':return {}
    class Counters(ctypes.Structure):
        _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[
            (name,ctypes.c_size_t) for name in ('peak_working_set','working_set',
                'peak_paged_pool','paged_pool','peak_nonpaged_pool','nonpaged_pool',
                'pagefile','peak_pagefile')]
    row=Counters();row.cb=ctypes.sizeof(row)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=ctypes.c_void_p
    query=ctypes.WinDLL('psapi').GetProcessMemoryInfo
    query.argtypes=[ctypes.c_void_p,ctypes.POINTER(Counters),ctypes.c_ulong]
    if not query(kernel.GetCurrentProcess(),ctypes.byref(row),row.cb):raise ctypes.WinError()
    return {'working_set_bytes':row.working_set,'peak_working_set_bytes':row.peak_working_set}


def load(source,name,Image):
    module=ModuleType(name)
    exec(compile(source,name,'exec'),module.__dict__)
    module._image_library=lambda root:Image
    return module


def decision(references=False,staged=False):
    return dict(understanding='needs_references' if references else 'sufficient',
        reference_scope='structure' if staged else 'appearance',
        fidelity='Preserve the requested shapes and spatial relationships',
        components=['object','support'],relationships=['object rests on support'],
        uncertainties=['Reference geometry'] if references else [],
        rationale='Reference inspection resolves the requested geometry and appearance.',
        staged=staged,staging_reason='Layout must precede detail.' if staged else 'One independent edit.')


def replay(module,root,images,*,updated,references,staged):
    planner=module.MediaPlanning('Synthetic composition fixture')
    runtime=SimpleNamespace(root=root,_media_planning=planner,
        profile=SimpleNamespace(check=lambda:None,resolve=lambda name,**kw:Path(name)))
    chat=SimpleNamespace(tool_runtime=runtime)
    phases=[]
    def response(label):
        visual=module.context(chat)
        phases.append({'response':label,'images':sum(x.get('type')=='image_url'
            for x in visual['content']) if visual else 0,
            'visual_json_bytes':len(json.dumps(visual).encode()) if visual else 0})
    judgment=decision(references,staged)
    if references:
        response('inspect_references')
        planner.call(runtime,dict(action='inspect',paths=images[:3 if staged else 2]))
        if not updated:
            response('assess');planner.call(runtime,dict(action='assess',assessment=judgment))
        sources=['https://source-one.example/reference','https://source-two.example/reference'] if staged else []
        for url in sources:planner.observe('web',dict(action='read',arguments={'url':url}),{'ok':True})
        response('plan')
        args=dict(action='plan',constraints=['Shape','Relationship'],stages=['Layout','Detail'] if staged else ['Edit'],
                  sources=sources,reference_comparison='The inspected images establish the object shape and placement. This synthetic fixture makes no factual claims.')
        if updated:args['assessment']=judgment
        planner.call(runtime,args)
    elif not updated:
        response('assess');planner.call(runtime,dict(action='assess',assessment=judgment))
    for stage in range(2 if staged else 1):
        response('generate_'+str(stage+1))
        args={'command':'edit','arguments':[planner.outputs[-1] if planner.outputs else images[0],'fixture edit']} if references else {'prompt':'fixture composition'}
        name='media_tool' if references else 'generate_image'
        if updated and not references:args['assessment']=judgment
        assert planner.before(name,args) is None
        output=images[3+stage]
        planner.observe(name,args,{'success':True,'files':[output]})
        if updated:planner.attach_generated_output(runtime)
        else:
            response('inspect_output_'+str(stage+1))
            planner.call(runtime,dict(action='inspect',paths=[output]))
        response('review_'+str(stage+1))
        planner.call(runtime,dict(action='review',passed=['Shape','Relationship']))
    response('final')
    assert planner.call(runtime,{'action':'status'})['complete']
    assert all(Path(p).exists() for p in planner.outputs+planner.references)
    return dict(responses=len(phases),image_attachments=sum(p['images'] for p in phases),
        visual_json_bytes=sum(p['visual_json_bytes'] for p in phases),phases=phases,
        references_retained=len(planner.references),reviews_retained=len(planner.reviews),
        completed_stages=planner.completed_stages)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',required=True)
    parser.add_argument('--pillow-packages',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.pillow_packages))
    from PIL import Image
    sys.modules['native_chat']=SimpleNamespace(model_props=lambda:{'modalities':{'vision':True}})
    baseline=subprocess.check_output(['git','show',args.baseline+':'+REL],cwd=REPO).decode('utf-8-sig')
    current=(ROOT/'ControlCenter/media_planning.py').read_text(encoding='utf-8-sig')
    modules={'baseline':load(baseline,'baseline_planner',Image),'candidate':load(current,'candidate_planner',Image)}
    result={'kind':'CPU structural replay, not an inference benchmark','baseline':args.baseline,
        'new_model_bytes':0,'new_persistent_cache_bytes':0,'scenarios':{}}
    with tempfile.TemporaryDirectory(prefix='PortalAI-cpu-replay-') as folder:
        root=Path(folder);images=[]
        noise=Image.effect_noise((1024,1024),64).convert('RGB')
        for n in range(6):
            path=root/(str(n)+'.png');noise.save(path);images.append(str(path))
        noise.close();gc.collect()
        result['before']=memory();tracemalloc.start();started=time.perf_counter()
        for name,references,staged in [('simple',False,False),('two_references',True,False),('technical_staged',True,True)]:
            result['scenarios'][name]={kind:replay(module,root,images,updated=kind=='candidate',references=references,staged=staged)
                                      for kind,module in modules.items()}
        module=modules['candidate'];planner=module.MediaPlanning()
        rt=SimpleNamespace(root=root,profile=SimpleNamespace(check=lambda:None,resolve=lambda name,**kw:Path(name)))
        planner.call(rt,dict(action='inspect',paths=images))
        result['six_reference_preview_json_bytes']=len(json.dumps(planner.visual).encode())
        result['python_traced_current_bytes'],result['python_traced_peak_bytes']=tracemalloc.get_traced_memory()
        tracemalloc.stop();result['after']=memory();result['cpu_replay_wall_seconds']=round(time.perf_counter()-started,3)
    result['limitations']=['Fixed scripted decisions; no LLM, GPU, web or actual image quality evaluation.',
        'Counts start after reference retrieval; batching independent search/download calls could save more responses.',
        'Working-set peak includes interpreter, Pillow and fixtures; tracemalloc excludes native Pillow allocations.',
        'Fixtures are six 1024-square noise images, not a worst-case decoder memory bound.']
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('scenarios','limitations')},indent=2))
    for name,rows in result['scenarios'].items():print(name,{k:{f:r[f] for f in ('responses','image_attachments')} for k,r in rows.items()})


if __name__=='__main__':main()
