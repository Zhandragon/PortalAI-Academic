"""Offline instrumental MusicGen Small, on the bundled CPU runtime only."""
import json
import math
from pathlib import Path
import subprocess

from runtime_policy import ROOT, GIB, detect_hardware
from platform_runtime import python_path, ffmpeg_path
from sdcpp_bridge import run_generation

REVISION = '4c8334b02c6ec4e8664a91979669a501ec497792'
MODEL_SHA256 = '1bdc99d43eb6c775967df24b65b0a9f847c0907e95664698d93b5a1c35f5090d'
MODEL_BYTES = 2364427288
MODEL_FILES = ('config.json', 'generation_config.json', 'model.safetensors', 'preprocessor_config.json',
               'special_tokens_map.json', 'spiece.model', 'tokenizer.json', 'tokenizer_config.json')


def validate_request(prompt, lyrics, duration, instrumental, seed=42):
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 512:
        raise ValueError('MusicGen prompt must contain 1..512 characters')
    if not instrumental or (lyrics or '').strip():
        raise ValueError('MusicGen CPU generates instrumentals only. Use --instrumental without lyrics, or choose a compatible ACE-Step GPU route for vocals.')
    if not math.isfinite(duration) or not 1 <= duration <= 30:
        raise ValueError('MusicGen CPU supports 1..30 seconds. Longer requests are not truncated or looped.')
    if type(seed) is not int or not 0 <= seed < 2**31:
        raise ValueError('Invalid music seed')


def assets(root=ROOT, *, verify=False):
    import hashlib
    from profile_paths import _contained
    root = Path(root).resolve(); folder = root/'Music/MusicGen-small'
    for name in MODEL_FILES:
        path = folder/name
        _contained(root, path)
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise RuntimeError('MusicGen asset is missing or linked: '+name)
        receipt = root/'Maintenance/Imports'/('musicgen-small-'+name.replace('.', '-')+'.json')
        _contained(root, receipt)
        row = json.loads(receipt.read_text(encoding='utf-8'))
        if row.get('verified') is not True or row.get('revision') != REVISION or row.get('size') != path.stat().st_size:
            raise RuntimeError('MusicGen asset does not match the pinned receipt: '+name)
        if name == 'model.safetensors' and (row.get('sha256') != MODEL_SHA256 or row['size'] != MODEL_BYTES):
            raise RuntimeError('MusicGen weight receipt does not match the reviewed model')
        if verify:
            with path.open('rb') as stream: digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            if digest != row.get('sha256'): raise RuntimeError('MusicGen asset checksum differs: '+name)
    return folder


def plan(root=ROOT, hardware=None):
    hw = hardware if hardware is not None else detect_hardware()
    if hw.get('system') not in ('Windows', 'Linux') or hw.get('machine', '').lower() not in ('amd64', 'x86_64'):
        raise RuntimeError('MusicGen CPU requires bundled Windows/Linux x64 Python')
    if hw['ram_available_bytes'] < 10*GIB:
        raise RuntimeError('MusicGen CPU needs 10 GiB available RAM after chat unload (8 GiB worker cap plus 2 GiB reserve)')
    assets(root)
    layer = 'Runtime/ProteinDesign/windows-cpu' if hw['system'] == 'Windows' else 'Runtime/LinuxTorch/cpu'
    if not (Path(root)/layer/'torch/__init__.py').is_file():
        raise RuntimeError('Bundled CPU Torch is not installed')
    return {'engine':'musicgen-cpu', 'backend':'cpu', 'profile':'musicgen-small',
            'max_memory_bytes':8*GIB, 'min_free_ram_bytes':2*GIB, 'max_seconds':30}


def command(root, output, prompt, duration, seed=42, *, artifacts_dir=None):
    argv = [str(python_path(root)), '-B', '-I', '-X', 'utf8', str(Path(root)/'Agent/music_cpu_entry.py'),
            '--output', str(output), '--prompt', prompt, '--duration', str(duration), '--seed', str(seed)]
    if artifacts_dir is not None: argv += ['--artifacts-dir', str(artifacts_dir)]
    return argv


def validate_audio(path, duration, root=ROOT):
    if not path.is_file() or not 1024 <= path.stat().st_size <= 8*1024**2:
        raise RuntimeError('MusicGen did not produce a bounded FLAC')
    cp = subprocess.run([str(ffmpeg_path(root, True)), '-v', 'error', '-show_entries',
        'stream=sample_rate,channels,duration', '-of', 'json', str(path)], capture_output=True,
        check=True, timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    streams = json.loads(cp.stdout)['streams']
    if len(streams) != 1 or int(streams[0]['sample_rate']) != 32000 or int(streams[0]['channels']) != 1 or abs(float(streams[0]['duration'])-duration) > .02:
        raise RuntimeError('MusicGen output has an unexpected rate, channel count or duration')


def generate(profile, prompt, lyrics='', duration=15, instrumental=False, seed=42, root=ROOT, timeout=900, check_request=None):
    validate_request(prompt, lyrics, duration, instrumental, seed)
    result = run_generation(profile, lambda output: command(root, output, prompt, duration, seed),
                            lambda output: validate_audio(output, duration, root), root=root, timeout=timeout, kind='music', check_request=check_request)
    return {**result, 'backend':'cpu', 'profile':'musicgen-small', 'duration_seconds':duration, 'seed':seed,
            'instrumental':True, 'license':'CC-BY-NC-4.0',
            'variant_note':'No separate runtime prompt filter; standard MusicGen weights, not a separately abliterated checkpoint.'}
