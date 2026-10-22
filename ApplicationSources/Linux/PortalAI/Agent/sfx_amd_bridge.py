"""Small MMAudio on isolated ROCm; CPU path is an explicit validation facility."""
import json
import math
from pathlib import Path
import subprocess

from runtime_policy import ROOT, GIB, detect_hardware
from platform_runtime import python_path,ffmpeg_path
from sdcpp_bridge import run_generation
from media_paths import media_reference


def plan(root=ROOT, hardware=None, cpu_validation=False):
    hw=hardware or detect_hardware()
    if hw['system'] not in ('Windows','Linux') or hw['machine'].lower() not in ('amd64','x86_64'):
        raise RuntimeError('MMAudio ROCm package layer currently requires Windows x64')
    if cpu_validation:
        gpu={}; backend='rocm-cpu-validation';needed=14*GIB
    else:
        from amd_runtime import probe
        from linux_ml import media_compute
        gpu=media_compute(root,hw,hardware is not None)
        if not gpu or not gpu.get('available') or not gpu.get('compute_ok'):
            raise RuntimeError('MMAudio needs a successful real AMD compute probe')
        if gpu.get('free_bytes',0)<6*GIB:raise RuntimeError('Small MMAudio needs 6 GiB free AMD GPU memory after chat unload')
        backend=gpu.get('backend','rocm');needed=(18 if gpu.get('shared_memory',True) else 10)*GIB
    if hw['ram_available_bytes']<needed:
        raise RuntimeError(f'Small MMAudio needs {needed/GIB:g} GiB available RAM after chat unload')
    if not cpu_validation:
        from media_precision import probe_bf16
        precision=gpu if hardware is not None else probe_bf16(root,backend)
        if not precision.get('bf16_compute_ok'):
            raise RuntimeError('MMAudio requires a successful BF16 GPU compute probe: '+precision.get('reason','BF16 was not validated'))
    root=Path(root)
    for name in (('Runtime/AMDAudio/packages/open_clip/__init__.py' if hw['system']=='Windows' else 'Runtime/LinuxPackages/media/open_clip/__init__.py'), 'Services/MMAudio/weights/mmaudio_small_44k.pth'):
        if not (root/name).is_file():raise RuntimeError('Small MMAudio dependency is missing: '+name)
    return {'backend':backend,'engine':'mmaudio-rocm','variant':'small_44k','cpu_validation':cpu_validation,
            'min_free_ram_bytes':4*GIB,'max_memory_bytes':14*GIB,
            'max_seconds':8,'reason':'Small MMAudio; separate Python 3.12 ROCm layer; physical Radeon validation pending'}


def generate(profile, prompt, duration=2, negative_prompt='music, speech, vocals', seed=42,
             num_steps=25, cfg_strength=4.5, video=None, root=ROOT, timeout=900):
    if not isinstance(prompt,str) or len(prompt)>4000:raise ValueError('SFX prompt exceeds 4000 characters')
    if not math.isfinite(duration) or not 1<=duration<=8:raise ValueError('Small SFX duration must be 1..8 seconds')
    if type(num_steps) is not int or not 1<=num_steps<=50:raise ValueError('SFX steps must be 1..50')
    if type(seed) is not int or not 0<=seed<2**63:raise ValueError('Invalid SFX seed')
    if not math.isfinite(cfg_strength) or not 0<=cfg_strength<=10:raise ValueError('Invalid SFX guidance')
    if not isinstance(negative_prompt,str) or len(negative_prompt)>4000:raise ValueError('Invalid negative prompt')
    root=Path(root).resolve()
    def command(part):
        args=[str(python_path(root)),'-B','-I',str(root/'Agent/mmaudio_amd_entry.py'),
            '--portalai-output',str(part),'--variant','small_44k','--prompt',prompt,'--negative_prompt',negative_prompt,
            '--duration',str(duration),'--cfg_strength',str(cfg_strength),'--num_steps',str(num_steps),
            '--seed',str(seed),'--output',str(part.parent),'--skip_video_composite']
        if video is not None:
            path=media_reference(root,video)
            if not path.is_file():raise FileNotFoundError(path)
            args+=['--video',str(path)]
        if profile.get('cpu_validation'):args.append('--portalai-cpu-validation')
        return args
    def validate(part):
        if not part.is_file() or not 1024<=part.stat().st_size<=16*1024**2:
            raise RuntimeError('MMAudio did not produce a bounded FLAC')
        cp=subprocess.run([str(ffmpeg_path(root,True)),'-v','error','-show_entries',
            'stream=sample_rate,channels,duration','-of','json',str(part)],capture_output=True,timeout=30,check=True)
        stream=json.loads(cp.stdout)['streams'][0]
        if int(stream['sample_rate'])!=44100 or int(stream['channels']) not in (1,2) or abs(float(stream['duration'])-duration)>.15:
            raise RuntimeError('Generated SFX has unexpected rate/channels/duration')
    result=run_generation(profile,command,validate,root=root,timeout=timeout,kind='sfx')
    return {**result,'variant':'small_44k','duration_seconds':duration,'backend':profile['backend']}
