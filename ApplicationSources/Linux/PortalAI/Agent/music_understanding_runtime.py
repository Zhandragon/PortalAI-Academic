"""Offline Linux specialist admission and isolated portable worker launch."""
import hashlib
import json
import os
from pathlib import Path
import sys

from runtime_policy import GIB, detect_hardware, memory_info, portable_env
from platform_runtime import python_path

VERSIONS = {'demucs':'4.1.0','julius':'0.2.8','lameenc':'1.8.4','sphn':'0.2.1'}
DEMUCS_MODEL = ('MusicUnderstanding/cache/huggingface/hub/models--adefossez--HTDemucs/'
                'snapshots/cbc8a9b1a87023b7fd74e7b3412e6321c0eab003/955717e8.safetensors')


def package_layer(root, *, verify=False):
    root = Path(root).resolve()
    layer = root/'Runtime/LinuxPackages/musicunderstanding'
    receipt = root/'Maintenance/Imports/linux-musicunderstanding-lock.json'
    lock = json.loads(receipt.read_text(encoding='utf-8'))
    if (not isinstance(lock,dict) or not isinstance(lock.get('assets'),list) or
            any(not isinstance(row,dict) for row in lock['assets']) or
            not lock.get('verified') or {row.get('name'):row.get('version') for row in lock['assets']} != VERSIONS):
        raise RuntimeError('Linux music dependency receipt does not match the reviewed versions')
    for name in ('demucs/__init__.py','julius/__init__.py','sphn/__init__.py'):
        if not (layer/name).is_file(): raise RuntimeError('Linux music dependency is incomplete: '+name)
    if verify:
        for row in lock['files']:
            path = (layer/row['path']).resolve()
            if not path.is_relative_to(layer.resolve()) or not path.is_file() or path.stat().st_size != row['bytes']:
                raise RuntimeError('Linux music dependency path or size changed')
            with path.open('rb') as source: digest = hashlib.file_digest(source,'sha256').hexdigest()
            if digest != row['sha256']: raise RuntimeError('Linux music dependency hash changed')
    return layer


def available(root, kind):
    root = Path(root)
    try:
        if not (root/'Runtime/LinuxPython/run-python').is_file():
            raise RuntimeError('Bundled Linux interpreter is missing')
        package_layer(root)
        models = root/'MusicUnderstanding/models'
        if kind == 'moss':
            base = models/'MOSS-Music-8B-Instruct'
            index = json.loads((base/'model.safetensors.index.json').read_text())
            shards = set(index['weight_map'].values())
            if not shards or any('/' in name or '\\' in name or not (base/name).is_file() for name in shards):
                raise RuntimeError('MOSS weights are incomplete')
            if not (base/'config.json').is_file(): raise RuntimeError('MOSS config is missing')
        elif kind == 'clap':
            if not all((models/'CLAP-larger-music'/name).is_file() for name in ('config.json','pytorch_model.bin')):
                raise RuntimeError('CLAP model is incomplete')
        elif kind == 'separate-vocals':
            if not (root/DEMUCS_MODEL).is_file(): raise RuntimeError('Pinned offline Demucs weights are missing')
        else:
            raise RuntimeError('This Linux music specialist is not packaged: '+kind)
        return True, None
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return False, str(exc)


def limits(kind, backend, shared=False):
    if kind not in ('moss','clap','separate-vocals'): raise ValueError('Unknown specialist')
    if kind == 'moss':
        # CPU uses float32; no unbounded auto-offload or large BF16 CPU load.
        ram, gpu, process = ((44,0,40) if backend=='cpu' else (44 if shared else 26,20,24))
    else:
        ram, gpu, process = (3,0,4) if backend=='cpu' else (6 if shared else 3,2,4)
    return {'min_ram_bytes':ram*GIB,'min_gpu_bytes':gpu*GIB,'max_memory_bytes':process*GIB}


def plan(root, kind, requested='auto', *, hardware=None):
    if requested not in ('auto','cpu','cuda','rocm'): raise ValueError('Invalid specialist device')
    hw = hardware if hardware is not None else detect_hardware()
    if hw.get('system') != 'Linux' or hw.get('machine','').lower() not in ('x86_64','amd64'):
        raise RuntimeError('Linux specialists require Linux x86-64')
    backend = 'cpu'; gpu = {}
    if requested != 'cpu':
        candidate = requested if requested != 'auto' else ('cuda' if any(
            item.get('index',0)==0 and item.get('backend','cuda')=='cuda' for item in hw.get('gpus',[])) else 'rocm')
        if hardware is None:
            from linux_ml import probe
            gpu = probe(root, candidate)
        else:
            gpu = hw.get('media_gpu',{})
        if gpu.get('available') and gpu.get('compute_ok') and gpu.get('backend') == candidate:
            backend = candidate
        elif requested != 'auto':
            raise RuntimeError('Requested '+candidate+' music device failed its real compute probe')
    selected = limits(kind, backend, bool(gpu.get('shared_memory')))
    fits = hw.get('ram_available_bytes',0) >= selected['min_ram_bytes'] and gpu.get('free_bytes',0) >= selected['min_gpu_bytes']
    if not fits and requested == 'auto' and backend != 'cpu':
        backend = 'cpu'; gpu = {}; selected = limits(kind,backend)
        fits = hw.get('ram_available_bytes',0) >= selected['min_ram_bytes']
    if not fits:
        raise RuntimeError(f'{kind} on {backend} needs {selected["min_ram_bytes"]/GIB:g} GiB free RAM'
                           f' and {selected["min_gpu_bytes"]/GIB:g} GiB free GPU memory after chat handoff')
    return {'kind':kind,'backend':backend,'device':'cpu' if backend=='cpu' else 'cuda',
            'shared_memory':bool(gpu.get('shared_memory')),**selected}


def activate(root, backend):
    layer = package_layer(root, verify=True)
    from linux_ml import activate as activate_ml
    activate_ml(root,backend)
    sys.path.insert(0,str(layer))
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')


def check_worker(kind, backend, *, shared=False):
    """Recheck free memory and selected device before loading model weights."""
    import torch
    needed = limits(kind,backend,shared)
    if memory_info()[1] < needed['min_ram_bytes']:
        raise RuntimeError('Free host memory dropped below specialist admission')
    if backend != 'cpu':
        if not torch.cuda.is_available() or bool(torch.version.hip) != (backend=='rocm'):
            raise RuntimeError('Selected specialist GPU backend is unavailable')
        test = torch.ones((16,16),device='cuda',dtype=torch.float16)
        if not bool(torch.all(test@test==16).item()): raise RuntimeError('Specialist GPU compute failed')
        del test
        if torch.cuda.mem_get_info()[0] < needed['min_gpu_bytes']:
            raise RuntimeError('Free GPU memory dropped below specialist admission')
    return 'cpu' if backend=='cpu' else 'cuda'


def run(root, arguments, timeout):
    root = Path(root).resolve(); kind = arguments[0]
    from profile_paths import capture, ProfileLocked
    identity = capture(root)
    requested = arguments[arguments.index('--device')+1] if '--device' in arguments else 'auto'
    admitted = plan(root,kind,requested)
    command = [str(python_path(root)),'-B','-I',str(root/'MusicUnderstanding/runtime_driver.py'),
               '--portalai-backend',admitted['backend']]
    if admitted['shared_memory']: command.append('--portalai-shared-memory')
    command += list(arguments)
    env = portable_env(root)
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1')
    if capture(root) != identity: raise ProfileLocked('The music request login ended before launch')
    from linux_owned_run import run as owned_run
    result = owned_run(command,cwd=root,env=env,timeout=timeout,memory_bytes=admitted['max_memory_bytes'])
    if capture(root) != identity: raise ProfileLocked('The music request login ended before its result')
    return result
