"""Optional Qwen 2511 editor: bounded native multi-reference Comfy graph.

No model download or service start occurs here. Admission uses fresh resources
after the existing exclusive GPU lease and chat handoff.
"""
import json
from pathlib import Path
from runtime_policy import ROOT, GIB, detect_hardware, load_effective_policy, portable_path
from media_policy import cuda_memory

PROFILES=('auto','qwen-lightning','qwen-quality','legacy')
MODEL='qwen_image_edit_2511_int8_convrot.safetensors'
ENCODER='qwen_2.5_vl_7b_fp8_scaled.safetensors'
VAE='qwen_image_vae.safetensors'
LORA='Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors'


def assets(root=ROOT):
    return json.loads((Path(root)/'Agent/qwen_image_edit_assets.json').read_text(encoding='utf-8'))['assets']


def missing_assets(root=ROOT, lightning=True):
    missing=[]
    for row in assets(root):
        if not lightning and row['id']=='qwen-edit-loras':continue
        path=portable_path(Path(root),row['dest'])
        if not path.is_file() or path.stat().st_size!=row['size']:missing.append(row['id'])
    return missing


def preference(root=ROOT, explicit=None, policy=None):
    policy=load_effective_policy(root) if policy is None else policy
    value=explicit if explicit not in (None,'auto') else policy.get('media',{}).get('edit_profile','auto')
    if value not in (*PROFILES,'flux','klein4','pix2pix'):raise ValueError('Unknown image editing profile')
    return value


def plan(root=ROOT, *, profile=None, references=1, hardware=None, policy=None, variant='standard', engine='auto'):
    """Auto can retain the existing editor; explicit Qwen never silently falls back."""
    if type(references) is not int or not 1<=references<=3:raise ValueError('Editing accepts 1-3 ordered input images')
    chosen=preference(root,profile,policy)
    if chosen not in ('auto','qwen-lightning','qwen-quality'):
        return {'profile':chosen,'qwen':False,'reason':'Saved or explicit existing editing method'}
    if engine not in (None,'auto'):
        if chosen!='auto':raise ValueError('Qwen image editing cannot use a native CPU/Vulkan engine')
        return {'profile':'legacy','qwen':False,'reason':'Explicit native image engine selected'}
    hw=hardware if hardware is not None else detect_hardware()
    failures=[]
    if variant not in ('standard','official'):failures.append('Qwen 2511 has no configured uncensored counterpart')
    if hw.get('system')!='Windows' or hw.get('machine','').lower() not in ('amd64','x86_64'):
        failures.append('Qwen 2511 is currently validated through Windows NVIDIA CUDA only')
    required_vram=(12 if references==1 else 16 if references==2 else 18)*GIB
    if cuda_memory(hw)<required_vram:failures.append(f'needs {required_vram//GIB} GiB free CUDA VRAM after chat handoff')
    if hw.get('ram_available_bytes',0)<12*GIB:failures.append('needs 12 GiB available host RAM after chat handoff')
    if hw.get('commit_available_bytes',hw.get('ram_available_bytes',0))<20*GIB:
        failures.append('needs 20 GiB available Windows commit for model staging and GPU transfers')
    missing=missing_assets(root,chosen!='qwen-quality')
    if missing:failures.append('optional Qwen model downloads are incomplete; use the optional model installer')
    if failures:
        reason='; '.join(failures)
        if chosen!='auto':raise RuntimeError('Qwen image editing unavailable: '+reason)
        return {'profile':'legacy','qwen':False,'reason':reason,'optional_models_missing':missing}
    return {'profile':'qwen-quality' if chosen=='qwen-quality' else 'qwen-lightning','qwen':True,
            'backend':'cuda','references':references,'steps':40 if chosen=='qwen-quality' else 4,
            'cfg':4.0 if chosen=='qwen-quality' else 1.0,'max_pixels':1024**2,
            'free_cuda_bytes':cuda_memory(hw),'ram_available_bytes':hw['ram_available_bytes'],
            'reason':'Optional Qwen 2511 admitted after chat handoff; dynamic Comfy offload remains active'}


def workflow(images,instruction,seed,profile):
    if not isinstance(images,list) or not 1<=len(images)<=3 or any(not isinstance(p,str) or not p for p in images):
        raise ValueError('Supply 1-3 uploaded image names in their intended order')
    if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>16000 or '\x00' in instruction:
        raise ValueError('Editing instruction must contain 1-16000 characters')
    if type(seed) is not int or not 0<=seed<2**63:raise ValueError('Seed must be a nonnegative 63-bit integer')
    if not profile.get('qwen') or profile['profile'] not in ('qwen-lightning','qwen-quality'):
        raise ValueError('A Qwen image editing admission is required')
    fast=profile['profile']=='qwen-lightning'
    def node(kind,**inputs):return {'class_type':kind,'inputs':inputs}
    graph={
        'model':node('UNETLoader',unet_name=MODEL,weight_dtype='default'),
        'clip':node('CLIPLoader',clip_name=ENCODER,type='qwen_image',device='default'),
        'vae':node('VAELoader',vae_name=VAE),
        'shift':node('ModelSamplingAuraFlow',model=['model',0],shift=3.1),
        'norm':node('CFGNorm',model=['shift',0],strength=1.0),
        'positive':node('TextEncodeQwenImageEditPlus',clip=['clip',0],vae=['vae',0],prompt=instruction),
        'negative':node('TextEncodeQwenImageEditPlus',clip=['clip',0],vae=['vae',0],prompt=''),
        'latent':node('VAEEncode',pixels=['scale1',0],vae=['vae',0]),
        'sample':node('KSampler',model=['norm',0],positive=['positive',0],negative=['negative',0],
            latent_image=['latent',0],seed=seed,steps=4 if fast else 40,cfg=1.0 if fast else 4.0,
            sampler_name='euler',scheduler='simple',denoise=1.0),
        'decode':node('VAEDecode',samples=['sample',0],vae=['vae',0]),
        'save':node('SaveImage',images=['decode',0],filename_prefix='PortalAI-Qwen2511')}
    if fast:
        graph['lightning']=node('LoraLoaderModelOnly',model=['model',0],lora_name=LORA,strength_model=1.0)
        graph['shift']['inputs']['model']=['lightning',0]
    for index,name in enumerate(images,1):
        graph['image'+str(index)]=node('LoadImage',image=name)
        graph['scale'+str(index)]=node('ImageScaleToTotalPixels',image=['image'+str(index),0],
            upscale_method='lanczos',megapixels=1.0,resolution_steps=8)
        for key in ('positive','negative'):graph[key]['inputs']['image'+str(index)]=['scale'+str(index),0]
    return graph


def validate_nodes(graph,object_info):
    missing=sorted({row['class_type'] for row in graph.values()}-set(object_info))
    if missing:raise RuntimeError('The installed ComfyUI lacks Qwen editing nodes: '+', '.join(missing))
