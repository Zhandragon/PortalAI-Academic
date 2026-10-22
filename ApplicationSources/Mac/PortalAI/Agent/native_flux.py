"""Bounded FLUX Klein 4B generation/editing on bundled CPU/Vulkan engines."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from runtime_policy import ROOT, GIB, detect_hardware, portable_path
from sdcpp_bridge import engine_plan, run_generation, validate_png
from platform_runtime import ffmpeg_path
from media_paths import media_reference, media_temp

MODELS = 'Generative/ComfyUI_windows_portable/ComfyUI/models/'
DIT = MODELS+'diffusion_models/flux-2-klein-4b-Q4_0.gguf'
ENCODER = 'LLM/models/Qwen3-4B-Q4_K_M.gguf'
ALTERNATE = MODELS+'text_encoders/flux2-klein-4b-uncensored-q4_k_m.gguf'
VAE = MODELS+'vae/flux2-vae.safetensors'
SIZES = {DIT:2460378560, ENCODER:2497280256, ALTERNATE:2497280416, VAE:336211292}


def selected(args, hardware=None):
    if args.cmd not in {'edit', 'inpaint', 'autoedit', 'video-inpaint'}:
        return False
    from radeon_edit import uses_radeon
    profile = getattr(args, 'edit_profile', 'auto')
    engine = getattr(args, 'engine', None) or 'auto'
    if profile in {'pix2pix', 'flux'} and engine != 'auto':
        raise ValueError('Explicit native engine requires --edit-profile klein4 or auto')
    return profile == 'klein4' or (profile == 'auto' and (engine != 'auto' or uses_radeon(hardware)))


def plan(root=ROOT, *, engine='auto', width=512, height=512, variant='official', hardware=None):
    variant = 'official'
    if variant not in ('official', 'standard', 'uncensored'):
        raise ValueError('Unknown Klein 4B variant')
    if engine not in ('auto', 'sdcpp-cpu', 'sdcpp-vulkan'):
        raise ValueError('Klein 4B uses the native CPU/Vulkan engine')
    if any(type(v) is not int for v in (width, height)) or min(width, height) < 128 or max(width, height) > 512 or width%16 or height%16:
        raise ValueError('Klein 4B dimensions must be multiples of 16 from 128 to 512')
    root = Path(root).resolve(); hw = hardware or detect_hardware()
    backend = engine_plan(root, hw, engine)
    needed = 16 if backend.get('shared_memory') else 12
    fallback = ''
    if engine == 'auto' and backend.get('shared_memory') and 12*GIB <= hw.get('ram_available_bytes',0) < 16*GIB:
        backend = engine_plan(root, hw, 'sdcpp-cpu')
        needed = 12
        fallback = '; shared-memory GPU admission did not fit, so auto selected CPU with the same weights'
    if hw.get('ram_available_bytes', 0) < needed*GIB:
        raise RuntimeError(f'Klein 4B requires {needed} GiB available RAM after chat handoff')
    encoder = ALTERNATE if variant == 'uncensored' else ENCODER
    for relative in (DIT, encoder, VAE):
        path = portable_path(root, relative)
        if not path.is_file() or path.stat().st_size != SIZES[relative]:
            raise RuntimeError('Missing/incomplete Klein 4B asset: '+relative+'; run Tools/import_native_flux.py --install')
    return {**backend, 'profile':'klein4', 'model_name':'FLUX Klein 4B Q4',
            'model_variant':'uncensored' if variant == 'uncensored' else 'standard',
            'encoder_path':encoder, 'width':width, 'height':height, 'workflow':None,
            'max_memory_bytes':10*GIB, 'min_free_ram_bytes':3*GIB,
            'reason':'Native Klein 4B with matched Qwen3 4B encoder; CPU text/VAE and bounded diffusion offload'+fallback,
            'limitations':'Alternate modifies the text encoder only. No guarantee of model behavior or missing concepts. Physical Radeon/integrated/Linux inference requires recipient validation.'}


def command(profile, root, prompt, negative, seed, output, steps=4, source=None):
    if profile.get('model_variant') == 'uncensored':
        from academic_policy import NOTICE
        raise ValueError(NOTICE)
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 16000 or '\x00' in prompt:
        raise ValueError('Image prompt must contain 1..16000 characters')
    if negative:
        raise ValueError('Distilled Klein 4B has no separate negative prompt; express the constraints in the instruction')
    if '<lora:' in prompt.lower():
        raise ValueError('No architecture-matched Klein 4B LoRAs are configured')
    if type(seed) is not int or not 0 <= seed < 2**63 or type(steps) is not int or not 1 <= steps <= 50:
        raise ValueError('Klein 4B needs a nonnegative 63-bit seed and 1..50 steps')
    encoder = ALTERNATE if profile.get('model_variant') == 'uncensored' else ENCODER
    if profile.get('encoder_path') != encoder:
        raise ValueError('Klein 4B encoder differs from the admitted variant')
    backend = 'te=cpu,vae=cpu,diffusion='+profile['device'] if profile['backend']=='vulkan' else 'cpu'
    argv = [profile['executable'], '--diffusion-model', str(portable_path(root, DIT)),
            '--llm', str(portable_path(root, encoder)), '--vae', str(portable_path(root, VAE)),
            '--backend', backend, '--auto-fit', 'on', '--mmap', '-t', str(min(4, os.cpu_count() or 1)),
            '--diffusion-fa', '--vae-tiling', '--cfg-scale', '1', '--sampling-method', 'euler',
            '--steps', str(steps), '--seed', str(seed), '-W', str(profile['width']), '-H', str(profile['height']),
            '-p', prompt, '-o', str(output)]
    if source is not None: argv += ['-r', str(source)]
    if profile['backend']=='vulkan': argv += ['--max-vram', f"{profile['device']}={profile['max_vram_gib']}"]
    return argv


def generate(profile, prompt, negative=None, seed=52, *, root=ROOT, steps=4):
    result = run_generation(profile, lambda part: command(profile, Path(root), prompt, negative, seed, part, steps),
        lambda part: validate_png(part, profile['width'], profile['height']), root=root, timeout=1200)
    return {**result, 'seed':seed, 'steps':steps}


def dimensions(root, source):
    cp = subprocess.run([str(ffmpeg_path(root, True)), '-v', 'error', '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height', '-of', 'json', str(source)], capture_output=True,
        check=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    row = json.loads(cp.stdout)['streams'][0]; w, h = row['width'], row['height']
    if min(w,h) < 16 or max(w,h) > 4096 or w*h > 8_000_000:
        raise ValueError('Editing source must fit 16..4096 pixels per side and 8 megapixels')
    return w, h


def edit(profile, source, instruction, mask=None, seed=42, steps=4, root=ROOT):
    root = Path(root).resolve(); source = media_reference(root, source)
    original = dimensions(root, source)
    # A source is conditioning, not a request to silently change explicit output dimensions.
    if mask:
        mask = media_reference(root, mask)
        if dimensions(root, mask) != original: raise ValueError('Source and mask dimensions must match')
    scale = min(1, 512/max(original))
    size = tuple(max(128, int(v*scale)//16*16) for v in original)
    profile = {**profile, 'width':size[0], 'height':size[1]}
    scratch = media_temp(root); scratch.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='klein4-', dir=scratch) as temp:
        temp = Path(temp); normalized = temp/'source.png'; generated = temp/'generated.png'
        ff = [str(ffmpeg_path(root)), '-v', 'error', '-nostdin', '-y', '-threads', '1']
        def commands(part):
            normalize = [*ff, '-i', str(source), '-vf', f'scale={size[0]}:{size[1]}', '-frames:v', '1', '-pix_fmt', 'rgb24', str(normalized)]
            gen = command(profile, root, instruction, None, seed, generated if mask else part, steps, normalized)
            if not mask: return [normalize, gen]
            # Preserve every unselected original pixel; resizing is confined to the generated patch.
            graph = (f'[1:v]scale={original[0]}:{original[1]},format=gbrp[g];'
                     '[0:v]format=gbrp[s];[2:v]format=gray,format=gbrp[m];[s][g][m]maskedmerge,format=rgb24[out]')
            composite = [*ff, '-i', str(source), '-i', str(generated), '-i', str(mask),
                         '-filter_complex_threads', '1', '-filter_complex', graph, '-map', '[out]', '-frames:v', '1', str(part)]
            return [normalize, gen, composite]
        expected = original if mask else size
        result = run_generation(profile, commands, lambda part: validate_png(part, *expected), root=root, timeout=1200)
    return {**result, 'hardware_profile':profile, 'model_variant':profile['model_variant'],
            'route':'masked-instruction-edit' if mask else 'instruction-edit', 'seed':seed, 'steps':steps}
