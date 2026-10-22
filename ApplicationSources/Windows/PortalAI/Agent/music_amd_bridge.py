"""Bounded ACE-Step turbo music through isolated ROCm and the shared GPU lease."""
import json
import math
from pathlib import Path
import subprocess

from runtime_policy import ROOT, GIB, detect_hardware
from platform_runtime import python_path,ffmpeg_path
from sdcpp_bridge import run_generation


def use_rocm(hardware=None):
    hw = hardware or detect_hardware()
    return hw.get('system')=='Linux' or not any(g.get('index', 0) == 0 and g.get('backend', 'cuda') == 'cuda'
                   for g in hw.get('gpus', []))


def validate_request(prompt, lyrics, duration, seed):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 512:
        raise ValueError('Small music prompt must contain 1..512 characters')
    if not isinstance(lyrics, str) or len(lyrics) > 4096:
        raise ValueError('Small music lyrics exceed 4096 characters')
    if not math.isfinite(duration) or not 10 <= duration <= 30:
        raise ValueError('Small Radeon music supports 10..30 seconds; choose a duration explicitly within that range')
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Invalid music seed')


def plan(root=ROOT, hardware=None):
    hw = hardware or detect_hardware()
    if hw['system'] not in ('Windows','Linux') or hw['machine'].lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('The ROCm music package layer currently requires Windows x64')
    from amd_runtime import probe
    from linux_ml import media_compute
    gpu=media_compute(root,hw,hardware is not None)
    if not gpu or not gpu.get('available') or not gpu.get('compute_ok'):
        raise RuntimeError('Radeon music requires a successful real AMD compute probe')
    if gpu.get('free_bytes', 0) < 6*GIB:
        raise RuntimeError('Small Radeon music needs 6 GiB free GPU memory after chat unload')
    ram = (20 if gpu.get('shared_memory', True) else 12)*GIB
    if hw['ram_available_bytes'] < ram:
        raise RuntimeError(f'Small Radeon music needs {ram/GIB:g} GiB available RAM after chat unload')
    root = Path(root)
    for rel in ('Runtime/AMDMusic/packages/loguru/__init__.py',
                'Runtime/AMDMusic/api-packages/diffusers/__init__.py',
                'Runtime/AMDAudio/packages/numpy/__init__.py',
                'Music/ACE-Step-1.5/checkpoints/acestep-v15-turbo/config.json',
                'Music/ACE-Step-1.5/checkpoints/vae/config.json',
                'Music/ACE-Step-1.5/checkpoints/Qwen3-Embedding-0.6B/config.json'):
        if hw['system']=='Linux' and rel.startswith('Runtime/'):
            rel='Runtime/LinuxPackages/media/'+rel.split('/packages/')[-1].split('/api-packages/')[-1]
        if not (root/rel).is_file():
            raise RuntimeError('AMD music dependency missing: '+rel)
    return {'backend':gpu.get('backend','rocm'), 'engine':'acestep-rocm', 'profile':'turbo-diffusion-only',
            'min_free_ram_bytes':4*GIB, 'max_seconds':30,
            'reason':'One sample, eight steps, CPU offloading; physical Radeon inference validation pending'}


def generate(profile, prompt, lyrics='', duration=15, instrumental=False, seed=42, root=ROOT, timeout=900, check_request=None):
    validate_request(prompt, lyrics, duration, seed)
    root = Path(root).resolve()
    def command(part):
        argv = [str(python_path(root)), '-B', '-I', '-X', 'utf8',
                str(root/'Agent/acestep_amd_entry.py'), '--output', str(part), '--prompt', prompt,
                '--lyrics', lyrics, '--duration', str(duration), '--seed', str(seed)]
        if instrumental: argv.append('--instrumental')
        return argv
    def validate(part):
        if not part.is_file() or not 1024 <= part.stat().st_size <= 32*1024**2:
            raise RuntimeError('ACE-Step did not produce a bounded FLAC')
        cp = subprocess.run([str(ffmpeg_path(root,True)), '-v', 'error',
            '-show_entries', 'stream=sample_rate,channels,duration', '-of', 'json', str(part)],
            capture_output=True, timeout=30, check=True)
        streams = json.loads(cp.stdout)['streams']
        if len(streams) != 1:
            raise RuntimeError('Unexpected music stream count')
        stream = streams[0]
        if (int(stream['sample_rate']) != 48000 or int(stream['channels']) not in (1, 2)
                or abs(float(stream['duration'])-duration) > .2):
            raise RuntimeError('Generated music has unexpected rate/channels/duration')
    result = run_generation(profile, command, validate, root=root, timeout=timeout, kind='music', check_request=check_request)
    return {**result, 'backend':'rocm', 'profile':'turbo-diffusion-only',
            'duration_seconds':duration, 'seed':seed, 'physical_radeon_validation':'pending'}
