"""Small Radeon editing profiles, independent of the CUDA/FLUX workflow."""
import json
from pathlib import Path
import subprocess

from runtime_policy import ROOT,GIB,detect_hardware
from platform_runtime import python_path
from sdcpp_bridge import run_generation,validate_png
from media_paths import media_reference


def uses_radeon(hardware=None):
    hw=hardware or detect_hardware()
    return hw.get('system')=='Linux' or not any(g.get('index',0)==0 and g.get('backend','cuda')=='cuda' for g in hw.get('gpus',[]))


def plan(kind='edit',root=ROOT,hardware=None,cpu_validation=False):
    hw=hardware or detect_hardware()
    if hw['system'] not in ('Windows','Linux'):raise RuntimeError('Editing requires Windows/Linux x64')
    gpu={}
    if not cpu_validation:
        from amd_runtime import probe
        from linux_ml import media_compute
        gpu=media_compute(root,hw,hardware is not None)
        if not gpu or not gpu.get('compute_ok'):raise RuntimeError('Editing needs a real Radeon compute probe')
        if gpu.get('free_bytes',0)<(8 if kind=='video-edit' else 4)*GIB:raise RuntimeError('Insufficient free Radeon GPU memory after handoff')
    needed=(24 if gpu.get('shared_memory',True) else 16) if kind=='video-edit' else (14 if gpu.get('shared_memory',True) else 8)
    if hw['ram_available_bytes']<needed*GIB:raise RuntimeError(f'{kind} requires {needed} GiB free RAM after handoff')
    return {'engine':'instruct-pix2pix' if kind!='video-edit' else 'wan-vace-1.3b',
            'backend':'rocm-cpu-validation' if cpu_validation else gpu.get('backend','rocm'),'cpu_validation':cpu_validation,
            'min_free_ram_bytes':4*GIB,'max_memory_bytes':12*GIB,'max_side':512 if kind!='video-edit' else 320,
            'max_chunk_frames':17,'physical_radeon_validated':False}


def edit(profile,source,instruction,mask=None,seed=42,steps=20,root=ROOT):
    root=Path(root).resolve();source=media_reference(root,source)
    if not source.is_file():raise FileNotFoundError(source)
    if not isinstance(instruction,str) or not instruction.strip() or len(instruction)>4000:raise ValueError('Invalid editing instruction')
    if type(steps) is not int or not 1<=steps<=50:raise ValueError('Editing steps must be 1..50')
    if type(seed) is not int or not 0<=seed<2**63:raise ValueError('Invalid editing seed')
    def command(part):
        result=[str(python_path(root)),'-B','-I','-X','utf8',str(root/'Agent/radeon_edit_entry.py'),
                '--source',str(source),'--instruction',instruction,'--seed',str(seed),'--steps',str(steps),'--output',str(part)]
        if mask:result+=['--mask',str(media_reference(root,mask))]
        if profile.get('cpu_validation'):result+=['--cpu-validation']
        return result
    def validate(part):
        import struct
        if not part.is_file():raise RuntimeError('Editing produced no image')
        with part.open('rb') as f:header=f.read(24)
        w,h=struct.unpack('>II',header[16:24])
        if min(w,h)<64 or max(w,h)>512:raise RuntimeError('Edited image exceeds scaled profile dimensions')
        validate_png(part,w,h)
    result=run_generation(profile,command,validate,root=root,timeout=900)
    return {**result,'hardware_profile':profile,'model_variant':'instruct-pix2pix',
            'route':'masked-instruction-edit' if mask else 'instruction-edit','seed':seed}


def small_vace(wf):
    """Replace the architecture and remove incompatible 14B acceleration LoRAs."""
    wf['1']['inputs']['unet_name']='wan2.1_vace_1.3B_fp16.safetensors'
    wf['2']['inputs']['device']='cpu'
    wf.pop('3',None)
    wf['4']['inputs']['model']=['1',0]
    for key in ('5','6'):wf[key]['inputs']['clip']=['2',0]
    wf['11']['inputs'].update(steps=20,cfg=6.)
    wf['13']['class_type']='VAEDecodeTiled'
    wf['13']['inputs'].update(tile_size=256,overlap=64,temporal_size=16,temporal_overlap=4)
    return wf
